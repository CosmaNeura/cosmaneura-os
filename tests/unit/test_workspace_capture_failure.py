"""Closed Core diagnostics through the application graph and real API handler."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session
from starlette.requests import Request
from tests.unit.test_core_capture_admission import NOW, ref, selection

from cosmas_os.api import app as api
from cosmas_os.application import workspace as ws
from cosmas_os.application import workspace_capture as capture
from cosmas_os.models import CoreCaptureAccount, ExternalIdentity
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_protocol import ReadOperation
from cosmas_os.ports.core_capture import (
    CoreCaptureAdmissionSnapshot,
    CoreCaptureBindingSnapshot,
)
from cosmas_os.ports.creator_review import CreatorReviewView
from cosmas_os.private_recording_models import PrivateRecordingTransfer

PHASES = [
    "context_exchange",
    "context_resolution",
    "binding_resolution",
    "session_verification",
    "review",
]
FAILURE_CODES = [
    "core_capture_identity_unavailable",
    "core_capture_context_invalid",
    "core_capture_receipt_invalid",
    "core_capture_request_unconfirmed",
]


@pytest.fixture
def graph(monkeypatch):
    selected = selection()
    case = SimpleNamespace(
        selected=selected, session_id=uuid4(), calls=[], failure=None,
        authority_checks=0, rollbacks=0, revoked=False,
    )
    account = SimpleNamespace(
        id="invented-account", core_actor_ref=selected.expected_actor_ref,
        core_tenant_ref=selected.expected_tenant_ref,
    )

    class PrivateSession:
        def expire_all(self):
            pass

        def scalar(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is CoreCaptureAccount:
                return account
            if entity is ExternalIdentity:
                return object()
            assert entity is PrivateRecordingTransfer
            return None

        def commit(self):
            pass

        def rollback(self):
            case.rollbacks += 1

    def workspace(*args, **kwargs):
        if case.revoked:
            raise ws.WorkspaceError("capture_access_unavailable", 403)
        return SimpleNamespace(
            appointment_id="invented-appointment", patient_link_id="invented-patient",
            owner_id="invented-actor",
        )

    monkeypatch.setattr(capture.ws, "_workspace", workspace)
    monkeypatch.setattr(capture.ws, "_encounter", lambda *args, **kwargs: SimpleNamespace(
        source="cosmaneura_core", external_id=selected.appointment_ref,
    ))

    def reauthenticate():
        case.authority_checks += 1

    case.bearer = SecretStr("invented-private-bearer")
    case.token, case.credential = object(), object()
    case.binding = CoreCaptureBindingSnapshot(
        contract_version="1", binding_ref=ref("scribe_capture_binding"),
        workspace_id=selected.workspace_id, appointment_ref=selected.appointment_ref,
        actor_ref=selected.expected_actor_ref, tenant_ref=selected.expected_tenant_ref,
        request_nonce=uuid4(), checked_at=NOW,
    )
    case.receipt = CoreCaptureAdmissionSnapshot(
        contract_version="1", operation_ref=ref("scribe_admission"),
        binding_ref=case.binding.binding_ref, workspace_id=selected.workspace_id,
        appointment_ref=selected.appointment_ref, consent_record_id=uuid4(),
        session_id=case.session_id, status="admitted", request_nonce=uuid4(), checked_at=NOW,
    )
    golden = json.loads((Path(__file__).parents[1] / "fixtures/creator_review.json").read_text())["waiting"]
    golden["session_id"] = str(case.session_id)
    golden["review_queue"]["session_id"] = str(case.session_id)
    case.view = CreatorReviewView.model_validate(golden)

    class Port:
        def step(self, phase):
            case.calls.append(phase)
            if case.failure is not None and case.failure[0] == phase:
                raise ConnectorUnavailable(case.failure[1])

        def exchange_context(self, actual, bearer):
            assert actual == selected and bearer is case.bearer
            self.step("context_exchange")
            return case.token

        def resolve_context(self, actual, token):
            assert actual == selected and token is case.token
            self.step("context_resolution")
            return case.credential

        def resolve_binding(self, actual, credential):
            assert actual == selected and credential is case.credential
            self.step("binding_resolution")
            return case.binding

        def admit_capture(self, binding, credential, attestation, key, **kwargs):
            assert binding is case.binding and credential is case.credential
            assert attestation is None and key == f"verify:{case.session_id}"
            assert kwargs == {"expected_session_id": case.session_id, "configured_capture": None}
            self.step("session_verification")
            return case.receipt

        def perform_capture_operation(self, binding, credential, session_id, operation, key):
            assert binding is case.binding and credential is case.credential
            assert session_id == case.session_id and operation is case.operation
            assert key == "invented-review-key"
            self.step("review")
            return case.view

    case.port, case.session, case.reauthenticate = Port(), PrivateSession(), reauthenticate
    return case


def read(case, kind: Literal["creator_review", "capabilities"] = "creator_review"):
    case.operation = ReadOperation(kind=kind)
    return capture.admit(
        cast(Session, case.session), box="invented-box", actor="invented-actor",
        external_identity_id="invented-identity", workspace_id=str(case.selected.workspace_id),
        bearer=case.bearer, reauthenticate=case.reauthenticate, port=case.port,
        attestation=None, idempotency_key="invented-review-key", operation=case.operation,
        expected_session_id=case.session_id,
    )


def response_for(error):
    request = Request({"type": "http", "method": "POST", "path": "/workspaces/invented/capture/operations", "headers": []})
    response = asyncio.run(api.workspace_error(request, error))
    assert response.headers["cache-control"] == "no-store"
    return response, json.loads(bytes(response.body))


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("code", FAILURE_CODES)
def test_closed_core_failure_keeps_exact_code_and_failed_read_hop(graph, phase, code):
    graph.failure = phase, code
    with pytest.raises(capture.CoreCaptureFailure) as caught:
        read(graph)
    error = caught.value
    response, body = response_for(error)
    assert error.status == response.status_code == 503
    assert body == {"detail": code, "capture_phase": phase}
    assert error.__suppress_context__
    assert graph.calls == PHASES[:PHASES.index(phase) + 1]
    assert graph.authority_checks == len(graph.calls)
    assert graph.rollbacks == 1


@pytest.mark.parametrize("code", FAILURE_CODES)
def test_other_capture_reads_keep_closed_code_without_creator_review_phase(graph, code):
    graph.failure = "review", code
    with pytest.raises(capture.CoreCaptureFailure) as caught:
        read(graph, "capabilities")
    response, body = response_for(caught.value)
    assert response.status_code == 503
    assert body == {"detail": code}
    assert caught.value.capture_phase is None
    assert graph.calls == PHASES


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("code,status,detail", [
    ("PRIVATE_FAILURE_SENTINEL: invented response body", 503, "capture_request_unconfirmed"),
    ("core_capture_access_unavailable", 403, "core_capture_access_unavailable"),
    ("capture_request_conflict", 409, "capture_request_conflict"),
])
def test_unknown_access_and_conflict_failures_keep_existing_closed_response(graph, phase, code, status, detail):
    graph.failure = phase, code
    with pytest.raises(ws.WorkspaceError) as caught:
        read(graph)
    response, body = response_for(caught.value)
    assert type(caught.value) is ws.WorkspaceError
    assert response.status_code == status
    assert body == {"detail": detail}
    assert b"PRIVATE_FAILURE_SENTINEL" not in bytes(response.body)
    assert graph.calls == PHASES[:PHASES.index(phase) + 1]
    assert graph.rollbacks == 1


def test_successful_read_retains_original_authority_call_order_and_payload(graph):
    assert read(graph) is graph.view
    assert graph.calls == PHASES
    assert graph.authority_checks == 6
    assert graph.rollbacks == 1


def test_replaced_authority_after_core_read_still_stops_before_session_verification(graph):
    original = graph.port.resolve_binding

    def revoked(*args):
        result = original(*args)
        graph.revoked = True
        return result

    graph.port.resolve_binding = revoked
    with pytest.raises(ws.WorkspaceError) as caught:
        read(graph)
    response, body = response_for(caught.value)
    assert response.status_code == 403
    assert body == {"detail": "capture_access_unavailable"}
    assert graph.calls == PHASES[:3]
    assert graph.rollbacks == 1


def test_wrong_admitted_session_still_stops_before_review(graph):
    graph.receipt = graph.receipt.model_copy(update={"session_id": uuid4()})
    with pytest.raises(ws.WorkspaceError) as caught:
        read(graph)
    response, body = response_for(caught.value)
    assert response.status_code == 409
    assert body == {"detail": "capture_session_changed"}
    assert graph.calls == PHASES[:4]


def test_only_diagnostic_subclass_can_emit_a_phase():
    error = ws.WorkspaceError("core_capture_receipt_invalid", 503)
    cast(Any, error).capture_phase = capture.CoreCaptureReadPhase.REVIEW
    response, body = response_for(error)
    assert response.status_code == 503
    assert body == {"detail": "core_capture_receipt_invalid"}


@pytest.mark.parametrize("mutation", ["phase", "code", "status"])
def test_api_strips_untrusted_diagnostic_metadata(mutation):
    error = capture.CoreCaptureFailure("core_capture_receipt_invalid", capture.CoreCaptureReadPhase.REVIEW)
    if mutation == "phase":
        cast(Any, error).capture_phase = "PRIVATE_PHASE_SENTINEL"
    elif mutation == "code":
        error.code = "capture_request_unconfirmed"
    else:
        error.status = 409
    response, body = response_for(error)
    assert response.status_code == error.status
    assert body == {"detail": error.code}
    assert b"PRIVATE_PHASE_SENTINEL" not in bytes(response.body)


def test_diagnostic_subclass_rejects_non_allowlisted_values():
    with pytest.raises(ValueError, match="^invalid_capture_failure_code$"):
        capture.CoreCaptureFailure("PRIVATE_FAILURE_SENTINEL")
    with pytest.raises(ValueError, match="^invalid_capture_phase$"):
        capture.CoreCaptureFailure("core_capture_receipt_invalid", cast(Any, "review"))
