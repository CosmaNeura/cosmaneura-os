from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from azure.core.exceptions import ResourceNotFoundError
from sqlalchemy import func, select

from cosmas_os.application.runtime_acceptance import (
    RUNTIME_ACCEPTANCE_CONTRACT,
    RuntimeAcceptanceError,
    verify_beta_runtime,
)
from cosmas_os.config import Settings
from cosmas_os.models import BoxContext
from cosmas_os.ports import BlobRepresentationAbsence


class FakeBlob:
    def __init__(
        self,
        *,
        fail_read: bool = False,
        recoverable_representation: bool = False,
    ) -> None:
        self.store: dict[str, bytes] = {}
        self.fail_read = fail_read
        self.recoverable_representation = recoverable_representation
        self.delete_calls = 0

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        assert content_type == "application/octet-stream"
        assert "/runtime-acceptance/" in key
        self.store[key] = data
        return key

    def get_bytes(self, key: str) -> bytes:
        if self.fail_read:
            raise RuntimeError("invented secret Blob failure")
        try:
            return self.store[key]
        except KeyError:
            raise ResourceNotFoundError("invented missing Blob") from None

    def delete(self, key: str) -> None:
        self.delete_calls += 1
        if key not in self.store:
            raise ResourceNotFoundError("invented missing Blob")
        del self.store[key]

    def probe_recoverable_absence(self, key: str) -> BlobRepresentationAbsence:
        exact_current_absent = key not in self.store
        return BlobRepresentationAbsence(
            current_absent=exact_current_absent,
            versions_absent=not self.recoverable_representation,
            snapshots_absent=True,
            deleted_absent=True,
        )

    def issue_upload_token(self, artifact_id: str) -> str:
        raise AssertionError("runtime acceptance does not issue upload tokens")

    def consume_upload_token(self, token: str) -> str:
        raise AssertionError("runtime acceptance does not consume upload tokens")


class FakeRedis:
    def __init__(self, *, fail_read: bool = False) -> None:
        self.store: dict[str, bytes] = {}
        self.fail_read = fail_read
        self.delete_calls = 0

    def set(self, name: str, value: bytes, *, ex: int, nx: bool) -> bool | None:
        assert ":cosmas-os:runtime-acceptance:" in name
        assert ex == 60
        assert nx is True
        if name in self.store:
            return None
        self.store[name] = value
        return True

    def get(self, name: str) -> bytes | None:
        if self.fail_read:
            raise RuntimeError("invented secret Redis failure")
        return self.store.get(name)

    def delete(self, *names: str) -> int:
        self.delete_calls += 1
        deleted = 0
        for name in names:
            if name in self.store:
                del self.store[name]
                deleted += 1
        return deleted

    def close(self) -> None:
        return


def beta_settings(*, box_id: str | None = None) -> Settings:
    return Settings(
        database_url=(
            "postgresql+psycopg://runtime:invented-secret@database.example.invalid/"
            "cosmas_os?sslmode=verify-full&sslrootcert=system"
        ),
        redis_url=(
            "rediss://:invented-secret@redis.example.invalid:10000/0?ssl_cert_reqs=required"
        ),
        cosmas_env="early_adopter_beta",
        data_mode="synthetic",
        auth_mode="clerk_jwt",
        cors_allowed_origins="https://web.example.invalid",
        synth_seed=False,
        blob_backend="azure",
        azure_storage_account_url="https://storage.example.invalid",
        azure_blob_container="box-artifacts",
        clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-beta",
        clerk_organization_id="org_synthetic",
        clerk_authorized_parties="https://web.example.invalid",
        beta_box_id=box_id or str(uuid4()),
        human_deploy_evidence_ref="review:synthetic-runtime-acceptance",
        sync_worker=False,
    )


def test_runtime_acceptance_exercises_dependencies_and_rolls_back_database(engine) -> None:
    blob = FakeBlob()
    redis = FakeRedis()
    runtime = beta_settings()
    before = engine.connect()
    try:
        box_count_before = before.scalar(select(func.count()).select_from(BoxContext))
    finally:
        before.close()

    evidence = verify_beta_runtime(
        runtime,
        managed_identity_client_id="11111111-1111-4111-8111-111111111111",
        expected_managed_identity_client_id="11111111-1111-4111-8111-111111111111",
        blob=blob,
        redis_client=redis,
        database_engine=engine,
        now=lambda: datetime(2026, 9, 3, 16, 0, tzinfo=UTC),
    )

    after = engine.connect()
    try:
        box_count_after = after.scalar(select(func.count()).select_from(BoxContext))
    finally:
        after.close()
    assert box_count_after == box_count_before
    assert blob.store == {}
    assert redis.store == {}
    assert evidence.database_insert_read_rolled_back is True
    assert evidence.sync_worker_disabled is True
    assert evidence.blob_recoverable_absence_verified is True

    payload = json.loads(evidence.sanitized_json())
    evidence_hash = payload.pop("evidence_sha256")
    assert payload == evidence.sanitized_payload()
    assert (
        evidence_hash
        == hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert payload["contract"] == RUNTIME_ACCEPTANCE_CONTRACT
    assert payload["completed_at"] == "2026-09-03T16:00:00Z"
    serialized = evidence.sanitized_json()
    assert runtime.beta_box_id is not None
    assert runtime.beta_box_id not in serialized
    assert "invented-secret" not in serialized


def test_runtime_acceptance_cleans_blob_after_mid_probe_failure(engine) -> None:
    blob = FakeBlob(fail_read=True)

    with pytest.raises(RuntimeAcceptanceError, match="runtime acceptance failed"):
        verify_beta_runtime(
            beta_settings(),
            managed_identity_client_id="11111111-1111-4111-8111-111111111111",
            expected_managed_identity_client_id="11111111-1111-4111-8111-111111111111",
            blob=blob,
            redis_client=FakeRedis(),
            database_engine=engine,
        )

    assert blob.store == {}
    assert blob.delete_calls == 1


def test_runtime_acceptance_cleans_redis_after_mid_probe_failure(engine) -> None:
    redis = FakeRedis(fail_read=True)

    with pytest.raises(RuntimeAcceptanceError, match="runtime acceptance failed"):
        verify_beta_runtime(
            beta_settings(),
            managed_identity_client_id="11111111-1111-4111-8111-111111111111",
            expected_managed_identity_client_id="11111111-1111-4111-8111-111111111111",
            blob=FakeBlob(),
            redis_client=redis,
            database_engine=engine,
        )

    assert redis.store == {}
    assert redis.delete_calls == 1


def test_runtime_acceptance_rejects_a_recoverable_blob_version(engine) -> None:
    blob = FakeBlob(recoverable_representation=True)

    with pytest.raises(RuntimeAcceptanceError, match="runtime acceptance failed"):
        verify_beta_runtime(
            beta_settings(),
            managed_identity_client_id="11111111-1111-4111-8111-111111111111",
            expected_managed_identity_client_id="11111111-1111-4111-8111-111111111111",
            blob=blob,
            redis_client=FakeRedis(),
            database_engine=engine,
        )

    assert blob.store == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cosmas_env", "synth_os"),
        ("data_mode", "authorized_beta"),
        ("blob_backend", "local"),
        ("sync_worker", True),
    ],
)
def test_runtime_acceptance_rejects_wrong_runtime_before_side_effects(
    engine, field: str, value: object
) -> None:
    blob = FakeBlob()
    redis = FakeRedis()
    runtime = beta_settings().model_copy(update={field: value})

    with pytest.raises(RuntimeAcceptanceError, match="runtime acceptance failed"):
        verify_beta_runtime(
            runtime,
            managed_identity_client_id="11111111-1111-4111-8111-111111111111",
            expected_managed_identity_client_id="11111111-1111-4111-8111-111111111111",
            blob=blob,
            redis_client=redis,
            database_engine=engine,
        )

    assert blob.store == {}
    assert redis.store == {}


def test_runtime_acceptance_rejects_missing_exact_uami_before_side_effects(engine) -> None:
    blob = FakeBlob()

    with pytest.raises(RuntimeAcceptanceError, match="runtime acceptance failed"):
        verify_beta_runtime(
            beta_settings(),
            managed_identity_client_id="not-a-managed-identity-client-id",
            expected_managed_identity_client_id="11111111-1111-4111-8111-111111111111",
            blob=blob,
            redis_client=FakeRedis(),
            database_engine=engine,
        )

    assert blob.store == {}


@pytest.mark.parametrize(
    ("actual_client_id", "expected_client_id"),
    [
        ("11111111-1111-4111-8111-111111111111", None),
        (
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        ),
    ],
)
def test_runtime_acceptance_rejects_unbound_uami_before_side_effects(
    engine, actual_client_id: str, expected_client_id: str | None
) -> None:
    blob = FakeBlob()

    with pytest.raises(RuntimeAcceptanceError, match="runtime acceptance failed"):
        verify_beta_runtime(
            beta_settings(),
            managed_identity_client_id=actual_client_id,
            expected_managed_identity_client_id=expected_client_id,
            blob=blob,
            redis_client=FakeRedis(),
            database_engine=engine,
        )

    assert blob.store == {}
