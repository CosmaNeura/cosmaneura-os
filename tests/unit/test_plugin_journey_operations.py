"""Executable journey schemas select real routes without manufacturing consent."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
from fastapi.routing import APIRoute

from cosmas_os.api.capture_schemas import CaptureOperationRequest
from cosmas_os.api.handoff_review_schemas import HandoffRevision
from cosmas_os.api.plugin_catalog import tool
from cosmas_os.api.plugin_journey_operations import configured, definitions
from cosmas_os.api.team_schemas import ConversationRequest
from cosmas_os.application.core_connection import ConnectionCommand

UUID = "11111111-1111-4111-8111-111111111111"
KEY = "journey-exact-original-1"


def operation(identity):
    return next(row for row in definitions() if row.id == identity)


def test_every_journey_operation_is_real_closed_agent_callable_and_has_existing_evidence():
    from cosmas_os.api.app import app

    def registered(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, "original_router"):
                yield from registered(route.original_router.routes)

    routes = {(route.path, method) for route in registered(app.routes)
              for method in route.methods or ()}
    rows = definitions()
    assert len({row.id for row in rows}) == len(rows)
    for row in rows:
        assert row.agent_callable
        assert (row.path, row.method) in routes
        assert row.request.get("additionalProperties") is False
        schema = tool(row, False)["inputSchema"]
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert all(Path(path).is_file() for path in row.tests)
        assert not any(name in row.path for name in ("/review", "/decide", "/execute", "/notes", "/source-packets"))


def test_saved_source_chief_request_refuses_new_consent_or_identity_or_bot_selection():
    request = {"expected_revision": 2, "team_revision": 3, "idempotency_key": KEY,
               "role": "chief", "content": "Prepare private team drafts from my saved sources."}
    for identity in ("workspace.draft_from_saved_sources", "workspace.resolve_saved_source_draft"):
        row = operation(identity)
        valid = {"workspace_id": UUID, "request": request}
        validator = jsonschema.Draft202012Validator(tool(row, False)["inputSchema"])
        assert not list(validator.iter_errors(valid))
        assert ConversationRequest.model_validate(request).role == "chief"
        for field in ("research_analysis", "inbox_analysis", "membership_analysis", "session_prep_analysis",
                      "box_id", "actor_principal_id", "reviewed", "share_with_team"):
            invalid = deepcopy(valid)
            invalid["request"][field] = {"consented": True}
            assert list(validator.iter_errors(invalid))
        assert list(validator.iter_errors({**valid, "request": request | {"role": "scribe"}}))


def test_revision_consumes_saved_review_id_but_cannot_record_acceptance_or_feedback():
    row = operation("workspace.revise_after_human_feedback")
    assert row.header == "X-Cosmas-Handoff-Review"
    assert row.extra_headers == (("X-Cosmas-Model-Contract", "1"),)
    request = {"expected_revision": 3, "idempotency_key": KEY, "review_id": UUID}
    HandoffRevision.model_validate(request)
    validator = jsonschema.Draft202012Validator(tool(row, True)["inputSchema"])
    args = {"workspace_id": UUID, "handoff_id": UUID, "request": request}
    assert not list(validator.iter_errors(args))
    for change in ({"decision": "accepted"}, {"feedback": "Accept this."}, {"review_id": None}):
        assert list(validator.iter_errors(args | {"request": request | change}))
    assert "existing current human review_id" in " ".join(row.permission)


@pytest.mark.parametrize("action,fields", [
    ("connection", {}),
    ("encounters", {"connection_sha256": "a" * 64, "window": {"start_date": "2026-10-05", "end_date": "2026-10-06"}}),
    ("encounter", {"connection_sha256": "a" * 64, "appointment_ref": "appointment_" + "0" * 26, "source_sha256": "b" * 64}),
])
def test_core_reads_select_only_exact_handler_branch_and_refuse_mapping_change(action, fields):
    row = operation("core.read_" + action)
    request = {"action": action, "request_nonce": UUID, **fields}
    command = ConnectionCommand.model_validate(request)
    command.validate_selection()
    validator = jsonschema.Draft202012Validator(row.request)
    assert not list(validator.iter_errors(request))
    for unsafe in ("connect", "open", "appointment_setup_connect", "athena_visit_link"):
        assert list(validator.iter_errors(request | {"action": unsafe}))
    assert list(validator.iter_errors(request | {"actor_ref": UUID}))
    assert list(validator.iter_errors(request | {"connection_sha256": None}))


@pytest.mark.parametrize("identity,kind", [("scribe.read_transcription_status", "transcription_status"),
                                           ("scribe.read_source_review", "capture_source")])
def test_scribe_read_schema_cannot_start_recording_correct_or_approve_source(identity, kind):
    row = operation(identity)
    request = {"idempotency_key": KEY, "session_id": UUID, "operation": {"kind": kind}}
    assert CaptureOperationRequest.model_validate(request).operation.kind == kind
    validator = jsonschema.Draft202012Validator(row.request)
    assert not list(validator.iter_errors(request))
    for unsafe in ("encryption_key", "source_start", "correct_transcript", "decide_translation", "complete"):
        assert list(validator.iter_errors(request | {"operation": {"kind": unsafe}}))
    assert list(validator.iter_errors(request | {"operation": {"kind": kind, "payload": {}}}))


def test_research_query_bot_is_flat_closed_uuid4_argument_and_never_get_body():
    row = operation("research.read_saved_evidence")
    schema = tool(row, False)["inputSchema"]
    assert set(schema["required"]) == {"workspace_id", "bot"}
    validator = jsonschema.Draft202012Validator(schema)
    assert not list(validator.iter_errors({"workspace_id": UUID, "bot": UUID}))
    for invalid in ({"workspace_id": UUID, "bot": "research"},
                    {"workspace_id": UUID, "bot": UUID, "request": {}},
                    {"workspace_id": UUID, "bot": UUID, "actor_id": UUID}):
        assert list(validator.iter_errors(invalid))


def test_patient_binding_reads_refuse_confirmation_and_preview():
    for identity in ("scheduling.read_patient_binding", "scheduling.inspect_patient_binding_request",
                     "scheduling.resolve_patient_binding_request"):
        row = operation(identity)
        assert row.header == "X-Cosmas-Scheduling-Patient"
        assert row.read_only
        validator = jsonschema.Draft202012Validator(row.request)
        for action in ("preview", "confirm"):
            assert list(validator.iter_errors({"action": action, "reviewed_exact_identity": True}))


def test_feature_gates_do_not_claim_account_or_model_ready_or_require_publisher_for_saved_read():
    assert configured("workspace.read", SimpleNamespace(workspace_available=True))
    assert configured("workspace.draft_from_saved_sources", SimpleNamespace(workspace_available=True))
    assert not configured("core.read_connection", SimpleNamespace(workspace_available=True))
    assert not configured("scribe.read_source_review", SimpleNamespace(workspace_capture_available=True))
    assert configured("visit_prep.list_prepared_work", SimpleNamespace(workspace_available=True, workspace_prep_work_enabled=True))
    assert configured("research.read_saved_evidence", SimpleNamespace(workspace_research_available=True))
    assert not configured("unknown.operation", SimpleNamespace())
    assert not configured("workspace.injected", SimpleNamespace(workspace_available=True))
