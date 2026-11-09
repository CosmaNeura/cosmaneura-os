"""C9: athena today's schedule from Encounter FHIR — mocks, flags, and refusals."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.athena_fhir_r4 import (
    ATHENA_FHIR_SYSTEM_READ_SCOPES,
    ATHENA_FHIR_TOKEN_URL,
    ATHENA_PRACTICE_PARAM,
    ATHENA_PRACTICE_VALUE,
    AthenaFhirR4Adapter,
)
from cosmas_os.adapters.athena_fhir_schedule_read import (
    AthenaFhirScheduleError,
    assert_no_appointment_calls,
    preview_schedule_account,
    read_athena_fhir_schedule,
)
from cosmas_os.adapters.athena_fhir_schedule_runtime import AthenaFhirScheduleReads
from cosmas_os.adapters.ehr_auth import (
    ATHENA_FHIR_CLIENT_ID_REF,
    ATHENA_FHIR_CLIENT_SECRET_REF,
    ClientCredentialsConfig,
    ClientCredentialsTokenClient,
    ManagedSecretEnvResolver,
)
from cosmas_os.application.ehr_fhir_us_core_mapping import (
    map_encounter_to_schedule,
    vendor_numeric_id,
)
from cosmas_os.config import Settings
from cosmas_os.ports.athena_schedule import AthenaScheduleRequest
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_encounters import digest

FIXTURES = Path(__file__).parent / "fixtures" / "ehr_fhir"
BUNDLE = json.loads((FIXTURES / "schedule_encounter_bundle.json").read_text())
FAKE_CLIENT_ID = "fake-athena-fhir-c9-client-id-PLACEHOLDER"
FAKE_CLIENT_SECRET = "fake-athena-fhir-c9-client-secret-PLACEHOLDER"
CANARY_TOKEN = "CANARY_ATHENA_FHIR_C9_TOKEN_aa11bb22_NEVER_LOG"
CANARY_SECRET = "CANARY_ATHENA_FHIR_C9_SECRET_cc33dd44_NEVER_LOG"
READ_TIME = datetime(2026, 11, 9, 16, 0, 0, tzinfo=UTC)


def connection_snapshot():
    content = dict(
        actor_ref="authority_actor_00000000000000000000000001",
        tenant_ref="authority_tenant_00000000000000000000000001",
        provider_link_ref="scribe_provider_link_00000000000000000000000001",
        practice_ref="practice_00000000000000000000000001",
        practice_label="Invented practice",
        review_sha256="a" * 64,
    )
    return {**content, "connection_sha256": digest(content)}


CONNECTION = connection_snapshot()


def schedule_request(action="appointments", **changes):
    account = preview_schedule_account()
    body = dict(
        action=action,
        request_nonce=uuid4(),
        expected_tenant_ref=CONNECTION["tenant_ref"],
        expected_actor_ref=CONNECTION["actor_ref"],
        connection_sha256=CONNECTION["connection_sha256"],
    )
    if action == "appointments":
        body.update(
            account_sha256=account.account_sha256,
            start_date=date(2026, 11, 9),
            end_date=date(2026, 11, 9),
            offset=0,
        )
    body.update(changes)
    return AthenaScheduleRequest.model_validate(body)


class InventedScheduleFhir:
    def __init__(self):
        self.token_calls = 0
        self.fhir_calls: list[str] = []
        self.bundle = deepcopy(BUNDLE)
        self.access_token = CANARY_TOKEN
        self.fail = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url.rstrip("/") == ATHENA_FHIR_TOKEN_URL:
            self.token_calls += 1
            return httpx.Response(
                200,
                json={
                    "access_token": self.access_token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": " ".join(sorted(ATHENA_FHIR_SYSTEM_READ_SCOPES)),
                },
            )
        assert request.method == "GET"
        self.fhir_calls.append(url)
        if self.fail:
            raise httpx.ReadTimeout("invented athena schedule failure", request=request)
        assert "/Appointment" not in request.url.path
        assert request.url.path.endswith("/Encounter")
        raw = request.url.query
        if isinstance(raw, bytes):
            raw = raw.decode()
        assert f"{ATHENA_PRACTICE_PARAM}={ATHENA_PRACTICE_VALUE}" in raw.replace("%2F", "/")
        assert "system/Appointment.read" not in raw
        return httpx.Response(
            200,
            headers={"Content-Type": "application/fhir+json"},
            content=json.dumps(self.bundle).encode(),
        )


def token_client(transport, monkeypatch):
    monkeypatch.setenv(ATHENA_FHIR_CLIENT_ID_REF, FAKE_CLIENT_ID)
    monkeypatch.setenv(ATHENA_FHIR_CLIENT_SECRET_REF, FAKE_CLIENT_SECRET)
    return ClientCredentialsTokenClient(
        config=ClientCredentialsConfig(
            client_id_ref=ATHENA_FHIR_CLIENT_ID_REF,
            client_secret_ref=ATHENA_FHIR_CLIENT_SECRET_REF,
            token_url=ATHENA_FHIR_TOKEN_URL,
            scopes=ATHENA_FHIR_SYSTEM_READ_SCOPES,
        ),
        secrets=ManagedSecretEnvResolver(),
        transport=transport,
    )


def adapter(provider, monkeypatch, *, sandbox=True):
    transport = httpx.MockTransport(provider)
    return AthenaFhirR4Adapter(
        token_client=token_client(transport, monkeypatch),
        transport=transport,
        sandbox_enabled=sandbox,
    )


def test_map_encounter_to_schedule_local_time_and_status():
    resource = BUNDLE["entry"][0]["resource"]
    mapped = map_encounter_to_schedule(
        resource,
        vendor="athena",
        read_time=READ_TIME,
        department_timezone="America/New_York",
    )
    assert mapped.appointment_ref == "8001"
    assert mapped.patient_ref == "9001"
    assert mapped.source_status == "f"
    assert mapped.duration_minutes == 30
    assert mapped.source_local_start == datetime(2026, 11, 9, 9, 30, 0)
    assert mapped.source_local_start.tzinfo is None
    cancelled = map_encounter_to_schedule(
        BUNDLE["entry"][1]["resource"],
        vendor="athena",
        read_time=READ_TIME,
        department_timezone="America/New_York",
    )
    assert cancelled.source_status == "x"
    assert cancelled.duration_minutes == 45


def test_vendor_numeric_id_accepts_athena_style_suffix():
    assert vendor_numeric_id("8001") == "8001"
    assert vendor_numeric_id("a-1.Encounter-8001") == "8001"
    assert vendor_numeric_id("synth-encounter-2001") == "2001"
    with pytest.raises(ValueError):
        vendor_numeric_id("synth-encounter")
    with pytest.raises(ValueError):
        vendor_numeric_id("0")


def test_preview_account_is_stable():
    first = preview_schedule_account()
    second = preview_schedule_account()
    assert first.account_sha256 == second.account_sha256
    assert first.environment == "preview"
    assert "195900" in first.department_label


def test_connection_action_does_not_mint_token_or_call_fhir(monkeypatch):
    from cosmas_os.ports.core_encounters import ConnectionSnapshot

    provider = InventedScheduleFhir()
    result = read_athena_fhir_schedule(
        adapter(provider, monkeypatch),
        schedule_request("connection"),
        connection=ConnectionSnapshot.model_validate(CONNECTION),
        now=READ_TIME,
    )
    assert result.action == "connection"
    assert result.account is not None
    assert result.appointments == ()
    assert provider.token_calls == 0
    assert provider.fhir_calls == []


def test_appointments_from_encounter_bundle(monkeypatch):
    from cosmas_os.ports.core_encounters import ConnectionSnapshot

    provider = InventedScheduleFhir()
    conn = ConnectionSnapshot.model_validate(CONNECTION)
    result = read_athena_fhir_schedule(
        adapter(provider, monkeypatch),
        schedule_request("appointments"),
        connection=conn,
        now=READ_TIME,
    )
    assert result.action == "appointments"
    assert result.total_count == 2
    assert result.complete is True
    assert [row.appointment_ref for row in result.appointments] == ["8001", "8002"]
    assert result.appointments[0].source_status == "f"
    assert result.appointments[1].source_status == "x"
    assert provider.token_calls == 1
    assert_no_appointment_calls(provider.fhir_calls)
    shown = result.model_dump_json()
    assert CANARY_TOKEN not in shown
    assert CANARY_SECRET not in shown
    assert FAKE_CLIENT_SECRET not in shown


def test_sandbox_flag_off_refuses_before_token(monkeypatch):
    from cosmas_os.ports.core_encounters import ConnectionSnapshot

    provider = InventedScheduleFhir()
    with pytest.raises(AthenaFhirScheduleError) as raised:
        read_athena_fhir_schedule(
            adapter(provider, monkeypatch, sandbox=False),
            schedule_request("appointments"),
            connection=ConnectionSnapshot.model_validate(CONNECTION),
            now=READ_TIME,
        )
    assert raised.value.code == "sandbox_flag_required"
    assert provider.token_calls == 0
    assert provider.fhir_calls == []


def test_appointment_resource_assert_refused(monkeypatch):

    provider = InventedScheduleFhir()
    built = adapter(provider, monkeypatch)
    with pytest.raises(Exception) as raised:
        built.assert_resource_allowed("Appointment")
    assert raised.value.code == "resource_unsupported"
    assert "Appointment" not in " ".join(ATHENA_FHIR_SYSTEM_READ_SCOPES)


def test_runtime_sandbox_off_refuses_before_companion(monkeypatch):
    provider = InventedScheduleFhir()
    transport = httpx.MockTransport(provider)
    runtime = AthenaFhirScheduleReads(
        token_client=token_client(transport, monkeypatch),
        transport=transport,
        sandbox_enabled=False,
        enabled=True,
    )

    class Boom:
        def read(self, *args, **kwargs):
            raise AssertionError("companion must not be called when sandbox is off")

    with pytest.raises(ConnectorUnavailable):
        runtime.read_schedule(
            Boom(),
            schedule_request("appointments"),
            SecretStr("invented-session"),
        )
    assert provider.token_calls == 0


def test_runtime_reads_schedule_via_companion_then_encounter(monkeypatch):
    from cosmas_os.ports.core_encounters import ConnectionSnapshot, DiscoveryResponse

    provider = InventedScheduleFhir()
    transport = httpx.MockTransport(provider)
    runtime = AthenaFhirScheduleReads(
        token_client=token_client(transport, monkeypatch),
        transport=transport,
        sandbox_enabled=True,
        enabled=True,
    )
    request = schedule_request("appointments")
    companion_calls = []

    class Companion:
        def read(self, discovery_request, bearer):
            companion_calls.append(discovery_request)
            assert discovery_request.expected_tenant_ref == request.expected_tenant_ref
            assert bearer.get_secret_value() == "invented-session"
            return DiscoveryResponse(
                action="connection",
                request_nonce=discovery_request.request_nonce,
                checked_at=READ_TIME,
                connection=ConnectionSnapshot.model_validate(CONNECTION),
                encounters=(),
                next_cursor=None,
            )

        def read_athena(self, *args, **kwargs):
            raise AssertionError("Core appointments/read must not be used")

    result = runtime.read_schedule(Companion(), request, SecretStr("invented-session"), now=READ_TIME)
    assert len(companion_calls) == 1
    assert result.total_count == 2
    assert_no_appointment_calls(provider.fhir_calls)
    assert provider.token_calls == 1
    shown = result.model_dump_json()
    assert CANARY_TOKEN not in shown and CANARY_SECRET not in shown


def test_canary_absent_when_fhir_fails(monkeypatch):
    from cosmas_os.ports.core_encounters import ConnectionSnapshot

    provider = InventedScheduleFhir()
    provider.fail = True
    monkeypatch.setenv(ATHENA_FHIR_CLIENT_SECRET_REF, CANARY_SECRET)
    with pytest.raises(AthenaFhirScheduleError) as raised:
        read_athena_fhir_schedule(
            adapter(provider, monkeypatch),
            schedule_request("appointments"),
            connection=ConnectionSnapshot.model_validate(CONNECTION),
            now=READ_TIME,
        )
    text = repr(raised.value) + raised.value.code
    assert CANARY_TOKEN not in text and CANARY_SECRET not in text
    assert FAKE_CLIENT_ID not in text


def test_flags_off_leave_schedule_unavailable_for_existing_users():
    cfg = Settings()
    assert cfg.workspace_athena_fhir_sandbox_available is False
    assert cfg.workspace_athena_connection_available is False
    assert cfg.workspace_athena_fhir_sandbox_enabled is False
    assert cfg.workspace_ehr_read_enabled is False


def test_both_c8_flags_required_for_fhir_schedule_gate():
    only_ehr = Settings().model_copy(update={
        "workspace_ehr_read_enabled": True,
        "workspace_athena_fhir_sandbox_enabled": False,
    })
    only_athena = Settings().model_copy(update={
        "workspace_ehr_read_enabled": False,
        "workspace_athena_fhir_sandbox_enabled": True,
    })
    assert only_ehr.workspace_athena_fhir_sandbox_available is False
    assert only_athena.workspace_athena_fhir_sandbox_available is False
    # Availability also needs an authenticated workspace; the two flags alone are
    # not enough, matching C8. Hosted still refuses the sandbox flag at startup.
    hosted = Settings(workspace_hosted_enabled=True, workspace_athena_fhir_sandbox_enabled=True)
    assert any(
        "WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED must remain false" in error
        for error in hosted.runtime_configuration_errors()
    )
