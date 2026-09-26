"""Exact Core-mediated Athena observations; no external services or database."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.core_athena import PATH
from cosmas_os.adapters.core_encounters import CoreEncounterConnection
from cosmas_os.application.core_connection import COMMAND_ADAPTER
from cosmas_os.application.core_record_deadline import RecordDeadline
from cosmas_os.config import Settings
from cosmas_os.ports.athena_schedule import (
    AthenaCommand,
    AthenaScheduleRequest,
    AthenaScheduleResponse,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_encounters import digest


def fixture():
    suffix = "00000000000000000000000001"
    content = dict(
        actor_ref="authority_actor_" + suffix,
        tenant_ref="authority_tenant_" + suffix,
        provider_link_ref="scribe_provider_link_" + suffix,
        practice_ref="practice_" + suffix,
        practice_label="Invented practice",
        review_sha256="a" * 64,
    )
    connection = {**content, "connection_sha256": digest(content)}
    request = AthenaScheduleRequest(
        action="appointments",
        request_nonce=uuid4(),
        expected_tenant_ref=content["tenant_ref"],
        expected_actor_ref=content["actor_ref"],
        connection_sha256=connection["connection_sha256"],
        account_sha256="b" * 64,
        start_date="2026-11-01",
        end_date="2026-11-01",
        offset=0,
    )
    account = dict(
        account_ref=str(uuid4()),
        account_sha256=request.account_sha256,
        department_label="Invented office",
        department_timezone="America/New_York",
        environment="preview",
        state="practice_enabled",
        access="appointments_read_only",
    )
    row = dict(
        appointment_ref="8001",
        patient_ref="9001",
        source_local_start="2026-11-01T01:30:00",
        department_timezone=account["department_timezone"],
        duration_minutes=30,
        source_status="f",
    )
    row["source_sha256"] = digest({"account_sha256": request.account_sha256, **row})
    result = dict(
        action="appointments",
        request_nonce=str(request.request_nonce),
        checked_at=datetime.now(UTC).isoformat(),
        connection=connection,
        account=account,
        appointments=[row],
        total_count=1,
        next_offset=None,
        complete=True,
        truncated=False,
    )
    return request, result


def read(request, payload, status=200):
    calls = []

    def handler(incoming):
        calls.append(incoming)
        assert str(incoming.url) == "https://core.example.invalid" + PATH
        assert incoming.headers["authorization"] == "Bearer invented-session"
        assert incoming.headers["x-cosmaneura-athena-version"] == "1"
        assert "cookie" not in incoming.headers
        assert json.loads(incoming.content) == request.model_dump(mode="json")
        return httpx.Response(
            status,
            content=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "X-Cosmaneura-Athena-Version": "1",
            },
        )

    port = CoreEncounterConnection(
        "https://core.example.invalid",
        RecordDeadline(),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    try:
        result = port.read_athena(request, SecretStr("invented-session"))
        assert len(calls) == 1
        return result
    finally:
        port.close()


def test_actual_adapter_preserves_source_local_time_and_checks_projection():
    request, payload = fixture()
    result = read(request, payload)
    assert result == AthenaScheduleResponse.model_validate(payload)
    assert result.appointments[0].source_local_start == datetime(2026, 11, 1, 1, 30)
    assert result.appointments[0].source_local_start.tzinfo is None


@pytest.mark.parametrize(
    "fault",
    [
        "nonce",
        "actor",
        "account",
        "digest",
        "window",
        "timezone",
        "duplicate",
        "pagination",
        "stale",
        "redirect",
        "extra",
    ],
)
def test_wrong_or_stale_scope_never_reaches_client(fault):
    request, p = fixture()
    status = 200
    if fault == "nonce":
        p["request_nonce"] = str(uuid4())
    if fault == "actor":
        p["connection"]["actor_ref"] = "authority_actor_00000000000000000000000002"
        p["connection"]["connection_sha256"] = digest(
            {k: v for k, v in p["connection"].items() if k != "connection_sha256"}
        )
    if fault == "account":
        p["account"]["account_sha256"] = "c" * 64
    if fault == "digest":
        p["appointments"][0]["source_sha256"] = "c" * 64
    if fault == "window":
        row = p["appointments"][0]
        row["source_local_start"] = "2026-11-02T01:30:00"
        row["source_sha256"] = digest(
            {
                "account_sha256": p["account"]["account_sha256"],
                **{k: v for k, v in row.items() if k != "source_sha256"},
            }
        )
    if fault == "timezone":
        p["account"]["department_timezone"] = "Invalid/Zone"
    if fault == "duplicate":
        p["appointments"].append(p["appointments"][0])
        p["total_count"] = 2
    if fault == "pagination":
        p["next_offset"] = 1
    if fault == "stale":
        p["checked_at"] = "2000-01-01T00:00:00Z"
    if fault == "redirect":
        status = 302
    if fault == "extra":
        p["private_note"] = "Invented unrelated data"
    with pytest.raises(ConnectorUnavailable):
        read(request, p, status)


def test_ready_profile_is_not_a_successfully_read_schedule():
    request, p = fixture()
    request = AthenaScheduleRequest(
        action="connection",
        request_nonce=request.request_nonce,
        expected_tenant_ref=request.expected_tenant_ref,
        expected_actor_ref=request.expected_actor_ref,
        connection_sha256=request.connection_sha256,
    )
    p.update(
        action="connection", appointments=[], total_count=None, next_offset=None, complete=False
    )
    assert read(request, p).account.state == "practice_enabled"
    p["complete"] = True
    with pytest.raises(ConnectorUnavailable):
        read(request, p)


@pytest.mark.parametrize(
    "extra",
    [
        {"provider_id": "702"},
        {"core_actor_ref": "untrusted"},
        {"offset": -1},
        {"offset": True},
        {"end_date": "2026-12-02"},
    ],
)
def test_renderer_cannot_supply_scope_or_unbounded_dates(extra):
    command = dict(
        action="athena_appointments",
        request_nonce=str(uuid4()),
        connection_sha256="a" * 64,
        account_sha256="b" * 64,
        start_date="2026-11-01",
        end_date="2026-11-01",
        offset=0,
    )
    assert isinstance(COMMAND_ADAPTER.validate_python(command), AthenaCommand)
    with pytest.raises(ValueError):
        COMMAND_ADAPTER.validate_python(command | extra)


def test_enabled_athena_profile_starts_and_missing_core_fails_without_recursion():
    values = dict(
        _env_file=None,
        workspace_enabled=True,
        workspace_authenticated_enabled=True,
        synth_seed=False,
        auth_mode="clerk_jwt",
        database_url="postgresql+psycopg://synthetic@127.0.0.1/w1a_synthetic",
        clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="synthetic",
        clerk_organization_id="org_synthetic",
        clerk_authorized_parties="http://localhost:5173",
        beta_box_id=str(uuid4()),
        cors_allowed_origins="http://localhost:5173",
        workspace_core_connection_enabled=True,
        core_capture_origin="https://core.example.invalid",
        core_connection_tenant_ref="authority_tenant_00000000000000000000000001",
    )
    assert not Settings(**values).workspace_athena_connection_available
    enabled = Settings(**values, workspace_athena_connection_enabled=True)
    assert enabled.workspace_available and enabled.workspace_athena_connection_available
    assert not enabled.runtime_configuration_errors()
    for missing in (
        {"workspace_core_connection_enabled": False},
        {"core_capture_origin": ""},
        {"core_connection_tenant_ref": ""},
        {"clerk_audience": ""},
    ):
        config = Settings(**(values | missing), workspace_athena_connection_enabled=True)
        assert not config.workspace_athena_connection_available
        assert (
            "Athena connection requires an authenticated, configured Core connection"
            in config.runtime_configuration_errors()
        )
