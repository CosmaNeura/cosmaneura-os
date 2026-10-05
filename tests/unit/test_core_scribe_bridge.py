"""Published receiver contracts exercised with invented payloads only."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from tests.unit.test_core_capture_admission import core_handler
from tests.unit.test_core_capture_admission import selection as capture_selection
from tests.unit.test_core_connection_transport import fixture as connection_fixture

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.adapters.core_encounters import CoreEncounterConnection
from cosmas_os.adapters.core_scribe_encounters import PATH
from cosmas_os.application.core_record_deadline import RecordDeadline
from cosmas_os.application.scribe_source import packet_content, require_complete_context, selection
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable, SourcePassage
from cosmas_os.ports.core_encounters import (
    DiscoveryResponse,
    EncounterContent,
    EncounterSnapshot,
    digest,
)
from cosmas_os.ports.creator_review import CreatorReviewView


def reviewed_fixture(text=None):
    value = json.loads((Path(__file__).parents[1] / "fixtures/creator_review.json").read_text())[
        "ready"
    ]
    value["capture_continuity"] = json.loads(
        (Path(__file__).parents[1] / "fixtures/capture_continuity.json").read_text()
    )
    if text is not None:
        value["source"]["segments"][0]["content"] = text
        value["working"]["segments"][0]["content"] = text
    return CreatorReviewView.model_validate(value)


def catalog_case():
    _, observed = connection_fixture()
    content = EncounterContent.model_validate(
        {
            "connection_sha256": observed.connection.connection_sha256,
            "patient": {
                "patient_ref": "patient_" + "0" * 25 + "1",
                "display_name": "Invented Cypress",
            },
            "appointment": {
                "appointment_ref": "appointment_" + "0" * 25 + "1",
                "patient_ref": "patient_" + "0" * 25 + "1",
                "appointment_date": datetime(2026, 9, 30, 12),
                "timezone_known": False,
            },
        }
    )
    encounter = EncounterSnapshot(
        **content.model_dump(mode="json"), source_sha256=digest(content.model_dump(mode="json"))
    )
    discovery = DiscoveryResponse(
        **{**observed.model_dump(), "action": "encounter", "encounters": (encounter,)}
    )
    row = {
        "workspace_id": str(uuid4()),
        "appointment_ref": encounter.appointment.appointment_ref,
        "patient_ref": encounter.patient.patient_ref,
        "patient_name": encounter.patient.display_name,
        "title": "Invented walk-in",
        "appointment_at": "2026-09-30T12:00:00Z",
    }
    return discovery, row


@pytest.mark.parametrize("metadata,accepted", [
    ({}, True),
    ({"date_of_birth": None}, True),
    ({"date_of_birth": "2000-02-29", "status": "recording_saved"}, True),
    ({"date_of_birth": None, "status": "draft_ready"}, True),
    ({"date_of_birth": "20000229"}, False),
    ({"date_of_birth": "2000-02-30"}, False),
    ({"date_of_birth": "2000-02-29T00:00:00Z"}, False),
    ({"date_of_birth": 951782400}, False),
    ({"date_of_birth": True}, False),
    ({"status": "admitted"}, False),
    ({"status": 1}, False),
    ({"unrequested": True}, False),
])
def test_current_core_catalog_metadata_is_optional_closed_and_read_only(metadata, accepted):
    discovery, row = catalog_case()
    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert request.method == "POST" and request.url.path == PATH
        assert payload == {
            "action": "list", "expected_actor_ref": discovery.connection.actor_ref,
            "expected_tenant_ref": discovery.connection.tenant_ref,
            "request_nonce": payload["request_nonce"],
        }
        return httpx.Response(200, json={
            "version": "1", "action": "list", "request_nonce": payload["request_nonce"],
            "account": {"actor_ref": discovery.connection.actor_ref,
                        "tenant_ref": discovery.connection.tenant_ref,
                        "doctor_ref": "doctor_" + "0" * 25 + "1",
                        "email": "invented@example.invalid"},
            "encounters": [{**row, **metadata}],
        }, headers={"Cache-Control": "no-store", "X-Cosmaneura-Scribe-Encounter-Version": "1"})

    port = CoreEncounterConnection("https://core.example.invalid", RecordDeadline(),
                                   transport_factory=lambda: httpx.MockTransport(handler))
    try:
        if accepted:
            assert str(port.scribe_workspace(discovery, SecretStr("invented-human"))) == row["workspace_id"]
        else:
            with pytest.raises(ConnectorUnavailable):
                port.scribe_workspace(discovery, SecretStr("invented-human"))
        assert len(calls) == 1
    finally:
        port.close()


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "actor",
        "tenant",
        "patient",
        "patient_name",
        "appointment_time",
        "workspace_duplicate",
        "appointment_duplicate",
        "nonce",
        "missing",
        "unavailable",
        "extra",
        "oversize",
    ],
)
def test_catalog_preserves_canonical_id_and_rejects_unknown_or_ambiguous_scope(fault):
    discovery, row = catalog_case()

    def handler(request):
        assert (
            request.url.path == PATH and request.headers["authorization"] == "Bearer invented-human"
        )
        assert "cookie" not in request.headers
        incoming = json.loads(request.content)
        assert incoming["action"] == "list" and "patient" not in incoming
        value = {
            "version": "1",
            "action": "list",
            "request_nonce": incoming["request_nonce"],
            "account": {
                "actor_ref": discovery.connection.actor_ref,
                "tenant_ref": discovery.connection.tenant_ref,
                "doctor_ref": "doctor_" + "0" * 25 + "1",
                "email": "invented@example.invalid",
            },
            "encounters": [copy.deepcopy(row)],
        }
        if fault in {"actor", "tenant"}:
            value["account"][fault + "_ref"] = value["account"][fault + "_ref"][:-1] + "2"
        if fault == "patient":
            value["encounters"][0]["patient_ref"] = row["patient_ref"][:-1] + "2"
        if fault == "patient_name":
            value["encounters"][0]["patient_name"] = "Another invented patient"
        if fault == "appointment_time":
            value["encounters"][0]["appointment_at"] = "2026-09-30T13:00:00Z"
        if fault in {"workspace_duplicate", "appointment_duplicate"}:
            other = (
                {**row, "appointment_ref": row["appointment_ref"][:-1] + "2"}
                if fault == "workspace_duplicate"
                else {**row, "workspace_id": str(uuid4())}
            )
            value["encounters"].append(other)
        if fault == "missing":
            value["encounters"] = []
        if fault == "nonce":
            value["request_nonce"] = str(uuid4())
        if fault == "extra":
            value["encounters"][0]["unrequested"] = True
        if fault == "oversize":
            return httpx.Response(200, content="x" * 65537)
        return httpx.Response(
            503 if fault == "unavailable" else 200,
            json=value,
            headers={"Cache-Control": "no-store", "X-Cosmaneura-Scribe-Encounter-Version": "1"},
        )

    port = CoreEncounterConnection(
        "https://core.example.invalid",
        RecordDeadline(),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    try:
        if fault not in {None, "missing"}:
            with pytest.raises(ConnectorUnavailable):
                port.scribe_workspace(discovery, SecretStr("invented-human"))
        else:
            result = port.scribe_workspace(discovery, SecretStr("invented-human"))
            assert result is None if fault else str(result) == row["workspace_id"]
    finally:
        port.close()


@pytest.mark.parametrize(
    "fault", [None, "workspace", "nonce", "operation", "consent", "unprepared"]
)
def test_existing_recording_read_never_admits_or_starts_capture(fault):
    selected, calls = capture_selection(), []
    base = core_handler(selected, calls)
    view = reviewed_fixture()

    def handler(request):
        if not request.url.path.endswith("capture-operations"):
            return base(request)
        calls.append(request)
        body = json.loads(request.content)
        assert body["operation"] == {"kind": "provider_encounter"}
        value = {
            "contract_version": "1",
            "binding_ref": body["binding_ref"],
            "workspace_id": body["workspace_id"],
            "request_nonce": body["request_nonce"],
            "operation": "provider_encounter",
            "checked_at": datetime.now(UTC).isoformat(),
            "receipt": {
                "schema_version": "1.0",
                "status": "available",
                "review": view.model_dump(mode="json"),
            },
        }
        if fault == "workspace":
            value["workspace_id"] = str(uuid4())
        if fault == "nonce":
            value["request_nonce"] = str(uuid4())
        if fault == "operation":
            value["operation"] = "creator_review"
        if fault == "unprepared":
            value["receipt"] = {"schema_version": "1.0", "status": "not_prepared", "review": None}
        return httpx.Response(
            409 if fault == "consent" else 200,
            json=value,
            headers={"Cache-Control": "no-store", "X-Cosmaneura-Capture-Version": "1"},
        )

    port = HttpCoreCaptureAdmission(
        "https://core.example.invalid",
        lambda: "synthetic_PRIVATE_workload",
        transport=httpx.MockTransport(handler),
    )
    try:
        token = port.exchange_context(selected, SecretStr("synthetic_PRIVATE_jwt"))
        credential = port.resolve_context(selected, token)
        binding = port.resolve_binding(selected, credential)
        if fault not in {None, "unprepared"}:
            with pytest.raises(ConnectorUnavailable):
                port.provider_encounter(binding, credential, "invented-read-key")
        else:
            result = port.provider_encounter(binding, credential, "invented-read-key")
            assert result.review is None if fault else result.review == view
        assert len(calls) == 4 and not any("admissions" in str(call.url) for call in calls)
    finally:
        port.close()


def test_snapshot_anchor_binds_full_source_and_continuity_without_truncation():
    view = reviewed_fixture()
    chosen = selection(view)
    assert chosen is not None
    text = packet_content(view, chosen)
    assert str(view.session_id) in text and chosen.snapshot_sha256 in text
    assert "continuity is unconfirmed" in text and "not a live-synced" in text
    changed = view.model_copy(update={"capture_continuity": None})
    assert selection(changed) != chosen
    with pytest.raises(WorkspaceError, match="scribe_source_packet_too_large"):
        huge = reviewed_fixture("Invented. " * 4000)
        packet_content(huge, selection(huge))


@pytest.mark.parametrize("fault", ["part_dropped", "part_truncated", "missing_part", "wrong_count"])
def test_model_cannot_silently_omit_a_saved_packet_part(fault):
    digest = "a" * 64

    def passage(i, count=2, content="invented " * 50):
        return SourcePassage(
            str(uuid4()),
            i,
            f"Reviewed Scribe snapshot · {digest} · {i}/{count}",
            "evidence",
            content,
        )

    sources = [passage(1), passage(2)]
    require_complete_context(sources)
    if fault == "part_dropped":
        sources += [
            SourcePassage(str(uuid4()), 3, "Later evidence", "evidence", "x") for _ in range(11)
        ]
    if fault == "part_truncated":
        sources += [
            SourcePassage(str(uuid4()), 3, "Later evidence", "evidence", "x" * 5000)
            for _ in range(6)
        ]
    if fault == "missing_part":
        sources.pop()
    if fault == "wrong_count":
        sources[1] = passage(2, 3)
    with pytest.raises(WorkspaceError, match="scribe_source_context_too_large"):
        require_complete_context(sources)
