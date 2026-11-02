"""Private allocated synthetic Box migration/reservation; reuse the existing beta contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from uuid import UUID, uuid5

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from cosmas_os.application.beta_bootstrap import BetaBootstrapManifest
from cosmas_os.application.database_preparation import prepare_beta_database
from cosmas_os.application.practice_setup import reserve_first_owner
from cosmas_os.config import Settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.practice_setup_models import PracticeOwnerReservation
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

BOX_NAMESPACE = UUID("f17d7eec-39ee-5d1e-8071-0d94453d91bd")


def binding(environ: dict[str, str]) -> dict[str, str]:
    if (
        environ.get("COSMAS_ENV") != "early_adopter_beta"
        or environ.get("DATA_MODE") != "synthetic"
        or environ.get("WORKSPACE_ENROLLMENT_MANAGED") != "true"
        or environ.get("CLERK_SESSION_POLICY") != "enrollment_default"
        or type(environ.get("CLERK_AUDIENCE")) is not str
        or environ["CLERK_AUDIENCE"] and not re.fullmatch(r"[\x21-\x7e]{1,255}", environ["CLERK_AUDIENCE"])
        or environ.get("EXPECTED_SCHEMA_REVISION") != EXPECTED_SCHEMA_REVISION
    ):
        raise ValueError("synthetic bound deployment required")
    practice = str(UUID(environ.get("WORKSPACE_ENROLLMENT_PRACTICE_ID", "")))
    box = str(UUID(environ.get("BETA_BOX_ID", "")))
    if (
        practice != environ["WORKSPACE_ENROLLMENT_PRACTICE_ID"]
        or box != environ["BETA_BOX_ID"]
        or str(uuid5(BOX_NAMESPACE, practice)) != box
        or not re.fullmatch(r"org_[A-Za-z0-9]+", environ.get("CLERK_ORGANIZATION_ID", ""))
        or not re.fullmatch(r"user_[A-Za-z0-9]+", environ.get("RESERVED_OWNER_SUBJECT", ""))
        or not re.fullmatch(r"[0-9a-f]{40}", environ.get("WORKSPACE_RELEASE_SOURCE_COMMIT", ""))
        or not re.fullmatch(r"[0-9a-f]{64}", environ.get("WORKSPACE_RELEASE_IMAGE_SHA256", ""))
    ):
        raise ValueError("immutable practice release binding required")
    host = environ.get("BOX_POSTGRES_HOST", "")
    if host != "psql-cbaw-" + practice.replace("-", "") + ".postgres.database.azure.com":
        raise ValueError("dedicated Box PostgreSQL required")
    for name in ("DATABASE_ADMIN_URL", "DATABASE_URL"):
        url = make_url(environ.get(name, ""))
        expected_login = "box_bootstrap" if name == "DATABASE_ADMIN_URL" else "box_runtime"
        if (
            url.drivername != "postgresql+psycopg"
            or url.host != host
            or url.port not in (None, 5432)
            or url.database != "cosmas_os"
            or url.username != expected_login
            or not url.password
            or dict(url.query) != {"sslmode": "verify-full", "sslrootcert": "system"}
        ):
            raise ValueError("protected exact Box database URL required")
    return {
        "practice_id": practice,
        "box_id": box,
        "organization_id": environ["CLERK_ORGANIZATION_ID"],
        "source_commit": environ["WORKSPACE_RELEASE_SOURCE_COMMIT"],
        "image_sha256": environ["WORKSPACE_RELEASE_IMAGE_SHA256"],
    }


def run(operation: str, environ: dict[str, str]) -> dict:
    selected = binding(environ)
    if operation == "migrate":
        evidence = prepare_beta_database(environ["DATABASE_ADMIN_URL"], environ["DATABASE_URL"])
        return {
            "contract": "enrollment-workspace-migration.v1",
            **selected,
            "database": evidence.sanitized_payload(),
            "owner_ready": False,
            "workspace_ready": False,
        }
    if operation != "reserve":
        raise ValueError("explicit private migration or reservation required")
    raw = environ.get("OWNER_MANIFEST", "")
    expected = environ.get("OWNER_MANIFEST_SHA256", "")
    if (
        len(raw.encode()) > 8192
        or not re.fullmatch(r"[0-9a-f]{64}", expected)
        or hashlib.sha256(raw.encode()).hexdigest() != expected
    ):
        raise ValueError("exact protected owner manifest required")
    manifest = BetaBootstrapManifest.model_validate_json(raw)
    if (
        str(manifest.box_id) != selected["box_id"]
        or manifest.clerk_subject != environ["RESERVED_OWNER_SUBJECT"]
        or manifest.clerk_organization_id != selected["organization_id"]
        or manifest.clerk_issuer != environ.get("CLERK_ISSUER")
        or manifest.evidence_ref != environ.get("HUMAN_DEPLOY_EVIDENCE_REF")
    ):
        raise ValueError("owner manifest differs from reserved practice")
    runtime = Settings()
    runtime.validate_runtime_configuration()
    engine = create_engine(environ["DATABASE_ADMIN_URL"], pool_pre_ping=True, hide_parameters=True)
    try:
        with Session(engine) as session:
            # The existing restricted runtime cannot INSERT reservations. Only
            # this isolated host job uses its Box administrator connection.
            reserve_first_owner(session, runtime, manifest)
            saved = session.get(PracticeOwnerReservation, selected["box_id"])
            if (
                saved is None
                or saved.subject != manifest.clerk_subject
                or saved.organization_id != manifest.clerk_organization_id
                or saved.manifest_sha256 != payload_hash(manifest.model_dump(mode="json"))
                or saved.consumed_at is not None
            ):
                raise ValueError("reservation readback failed")
            return {
                "contract": "enrollment-workspace-reservation.v1",
                **selected,
                "owner_manifest_sha256": expected,
                "owner_reserved": True,
                "expires_at": saved.expires_at.isoformat(),
                "owner_ready": False,
                "workspace_ready": False,
            }
    finally:
        engine.dispose()


def persist_receipt(operation: str, environ: dict[str, str], receipt: dict) -> dict:
    """Write only actual scoped preparation evidence to a host-only container.

    Runtime identities have no access to this receipt container. The operation
    key is stable; an identical first result survives a lost job reply.
    """
    from azure.core.exceptions import ResourceExistsError
    from azure.identity import ManagedIdentityCredential
    from azure.storage.blob import BlobServiceClient

    selected = binding(environ)
    operation_id = environ.get("HOST_ALLOCATION_OPERATION_ID", "")
    if str(UUID(operation_id)) != operation_id or environ.get("HOST_RECEIPT_CONTAINER") != "hosting-receipts":
        raise ValueError("exact private allocation operation required")
    account = environ.get("AZURE_STORAGE_ACCOUNT_URL", "")
    expected = "https://stca" + selected["practice_id"].replace("-", "")[:20] + ".blob.core.windows.net"
    if account != expected:
        raise ValueError("only this Box's private receipt storage is allowed")
    client_id = environ.get("AZURE_CLIENT_ID", "")
    if str(UUID(client_id)) != client_id:
        raise ValueError("explicit private job managed identity required")
    credential = ManagedIdentityCredential(client_id=client_id)
    service = BlobServiceClient(account, credential=credential, logging_enable=False)
    blob = service.get_blob_client("hosting-receipts", operation_id + "/" + operation + ".json")
    complete = {**receipt, "allocation_operation_id": operation_id}
    raw = json.dumps(complete, sort_keys=True, separators=(",", ":")).encode()
    try:
        blob.upload_blob(raw, overwrite=False)
    except ResourceExistsError:
        existing = blob.download_blob().readall()
        if len(existing) > 65536:
            raise ValueError("bounded receipt required") from None
        stored = json.loads(existing)
        if (not isinstance(stored, dict) or stored.get("allocation_operation_id") != operation_id
                or stored.get("contract") != receipt["contract"]
                or any(stored.get(name) != item for name, item in selected.items())
                or stored.get("owner_ready") is not False or stored.get("workspace_ready") is not False
                or operation == "reserve" and stored.get("owner_manifest_sha256") != receipt["owner_manifest_sha256"]):
            raise ValueError("saved receipt differs from selected allocation") from None
        raw = existing
    finally:
        service.close()
        credential.close()
    return {"contract": "cosmas-allocated-workspace-job.v1", "operation": operation,
            **selected, "allocation_operation_id": operation_id,
            "receipt_sha256": hashlib.sha256(raw).hexdigest(), "owner_ready": False, "workspace_ready": False}


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise ValueError("explicit operation required")
        environment = dict(os.environ)
        print(json.dumps(persist_receipt(sys.argv[1], environment, run(sys.argv[1], environment)), sort_keys=True))
        return 0
    except Exception as error:
        # No driver errors, SQL, URLs, owner contents, or credentials in logs.
        print(json.dumps({"error": "allocated_workspace_job_failed", "class": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
