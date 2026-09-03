from __future__ import annotations

import hashlib
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from cosmas_os.application.database_fingerprint import (
    DATABASE_FINGERPRINT_CONTRACT,
    DatabaseFingerprintError,
    fingerprint_beta_database,
)
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION


def test_database_fingerprint_is_deterministic_and_detects_structural_change(engine) -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os",
    )
    probe_id = str(uuid4())
    probe_label = "Synthetic restore fingerprint probe"

    first = fingerprint_beta_database(
        database_url,
        cosmas_env="early_adopter_beta",
        data_mode="synthetic",
        database_engine=engine,
        require_verify_full=False,
    )
    repeated = fingerprint_beta_database(
        database_url,
        cosmas_env="early_adopter_beta",
        data_mode="synthetic",
        database_engine=engine,
        require_verify_full=False,
    )
    assert first == repeated

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO public.box_contexts (id, display_name) "
                    "VALUES (:probe_id, :display_name)"
                ),
                {"probe_id": probe_id, "display_name": probe_label},
            )

        changed = fingerprint_beta_database(
            database_url,
            cosmas_env="early_adopter_beta",
            data_mode="synthetic",
            database_engine=engine,
            require_verify_full=False,
        )

        assert changed.aggregate_sha256 != first.aggregate_sha256
        initial_box_count = first.structures["box_contexts"]["count"]
        assert isinstance(initial_box_count, int)
        assert changed.structures["box_contexts"]["count"] == initial_box_count + 1
        assert changed.structures["box_contexts"]["sha256"] != (
            first.structures["box_contexts"]["sha256"]
        )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM public.box_contexts WHERE id = :probe_id"),
                {"probe_id": probe_id},
            )

    restored = fingerprint_beta_database(
        database_url,
        cosmas_env="early_adopter_beta",
        data_mode="synthetic",
        database_engine=engine,
        require_verify_full=False,
    )
    assert restored == first
    assert restored.contract == DATABASE_FINGERPRINT_CONTRACT
    assert restored.schema_revision == EXPECTED_SCHEMA_REVISION

    payload = json.loads(restored.sanitized_json())
    evidence_hash = payload.pop("evidence_sha256")
    assert evidence_hash == hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    serialized = restored.sanitized_json()
    assert probe_id not in serialized
    assert probe_label not in serialized
    assert database_url not in serialized


@pytest.mark.parametrize(
    "database_url",
    [
        "",
        "sqlite+pysqlite:///:memory:",
        "postgresql+psycopg://runtime@database.example.invalid/cosmas_os?sslmode=verify-full&sslrootcert=system",
        "postgresql+psycopg://runtime:secret@localhost/cosmas_os?sslmode=verify-full&sslrootcert=system",
        "postgresql+psycopg://runtime:secret@database.example.invalid/other?sslmode=verify-full&sslrootcert=system",
        "postgresql+psycopg://runtime:secret@database.example.invalid/cosmas_os?sslmode=require&sslrootcert=system",
        "postgresql+psycopg://runtime:secret@database.example.invalid/cosmas_os?sslmode=verify-full&sslrootcert=system&application_name=unreviewed",
    ],
)
def test_database_fingerprint_rejects_unsafe_target_before_connect(database_url: str) -> None:
    with pytest.raises(DatabaseFingerprintError, match="database fingerprint failed"):
        fingerprint_beta_database(
            database_url,
            cosmas_env="early_adopter_beta",
            data_mode="synthetic",
        )


@pytest.mark.parametrize(
    ("cosmas_env", "data_mode"),
    [("synth_os", "synthetic"), ("early_adopter_beta", "authorized_beta")],
)
def test_database_fingerprint_function_rejects_non_synthetic_beta_mode(
    engine, cosmas_env: str, data_mode: str
) -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os",
    )
    with pytest.raises(DatabaseFingerprintError, match="database fingerprint failed"):
        fingerprint_beta_database(
            database_url,
            cosmas_env=cosmas_env,
            data_mode=data_mode,
            database_engine=engine,
            require_verify_full=False,
        )
