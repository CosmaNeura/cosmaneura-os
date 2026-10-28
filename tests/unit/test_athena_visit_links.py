"""Read-only vendor scope and exact reviewed commands across the Core adapter."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.core_athena_visit_links import PATH
from cosmas_os.adapters.core_encounters import CoreEncounterConnection
from cosmas_os.application.core_connection import COMMAND_ADAPTER
from cosmas_os.application.core_record_deadline import RecordDeadline
from cosmas_os.config import Settings
from cosmas_os.ports.athena_visit_links import AthenaVisitLinkCommand, AthenaVisitLinkRequest
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_encounters import EncounterSnapshot, digest


def fixture(name="link"):
    item = json.loads((Path(__file__).parents[1] / "fixtures/athena-visit-links.json").read_text())[
        name
    ]
    item["response"]["athena_visit_link"]["checked_at"] = datetime.now(UTC).isoformat()
    return (
        AthenaVisitLinkRequest.model_validate(item["request"]),
        item["response"]["athena_visit_link"],
        item["command"],
    )


def read(request, payload, status=200):
    calls = []

    def handler(incoming):
        calls.append(incoming)
        assert str(incoming.url) == "https://core.example.invalid" + PATH
        assert (
            incoming.method == "POST"
            and incoming.headers["authorization"] == "Bearer invented-session"
        )
        assert (
            incoming.headers["x-cosmaneura-athena-link-version"] == "1"
            and "cookie" not in incoming.headers
        )
        assert json.loads(incoming.content) == request.model_dump(mode="json")
        return httpx.Response(
            status,
            json=payload,
            headers={"Cache-Control": "no-store", "X-Cosmaneura-Athena-Link-Version": "1"},
        )

    port = CoreEncounterConnection(
        "https://core.example.invalid",
        RecordDeadline(),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    try:
        return port.athena_visit_link(request, SecretStr("invented-session"))
    finally:
        port.close()
        assert len(calls) == 1


@pytest.mark.parametrize(
    "name",
    [
        "lookup",
        "preview",
        "link",
        "status",
        "not_found",
        "linked_lookup",
        "unlink_preview",
        "unlink",
    ],
)
def test_all_actions_and_receipts_are_bound_to_server_account(name):
    request, payload, command = fixture(name)
    assert read(request, payload).state == payload["state"]
    parsed = COMMAND_ADAPTER.validate_python(command)
    assert isinstance(parsed, AthenaVisitLinkCommand)
    assert parsed.as_core(request.expected_tenant_ref, request.expected_actor_ref) == request


@pytest.mark.parametrize(
    "fault", ["nonce", "patient", "command", "applied", "stale", "extra", "unknown_status"]
)
def test_corrupted_or_unknown_reply_is_refused_without_replaying(fault):
    request, payload, _ = fixture()
    status = 200
    if fault == "nonce":
        payload["request_nonce"] = str(uuid4())
    if fault == "patient":
        payload["source"]["patient_ref"] = "9002"
    if fault == "command":
        payload["command_sha256"] = "f" * 64
    if fault == "applied":
        payload["applied"] = False
    if fault == "stale":
        payload["checked_at"] = "2000-01-01T00:00:00Z"
    if fault == "extra":
        payload["clinical_note"] = "invented unrelated data"
    if fault == "unknown_status":
        status = 503
    with pytest.raises(ConnectorUnavailable):
        read(request, payload, status)


@pytest.mark.parametrize("fault", ["appointment", "source"])
def test_applied_link_must_return_the_exact_reviewed_encounter(fault):
    request, payload, _ = fixture()
    encounter = payload["encounter"]
    if fault == "appointment":
        encounter["appointment"]["appointment_ref"] = "appointment_00000000000000000000000002"
    else:
        encounter["patient"]["display_name"] = "Invented updated display name"
    encounter["source_sha256"] = digest(
        {key: value for key, value in encounter.items() if key != "source_sha256"}
    )
    # A valid, same-account projection and the original command receipt must
    # still be rejected when they no longer describe the reviewed encounter.
    assert EncounterSnapshot.model_validate(encounter).connection_sha256 == request.connection_sha256
    with pytest.raises(ConnectorUnavailable, match="^core_connection_unavailable$"):
        read(request, payload)


@pytest.mark.parametrize("name", ["lookup", "link", "status", "unlink"])
def test_invalid_account_timezone_has_a_bounded_error_without_replay(name):
    request, payload, _ = fixture(name)
    payload["account"]["department_timezone"] = "Invalid/Zone"
    with pytest.raises(ConnectorUnavailable, match="^core_connection_unavailable$"):
        read(request, payload)


def test_status_can_report_current_projection_after_reviewed_source_changes():
    request, payload, _ = fixture("status")
    encounter = payload["encounter"]
    encounter["patient"]["display_name"] = "Invented updated display name"
    encounter["source_sha256"] = digest(
        {key: value for key, value in encounter.items() if key != "source_sha256"}
    )
    # Status has an exact command key/hash, not a newly approved encounter.
    result = read(request, payload)
    assert result.command_sha256 == request.command_sha256
    assert result.encounter is not None
    assert result.encounter.source_sha256 == encounter["source_sha256"]


def test_renderer_cannot_select_the_actor_or_skip_confirmation():
    _, _, command = fixture()
    for extra in [{"expected_actor_ref": "invented"}, {"confirmed": False}, {"plan_sha256": None}]:
        with pytest.raises(ValueError):
            COMMAND_ADAPTER.validate_python(command | extra)
    assert not Settings(_env_file=None).workspace_athena_visit_link_available
    config = Settings(_env_file=None, workspace_athena_visit_link_enabled=True)
    assert (
        "Athena visit linking requires a configured, read-only Athena connection"
        in config.runtime_configuration_errors()
    )
