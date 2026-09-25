from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from tests.integration.test_workspace_capture import admit
from tests.integration.test_workspace_capture import capture_case as _capture_case
from tests.unit.test_core_capture_notes import draft, edit_input

from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, PatientLink
from cosmas_os.ports.core_notes import (
    CoreDraftReceipt,
    CoreSaveResolution,
    CoreTemplateReceipt,
    core_note_edit_hash,
)

capture_case = _capture_case


def setup(f):
    f.configuration.workspace_capture_notes_enabled = True
    response = admit(f)
    assert response.status_code == 200
    f.session_id = response.json()["session_id"]
    f.port.calls.clear()

    def read_note(binding, credential, session_id, selection):
        f.port.step("note")
        if selection.action == "templates":
            return CoreTemplateReceipt(session_id=session_id, templates=())
        if selection.action == "resolve":
            return CoreSaveResolution(session_id=session_id,schema_ref=selection.schema_ref,
                client_key=selection.edit.client_key,
                request_sha256=core_note_edit_hash(selection.edit,selection.schema_ref,session_id,binding.workspace_id),status="closed")
        return CoreDraftReceipt.model_validate(draft(session_id))

    f.port.capture_note = read_note


def perform(f, action="read", **changes):
    return f.client.post(f.path.replace("/admission", "/notes"),
        headers={"Authorization":"Bearer " + f.token()},
        json={"session_id": f.session_id, "idempotency_key": uuid4().hex,
              "note": {"action": action, **({} if action == "templates" else {"schema_ref":"doctor_note_schema_" + "0" * 25 + "1"}),
                       **({"edit": edit_input().model_dump(mode="json")} if action in {"save", "resolve"} else {})}, **changes})


@pytest.mark.parametrize("action", ["templates", "read", "prepare", "save", "resolve"])
def test_note_uses_current_signed_workspace_and_admission(capture_case, action):
    f = capture_case
    setup(f)
    response = perform(f, action)
    assert response.status_code == 200
    assert response.json()["session_id"] == f.session_id
    assert response.json()["action"] == action
    assert response.headers["cache-control"] == "no-store"
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "note"]


@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding", "admit", "note"])
@pytest.mark.parametrize("target", ["identity", "account", "patient"])
@pytest.mark.parametrize("action", ["templates", "read", "prepare", "save", "resolve"])
def test_changed_workspace_scope_withholds_note_and_stops_next_phase(capture_case, phase, target, action):
    f = capture_case
    setup(f)

    def revoke(observed):
        if phase == observed:
            with Session(f.engine) as session:
                model, key = {"identity": (ExternalIdentity, f.identity_id),
                              "account": (CoreCaptureAccount, f.account_id),
                              "patient": (PatientLink, f.patient_link_id)}[target]
                row = session.get(model, key)
                assert row is not None
                if isinstance(row, ExternalIdentity):
                    row.active = False
                else:
                    row.revoked_at = datetime.now(UTC)
                session.commit()

    f.port.after = revoke
    response = perform(f, action)
    assert response.status_code in {403, 404, 409}
    assert "receipt" not in response.text and "Invented visit" not in response.text
    assert len(f.port.calls) == ["exchange", "resolve", "binding", "admit", "note"].index(phase) + 1


def test_notes_default_gate_and_claimed_session(capture_case):
    f = capture_case
    setup(f)
    f.configuration.workspace_capture_notes_enabled = False
    assert perform(f).status_code == 404
    assert not f.port.calls
    f.configuration.workspace_capture_notes_enabled = True
    assert perform(f, session_id=str(uuid4())).status_code == 409
    assert f.port.calls == ["exchange", "resolve", "binding", "admit"]


@pytest.mark.parametrize("fault", [None, "too_large", "claimed_doctor"])
def test_edit_text_is_bounded_without_accepting_authority_fields(capture_case, fault):
    f = capture_case
    setup(f)
    edit = edit_input().model_dump(mode="json")
    edit["fields"]["Plan"] = "x" * (270337 if fault == "too_large" else 2200)
    if fault == "claimed_doctor":
        edit["doctor_id"] = "private sentinel"
    response = perform(f, "save", note={"action": "save", "schema_ref": "doctor_note_schema_" + "0" * 25 + "1", "edit": edit})
    assert response.status_code == (200 if fault is None else 422)
    if fault is not None:
        assert not f.port.calls and "private sentinel" not in response.text
