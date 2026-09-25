import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from tests.unit.test_core_capture_admission import NOW, core_handler, ref, selection

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_notes import (
    CoreDraftReceipt,
    CoreNoteEdit,
    CoreNoteSelection,
    CoreSaveResolution,
    NoteAction,
    core_note_edit_hash,
    note_content_hash,
)


def draft(session_id):
    fields = {"CC": "Invented visit", "Plan": "Discuss sleep — synthetic only."}
    return {
        "session_id": str(session_id), "scribe_source_id": str(uuid4()),
        "source_sha256": "a" * 64, "schema_ref": ref("doctor_note_schema"),
        "transcript_ref": ref("ai_visit_transcript"), "note_ref": ref("visit_note"),
        "status": "draft", "note_type": "Visit note", "fields": fields, "field_order": list(fields),
        "note_sha256": note_content_hash(fields), "created_at": NOW.isoformat(),
        "review_required": True,
    }


def edit_input():
    return CoreNoteEdit(client_key=uuid4(), expected_note_ref=ref("visit_note")[:-1] + "2",
        expected_note_sha256="b" * 64, expected_source_sha256="a" * 64,
        fields={"CC": "Invented visit", "Plan": "Discuss sleep — synthetic only."})


def test_resolution_request_hash_matches_core_numeric_and_unicode_contract():
    fixture=Path(__file__).parents[1]/"fixtures/capture_note_save_resolution.json"
    for case in json.loads(fixture.read_text())["cases"]:
        edit=CoreNoteEdit.model_validate(case["edit"])
        assert core_note_edit_hash(edit,case["base"]["schema_ref"],UUID(case["base"]["session_id"]),UUID(case["workspace_id"]))==case["receipt"]["request_sha256"]


def exercise(action: NoteAction = "read", mutate=lambda value: None):
    selected, session_id, calls = selection(), uuid4(), []
    base = core_handler(selected, calls)

    def handle(request):
        if not request.url.path.endswith("capture-notes"):
            return base(request)
        body = json.loads(request.content)
        assert body["expected_session_id"] == str(session_id)
        assert body["action"] == action
        assert request.headers["Authorization"] == "Bearer synthetic_PRIVATE_workload"
        assert request.headers["X-Cosmaneura-Mount-Context"] == "synthetic_PRIVATE_context"
        assert request.extensions["timeout"]["read"] == (100 if action == "prepare" else 30)
        receipt = {"session_id": str(session_id), "templates": [{"schema_ref": ref("doctor_note_schema"), "note_type": "Visit note", "field_names": ["CC", "Plan"]}]} if action == "templates" else draft(session_id)
        if action == "resolve":
            edit = CoreNoteEdit.model_validate(body["edit"])
            receipt = {"session_id": str(session_id), "schema_ref": body["schema_ref"],
                       "client_key": str(edit.client_key), "request_sha256": core_note_edit_hash(edit, body["schema_ref"], session_id, selected.workspace_id),
                       "status": "saved", "result_note_ref": ref("visit_note"), "result_sha256": note_content_hash(edit.fields)}
        data = {"contract_version": "1", "binding_ref": ref("scribe_capture_binding"),
                "workspace_id": str(selected.workspace_id), "request_nonce": body["request_nonce"],
                "action": action, "receipt": receipt, "checked_at": NOW.isoformat()}
        mutate(data)
        return httpx.Response(200, json=data, headers={"Cache-Control":"no-store", "X-Cosmaneura-Capture-Version":"1"})

    port = HttpCoreCaptureAdmission("https://core.example.invalid", lambda: "synthetic_PRIVATE_workload",
        transport=httpx.MockTransport(handle), now=lambda: NOW)
    try:
        token = port.exchange_context(selected, SecretStr("synthetic_PRIVATE_jwt"))
        credential = port.resolve_context(selected, token)
        binding = port.resolve_binding(selected, credential)
        return port.capture_note(binding, credential, session_id, CoreNoteSelection(action=action,
            schema_ref=None if action == "templates" else ref("doctor_note_schema"),
            edit=edit_input() if action in {"save", "resolve"} else None))
    finally:
        port.close()


@pytest.mark.parametrize("action", ["templates", "read", "prepare", "save", "resolve"])
def test_template_and_draft_transport(action):
    result = exercise(action)
    assert "Invented" not in repr(result)
    if isinstance(result, CoreDraftReceipt):
        assert result.review_required


@pytest.mark.parametrize("fault", ["key", "request", "schema", "session", "closed_with_result", "saved_without_result", "status"])
def test_resolution_must_match_the_exact_request(fault):
    def mutate(value):
        receipt=value["receipt"]
        if fault == "key":
            receipt["client_key"]=str(uuid4())
        elif fault == "request":
            receipt["request_sha256"]="f"*64
        elif fault == "schema":
            receipt["schema_ref"]=ref("doctor_note_schema")[:-1]+"2"
        elif fault == "session":
            receipt["session_id"]=str(uuid4())
        elif fault == "closed_with_result":
            receipt["status"]="closed"
        elif fault == "saved_without_result":
            receipt["result_note_ref"]=None
        else:
            receipt["status"]="reviewed"
    with pytest.raises(ConnectorUnavailable):
        exercise("resolve",mutate)


def test_closed_resolution_has_no_note_or_review_authority():
    def close(value):
        value["receipt"].update(status="closed",result_note_ref=None,result_sha256=None)
    result=exercise("resolve",close)
    assert isinstance(result,CoreSaveResolution) and result.status=="closed"
    assert not hasattr(result,"review_required")


@pytest.mark.parametrize("fault", ["binding", "workspace", "nonce", "action", "session", "schema", "source", "hash", "content", "extra", "stale", "reviewed", "oversized"])
def test_substituted_or_invalid_note_receipt_is_withheld(fault):
    def mutate(value):
        if fault == "binding":
            value["binding_ref"] = ref("scribe_capture_binding")[:-1] + "2"
        elif fault in {"workspace", "nonce"}:
            value["workspace_id" if fault == "workspace" else "request_nonce"] = str(uuid4())
        elif fault == "action":
            value["action"] = "prepare"
        elif fault == "session":
            value["receipt"]["session_id"] = str(uuid4())
        elif fault == "schema":
            value["receipt"]["schema_ref"] = ref("doctor_note_schema")[:-1] + "2"
        elif fault == "source":
            value["receipt"]["source_sha256"] = "unverified"
        elif fault == "hash":
            value["receipt"]["note_sha256"] = "b" * 64
        elif fault == "content":
            value["receipt"]["fields"]["Plan"] = "Changed private sentinel"
        elif fault == "extra":
            value["receipt"]["private"] = "private sentinel"
        elif fault == "stale":
            value["checked_at"] = (NOW - timedelta(minutes=5)).isoformat()
        elif fault == "reviewed":
            value["receipt"]["review_required"] = False
        else:
            value["receipt"]["fields"]["Plan"] = "x" * 275_000
    with pytest.raises(ConnectorUnavailable) as error:
        exercise(mutate=mutate)
    assert "private sentinel" not in str(error.value)


def test_duplicate_templates_are_rejected():
    def mutate(value):
        value["receipt"]["templates"] *= 2
    with pytest.raises(ConnectorUnavailable):
        exercise("templates", mutate)


@pytest.mark.parametrize("fault", ["source", "fields", "unchanged_id"])
def test_save_receipt_must_confirm_the_requested_edit(fault):
    def mutate(value):
        receipt = value["receipt"]
        if fault == "source":
            receipt["source_sha256"] = "b" * 64
        elif fault == "unchanged_id":
            receipt["note_ref"] = edit_input().expected_note_ref
        else:
            receipt["fields"]["Plan"] = "Different edit"
            receipt["note_sha256"] = note_content_hash(receipt["fields"])
    with pytest.raises(ConnectorUnavailable):
        exercise("save", mutate)
