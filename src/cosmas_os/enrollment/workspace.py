"""Root-owned provisioning qualification port; no caller-provided destinations."""
import hashlib
import json
import os
import re
import stat
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .domain import EnrollmentError, HumanIdentity

NativeOrigin = Literal["capacitor://localhost", "app://cosmas"]
NATIVE_PROOF_CONTRACT = "cosmas-native-workspace-qualification.v1"


class WorkspaceAllocationSchedulerPort(Protocol):
    def request(self, identity: HumanIdentity, *, session: Session | None = None) -> str | None: ...


@dataclass(frozen=True)
class NativeWorkspaceScope:
    practice_id: str
    box_id: str
    organization_id: str
    workspace_api_origin: str
    workspace_url: str
    source_commit: str
    image_sha256: str
    issuer: str
    native_origin: NativeOrigin

    def __post_init__(self):
        try:
            if any(str(UUID(value)) != value for value in (self.practice_id, self.box_id)):
                raise ValueError
            if (not re.fullmatch(r"org_[A-Za-z0-9_]{1,251}", self.organization_id)
                    or not re.fullmatch(r"[a-f0-9]{40}", self.source_commit)
                    or not re.fullmatch(r"[a-f0-9]{64}", self.image_sha256)
                    or self.native_origin not in ("capacitor://localhost", "app://cosmas")):
                raise ValueError
            api, web, issuer = (urlparse(value) for value in
                                (self.workspace_api_origin, self.workspace_url, self.issuer))
            for value in (api, web, issuer):
                if (value.scheme != "https" or not value.hostname or value.port
                        or value.username or value.password or value.query or value.fragment
                        or value.hostname != value.hostname.lower()):
                    raise ValueError
            if api.path not in ("", "/") or issuer.path not in ("", "/"):
                raise ValueError
            paired = "api.cosmas.ai" if web.hostname == "app.cosmas.ai" else "api." + str(web.hostname)
            if api.hostname != paired:
                raise ValueError
        except (ValueError, TypeError):
            raise EnrollmentError("native_workspace_scope_invalid", "The registered native workspace is unavailable.", 503) from None


@dataclass(frozen=True)
class NativeWorkspaceProof:
    scope: NativeWorkspaceScope
    qualification_sha256: str
    measurement_json: str

    def __post_init__(self):
        try:
            if (not re.fullmatch(r"[a-f0-9]{64}", self.qualification_sha256)
                    or len(self.measurement_json.encode()) > 32_000
                    or hashlib.sha256(self.measurement_json.encode()).hexdigest() != self.qualification_sha256):
                raise ValueError
            value = json.loads(self.measurement_json)
            if self.measurement_json != json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False):
                raise ValueError
            if not isinstance(value, dict) or set(value) != {"contract_version", "request", "response"}:
                raise ValueError
            request, response = value["request"], value["response"]
            if (value["contract_version"] != "cosmas-native-workspace-measurement.v1"
                    or request != {"method": "GET", "url": self.scope.workspace_api_origin + "/practice-access/native-qualification",
                                   "native_origin": self.scope.native_origin}
                    or not isinstance(response, dict) or set(response) != {"status_code", "headers", "body"}
                    or type(response["status_code"]) is not int or response["status_code"] != 200
                    or response["headers"] != {"cache-control": "no-store", "x-cosmas-workspace-protocol": "1"}):
                raise ValueError
            body = response["body"]
            expected = {"box_id": self.scope.box_id, "organization_id": self.scope.organization_id,
                        "issuer": self.scope.issuer, "source_commit": self.scope.source_commit,
                        "image_sha256": self.scope.image_sha256, "native_origin": self.scope.native_origin}
            if (not isinstance(body, dict) or set(body) != set(expected) | {
                    "contract_version", "state", "role", "subject", "session_id", "initial_setup_complete"}
                    or any(body.get(k) != v for k, v in expected.items())
                    or type(body["contract_version"]) is not int or body["contract_version"] != 1
                    or body["state"] != "connected" or body["role"] not in ("owner", "member")
                    or body["initial_setup_complete"] is not True
                    or any(not isinstance(body[k], str) or not 1 <= len(body[k]) <= 255 for k in ("subject", "session_id"))):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise EnrollmentError("native_workspace_proof_invalid", "Native workspace qualification is unavailable.", 503) from None

    @property
    def measurement(self) -> dict:
        # Return a copy; the retained evidence itself is an immutable JSON string.
        return json.loads(self.measurement_json)

    @classmethod
    def from_measurement(cls, scope: NativeWorkspaceScope, measurement: dict,
                         qualification_sha256: str | None = None) -> "NativeWorkspaceProof":
        try:
            raw = json.dumps(measurement, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError):
            raise EnrollmentError("native_workspace_proof_invalid", "Native workspace qualification is unavailable.", 503) from None
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return cls(scope, qualification_sha256 or digest, raw)


class NativeWorkspaceAuthority(Protocol):
    def require(self, scope: NativeWorkspaceScope) -> NativeWorkspaceProof: ...


class ProductionNativeWorkspaceAuthority(ABC):
    """Root-owned native measurements, separate from browser readiness.

    The proof digest identifies retained measurement evidence; it is never a
    bearer capability. No enrollment customer route may install this authority.
    """

    @abstractmethod
    def require(self, scope: NativeWorkspaceScope) -> NativeWorkspaceProof:
        raise NotImplementedError


class NativeWorkspaceProofRegistry(ProductionNativeWorkspaceAuthority):
    """Immutable host input populated only after actual native qualification.

    Admission reads the retained measurement instead of recursively probing a
    runtime whose own request requires admission. A changed release/origin/Box
    requires new native measurement and a new host-owned registry.
    """

    def __init__(self, proofs: list[NativeWorkspaceProof]):
        self._proofs: dict[tuple[str, NativeOrigin], NativeWorkspaceProof] = {}
        for proof in proofs:
            key = (proof.scope.practice_id, proof.scope.native_origin)
            if key in self._proofs:
                raise EnrollmentError("native_workspace_proof_invalid", "Native qualification contains a duplicate practice transport.", 503)
            self._proofs[key] = proof

    def require(self, scope: NativeWorkspaceScope) -> NativeWorkspaceProof:
        proof = self._proofs.get((scope.practice_id, scope.native_origin))
        if proof is None or proof.scope != scope:
            raise EnrollmentError("native_workspace_unqualified", "This practice is not available in the native app yet.", 503)
        return proof

    @classmethod
    def from_path(cls, path: Path) -> "NativeWorkspaceProofRegistry":
        if not path.is_absolute():
            raise EnrollmentError("native_workspace_proof_invalid", "Native qualification must be an owned host input.", 503)
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 128_000):
                    raise ValueError
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    raw = stream.read(128_001)
            finally:
                os.close(fd)
            value = json.loads(raw)
            if (not isinstance(value, dict) or set(value) != {"contract_version", "proofs"}
                    or value["contract_version"] != NATIVE_PROOF_CONTRACT
                    or not isinstance(value["proofs"], list) or len(value["proofs"]) > 100):
                raise ValueError
            proofs = []
            expected = set(NativeWorkspaceScope.__dataclass_fields__)
            for item in value["proofs"]:
                if (not isinstance(item, dict) or set(item) != {"scope", "qualification_sha256", "measurement"}
                        or not isinstance(item["scope"], dict) or set(item["scope"]) != expected
                        or any(not isinstance(v, str) for v in item["scope"].values())
                        or not isinstance(item["qualification_sha256"], str)):
                    raise ValueError
                proofs.append(NativeWorkspaceProof.from_measurement(NativeWorkspaceScope(**item["scope"]),
                    item["measurement"], item["qualification_sha256"]))
            return cls(proofs)
        except (OSError, ValueError, TypeError):
            raise EnrollmentError("native_workspace_proof_invalid", "Native workspace qualification is unavailable.", 503) from None

    def public_measurement(self, scope: NativeWorkspaceScope) -> dict:
        proof = self.require(scope)
        return native_proof_record(proof)


def native_proof_record(proof: NativeWorkspaceProof) -> dict:
    return {"contract_version": NATIVE_PROOF_CONTRACT, "scope": asdict(proof.scope),
            "qualification_sha256": proof.qualification_sha256, "measurement": proof.measurement}


class NativeWorkspaceRecordedAuthority(ProductionNativeWorkspaceAuthority):
    """Revalidate actual root-confirmer measurements from existing command receipts.

    This does not probe admission-protected runtime routes and does not accept
    customer-supplied readiness. Each receipt is written only after the concrete
    production confirmation port measures the selected native release/session.
    """

    def __init__(self, sessions: sessionmaker, imported: ProductionNativeWorkspaceAuthority | None = None):
        self.sessions, self.imported = sessions, imported

    def require(self, scope: NativeWorkspaceScope) -> NativeWorkspaceProof:
        from .models import Command

        with self.sessions() as session:
            # The scope is selected from the practice row, never a supplied URL.
            rows = session.scalars(select(Command).where(
                Command.operation == "workspace_confirm",
                Command.response["scope"]["practice_id"].as_string() == scope.practice_id,
                Command.response["scope"]["native_origin"].as_string() == scope.native_origin,
                Command.response["completed"].as_boolean().is_(True),
            ).order_by(Command.created_at.desc()).limit(100)).all()
            for row in rows:
                saved = row.response.get("native_qualification")
                if (not isinstance(saved, dict) or set(saved) != {
                        "contract_version", "scope", "qualification_sha256", "measurement"}
                        or saved["contract_version"] != NATIVE_PROOF_CONTRACT
                        or saved["scope"] != asdict(scope)):
                    continue
                try:
                    proof = NativeWorkspaceProof.from_measurement(scope, saved["measurement"], saved["qualification_sha256"])
                except EnrollmentError:
                    continue
                return proof
        if self.imported is not None:
            return self.imported.require(scope)
        raise EnrollmentError("native_workspace_unqualified", "This practice has not completed native confirmation yet.", 503)


@dataclass(frozen=True)
class WorkspaceConfirmationRequest:
    practice_id: str
    box_id: str
    organization_id: str
    workspace_api_origin: str
    workspace_url: str
    source_commit: str
    image_sha256: str
    issuer: str
    subject: str
    email: str
    display_name: str
    role: str


@dataclass(frozen=True)
class NativeWorkspaceConfirmationRequest(WorkspaceConfirmationRequest):
    native_origin: NativeOrigin


@dataclass(frozen=True)
class WorkspaceConfirmationResult:
    # None means membership prepared, never admitted to a clinical workspace.
    proof_sha256: str | None


@dataclass(frozen=True)
class NativeWorkspaceConfirmationResult(WorkspaceConfirmationResult):
    native_proof: NativeWorkspaceProof | None


class WorkspaceConfirmer(Protocol):
    def confirm(self, request: WorkspaceConfirmationRequest, workspace_token: str) -> WorkspaceConfirmationResult: ...


class ProductionWorkspaceConfirmer(ABC):
    """Only a real root provisioner may be installed in the production entrypoint."""

    @abstractmethod
    def confirm(self, request: WorkspaceConfirmationRequest, workspace_token: str) -> WorkspaceConfirmationResult:
        raise NotImplementedError
