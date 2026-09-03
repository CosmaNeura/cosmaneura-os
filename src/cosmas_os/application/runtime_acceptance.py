from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

from azure.core.exceptions import ResourceNotFoundError
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from cosmas_os.adapters.azure import AzureBlobAdapter
from cosmas_os.config import Settings
from cosmas_os.ports import BlobPort
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

RUNTIME_ACCEPTANCE_CONTRACT = "cosmas-os-d3-runtime-acceptance-v2"
_DATABASE_CONNECT_TIMEOUT_SECONDS = 5
_DATABASE_STATEMENT_TIMEOUT_MILLISECONDS = 5_000
_REDIS_TIMEOUT_SECONDS = 5
_REDIS_SENTINEL_TTL_SECONDS = 60
_SYNTHETIC_DATABASE_LABEL = "Cosmas synthetic runtime acceptance probe"


class RuntimeAcceptanceError(RuntimeError):
    """A live runtime dependency did not satisfy the sanitized D3 contract."""


class RedisProbeClient(Protocol):
    def set(
        self,
        name: str,
        value: bytes,
        *,
        ex: int,
        nx: bool,
    ) -> bool | None: ...

    def get(self, name: str) -> bytes | None: ...

    def delete(self, *names: str) -> int: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class RuntimeAcceptanceEvidence:
    contract: str
    status: str
    completed_at: str
    environment: str
    data_mode: str
    blob_backend: str
    sync_worker_disabled: bool
    user_assigned_managed_identity: bool
    blob_write_read_sha_match: bool
    blob_current_representation_absent_after_delete: bool
    blob_version_representations_absent_after_delete: bool
    blob_snapshot_representations_absent_after_delete: bool
    blob_deleted_representations_absent_after_delete: bool
    blob_recoverable_absence_verified: bool
    redis_round_trip: bool
    redis_cleanup_confirmed: bool
    database_schema_revision: str
    database_schema_at_expected_head: bool
    database_insert_read_rolled_back: bool

    def sanitized_payload(self) -> dict[str, str | bool]:
        return asdict(self)

    def sanitized_json(self) -> str:
        payload = self.sanitized_payload()
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["evidence_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def runtime_acceptance_failure_json() -> str:
    return json.dumps(
        {"contract": RUNTIME_ACCEPTANCE_CONTRACT, "status": "failed"},
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_client_id(value: str | None) -> str:
    try:
        canonical = str(UUID(value or ""))
    except ValueError:
        raise RuntimeAcceptanceError("runtime acceptance failed") from None
    if canonical.lower() != (value or "").lower():
        raise RuntimeAcceptanceError("runtime acceptance failed")
    return canonical


def _validate_runtime(
    runtime: Settings,
    managed_identity_client_id: str | None,
    expected_managed_identity_client_id: str | None,
) -> str:
    try:
        runtime.validate_runtime_configuration()
    except Exception:
        raise RuntimeAcceptanceError("runtime acceptance failed") from None

    if (
        runtime.cosmas_env != "early_adopter_beta"
        or runtime.data_mode != "synthetic"
        or runtime.blob_backend != "azure"
        or runtime.sync_worker
    ):
        raise RuntimeAcceptanceError("runtime acceptance failed")

    client_id = _canonical_client_id(managed_identity_client_id)
    expected_client_id = _canonical_client_id(expected_managed_identity_client_id)
    if client_id != expected_client_id:
        raise RuntimeAcceptanceError("runtime acceptance failed")
    return client_id


def _make_blob_adapter(runtime: Settings, client_id: str) -> AzureBlobAdapter:
    account_url = runtime.azure_storage_account_url
    container_name = runtime.azure_blob_container
    box_id = runtime.beta_box_id
    if not account_url or not container_name or not box_id:
        raise RuntimeAcceptanceError("runtime acceptance failed")
    return AzureBlobAdapter.from_user_assigned_managed_identity(
        account_url=account_url,
        container_name=container_name,
        box_id=box_id,
        client_id=client_id,
    )


def _make_redis_client(runtime: Settings) -> RedisProbeClient:
    return cast(
        RedisProbeClient,
        Redis.from_url(
            runtime.redis_url,
            socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
            socket_timeout=_REDIS_TIMEOUT_SECONDS,
            decode_responses=False,
        ),
    )


def _make_database_engine(runtime: Settings) -> Engine:
    return create_engine(
        runtime.database_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": _DATABASE_CONNECT_TIMEOUT_SECONDS,
            "options": f"-c statement_timeout={_DATABASE_STATEMENT_TIMEOUT_MILLISECONDS}",
        },
    )


def _blob_is_not_found(error: Exception) -> bool:
    return isinstance(error, ResourceNotFoundError)


def _verify_database(engine: Engine, probe_id: str) -> str:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            if revision != EXPECTED_SCHEMA_REVISION:
                raise RuntimeAcceptanceError("runtime acceptance failed")
            connection.execute(
                text(
                    "INSERT INTO public.box_contexts (id, display_name) "
                    "VALUES (:probe_id, :display_name)"
                ),
                {"probe_id": probe_id, "display_name": _SYNTHETIC_DATABASE_LABEL},
            )
            inserted = connection.execute(
                text("SELECT display_name FROM public.box_contexts WHERE id = :probe_id"),
                {"probe_id": probe_id},
            ).scalar_one()
            if inserted != _SYNTHETIC_DATABASE_LABEL:
                raise RuntimeAcceptanceError("runtime acceptance failed")
        finally:
            transaction.rollback()

        remains = connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM public.box_contexts WHERE id = :probe_id)"),
            {"probe_id": probe_id},
        ).scalar_one()
        connection.rollback()
        if remains:
            raise RuntimeAcceptanceError("runtime acceptance failed")
    return str(revision)


def verify_beta_runtime(
    runtime: Settings,
    *,
    managed_identity_client_id: str | None = None,
    expected_managed_identity_client_id: str | None = None,
    blob: BlobPort | None = None,
    redis_client: RedisProbeClient | None = None,
    database_engine: Engine | None = None,
    now: Callable[[], datetime] | None = None,
    blob_not_found: Callable[[Exception], bool] = _blob_is_not_found,
) -> RuntimeAcceptanceEvidence:
    """Exercise live D3 dependencies without persisting synthetic probe data."""

    client_id = _validate_runtime(
        runtime,
        managed_identity_client_id or os.environ.get("AZURE_CLIENT_ID"),
        expected_managed_identity_client_id
        or os.environ.get("EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID"),
    )
    box_id = runtime.beta_box_id
    if not box_id:
        raise RuntimeAcceptanceError("runtime acceptance failed")

    nonce = uuid4().hex
    blob_key = f"{box_id}/runtime-acceptance/{nonce}.bin"
    redis_key = f"{box_id}:cosmas-os:runtime-acceptance:{nonce}"
    blob_payload = secrets.token_bytes(64)
    redis_payload = secrets.token_bytes(32)

    actual_blob: BlobPort | None = blob
    actual_redis: RedisProbeClient | None = redis_client
    actual_engine: Engine | None = database_engine
    owns_redis = redis_client is None
    owns_engine = database_engine is None
    blob_cleanup_required = False
    redis_cleanup_required = False
    failed = False
    cleanup_ok = True
    database_revision: str | None = None
    blob_absence_verified = False

    try:
        if actual_blob is None:
            actual_blob = _make_blob_adapter(runtime, client_id)
        if actual_redis is None:
            actual_redis = _make_redis_client(runtime)
        if actual_engine is None:
            actual_engine = _make_database_engine(runtime)

        blob_cleanup_required = True
        stored_name = actual_blob.put_bytes(blob_key, blob_payload, "application/octet-stream")
        if stored_name != blob_key:
            raise RuntimeAcceptanceError("runtime acceptance failed")
        downloaded = actual_blob.get_bytes(blob_key)
        if not secrets.compare_digest(
            hashlib.sha256(downloaded).digest(), hashlib.sha256(blob_payload).digest()
        ):
            raise RuntimeAcceptanceError("runtime acceptance failed")
        actual_blob.delete(blob_key)
        try:
            actual_blob.get_bytes(blob_key)
        except Exception as error:  # noqa: BLE001 - provider-specific absence is normalized
            if not blob_not_found(error):
                raise RuntimeAcceptanceError("runtime acceptance failed") from None
        else:
            raise RuntimeAcceptanceError("runtime acceptance failed")
        absence = actual_blob.probe_recoverable_absence(blob_key)
        if not absence.verified:
            raise RuntimeAcceptanceError("runtime acceptance failed")
        blob_absence_verified = True
        blob_cleanup_required = False

        redis_cleanup_required = True
        if (
            actual_redis.set(
                redis_key,
                redis_payload,
                ex=_REDIS_SENTINEL_TTL_SECONDS,
                nx=True,
            )
            is not True
        ):
            raise RuntimeAcceptanceError("runtime acceptance failed")
        cached = actual_redis.get(redis_key)
        if not isinstance(cached, bytes) or not secrets.compare_digest(cached, redis_payload):
            raise RuntimeAcceptanceError("runtime acceptance failed")
        if actual_redis.delete(redis_key) != 1 or actual_redis.get(redis_key) is not None:
            raise RuntimeAcceptanceError("runtime acceptance failed")
        redis_cleanup_required = False

        database_revision = _verify_database(actual_engine, str(uuid4()))
    except Exception:  # noqa: BLE001 - the CLI exposes only the generic contract failure
        failed = True
    finally:
        if blob_cleanup_required and actual_blob is not None:
            try:
                actual_blob.delete(blob_key)
            except Exception as error:  # noqa: BLE001 - cleanup is best effort and never reflected
                if not blob_not_found(error):
                    cleanup_ok = False
        if redis_cleanup_required and actual_redis is not None:
            try:
                actual_redis.delete(redis_key)
            except Exception:  # noqa: BLE001 - cleanup is best effort and never reflected
                cleanup_ok = False
        if owns_redis and actual_redis is not None:
            try:
                actual_redis.close()
            except Exception:  # noqa: BLE001 - resource-close failure fails the attestation
                cleanup_ok = False
        if owns_engine and actual_engine is not None:
            try:
                actual_engine.dispose()
            except Exception:  # noqa: BLE001 - resource-close failure fails the attestation
                cleanup_ok = False

    if (
        failed
        or not cleanup_ok
        or not blob_absence_verified
        or database_revision != EXPECTED_SCHEMA_REVISION
    ):
        raise RuntimeAcceptanceError("runtime acceptance failed")

    completed = (now or (lambda: datetime.now(UTC)))().astimezone(UTC).replace(microsecond=0)
    return RuntimeAcceptanceEvidence(
        contract=RUNTIME_ACCEPTANCE_CONTRACT,
        status="ready",
        completed_at=completed.isoformat().replace("+00:00", "Z"),
        environment="early_adopter_beta",
        data_mode="synthetic",
        blob_backend="azure",
        sync_worker_disabled=True,
        user_assigned_managed_identity=True,
        blob_write_read_sha_match=True,
        blob_current_representation_absent_after_delete=True,
        blob_version_representations_absent_after_delete=True,
        blob_snapshot_representations_absent_after_delete=True,
        blob_deleted_representations_absent_after_delete=True,
        blob_recoverable_absence_verified=True,
        redis_round_trip=True,
        redis_cleanup_confirmed=True,
        database_schema_revision=database_revision,
        database_schema_at_expected_head=True,
        database_insert_read_rolled_back=True,
    )
