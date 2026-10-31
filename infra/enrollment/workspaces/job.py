"""Manual synthetic Box migration/reservation; reuse the existing beta contracts."""

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
        or environ.get("CLERK_AUDIENCE") != ""
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
    if not re.fullmatch(r"psql-cews-stg-[a-z0-9]{6,8}-[ab]\.postgres\.database\.azure\.com", host):
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
        raise ValueError("manual migration or reservation required")
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


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise ValueError("explicit operation required")
        print(json.dumps(run(sys.argv[1], dict(os.environ)), sort_keys=True))
        return 0
    except Exception as error:
        # No driver errors, SQL, URLs, manifest contents or credentials in logs.
        print(
            json.dumps({"error": "enrollment_workspace_job_failed", "class": type(error).__name__}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
