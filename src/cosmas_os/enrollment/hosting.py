"""Private automatic single-practice allocation; never a public ready endpoint.

The worker executes only a host-reviewed release in dedicated synthetic staging.
Runtime membership/native qualification and billing remain separate afterwards.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from sqlalchemy import select

from .admission import derive_runtime_admission_key
from .allocation import (
    ProductionWorkspaceAllocator,
    WorkspaceAllocationDestination,
    WorkspaceAllocationRequest,
)
from .domain import EnrollmentError
from .models import Account, Membership, Practice
from .provisioning import BOX_NAMESPACE, WorkspacePlan
from .service import EnrollmentService

HOSTING_CONTRACT = "cosmas-private-hosting.v1"
SECRET_NAMES = {"DATABASE_URL": "database-url", "DATABASE_ADMIN_URL": "database-admin-url",
                "REDIS_URL": "redis-url", "WORKSPACE_ENROLLMENT_ADMISSION_SECRET": "enrollment-admission-key",
                "OWNER_MANIFEST": "owner-manifest"}


def private_read(path: Path, maximum: int = 128_000) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (not path.is_absolute() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > maximum):
            raise ValueError("protected owner file required")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read(maximum + 1)
    finally:
        os.close(fd)


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class HostingConfiguration:
    """Root-owned public coordinates and protected file references, not keys."""

    def __init__(self, value: dict):
        expected = {"contract_version", "enabled", "synthetic_only", "foundation", "account", "release",
                    "worker_client_id", "worker_object_id", "source_repository", "state_root", "cloudflare_zone_id",
                    "cloudflare_token_file", "native_origins"}
        if (set(value) != expected or value["contract_version"] != HOSTING_CONTRACT
                or type(value["enabled"]) is not bool or value["synthetic_only"] is not True):
            raise ValueError("explicit dedicated synthetic hosting configuration required")
        self.value = json.loads(json.dumps(value))
        self.foundation, self.account, self.release = (self.value[name] for name in ("foundation", "account", "release"))
        f, a, release = self.foundation, self.account, self.release
        for name in ("subscription_id", "tenant_id"):
            if str(UUID(f[name])) != f[name]:
                raise ValueError("canonical foundation identity required")
        suffix = re.fullmatch(r"rg-cosmabot-enrollment-staging-([a-z0-9]{6,8})", f["resource_group_name"])
        if (not suffix or f["contract_version"] != "enrollment-foundation.v1" or f["environment"] != "staging"
                or f["location"] not in {"eastus2", "centralus"}
                or f["registry_server"] != "acrcbotenrstg" + suffix[1] + ".azurecr.io"):
            raise ValueError("dedicated enrollment foundation required")
        self.scope = f"/subscriptions/{f['subscription_id']}/resourceGroups/{f['resource_group_name']}/providers/"
        for name in ("vnet_id", "container_app_environment_id", "container_registry_id", "postgres_subnet_id",
                     "private_endpoint_subnet_id", "vault_private_dns_zone_id", "blob_private_dns_zone_id", "redis_private_dns_zone_id"):
            if not isinstance(f[name], str) or not f[name].lower().startswith(self.scope.lower()):
                raise ValueError("foundation reference leaves dedicated resource group")
        if (not f["blob_private_dns_zone_id"].endswith("/privatelink.blob.core.windows.net")
                or not f["redis_private_dns_zone_id"].endswith("/privatelink.redis.azure.net")
                or not f["vault_private_dns_zone_id"].endswith("/privatelink.vaultcore.azure.net")):
            raise ValueError("exact read-only private service DNS zones required")
        backend = f["state_backend"]
        if (backend["resource_group_name"] != f["resource_group_name"]
                or backend["storage_account_name"] != "stcbotenrstg" + suffix[1]
                or backend["container_name"] != "enrollment-runtime-state" or backend["use_azuread_auth"] is not True):
            raise ValueError("independent per-practice state keys in owned backend required")
        if (set(a) != {"app_origin", "api_origin", "issuer", "publishable_key", "audience"}
                or a["app_origin"] != "https://onboarding.staging.cosmas.ai"
                or a["api_origin"] != "https://enrollment-api.staging.cosmas.ai"
                or not re.fullmatch(r"https://[a-z0-9-]+[.]clerk[.]accounts[.]dev", a["issuer"])
                or a["publishable_key"] != "pk_test_" + base64.b64encode((a["issuer"][8:] + "$").encode()).decode()
                or not isinstance(a["audience"], str) or len(a["audience"]) > 255
                or a["audience"] and not re.fullmatch(r"[\x21-\x7e]+", a["audience"])):
            raise ValueError("selected development account identity required")
        if set(release) != {"source_commit", "api_image", "job_image"} or not re.fullmatch(r"[a-f0-9]{40}", release["source_commit"]):
            raise ValueError("immutable reviewed release required")
        for name in ("api_image", "job_image"):
            if not re.fullmatch(re.escape(f["registry_server"]) + r"/[a-z0-9/_-]+@sha256:[a-f0-9]{64}", release[name]):
                raise ValueError("owned immutable image required")
        for name in ("worker_client_id", "worker_object_id"):
            if str(UUID(value[name])) != value[name]:
                raise ValueError("explicit private worker identity required")
        if (not re.fullmatch(r"[a-f0-9]{32}", value["cloudflare_zone_id"])
                or not value["native_origins"] or len(set(value["native_origins"])) != len(value["native_origins"])
                or any(origin not in {"capacitor://localhost", "app://cosmas"} for origin in value["native_origins"])):
            raise ValueError("exact owned DNS zone/native transport input required")
        self.source = Path(value["source_repository"])
        self.state_root = Path(value["state_root"])
        self.token_file = Path(value["cloudflare_token_file"])
        if (not all(path.is_absolute() for path in (self.source, self.state_root, self.token_file))
                or self.state_root == Path("/") or self.state_root.is_relative_to(self.source)):
            raise ValueError("private persistent worker state outside source required")

    @classmethod
    def from_path(cls, path: Path):
        return cls(json.loads(private_read(path)))


class OpenTofuWorkspaceAllocator(ProductionWorkspaceAllocator):
    """Real private allocation pipeline. The concrete backend has no allow/fake mode."""

    def __init__(self, service: EnrollmentService, configuration: HostingConfiguration, *, backend=None):
        from .hosting_cloud import AzureAllocationBackend

        self.service, self.configuration = service, configuration
        if backend is not None and not isinstance(backend, AzureAllocationBackend):
            raise ValueError("a concrete private Azure allocation backend is required")
        self.backend = backend or AzureAllocationBackend(configuration)

    def destination(self, request: WorkspaceAllocationRequest) -> WorkspaceAllocationDestination:
        if (not self.configuration.value["enabled"] or not self.service.settings.workspace_allocation_enabled
                or not self.service.settings.provisioning_enabled or self.service.settings.data_mode != "synthetic"):
            raise EnrollmentError("workspace_allocation_disabled", "Private workspace allocation is unavailable.", 503)
        if (str(UUID(request.practice_id)) != request.practice_id
                or request.box_id != str(uuid5(BOX_NAMESPACE, request.practice_id))
                or request.issuer != self.configuration.account["issuer"]):
            raise EnrollmentError("workspace_allocation_conflict", "Registered practice identity changed.")
        web = "https://" + request.practice_id + ".staging.cosmas.ai"
        release = self.configuration.release
        return WorkspaceAllocationDestination("https://api." + request.practice_id + ".staging.cosmas.ai", web + "/chief",
            release["source_commit"], release["api_image"].split("@sha256:")[1])

    def _deployment(self, plan: WorkspacePlan, operation_id: str) -> dict:
        from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

        settings, c = self.service.settings, self.configuration
        if (not c.value["enabled"] or not settings.workspace_allocation_enabled or not settings.provisioning_enabled
                or settings.data_mode != "synthetic" or not settings.native_account_enabled
                or settings.clerk_issuer != c.account["issuer"] or settings.clerk_publishable_key != c.account["publishable_key"]
                or settings.clerk_audience != c.account["audience"] or settings.native_authorized_origins != c.value["native_origins"]):
            raise EnrollmentError("workspace_allocation_disabled", "Private native workspace allocation is unavailable.", 503)
        if str(UUID(operation_id)) != operation_id:
            raise ValueError("stable registered operation required")
        expected = self.destination(WorkspaceAllocationRequest(plan.practice_id, plan.box_id, "unused", plan.owner_subject, plan.issuer))
        if (plan.api_origin, plan.workspace_url, plan.source_commit, plan.image_sha256) != (
                expected.api_origin, expected.workspace_url, expected.source_commit, expected.image_sha256):
            raise EnrollmentError("workspace_allocation_conflict", "The selected immutable release changed.")
        with self.service.sessions() as session:
            practice = session.get(Practice, plan.practice_id)
            owner = session.get(Account, practice.owner_id) if practice else None
            membership = session.scalar(select(Membership).where(Membership.practice_id == plan.practice_id,
                Membership.account_id == owner.id, Membership.active.is_(True))) if owner else None
            if (not practice or not owner or not membership or membership.role != "owner"
                    or membership.account_id != practice.owner_id or membership.practice_id != practice.id
                    or owner.subject != plan.owner_subject or owner.issuer != plan.issuer
                    or practice.box_id != plan.box_id or practice.organization_id != plan.organization_id
                    or not self.service._acceptance(session, practice)):
                raise EnrollmentError("workspace_allocation_conflict", "Registered practice ownership changed.")
            names = (practice.display_name, owner.display_name)
        evidence = "cosmas-native-allocation.v1:" + operation_id
        manifest = {"schema_version": "cosmas-os/d3-beta-bootstrap/v1", "box_id": plan.box_id,
                    "clinic_display_name": names[0], "owner_display_name": names[1], "clerk_issuer": plan.issuer,
                    "clerk_subject": plan.owner_subject, "clerk_organization_id": plan.organization_id,
                    "reviewed_by": "CosmaBot approved allocation policy v1", "evidence_ref": evidence}
        selected = urlsplit(plan.workspace_url)
        web = selected.scheme + "://" + selected.netloc
        origins = [c.account["app_origin"], web, *c.value["native_origins"]]
        public = {"COSMAS_ENV": "early_adopter_beta", "DATA_MODE": "synthetic", "AUTH_MODE": "clerk_jwt",
                  "SYNTH_SEED": "false", "SYNC_WORKER": "false", "BLOB_BACKEND": "azure", "BETA_BOX_ID": plan.box_id,
                  "CLERK_ISSUER": plan.issuer, "CLERK_JWKS_URL": plan.issuer + "/.well-known/jwks.json",
                  "CLERK_ORGANIZATION_ID": plan.organization_id, "CLERK_SESSION_POLICY": "enrollment_default",
                  "CLERK_AUDIENCE": c.account["audience"], "CLERK_AUTHORIZED_PARTIES": ",".join(origins),
                  "CORS_ALLOWED_ORIGINS": ",".join(origins), "HUMAN_DEPLOY_EVIDENCE_REF": evidence,
                  "WORKSPACE_ENABLED": "true", "WORKSPACE_AUTHENTICATED_ENABLED": "true", "WORKSPACE_HOSTED_ENABLED": "true",
                  "WORKSPACE_DRAFT_RECOVERY_REQUIRED": "true", "WORKSPACE_ENROLLMENT_MANAGED": "true",
                  "WORKSPACE_APPLE_HOSTED_TRANSPORT_ENABLED": str("capacitor://localhost" in c.value["native_origins"]).lower(),
                  "WORKSPACE_DESKTOP_HOSTED_TRANSPORT_ENABLED": str("app://cosmas" in c.value["native_origins"]).lower(),
                  "WORKSPACE_ENROLLMENT_PRACTICE_ID": plan.practice_id, "WORKSPACE_ENROLLMENT_API_ORIGIN": c.account["api_origin"],
                  "WORKSPACE_ENROLLMENT_ACCOUNT_ORIGIN": c.account["app_origin"],
                  "WORKSPACE_ENROLLMENT_ORIGIN_ALLOWLIST": c.account["api_origin"] + "," + c.account["app_origin"],
                  "WORKSPACE_RELEASE_SOURCE_COMMIT": plan.source_commit, "WORKSPACE_RELEASE_IMAGE_SHA256": plan.image_sha256}
        return {"contract_version": "cosmas-allocated-workspace.v1", "version": 1, "environment": "staging", "synthetic_only": True,
                "namespace": plan.practice_id.replace("-", "")[:16], "operation_id": operation_id,
                "allocator_object_id": c.value["worker_object_id"], "foundation": c.foundation, "account": c.account,
                "release": c.release, "expected_schema_revision": EXPECTED_SCHEMA_REVISION,
                "create_migration_jobs": False, "create_owner_reservation_jobs": False, "deploy_workloads": False, "bind_domains": False,
                "practice": {"plan": asdict(plan), "web_origin": web, "api_env": public, "web_image": None,
                    "secret_references": {}, "owner_manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest(),
                    "migration_receipt_sha256": None, "reservation_receipt_sha256": None, "dns_ownership_qualified": False},
                "_owner_manifest": manifest}

    def allocate(self, plan: WorkspacePlan, *, operation_id: str) -> None:
        deployment = self._deployment(plan, operation_id)
        # The concrete backend persists each exact handle/receipt and recovers
        # interrupted steps; it never declares member/workspace admission.
        self.backend.allocate(deployment, self.service.settings.runtime_admission_secret.get_secret_value())


def box_admission_key(deployment: dict, master: str) -> str:
    plan = deployment["practice"]["plan"]
    return derive_runtime_admission_key(master, plan["practice_id"], plan["box_id"], plan["organization_id"])
