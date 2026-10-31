"""Trusted enrollment-to-workspace bridge, never mounted on the public API.

Clerk creation is recoverable by a stable slug and private binding. Membership
alone never qualifies a workspace: the independent runtime must admit that
exact human through its signed practice-access protocol.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from uuid import UUID, uuid5

import httpx
import jwt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from .config import EnrollmentSettings
from .domain import EnrollmentError, canonical_hash, now_utc
from .migration import schema_ready
from .models import Account, Membership, Practice
from .service import EnrollmentService
from .stripe import StripeCommerce
from .workspace import (
    ProductionWorkspaceConfirmer,
    WorkspaceConfirmationRequest,
    WorkspaceConfirmationResult,
)

BOX_NAMESPACE = UUID("f17d7eec-39ee-5d1e-8071-0d94453d91bd")


def paired_api(host: str | None) -> str:
    return "api.cosmas.ai" if host == "app.cosmas.ai" else "api." + str(host)


@dataclass(frozen=True)
class WorkspacePlan:
    practice_id: str
    box_id: str
    organization_id: str
    owner_subject: str
    issuer: str
    api_origin: str
    workspace_url: str
    source_commit: str
    image_sha256: str


class ClerkProvisioningPort:
    """Fixed Clerk BAPI transport; values/errors never appear in diagnostics."""

    def __init__(self, secret: str, *, client: httpx.Client | None = None):
        self.secret = secret
        self.client = client or httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False)

    def request(self, method: str, path: str, body: dict | None = None, *, missing: bool = False) -> dict | None:
        try:
            response = self.client.request(method, "https://api.clerk.com/v1" + path,
                                           headers={"Authorization": "Bearer " + self.secret}, json=body)
            if missing and response.status_code == 404:
                return None
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("invalid response")
            return value
        except Exception as exc:
            raise EnrollmentError("provisioning_identity_unavailable", "Practice identity setup can be retried safely.", 503) from exc

    def organization(self, slug: str, binding: dict, name: str, owner: str, seats: int) -> dict:
        path = "/organizations/" + quote(slug, safe="")
        value = self.request("GET", path, missing=True)
        if value is None:
            try:
                value = self.request("POST", "/organizations", {
                    "name": name, "slug": slug, "created_by": owner,
                    "max_allowed_memberships": seats, "private_metadata": {"cosmas_enrollment": binding},
                })
            except EnrollmentError:
                # A response can be lost after Clerk committed. Never switch slug
                # or create a second practice on a timeout or concurrent conflict.
                value = self.request("GET", path, missing=True)
                if value is None:
                    raise
        if (not value or not str(value.get("id", "")).startswith("org_") or value.get("slug") != slug
                or (value.get("private_metadata") or {}).get("cosmas_enrollment") != binding
                or value.get("created_by") != owner):
            raise EnrollmentError("provisioning_binding_conflict", "This organization does not match the saved practice.")
        return value

    def membership(self, org: str, subject: str, role: str) -> None:
        path = "/organizations/" + quote(org, safe="") + "/memberships"
        # Filter and inspect exact user/Org/role; a matching display name or email
        # is not authority. Unexpected roles are never silently upgraded.
        value = self.request("GET", path + "?user_id=" + quote(subject, safe="") + "&limit=100")
        rows = value.get("data") if value else None
        if not isinstance(rows, list):
            raise EnrollmentError("provisioning_membership_unavailable", "Practice membership could not be confirmed.", 503)
        matches = [r for r in rows if isinstance(r, dict) and (r.get("public_user_data") or {}).get("user_id") == subject]
        if not matches:
            try:
                self.request("POST", path, {"user_id": subject, "role": role})
            except EnrollmentError:
                pass  # Re-read after a lost create response; do not create twice.
            value = self.request("GET", path + "?user_id=" + quote(subject, safe="") + "&limit=100")
            rows = value.get("data") if value else []
            if not isinstance(rows, list):
                raise EnrollmentError("provisioning_membership_unavailable", "Practice membership could not be confirmed.", 503)
            matches = [r for r in rows if isinstance(r, dict) and (r.get("public_user_data") or {}).get("user_id") == subject]
        if len(matches) != 1 or matches[0].get("role") != role or (matches[0].get("organization") or {}).get("id") != org:
            raise EnrollmentError("provisioning_membership_conflict", "Practice membership requires review.")


class EnrollmentProvisioner:
    def __init__(self, service: EnrollmentService, clerk: ClerkProvisioningPort):
        self.service, self.clerk = service, clerk

    def saved_plan(self, practice_id: str) -> WorkspacePlan:
        with self.service.sessions() as session:
            practice = session.get(Practice, practice_id)
            owner = session.get(Account, practice.owner_id) if practice else None
            if (not practice or not owner or not practice.box_id or not practice.organization_id
                    or not practice.workspace_api_origin or not practice.source_commit or not practice.image_sha256
                    or owner.issuer != self.service.settings.clerk_issuer):
                raise EnrollmentError("provisioning_practice_pending", "Your practice workspace is still being prepared.")
            plan = WorkspacePlan(practice.id, practice.box_id, practice.organization_id, owner.subject, owner.issuer,
                                 practice.workspace_api_origin, practice.workspace_url or "",
                                 practice.source_commit, practice.image_sha256)
        binding = {"contract": "cosmas-enrollment-workspace.v1", "practice_id": plan.practice_id,
                   "box_id": plan.box_id, "owner_subject": plan.owner_subject, "issuer": plan.issuer}
        organization = self.clerk.request("GET", "/organizations/" + quote(plan.organization_id, safe=""))
        if (not organization or organization.get("id") != plan.organization_id
                or organization.get("slug") != "cosmas-" + plan.practice_id
                or organization.get("created_by") != plan.owner_subject
                or (organization.get("private_metadata") or {}).get("cosmas_enrollment") != binding):
            raise EnrollmentError("provisioning_binding_conflict", "The saved practice identity requires review.")
        return plan

    def prepare_memberships(self, practice_id: str) -> int:
        """Retryable trusted synchronization before a teammate can select Org.

        This creates only registry-authorized Clerk membership, never local
        runtime principals or a member-ready receipt. Runtime access remains
        subject to the existing explicit owner approval/provisioning path.
        """
        organization = self.saved_plan(practice_id).organization_id
        members = self.service.pending_human_memberships(practice_id)
        for member in members:
            if member["issuer"] != self.service.settings.clerk_issuer:
                raise EnrollmentError("provisioning_member_invalid", "This human belongs to a different identity instance.")
            self.clerk.membership(organization, member["subject"], "org:admin" if member["role"] == "owner" else "org:member")
        return len(members)

    def prepare(self, practice_id: str, *, api_origin: str, workspace_url: str,
                source_commit: str, image_sha256: str) -> WorkspacePlan:
        # Validate all destination/release fields before a remote mutation.
        for value, size in [(source_commit, 40), (image_sha256, 64)]:
            if len(value) != size or any(c not in "0123456789abcdef" for c in value):
                raise EnrollmentError("provisioning_release_invalid", "Select the exact reviewed workspace release.")
        app = urlparse(workspace_url)
        api = urlparse(api_origin)
        app_origin = f"https://{app.netloc}"
        if (app_origin not in self.service.settings.allowed_workspace_origins
                or app.scheme != "https" or app.username or app.password or app.query or app.fragment
                or api.scheme != "https" or api.username or api.password or api.port or api.path not in ("", "/")
                or api.query or api.fragment or api.hostname != paired_api(app.hostname)):
            raise EnrollmentError("provisioning_destination_invalid", "Use the admitted workspace and its paired API origin.")
        with self.service.sessions.begin() as session:
            practice = session.scalar(select(Practice).where(Practice.id == practice_id).with_for_update())
            if not practice or not self.service._acceptance(session, practice):
                raise EnrollmentError("agreement_required", "Accept the practice agreement before provisioning.")
            if practice.human_seats > 10:
                raise EnrollmentError("negotiated_quote_required", "This practice requires its negotiated activation contract.")
            owner = session.get(Account, practice.owner_id)
            member = session.scalar(select(Membership).where(Membership.practice_id == practice_id,
                                      Membership.account_id == practice.owner_id))
            if not owner or not member or not member.active or member.role != "owner" or owner.issuer != self.service.settings.clerk_issuer:
                raise EnrollmentError("provisioning_owner_invalid", "The saved practice owner cannot be confirmed.")
            box = str(uuid5(BOX_NAMESPACE, str(UUID(practice.id))))
            binding = {"contract": "cosmas-enrollment-workspace.v1", "practice_id": practice.id,
                       "box_id": box, "owner_subject": owner.subject, "issuer": owner.issuer}
            # The row lock also serializes this practice's provisioning callers.
            org = self.clerk.organization("cosmas-" + practice.id, binding, practice.display_name,
                                          owner.subject, practice.human_seats)
            self.clerk.membership(org["id"], owner.subject, "org:admin")
            if practice.box_id and (practice.box_id != box or practice.organization_id != org["id"]):
                raise EnrollmentError("workspace_binding_immutable", "Practice workspace identity cannot be replaced.")
            plan = WorkspacePlan(practice.id, box, org["id"], owner.subject, owner.issuer,
                                 f"https://{api.netloc}",
                                 workspace_url, source_commit, image_sha256)
            if practice.workspace_status != "ready":
                practice.box_id, practice.organization_id = box, org["id"]
                practice.workspace_url, practice.workspace_status = workspace_url, "provisioning"
                practice.workspace_proof_sha256 = canonical_hash(asdict(plan))
                practice.workspace_api_origin = plan.api_origin
                practice.source_commit = plan.source_commit
                practice.image_sha256 = plan.image_sha256
                practice.revision += 1
            return plan

    def qualify_member(self, plan: WorkspacePlan, *, subject: str, bearer: str,
                       client: httpx.Client | None = None, persist: bool = True) -> dict[str, Any]:
        """Measure a separately deployed runtime with this human's signed token.

        Unverified claims below only prevent sending a token to the wrong Box.
        The HTTPS runtime's signed protocol is the authority; no local claims
        parsing, client redirect or operator boolean is a readiness shortcut.
        """
        if self.saved_plan(plan.practice_id) != plan:
            raise EnrollmentError("provisioning_binding_conflict", "The selected workspace plan does not match its saved release.")
        with self.service.sessions.begin() as session:
            practice = session.get(Practice, plan.practice_id)
            account = session.scalar(select(Account).where(Account.issuer == plan.issuer, Account.subject == subject))
            member = session.scalar(select(Membership).where(Membership.practice_id == plan.practice_id,
                                      Membership.account_id == account.id)) if account else None
            if (not practice or not member or not member.active or practice.box_id != plan.box_id
                    or practice.organization_id != plan.organization_id or practice.workspace_url != plan.workspace_url
                    or plan.issuer != self.service.settings.clerk_issuer):
                raise EnrollmentError("provisioning_member_invalid", "This human does not match the saved practice workspace.")
            role = "owner" if member.role == "owner" else "member"
        app = urlparse(plan.workspace_url)
        api = urlparse(plan.api_origin)
        if (f"https://{app.netloc}" not in self.service.settings.allowed_workspace_origins
                or api.scheme != "https" or api.username or api.password or api.port
                or api.path not in ("", "/") or api.query or api.fragment
                or api.hostname != paired_api(app.hostname)):
            raise EnrollmentError("provisioning_destination_invalid", "Use the admitted workspace and its paired API origin.")
        try:
            claims = jwt.decode(bearer, options={"verify_signature": False})
            org = claims.get("org_id") or (claims.get("o") or {}).get("id")
            if claims.get("iss") != plan.issuer or claims.get("sub") != subject or org != plan.organization_id:
                raise ValueError("wrong scope")
            # Verify Clerk membership without allowing a registry staff role to
            # create a Clerk administrator. The runtime performs its own binding.
            self.clerk.membership(plan.organization_id, subject, "org:admin" if role == "owner" else "org:member")
            probe = client or httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False)
            observations = {}
            headers = {"Authorization": "Bearer " + bearer, "X-Cosmas-Practice-Access-Contract": "1",
                       "X-Cosmas-Draft-Recovery": "2", "X-Cosmas-Workspace-Protocol": "1", "Accept": "application/json"}
            qualification_path = "/practice-access/enrollment-qualification"
            for path in ("/health", "/ready", qualification_path):
                response = probe.get(plan.api_origin + path, headers=headers)
                response.raise_for_status()
                value = response.json()
                if not isinstance(value, dict):
                    raise ValueError("invalid response")
                if path == qualification_path:
                    if ("no-store" not in response.headers.get("cache-control", "") or value.get("contract_version") != 1
                            or response.headers.get("x-cosmas-workspace-protocol") != "1"
                            or value.get("state") != "connected" or value.get("role") != role):
                        raise ValueError("member not admitted")
                    expected = {"box_id": plan.box_id, "organization_id": plan.organization_id,
                                "issuer": plan.issuer, "subject": subject, "source_commit": plan.source_commit,
                                "image_sha256": plan.image_sha256}
                    if any(value.get(field) != selected for field, selected in expected.items()):
                        raise ValueError("runtime binding or release mismatch")
                elif value.get("status") != ("ready" if path == "/ready" else "ok"):
                    raise ValueError("runtime unavailable")
                observations[path] = value
        except Exception as exc:
            raise EnrollmentError("provisioning_runtime_unavailable", "Your workspace is still being prepared; no trial has started.", 503) from exc
        receipt = {"contract": "cosmas-enrollment-workspace-proof.v1", "plan": asdict(plan),
                   "member_subject": subject, "role": role, "observations": observations,
                   "checked_at": now_utc().isoformat()}
        proof = canonical_hash(receipt)
        if persist and role == "owner":
            self.service.record_workspace(plan.practice_id, box_id=plan.box_id, organization_id=plan.organization_id,
                                          url=plan.workspace_url, proof_sha256=proof, status="ready")
        elif persist:
            self.service.record_membership_ready(plan.practice_id, issuer=plan.issuer, subject=subject,
                                                 organization_id=plan.organization_id, proof_sha256=proof)
        return {"receipt": receipt, "sha256": proof}


class BoundWorkspaceConfirmer(ProductionWorkspaceConfirmer):
    def __init__(self, service: EnrollmentService, clerk: ClerkProvisioningPort):
        self.provisioner = EnrollmentProvisioner(service, clerk)

    def confirm(self, request: WorkspaceConfirmationRequest, workspace_token: str) -> WorkspaceConfirmationResult:
        plan = self.provisioner.saved_plan(request.practice_id)
        selected = WorkspacePlan(request.practice_id, request.box_id, request.organization_id,
                                 plan.owner_subject, request.issuer, request.workspace_api_origin,
                                 request.workspace_url, request.source_commit, request.image_sha256)
        if selected != plan:
            raise EnrollmentError("provisioning_binding_conflict", "The saved workspace release changed; check setup again.")
        role = "org:admin" if request.role == "owner" else "org:member"
        self.provisioner.clerk.membership(plan.organization_id, request.subject, role)
        try:
            claims = jwt.decode(workspace_token, options={"verify_signature": False})
            if claims.get("iss") != plan.issuer or claims.get("sub") != request.subject:
                raise ValueError("wrong human")
            org = claims.get("org_id") or (claims.get("o") or {}).get("id")
        except Exception as exc:
            raise EnrollmentError("provisioning_member_invalid", "Sign in again to confirm this practice account.", 401) from exc
        if org != plan.organization_id:
            return WorkspaceConfirmationResult(proof_sha256=None)
        # The service owns the command transaction and final registry update.
        # Measurements may not open a nested write transaction on the same row.
        result = self.provisioner.qualify_member(plan, subject=request.subject, bearer=workspace_token, persist=False)
        return WorkspaceConfirmationResult(proof_sha256=result["sha256"])


def create_workspace_confirmer(settings: EnrollmentSettings, service: EnrollmentService) -> ProductionWorkspaceConfirmer:
    return BoundWorkspaceConfirmer(service, ClerkProvisioningPort(settings.clerk_secret_key.get_secret_value()))


def main() -> int:
    import argparse
    import json
    import os
    import stat

    parser = argparse.ArgumentParser(description="Protected CosmaBot practice provisioning; no public ready route.")
    commands = parser.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser("prepare")
    for field in ("practice-id", "api-origin", "workspace-url", "source-commit", "image-sha256"):
        prepare.add_argument("--" + field, required=True)
    prepare.add_argument("--output", required=True)
    qualify = commands.add_parser("qualify-member")
    qualify.add_argument("--input", required=True)
    qualify.add_argument("--subject", required=True)
    qualify.add_argument("--token-file", required=True)
    qualify.add_argument("--output", required=True)
    members = commands.add_parser("prepare-memberships")
    members.add_argument("--practice-id", required=True)
    members.add_argument("--output", required=True)
    args = parser.parse_args()
    engine = None
    try:
        settings = EnrollmentSettings()
        if settings.registration_errors() or not settings.provisioning_enabled:
            raise EnrollmentError("provisioning_not_configured", "Protected practice provisioning is not configured.", 503)
        engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
        if not schema_ready(engine):
            raise EnrollmentError("provisioning_schema_unavailable", "Apply the dedicated enrollment migration first.", 503)
        service = EnrollmentService(sessionmaker(engine, expire_on_commit=False), settings, StripeCommerce(settings))
        provisioner = EnrollmentProvisioner(service, ClerkProvisioningPort(settings.clerk_secret_key.get_secret_value()))
        if args.action == "prepare":
            result = asdict(provisioner.prepare(args.practice_id, api_origin=args.api_origin,
                workspace_url=args.workspace_url, source_commit=args.source_commit, image_sha256=args.image_sha256))
        elif args.action == "prepare-memberships":
            result = {"prepared_memberships": provisioner.prepare_memberships(args.practice_id), "workspace_ready": False}
        else:
            token_path = Path(args.token_file)
            mode = token_path.lstat().st_mode
            if not stat.S_ISREG(mode) or mode & 0o077 or token_path.stat().st_size > 8192:
                raise EnrollmentError("provisioning_token_file_invalid", "Use a protected regular token file.")
            raw_plan = Path(args.input).read_text()
            if len(raw_plan.encode()) > 16384:
                raise ValueError("plan too large")
            plan = WorkspacePlan(**json.loads(raw_plan))
            result = provisioner.qualify_member(plan, subject=args.subject, bearer=token_path.read_text().strip())
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
        print("Saved protected practice provisioning evidence; billing was not activated by this command.")
        return 0
    except Exception:
        print("Practice provisioning could not finish. Preserve the saved practice and retry after reviewing its configuration.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
