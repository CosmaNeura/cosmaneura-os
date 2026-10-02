"""Real PostgreSQL personal mapping custody with bounded invented receiver reads."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_workspace_auth import signed_workspace as signed_workspace

from cosmas_os.adapters.scheduling import HttpSchedulingAvailability
from cosmas_os.api import app as api
from cosmas_os.application import note_review as notes
from cosmas_os.application import scheduling_patient_setup as setup
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    EncounterWorkspace,
    ExternalIdentity,
    Operation,
    PatientLink,
    Principal,
    SchedulingAccount,
    SchedulingPatientAccount,
    WorkspaceNote,
)
from cosmas_os.ports.scheduling import SchedulingSelection
from cosmas_os.ports.scheduling_patient_setup import (
    PatientPreview,
    PatientVerification,
    patient_digest,
)
from cosmas_os.scheduling_login_models import SchedulingLoginCredential
from cosmas_os.scheduling_patient_models import (
    SchedulingPatientMappingReview,
    SchedulingPatientSetupRequest,
    SchedulingPatientSetupSnapshot,
)


class InventedReceiver:
    def __init__(self, f):
        self.f, self.calls, self.after = f, [], lambda: None
        self.fail, self.changed, self.empty = False, False, False
        self.choice = {"choice_ref": str(uuid4()), "display_name": "Invented Jordan café", "birth_date": None, "subject_revision": 4}
        self.choice["identity_sha256"] = patient_digest("cosmas-scheduling-patient-identity.v1", self.choice)
        self.patient_id = str(uuid4())

    def _io(self, kind):
        assert not self.f.s.in_transaction(), "no SQL transaction/owner lock across provider I/O"
        self.calls.append(kind)
        self.after()
        if self.fail:
            raise TimeoutError("private invented receiver error must be redacted")

    def preview(self, selected, request):
        self._io("preview")
        now = datetime.now(UTC)
        value = {"contract_version": "1", "request_nonce": str(request.request_nonce), "practice_id": str(selected.practice_id),
            "actor_id": str(selected.expected_actor_id), "lookup_ref": str(uuid4()), "checked_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"), "choices": [] if self.empty else [self.choice], "more": False}
        value["preview_sha256"] = patient_digest("cosmas-scheduling-patient-preview.v1", value)
        return PatientPreview.model_validate(value)

    def verify(self, selected, request, preview):
        self._io("verify")
        now = datetime.now(UTC)
        identity = deepcopy(self.choice)
        if self.changed:
            identity["subject_revision"] += 1
            identity["identity_sha256"] = patient_digest("cosmas-scheduling-patient-identity.v1", {k: v for k, v in identity.items() if k != "identity_sha256"})
        value = {"contract_version": "1", "request_nonce": str(request.request_nonce), "practice_id": str(selected.practice_id),
            "actor_id": str(selected.expected_actor_id), "lookup_ref": str(request.lookup_ref), "patient_id": self.patient_id,
            "identity": identity, "verified_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=3)).isoformat().replace("+00:00", "Z")}
        value["verification_sha256"] = patient_digest("cosmas-scheduling-patient-verification.v1", value)
        return PatientVerification.model_validate(value)


@pytest.fixture
def case(session, seeded, monkeypatch):
    from tests.integration.test_note_review import prepare

    box, owner, state, patient = prepare(session, seeded)
    state = notes.save(session, box, owner, state["id"], expected=state["revision"], key=str(uuid4()),
        base_note_id=None, source_reply_id=None, content="Invented existing clinical note retained during patient correspondence.")["workspace"]
    note = state["note"]["latest"]
    state = notes.review(session, box, owner, state["id"], note["id"], expected=state["revision"], key=str(uuid4()),
        content_hash=note["content_hash"], source_hash=note["source_fingerprint"])["workspace"]
    identity = ExternalIdentity(box_id=box, principal_id=owner, provider="clerk", issuer="https://invented-patient.example.invalid",
        subject=str(uuid4()), organization_id="org_invented", reviewed_by=owner, evidence_ref="test:patient-setup")
    session.add(identity)
    session.flush()
    account = SchedulingAccount(external_identity_id=identity.id, label="Invented Scheduling", reviewed_by=owner,
        reviewed_at=datetime.now(UTC), evidence_ref="test:patient-setup",
        **{k: str(uuid4()) for k in ("practice_id", "actor_id", "practitioner_id", "location_id", "appointment_type_id")})
    session.add(account)
    session.flush()
    connected = datetime.now(UTC)
    session.add(SchedulingLoginCredential(account_id=account.id, binding_digest="a" * 64, status="ready", sealed=b"i" * 40,
        connected_at=connected, expires_at=connected + timedelta(hours=1)))
    session.commit()
    f = SimpleNamespace(s=session, engine=session.get_bind(), box=box, owner=owner, wid=state["id"], identity=identity.id,
        account=account.id, patient=patient, configuration=SimpleNamespace(workspace_scheduling_patient_setup_available=True),
        grant="b" * 64, connected=connected, before=state)
    f.port = InventedReceiver(f)
    save_snapshot = setup._save_snapshot
    def checked_snapshot(s, request, parsed):
        current = s.scalar(text("SELECT public.patient_setup_request_current(CAST(:id AS uuid),true)"), {"id": request.id})
        valid = s.scalar(text("SELECT public.patient_setup_payload_valid(:kind,CAST(:payload AS jsonb))"),
            {"kind": request.kind, "payload": json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False)})
        if not current:
            raise ws.WorkspaceError("test_sql_patient_current_parity_failed")
        if not valid:
            raise ws.WorkspaceError("test_sql_patient_payload_parity_failed")
        return save_snapshot(s, request, parsed)
    monkeypatch.setattr(setup, "_save_snapshot", checked_snapshot)

    def binding(s, identity_id, a):
        assert s is not None and identity_id == f.identity and a.id == f.account
        return setup.PatientSetupBinding(account_id=a.id, selection=SchedulingSelection.model_validate({"box_id": box, "owner_id": owner, "practice_id": a.practice_id,
            "expected_actor_id": a.actor_id, "practitioner_id": a.practitioner_id, "location_id": a.location_id,
            "appointment_type_id": a.appointment_type_id}), binding_sha256="a" * 64, connected_at=f.connected, grant_sha256=f.grant)

    with setup.install_binding_reader(binding):
        yield f


def preview(f, **changes):
    return setup.preview(f.s, f.box, f.owner, f.wid, f.identity, expected_revision=f.before["revision"],
        key=changes.pop("key", str(uuid4())), search={"kind": "search", "query": "Invented Jordan", "birth_date": None},
        port=f.port, configuration=f.configuration, **changes)


def confirmation(f, observed, **changes):
    choice = observed["preview"]["choices"][0]
    return {"expected_revision": f.before["revision"], "key": str(uuid4()), "preview_id": observed["request_id"],
        "preview_sha256": observed["source_sha256"], "choice_ref": choice["choice_ref"], "identity_sha256": choice["identity_sha256"],
        "reviewed_same_patient": True, "reviewed_exact_identity": True, **changes}


def confirm(f, command):
    return setup.confirm(f.s, f.box, f.owner, f.wid, f.identity, **command, port=f.port, configuration=f.configuration)


def count(f, model):
    return f.s.scalar(select(func.count()).select_from(model).where(model.box_id == f.box))


def assert_note_untouched(f):
    current = ws.read(f.s, f.box, f.owner, f.wid)
    assert current["note"] == f.before["note"] and current["entries"] == f.before["entries"] and current["revision"] == f.before["revision"]
    assert count(f, WorkspaceNote) == 1 and count(f, Operation) == 0


def test_explicit_null_dob_confirm_and_reopen_durable_personal_mapping_no_booking(case):
    f = case
    observed = preview(f)
    assert observed["preview"]["choices"][0]["birth_date"] is None and observed["mapping"] is None
    body = confirmation(f, observed)
    saved = confirm(f, body)
    assert saved["status"] == "saved" and not saved["source_withheld"] and saved["mapping"]
    assert f.port.calls == ["preview", "verify"]
    assert confirm(f, body) == saved and f.port.calls == ["preview", "verify"]
    assert setup.resolve(f.s, f.box, f.owner, f.wid, f.identity, kind="confirm", key=body["key"], configuration=f.configuration) == saved
    w, account = f.s.get(EncounterWorkspace, f.wid), f.s.get(SchedulingAccount, f.account)
    mapping = setup.personal_mapping_for(f.s, w, f.identity, account, configuration=f.configuration)
    assert mapping.patient_id == f.port.patient_id and mapping.reviewed_by == f.owner
    assert count(f, SchedulingPatientAccount) == count(f, SchedulingPatientMappingReview) == 1
    assert_note_untouched(f)


@pytest.mark.parametrize("reconnect", [False, True])
def test_new_search_after_saved_mapping_refuses_before_reservation_or_io(case, reconnect):
    f = case
    observed = preview(f)
    body = confirmation(f, observed)
    saved = confirm(f, body)
    if reconnect:
        credential = f.s.get(SchedulingLoginCredential, f.account)
        f.connected += timedelta(seconds=1)
        f.grant = "c" * 64
        credential.connected_at = f.connected
        f.s.commit()
    before = {model: count(f, model) for model in (SchedulingPatientSetupRequest,
        SchedulingPatientSetupSnapshot, SchedulingPatientMappingReview, SchedulingPatientAccount)}
    calls = list(f.port.calls)
    with pytest.raises(ws.WorkspaceError, match="scheduling_patient_mapping_review_required"):
        preview(f)
    assert f.port.calls == calls
    assert {model: count(f, model) for model in before} == before
    replay = confirm(f, body)
    assert (replay["request_id"], replay["source_sha256"], replay["request_sha256"]) == (
        saved["request_id"], saved["source_sha256"], saved["request_sha256"])
    status = setup.status(f.s, f.box, f.owner, f.wid, f.identity, configuration=f.configuration)
    if reconnect:
        assert replay["source_withheld"] and replay["mapping"] is replay["preview"] is None
        assert status == {"contract_version": 1, "state": "link_required", "mapping_id": None}
    else:
        assert replay == saved and status["state"] == "linked"
        mapping = setup.personal_mapping_for(f.s, f.s.get(EncounterWorkspace, f.wid), f.identity,
            f.s.get(SchedulingAccount, f.account), configuration=f.configuration)
        assert mapping.id == saved["mapping"]["mapping_id"] == status["mapping_id"]
    assert f.port.calls == calls
    assert_note_untouched(f)


def test_changed_same_key_refuses_exact_intent_and_creates_no_second_review(case):
    f = case
    observed = preview(f)
    body = confirmation(f, observed)
    confirm(f, body)
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        confirm(f, {**body, "expected_revision": body["expected_revision"] + 1})
    assert f.port.calls == ["preview", "verify"] and count(f, SchedulingPatientMappingReview) == 1


def test_current_maximum_safe_public_subject_revision_has_exact_sql_hash_parity(case):
    f = case
    f.port.choice["subject_revision"] = 9007199254740991
    f.port.choice["identity_sha256"] = patient_digest("cosmas-scheduling-patient-identity.v1",
        {k: v for k, v in f.port.choice.items() if k != "identity_sha256"})
    saved = confirm(f, confirmation(f, preview(f)))
    assert saved["mapping"]["subject_revision"] == 9007199254740991


@pytest.mark.parametrize("kind", ["preview", "confirm"])
def test_lost_receiver_response_remains_unconfirmed_never_automatically_retries(case, kind):
    f, key = case, str(uuid4())
    observed = preview(f) if kind == "confirm" else None
    body = confirmation(f, observed, key=key) if observed else None
    f.port.fail = True
    with pytest.raises(ws.WorkspaceError, match="scheduling_patient_response_unconfirmed"):
        confirm(f, body) if body else preview(f, key=key)
    calls = list(f.port.calls)
    result = confirm(f, body) if body else preview(f, key=key)
    assert result["status"] == "unconfirmed" and result["preview"] is result["mapping"] is None
    assert setup.resolve(f.s, f.box, f.owner, f.wid, f.identity, kind=kind, key=key, configuration=f.configuration)["status"] == "unconfirmed"
    assert f.port.calls == calls and count(f, SchedulingPatientMappingReview) == 0


@pytest.mark.parametrize("change", ["credential", "grant", "source", "mapping"])
def test_committed_lost_reply_exact_replay_masked_without_restoring_authority(case, change):
    f = case
    observed = preview(f)
    body = confirmation(f, observed)
    saved = confirm(f, body)
    if change == "credential":
        row = f.s.get(SchedulingLoginCredential, f.account)
        row.status, row.sealed = "disconnected", None
    elif change == "grant":
        f.grant = "c" * 64
    elif change == "source":
        link = f.s.get(PatientLink, f.patient)
        link.state = "unconfirmed"
        f.s.commit()
        with pytest.raises(ws.WorkspaceError, match="encounter_unavailable"):
            confirm(f, body)
        return
    else:
        f.s.get(SchedulingPatientAccount, saved["mapping"]["mapping_id"]).revoked_at = datetime.now(UTC)
    f.s.commit()
    calls, before = list(f.port.calls), count(f, SchedulingPatientMappingReview)
    replay = confirm(f, body)
    assert replay["source_withheld"] and replay["preview"] is replay["mapping"] is None
    assert (replay["request_id"], replay["request_sha256"], replay["source_sha256"], replay["status"]) == (
        saved["request_id"], saved["request_sha256"], saved["source_sha256"], "saved")
    assert f.port.calls == calls and count(f, SchedulingPatientMappingReview) == before
    with pytest.raises(ws.WorkspaceError):
        setup.personal_mapping_for(f.s, f.s.get(EncounterWorkspace, f.wid), f.identity, f.s.get(SchedulingAccount, f.account), configuration=f.configuration)


@pytest.mark.parametrize("kind", ["preview", "confirm"])
@pytest.mark.parametrize("change", ["credential", "revision", "source"])
def test_revoke_or_source_change_during_io_refuses_settlement(case, kind, change):
    f = case
    observed = preview(f) if kind == "confirm" else None
    def after():
        if change == "credential":
            row = f.s.get(SchedulingLoginCredential, f.account)
            row.status, row.sealed = "disconnected", None
        elif change == "revision":
            w = f.s.get(EncounterWorkspace, f.wid)
            ws.append(f.s, f.box, f.owner, f.wid, expected=w.revision, key=str(uuid4()), kind="scratchpad", content="Invented concurrent edit")
        else:
            f.s.get(PatientLink, f.patient).state = "unconfirmed"
        f.s.commit()
    f.port.after = after
    with pytest.raises(ws.WorkspaceError):
        confirm(f, confirmation(f, observed)) if observed else preview(f)
    assert count(f, SchedulingPatientMappingReview) == 0 and count(f, SchedulingPatientAccount) == 0


def test_empty_lookup_and_wrong_choice_do_not_create_mapping(case):
    f = case
    f.port.empty = True
    observed = preview(f)
    assert observed["preview"]["choices"] == []
    with pytest.raises(ws.WorkspaceError):
        confirm(f, {"expected_revision": f.before["revision"], "key": str(uuid4()), "preview_id": observed["request_id"],
            "preview_sha256": observed["source_sha256"], "choice_ref": str(uuid4()), "identity_sha256": "c" * 64,
            "reviewed_same_patient": True, "reviewed_exact_identity": True})
    assert f.port.calls == ["preview"] and count(f, SchedulingPatientAccount) == 0


def test_changed_then_restored_display_with_advanced_subject_revision_refuses(case):
    f = case
    observed = preview(f)
    f.port.changed = True
    with pytest.raises(ws.WorkspaceError):
        confirm(f, confirmation(f, observed))
    assert count(f, SchedulingPatientMappingReview) == 0


def test_newer_reserved_preview_invalidates_late_old_result(case):
    f, inner, called = case, [], False
    original = f.port.preview
    def out_of_order(selection, request):
        nonlocal called
        if not called:
            called = True
            inner.append(preview(f))
        return original(selection, request)
    f.port.preview = out_of_order
    with pytest.raises(ws.WorkspaceError, match="scheduling_patient_preview_superseded"):
        preview(f)
    assert inner[0]["status"] == "saved" and count(f, SchedulingPatientSetupSnapshot) == 1


@pytest.mark.parametrize("table", ["scheduling_patient_setup_requests", "scheduling_patient_setup_snapshots", "scheduling_patient_mapping_reviews"])
def test_immutable_history_cannot_be_updated_or_deleted(case, table):
    f = case
    confirm(f, confirmation(f, preview(f)))
    with pytest.raises(DBAPIError) as failure:
        f.s.execute(text(f"DELETE FROM {table} WHERE box_id=:box"), {"box": f.box})
        f.s.commit()
    assert getattr(failure.value.orig, "sqlstate", None) == "23514"
    f.s.rollback()


def test_forged_personal_mapping_without_review_never_commits(case):
    f = case
    account = f.s.get(SchedulingAccount, f.account)
    f.s.add(SchedulingPatientAccount(box_id=f.box, patient_link_id=f.patient, practice_id=account.practice_id,
        patient_id=str(uuid4()), reviewed_by=f.owner, evidence_ref="scheduling-patient:v1:" + str(uuid4()), reviewed_at=datetime.now(UTC)))
    with pytest.raises(DBAPIError) as failure:
        f.s.flush()
        f.s.execute(text("SET CONSTRAINTS personal_patient_mapping_review IMMEDIATE"))
        f.s.commit()
    assert getattr(failure.value.orig, "sqlstate", None) == "23514"
    f.s.rollback()
    assert count(f, SchedulingPatientAccount) == 0


@pytest.mark.parametrize("fault", ["string_revision", "extra", "invalid_date", "future_date", "missing_dob",
    "wrong_choice", "wrong_identity", "wrong_preview", "wrong_preview_hash", "integer_ack"])
def test_forged_closed_reservation_cannot_commit_even_with_recomputed_request_hash(case, fault):
    f = case
    observed = preview(f)
    if fault in {"wrong_choice", "wrong_identity", "wrong_preview", "wrong_preview_hash", "integer_ack"}:
        saved = confirm(f, confirmation(f, observed))
        original = f.s.get(SchedulingPatientSetupRequest, saved["request_id"])
    else:
        original = f.s.get(SchedulingPatientSetupRequest, observed["request_id"])
    values = {column.name: deepcopy(getattr(original, column.name)) for column in original.__table__.columns}
    values["id"], values["idempotency_key"], values["request_nonce"] = str(uuid4()), str(uuid4()), str(uuid4())
    values["ordinal"] = original.ordinal + 1
    command = values["command"]
    command["idempotency_key"] = values["idempotency_key"]
    if fault == "string_revision":
        command["expected_revision"] = str(command["expected_revision"])
    elif fault == "extra":
        command["patient_id"] = str(uuid4())
    elif fault in {"invalid_date", "future_date"}:
        command["search"]["birth_date"] = "not-a-date" if fault == "invalid_date" else "2999-01-01"
    elif fault == "missing_dob":
        command["search"].pop("birth_date")
    elif fault == "wrong_choice":
        command["choice_ref"] = str(uuid4())
    elif fault == "wrong_identity":
        command["identity_sha256"] = "f" * 64
    elif fault == "wrong_preview":
        command["preview_id"] = str(uuid4())
    elif fault == "wrong_preview_hash":
        command["preview_sha256"] = "f" * 64
    else:
        command["reviewed_exact_identity"] = 1
    values["request_sha256"] = setup.request_hash(f.wid, command)
    f.s.add(SchedulingPatientSetupRequest(**values))
    with pytest.raises(DBAPIError) as failure:
        f.s.commit()
    assert getattr(failure.value.orig, "sqlstate", None) == "23514"
    f.s.rollback()


@pytest.mark.parametrize("fault", ["unsafe_revision", "null_identity_hash", "wrong_more", "naive_time", "extra"])
def test_forged_snapshot_payload_cannot_commit_even_with_recomputed_source_hash(case, fault):
    f = case
    observed = preview(f)
    original = f.s.scalar(select(SchedulingPatientSetupSnapshot).where(SchedulingPatientSetupSnapshot.request_id == observed["request_id"]))
    payload = deepcopy(original.payload)
    key = str(uuid4())
    f.port.fail = True
    with pytest.raises(ws.WorkspaceError, match="scheduling_patient_response_unconfirmed"):
        preview(f, key=key)
    request = f.s.scalar(select(SchedulingPatientSetupRequest).where(SchedulingPatientSetupRequest.idempotency_key == key))
    payload["request_nonce"] = request.request_nonce
    if fault == "unsafe_revision":
        payload["choices"][0]["subject_revision"] = 9007199254740992
    elif fault == "null_identity_hash":
        payload["choices"][0]["identity_sha256"] = None
    elif fault == "wrong_more":
        payload["more"] = True
    elif fault == "naive_time":
        payload["checked_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
    else:
        payload["patient_id"] = str(uuid4())
    if fault == "unsafe_revision":
        payload["choices"][0]["identity_sha256"] = patient_digest("cosmas-scheduling-patient-identity.v1",
            {k: v for k, v in payload["choices"][0].items() if k != "identity_sha256"})
    payload["preview_sha256"] = patient_digest("cosmas-scheduling-patient-preview.v1", {k: v for k, v in payload.items() if k != "preview_sha256"})
    digest = patient_digest("cosmas-scheduling-patient-payload.v1", payload)
    f.s.add(SchedulingPatientSetupSnapshot(workspace_id=f.wid, box_id=f.box, owner_id=f.owner, request_id=request.id,
        payload=payload, payload_sha256=digest, source_sha256=setup._source_hash(request, digest)))
    with pytest.raises(DBAPIError) as failure:
        f.s.commit()
    assert getattr(failure.value.orig, "sqlstate", None) == "23514"
    f.s.rollback()


def test_foreign_human_or_agent_cannot_prepare_private_lookup(case):
    f = case
    agent = f.s.scalar(select(Principal.id).where(Principal.box_id == f.box, Principal.principal_type == "agent"))
    assert agent is not None
    for actor in (str(uuid4()), agent):
        with pytest.raises((ws.WorkspaceError, DBAPIError)):
            setup.preview(f.s, f.box, actor, f.wid, f.identity, expected_revision=f.before["revision"], key=str(uuid4()),
                search={"kind": "search", "query": "Invented", "birth_date": None}, port=f.port, configuration=f.configuration)
        f.s.rollback()
    assert not f.port.calls


@pytest.fixture
def http_case(signed_workspace, session, monkeypatch):
    from tests.integration.test_handoff_review import isolate_http_request, request_sessions

    f = signed_workspace
    for name in ("workspace_scheduling_enabled", "workspace_appointments_enabled", "workspace_scheduling_login_enabled",
                 "workspace_scheduling_patient_setup_enabled"):
        monkeypatch.setattr(f.configuration, name, True)
    f.s, f.owner, f.wid, f.identity = session, f.actor, f.workspace["id"], f.binding.id
    state = ws.read(session, f.box, f.actor, f.wid)
    state = notes.save(session, f.box, f.actor, f.wid, expected=state["revision"], key=str(uuid4()), base_note_id=None,
        source_reply_id=None, content="Invented signed preexisting clinical note.")["workspace"]
    note = state["note"]["latest"]
    state = notes.review(session, f.box, f.actor, f.wid, note["id"], expected=state["revision"], key=str(uuid4()),
        content_hash=note["content_hash"], source_hash=note["source_fingerprint"])["workspace"]
    account = SchedulingAccount(external_identity_id=f.identity, label="Invented Scheduling", reviewed_by=f.actor,
        reviewed_at=datetime.now(UTC), evidence_ref="test:signed-patient-setup",
        **{k: str(uuid4()) for k in ("practice_id", "actor_id", "practitioner_id", "location_id", "appointment_type_id")})
    session.add(account)
    session.flush()
    f.account, f.connected, f.grant, f.before, f.patient = account.id, datetime.now(UTC), "b" * 64, state, f.appointment.patient_link_id
    session.add(SchedulingLoginCredential(account_id=account.id, status="ready", binding_digest="a" * 64, sealed=b"i" * 40,
        connected_at=f.connected, expires_at=f.connected + timedelta(hours=1)))
    session.commit()
    f.port = InventedReceiver(f)

    def binding(s, identity_id, a):
        f.s = s
        assert identity_id == f.identity
        return setup.PatientSetupBinding(account_id=a.id, selection=SchedulingSelection.model_validate({
            "box_id": f.box, "owner_id": f.actor, "practice_id": a.practice_id, "expected_actor_id": a.actor_id,
            "practitioner_id": a.practitioner_id, "location_id": a.location_id, "appointment_type_id": a.appointment_type_id}),
            connected_at=f.connected, binding_sha256="a" * 64, grant_sha256=f.grant)

    monkeypatch.setitem(api.app.dependency_overrides, api.get_session, request_sessions(session))
    monkeypatch.setattr(f.client, "request", isolate_http_request(f.client, session))
    monkeypatch.setattr(api, "scheduling_runtime", lambda app: SimpleNamespace(patient_setup=f.port))
    f.path = "/workspaces/" + f.wid + "/scheduling-patient/setup"
    f.headers = {"Authorization": "Bearer " + f.token(), "X-Cosmas-Scheduling-Patient": "1", "X-Cosmas-Draft-Recovery": "2"}
    with setup.install_binding_reader(binding):
        yield f


def test_actual_signed_http_patient_preview_confirmation_reopen_and_masked_replay(http_case):
    f = http_case
    first = f.client.post(f.path, headers=f.headers, json={"action": "preview", "expected_revision": f.before["revision"],
        "idempotency_key": str(uuid4()), "search": {"kind": "search", "query": "Invented Jordan", "birth_date": None}})
    assert first.status_code == 200, first.text
    observed = first.json()
    body = confirmation(f, observed)
    body = {"action": "confirm", "idempotency_key": body.pop("key"), **body}
    saved = f.client.post(f.path, headers=f.headers, json=body)
    assert saved.status_code == 200, saved.text
    value = saved.json()
    assert value["status"] == "saved" and value["mapping"]
    assert f.client.post(f.path, headers=f.headers, json=body).json() == value
    assert f.port.calls == ["preview", "verify"]
    assert f.client.post(f.path, headers=f.headers, json={"action": "resolve", "kind": "confirm",
        "idempotency_key": body["idempotency_key"]}).json() == value
    f.grant = "c" * 64
    masked = f.client.post(f.path, headers=f.headers, json=body)
    assert masked.status_code == 200 and masked.json()["source_withheld"] and masked.json()["mapping"] is None
    assert masked.json()["request_sha256"] == value["request_sha256"] and masked.json()["source_sha256"] == value["source_sha256"]
    assert "Invented Jordan" not in masked.text and f.port.patient_id not in saved.text
    assert saved.headers["cache-control"] == "no-store"


def test_initially_unmapped_signed_hosted_setup_then_exact_appointment_proposal_never_books(http_case, session, monkeypatch):
    from tests.unit.test_hosted_workspace_config import hosted

    from cosmas_os.application import provider_team as team
    from cosmas_os.application import team_resources, team_setup
    from cosmas_os.models import AppointmentReceipt, AppointmentWork

    f, origin = http_case, "https://workspace.example.invalid"
    configuration = hosted(beta_box_id=f.box, clerk_issuer=f.configuration.clerk_issuer,
        clerk_jwks_url=f.configuration.clerk_jwks_url, clerk_audience=f.configuration.clerk_audience,
        workspace_scheduling_enabled=True, workspace_appointments_enabled=True, workspace_scheduling_login_enabled=True,
        workspace_scheduling_patient_setup_enabled=True, workspace_team_setup_enabled=True)
    for name, value in configuration.model_dump().items():
        monkeypatch.setattr(f.configuration, name, value)
    monkeypatch.setattr(team, "runtime_settings", f.configuration)
    assert f.configuration.workspace_hosted_enabled and f.configuration.workspace_scheduling_patient_setup_available
    headers = {**f.headers, "Authorization": "Bearer " + f.token(azp=origin)}
    account = session.get(SchedulingAccount, f.account)
    selected = team.default_configuration()
    follower = next(bot for bot in selected["bots"] if bot["role"] == "follow_up")
    follower["resources"] = {"version": 1, "allowed": [{"purpose": "scheduling_context",
        "resource_ref": team_resources.reference(f.box, f.actor, f.identity, "scheduling_context", account)}]}
    rehearsal = team_setup.rehearsal(session, f.box, f.actor, f.identity, expected=0, configuration=selected, contract=4)
    saved_team = team.save(session, f.box, f.actor, expected=0, key=str(uuid4()), configuration=selected,
        setup_review=rehearsal["setup_review"], external_identity_id=f.identity, team_contract=4)
    account_fields = {name: getattr(account, name) for name in (
        "practice_id", "actor_id", "practitioner_id", "location_id", "appointment_type_id")}
    calls = []
    def receive(request):
        assert request.method == "GET" and request.url.host == "scheduling.example.invalid"
        assert request.url.path.endswith("/availability/verified") and not f.s.in_transaction()
        calls.append(request.url.path)
        now = datetime.now(UTC)
        value = {"contract_version": "1", "request_nonce": request.url.params["requestNonce"],
            **account_fields, "range_start": request.url.params["from"], "range_end": request.url.params["to"],
            "google": {"provider": "google", "calendar_id": "primary", "connection_id": str(uuid4()),
                "connected_at": (now - timedelta(days=1)).isoformat(), "checked_at": now.isoformat()},
            "slots": [{"starts_at": request.url.params["from"], "ends_at": request.url.params["to"]}]}
        return httpx.Response(200, json=value, headers={"Content-Type": "application/json", "Cache-Control": "no-store"})
    availability = HttpSchedulingAvailability("https://scheduling.example.invalid", lambda _: SecretStr("invented-staff-token"),
        transport=httpx.MockTransport(receive))
    class NoAppointmentWrite:
        def read_appointment(self, *_):
            pytest.fail("book proposal has no current appointment read")
        def submit(self, *_):
            pytest.fail("patient setup/proposal never writes")
    monkeypatch.setitem(api.app.dependency_overrides, api._scheduling_connection, lambda: availability)
    monkeypatch.setitem(api.app.dependency_overrides, api._appointment_connection, NoAppointmentWrite)
    at = datetime.now(UTC) + timedelta(days=2)
    command = {"bot": {"address": "follow_up", "team_revision": saved_team["revision"]}, "action": "book", "share": True,
        "idempotency_key": str(uuid4()), "slot": {"starts_at": at.isoformat(), "ends_at": (at + timedelta(minutes=30)).isoformat()}}
    path = "/workspaces/" + f.wid + "/appointments"
    try:
        refused = f.client.post(path, headers=headers, json=command)
        assert refused.status_code == 409 and not calls and not f.port.calls
        observed = f.client.post(f.path, headers=headers, json={"action": "preview", "expected_revision": f.before["revision"],
            "idempotency_key": str(uuid4()), "search": {"kind": "search", "query": "Invented Jordan", "birth_date": None}})
        assert observed.status_code == 200, observed.text
        body = confirmation(f, observed.json())
        body = {"action": "confirm", "idempotency_key": body.pop("key"), **body}
        verified = f.client.post(f.path, headers=headers, json=body)
        assert verified.status_code == 200, verified.text
        proposed = f.client.post(path, headers=headers, json=command)
        assert proposed.status_code == 200, proposed.text
        item = proposed.json()
        assert item["state"] == "pending_approval" and item["operation_id"] is None
        assert f.client.post(path, headers=headers, json=command).json()["ticket_id"] == item["ticket_id"]
        assert len(calls) == 1 and f.port.calls == ["preview", "verify"]
        session.expire_all()
        assert session.scalar(select(func.count()).select_from(AppointmentWork).where(AppointmentWork.box_id == f.box)) == 1
        assert session.scalar(select(func.count()).select_from(Operation).where(Operation.box_id == f.box)) == 0
        assert session.scalar(select(func.count()).select_from(AppointmentReceipt).where(AppointmentReceipt.box_id == f.box)) == 0
        current = ws.read(session, f.box, f.actor, f.wid)
        assert current["note"] == f.before["note"] and current["entries"] == f.before["entries"]
    finally:
        availability.close()


def test_preview_snapshot_cannot_be_forged_into_a_personal_review(case):
    f = case
    observed = preview(f)
    snapshot = f.s.scalar(select(SchedulingPatientSetupSnapshot).where(SchedulingPatientSetupSnapshot.request_id == observed["request_id"]))
    review_id, mapping_id = str(uuid4()), str(uuid4())
    at = datetime.now(UTC)
    account = f.s.get(SchedulingAccount, f.account)
    f.s.add(SchedulingPatientAccount(id=mapping_id, box_id=f.box, patient_link_id=f.patient, practice_id=account.practice_id,
        patient_id=str(uuid4()), reviewed_by=f.owner, evidence_ref="scheduling-patient:v1:" + review_id, reviewed_at=at))
    f.s.flush()
    f.s.add(SchedulingPatientMappingReview(id=review_id, workspace_id=f.wid, box_id=f.box, owner_id=f.owner,
        request_id=observed["request_id"], snapshot_id=snapshot.id, mapping_id=mapping_id, patient_link_id=f.patient,
        reviewed_same_patient=True, reviewed_exact_identity=True, mapping_sha256="f" * 64, created_at=at))
    with pytest.raises(DBAPIError) as failure:
        f.s.flush()
        f.s.execute(text("SET CONSTRAINTS patient_setup_review_settlement IMMEDIATE"))
        f.s.commit()
    assert getattr(failure.value.orig, "sqlstate", None) == "23514"
    f.s.rollback()


@pytest.mark.parametrize("fault", ["scope", "header", "extra", "query", "duplicate", "disabled"])
def test_actual_signed_http_refuses_invalid_authority_before_provider(http_case, monkeypatch, fault):
    f = http_case
    body = {"action": "preview", "expected_revision": f.before["revision"], "idempotency_key": str(uuid4()),
        "search": {"kind": "search", "query": "Invented", "birth_date": None}}
    headers, path = dict(f.headers), f.path
    if fault == "scope":
        headers["Authorization"] = "Bearer " + f.token(sub="unbound-invented")
    elif fault == "header":
        headers["X-Cosmas-Scheduling-Patient"] = "2"
    elif fault == "extra":
        body["patient_id"] = str(uuid4())
    elif fault == "query":
        path += "?patient_id=" + str(uuid4())
    elif fault == "disabled":
        monkeypatch.setattr(f.configuration, "workspace_scheduling_patient_setup_enabled", False)
    if fault == "duplicate":
        response = f.client.post(path, headers={**headers, "Content-Type": "application/json"}, content='{"action":"status","action":"preview"}')
    else:
        response = f.client.post(path, headers=headers, json=body)
    assert response.status_code in {403, 404, 422, 426} and response.headers["cache-control"] == "no-store"
    assert not f.port.calls



def install_personal_fixture(s, *, box, owner, wid, identity_id, account, configuration, patient_id=None):
    """Context-managed real custody creation for synthetic hosted fixture migration.

    Start unmapped: caller must not insert raw SchedulingPatientAccount. Existing
    confirmed fixture mapping is a conflict, never silently adopted or removed.
    """
    from contextlib import contextmanager

    @contextmanager
    def installed():
        state = ws.read(s, box, owner, wid)
        account_id = account.id
        at = datetime.now(UTC)
        credential = s.get(SchedulingLoginCredential, account_id)
        if credential is None:
            credential = SchedulingLoginCredential(account_id=account_id, status="ready", binding_digest="a" * 64,
                sealed=b"i" * 40, connected_at=at, expires_at=at + timedelta(hours=1))
            s.add(credential)
            binding_digest, connected_at = "a" * 64, at
            s.commit()
        else:
            binding_digest, connected_at = credential.binding_digest, credential.connected_at
        f = SimpleNamespace(s=s, box=box, owner=owner, wid=wid, identity=identity_id, account=account_id,
            configuration=configuration, before=state, grant="b" * 64, connected=connected_at)
        port = InventedReceiver(f)
        if patient_id is not None:
            port.patient_id = patient_id
        f.port = port
        def binding(current, external_id, a):
            f.s = current
            assert external_id == identity_id and a.id == account_id
            return setup.PatientSetupBinding(account_id=a.id, selection=SchedulingSelection.model_validate({
                "box_id": box, "owner_id": owner, "practice_id": a.practice_id, "expected_actor_id": a.actor_id,
                "practitioner_id": a.practitioner_id, "location_id": a.location_id, "appointment_type_id": a.appointment_type_id}),
                binding_sha256=binding_digest, connected_at=f.connected, grant_sha256=f.grant)
        with setup.install_binding_reader(binding):
            observed = preview(f)
            receipt = confirm(f, confirmation(f, observed))
            yield receipt
    return installed()


def test_same_key_concurrent_confirmation_creates_one_mapping_and_one_verify(engine):
    from cosmas_os.application import services as svc

    with Session(engine) as owned:
        seed = svc.provision_box(svc.Container(owned), "Invented personal mapping concurrency")
        patcher = pytest.MonkeyPatch()
        generator = cast(Any, case).__wrapped__(owned, seed, patcher)
        f = next(generator)
        try:
            observed = preview(f)
            body = confirmation(f, observed)
            waiting, settled = Event(), Event()
            calls = []
            def attempt(block):
                with Session(engine) as current:
                    worker = SimpleNamespace(**vars(f))
                    worker.s = current
                    worker.port = InventedReceiver(worker)
                    worker.port.choice, worker.port.patient_id = f.port.choice, f.port.patient_id
                    original = worker.port.verify
                    def verify(selected, request, preview):
                        calls.append("verify")
                        if block:
                            waiting.set()
                            assert settled.wait(5)
                        return original(selected, request, preview)
                    worker.port.verify = verify
                    return confirm(worker, body)
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(attempt, True)
                assert waiting.wait(5)
                second = pool.submit(attempt, False)
                pending = second.result(timeout=5)
                assert pending["status"] == "unconfirmed"
                settled.set()
                saved = first.result(timeout=5)
            assert saved["status"] == "saved" and calls == ["verify"]
            owned.expire_all()
            assert confirm(f, body)["request_id"] == saved["request_id"]
            assert count(f, SchedulingPatientMappingReview) == count(f, SchedulingPatientAccount) == 1
        finally:
            generator.close()
            patcher.undo()
