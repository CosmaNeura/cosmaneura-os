"""Actual Core trial responses; injected HTTP only, without database fixtures."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.core_appointment_setup import PATH, CoreSetupChanged
from cosmas_os.adapters.core_encounters import CoreDiscoveryDenied, CoreEncounterConnection
from cosmas_os.application.core_connection import COMMAND_ADAPTER
from cosmas_os.application.core_record_deadline import RecordDeadline
from cosmas_os.config import Settings
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_appointment_setup import AppointmentSetupCommand, AppointmentSetupRequest


def fixture(action="connect"):
    item = json.loads(
        (Path(__file__).parents[1] / "fixtures/core-appointment-setup.json").read_text()
    )[action]
    item["response"]["checked_at"] = datetime.now(UTC).isoformat()
    return AppointmentSetupRequest.model_validate(item["request"]), item["response"]


def read(request, payload, status=200):
    calls = []

    def handler(incoming):
        calls.append(incoming)
        assert str(incoming.url) == "https://core.example.invalid" + PATH
        assert incoming.headers["authorization"] == "Bearer invented-session"
        assert incoming.headers["x-cosmaneura-appointment-setup-version"] == "1"
        assert "cookie" not in incoming.headers
        assert json.loads(incoming.content) == request.model_dump(mode="json")
        return httpx.Response(
            status,
            json=payload,
            headers={"Cache-Control": "no-store", "X-Cosmaneura-Appointment-Setup-Version": "1"},
        )

    port = CoreEncounterConnection(
        "https://core.example.invalid",
        RecordDeadline(),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    try:
        return port.setup_appointments(request, SecretStr("invented-session"))
    finally:
        port.close()
        assert len(calls) == 1  # Unknown or failed confirmation is never replayed.


@pytest.mark.parametrize("action", ["preview", "connect"])
def test_real_core_projection_reaches_the_shared_connection_command(action):
    request, payload = fixture(action)
    assert read(request, payload).connected_now_count == (25 if action == "connect" else 0)
    command = request.model_dump(mode="json", exclude={"expected_actor_ref", "expected_tenant_ref"})
    command["action"] = "appointment_setup_" + action
    assert isinstance(COMMAND_ADAPTER.validate_python(command), AppointmentSetupCommand)


@pytest.mark.parametrize(
    "fault",
    ["nonce", "plan", "connection", "window", "counts", "outcome", "stale", "cursor", "extra"],
)
def test_wrong_review_or_scope_is_refused(fault):
    request, p = fixture()
    if fault == "nonce":
        p["request_nonce"] = str(uuid4())
    if fault == "plan":
        p["plan_sha256"] = "a" * 64
    if fault == "connection":
        p["connection"]["connection_sha256"] = "a" * 64
    if fault == "window":
        p["window"]["end_date"] = "2026-09-26"
    if fault == "counts":
        p["eligible_count"] = True
    if fault == "outcome":
        p["connected_now_count"] = 24
    if fault == "stale":
        p["checked_at"] = "2000-01-01T00:00:00Z"
    if fault == "cursor":
        p["next_cursor"]["appointment_date"] = "2026-09-25T09:00:00"
    if fault == "extra":
        p["patient_name"] = "Invented unrelated content"
    with pytest.raises(ConnectorUnavailable):
        read(request, p)


@pytest.mark.parametrize(
    "status,error",
    [
        (401, CoreDiscoveryDenied),
        (403, CoreDiscoveryDenied),
        (409, CoreSetupChanged),
        (503, ConnectorUnavailable),
    ],
)
def test_rejection_and_unknown_confirmation_are_not_retried(status, error):
    request, p = fixture()
    with pytest.raises(error):
        read(request, p, status)


def test_renderer_cannot_supply_actor_or_connect_without_review():
    request, _ = fixture()
    command = request.model_dump(mode="json", exclude={"expected_actor_ref", "expected_tenant_ref"})
    command["action"] = "appointment_setup_connect"
    for extra in (
        {"expected_actor_ref": request.expected_actor_ref},
        {"plan_sha256": None},
        {"window": {"start_date": "2026-09-24", "end_date": "2026-12-01"}},
    ):
        with pytest.raises(ValueError):
            COMMAND_ADAPTER.validate_python(command | extra)


def test_setup_is_default_off_and_requires_core_configuration():
    assert not Settings(_env_file=None).workspace_core_appointment_setup_available
    config = Settings(_env_file=None, workspace_core_appointment_setup_enabled=True)
    assert not config.workspace_core_appointment_setup_available
    assert (
        "Appointment setup requires an authenticated, configured Core connection"
        in config.runtime_configuration_errors()
    )
