from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

DATABASE_FINGERPRINT_CONTRACT = "cosmas-os-d3-database-fingerprint-v1"
_DATABASE_CONNECT_TIMEOUT_SECONDS = 5
_DATABASE_STATEMENT_TIMEOUT_MILLISECONDS = 10_000
_STRUCTURE_TABLES = (
    "box_contexts",
    "principals",
    "external_identities",
    "patient_links",
    "appointment_observations",
    "tickets",
    "action_revisions",
    "decisions",
    "operations",
    "audit_events",
    "artifacts",
    "capability_configs",
)


class DatabaseFingerprintError(RuntimeError):
    """The database cannot produce a safe, comparable synthetic fingerprint."""


@dataclass(frozen=True)
class DatabaseFingerprintEvidence:
    contract: str
    status: str
    schema_revision: str
    schema_at_expected_head: bool
    structures: dict[str, dict[str, int | str]]
    aggregate_sha256: str

    def sanitized_payload(self) -> dict[str, Any]:
        return asdict(self)

    def sanitized_json(self) -> str:
        payload = self.sanitized_payload()
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["evidence_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def database_fingerprint_failure_json() -> str:
    return json.dumps(
        {"contract": DATABASE_FINGERPRINT_CONTRACT, "status": "failed"},
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_database_url(database_url: str, *, require_verify_full: bool) -> None:
    try:
        parsed = urlparse(database_url)
    except Exception:
        raise DatabaseFingerprintError("database fingerprint failed") from None
    if (
        parsed.scheme != "postgresql+psycopg"
        or not parsed.username
        or not parsed.password
        or parsed.hostname is None
        or (
            require_verify_full
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        or parsed.path != "/cosmas_os"
        or parsed.params
        or parsed.fragment
    ):
        raise DatabaseFingerprintError("database fingerprint failed")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if require_verify_full and (
        set(query) != {"sslmode", "sslrootcert"}
        or query.get("sslmode") != ["verify-full"]
        or query.get("sslrootcert") != ["system"]
    ):
        raise DatabaseFingerprintError("database fingerprint failed")


def _make_database_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": _DATABASE_CONNECT_TIMEOUT_SECONDS,
            "options": f"-c statement_timeout={_DATABASE_STATEMENT_TIMEOUT_MILLISECONDS}",
        },
    )


def _fingerprint_structure(connection: Any, table_name: str) -> dict[str, int | str]:
    digest = hashlib.sha256()
    digest.update(table_name.encode("ascii"))
    digest.update(b"\0")
    count = 0
    rows = connection.execute(
        text(f"SELECT to_jsonb(item) FROM public.{table_name} AS item ORDER BY id::text")
    ).scalars()
    for row in rows:
        canonical = json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest.update(len(canonical).to_bytes(8, "big"))
        digest.update(canonical)
        count += 1
    return {"count": count, "sha256": digest.hexdigest()}


def fingerprint_beta_database(
    database_url: str,
    *,
    cosmas_env: str,
    data_mode: str,
    database_engine: Engine | None = None,
    require_verify_full: bool = True,
) -> DatabaseFingerprintEvidence:
    """Read a consistent snapshot and expose only counts and deterministic hashes."""

    if cosmas_env != "early_adopter_beta" or data_mode != "synthetic":
        raise DatabaseFingerprintError("database fingerprint failed")
    _validate_database_url(database_url, require_verify_full=require_verify_full)
    engine = database_engine
    owns_engine = database_engine is None
    try:
        if engine is None:
            engine = _make_database_engine(database_url)
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                revision = connection.execute(
                    text("SELECT version_num FROM public.alembic_version")
                ).scalar_one()
                if revision != EXPECTED_SCHEMA_REVISION:
                    raise DatabaseFingerprintError("database fingerprint failed")
                structures = {
                    table_name: _fingerprint_structure(connection, table_name)
                    for table_name in _STRUCTURE_TABLES
                }
            finally:
                transaction.rollback()
    except DatabaseFingerprintError:
        raise
    except Exception:
        raise DatabaseFingerprintError("database fingerprint failed") from None
    finally:
        if owns_engine and engine is not None:
            try:
                engine.dispose()
            except Exception:
                raise DatabaseFingerprintError("database fingerprint failed") from None

    canonical_structures = json.dumps(structures, sort_keys=True, separators=(",", ":"))
    return DatabaseFingerprintEvidence(
        contract=DATABASE_FINGERPRINT_CONTRACT,
        status="ready",
        schema_revision=str(revision),
        schema_at_expected_head=True,
        structures=structures,
        aggregate_sha256=hashlib.sha256(canonical_structures.encode("utf-8")).hexdigest(),
    )
