"""Actual SQL and signed API proof; invented calendar/Chief ports never use network."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from tests.integration.test_google_calendar import InventedCalendar
from tests.integration.test_google_calendar import http_case as _http_case
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.application import conversation, provider_team
from cosmas_os.application import google_calendar as calendar
from cosmas_os.application import workspace as ws
from cosmas_os.google_calendar_models import (
    GoogleCalendarPrivateSourceReview,
    GoogleCalendarSourceReview,
)
from cosmas_os.google_connection_models import GoogleConnectionCredential
from cosmas_os.models import (
    AppointmentObservation,
    ExternalIdentity,
    PatientLink,
    WorkspaceEntry,
    WorkspaceNote,
)
from cosmas_os.ports.bot_capabilities import BotReply, SourcePassage

http_case = _http_case
signed_workspace = _signed_workspace


def counts(s):
    return tuple(s.scalar(select(func.count()).select_from(model)) for model in (PatientLink, AppointmentObservation, WorkspaceNote))


@pytest.fixture
def private_case(session, seeded):
    box, owner = seeded["box_id"], seeded["owner_id"]
    workspace = ws.create_private_draft(session, box, owner, "Invented personal planning", "private-notebook-create")
    account = ExternalIdentity(box_id=box, principal_id=owner, issuer="https://clerk.example.invalid",
        subject="user_invented_calendar", organization_id="org_invented", reviewed_by="Invented owner", evidence_ref="invented:calendar-private")
    session.add(account)
    session.flush()
    now = datetime.now(UTC)
    session.add(GoogleConnectionCredential(account_id=account.id, binding_digest="a" * 64, status="ready", sealed=b"i" * 40,
        connected_at=now, expires_at=now + timedelta(hours=1)))
    session.commit()
    port = InventedCalendar(session, account.id, now)
    port.change = lambda event: {**event, "subject": "Invented personal travel planning"}
    with calendar.install_binding_reader(lambda s, a: port.calendar_binding(calendar._scoped_identity(a), session=s)):
        observed = calendar.observe(session, box, owner, account.id, key="private-observe", port=port)
        event = observed["observation"]["items"][0]
        command = dict(expected=1, key="private-calendar-review", observation_id=observed["observation_id"],
            observation_sha256=observed["source_sha256"], event_id=event["id"], event_sha256=calendar.event_hash(event),
            reviewed_private_notebook=True, reviewed_exact_summary=True, reviewed_untrusted_source=True,
            external_identity_id=account.id, port=port)
        yield SimpleNamespace(s=session, box=box, owner=owner, w=workspace, account=account.id, port=port, command=command)


def save(f, **changes):
    return calendar.select_review(f.s, f.box, f.owner, f.w["id"], **{**f.command, **changes})


def test_private_exact_review_reopen_and_replay_never_create_clinical_records(private_case):
    f = private_case
    before = counts(f.s)
    saved = save(f)
    f.s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert saved["workspace"]["appointment_id"] is None and saved["workspace"]["private_draft"]["state"] == "unlinked"
    assert saved["source_withheld"] is False
    entry = next(e for e in saved["workspace"]["entries"] if e["id"] == saved["entry_id"])
    assert entry["kind"] == "google_calendar" and entry["calendar_source_state"] == "current"
    assert "personal travel" in entry["content"]
    assert counts(f.s) == before == (0, 0, 0)
    assert f.s.scalar(select(func.count()).select_from(GoogleCalendarSourceReview)) == 0
    assert f.s.scalar(select(func.count()).select_from(GoogleCalendarPrivateSourceReview)) == 1
    assert f.s.scalar(text("SELECT google_calendar_source_valid(:id)"), {"id": saved["entry_id"]})
    assert f.s.scalar(text("SELECT google_calendar_source_current(:id)"), {"id": saved["entry_id"]})
    assert save(f)["entry_id"] == saved["entry_id"] and len(f.port.calls) == 1
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        save(f, event_sha256="f" * 64)


def test_private_review_is_withheld_on_revocation_without_repeating_provider_io(private_case):
    f = private_case
    saved = save(f)
    credential = f.s.get(GoogleConnectionCredential, f.account)
    credential.status, credential.sealed = "disconnected", None
    f.s.commit()
    replay = save(f)
    assert replay["source_withheld"] is True and replay["entry_id"] == saved["entry_id"]
    entry = next(e for e in replay["workspace"]["entries"] if e["id"] == saved["entry_id"])
    assert entry["calendar_source_state"] == "unavailable" and "personal travel" not in str(entry)
    assert len(f.port.calls) == 1


def test_private_source_cannot_silently_become_clinical_when_notebook_is_linked(private_case):
    f = private_case
    saved = save(f)
    patient = PatientLink(box_id=f.box, source_pair_key="invented:" + str(uuid4()), label="Invented separate patient",
        state="confirmed", confirmed_by_principal_id=f.owner, attested_at=datetime.now(UTC))
    f.s.add(patient)
    f.s.flush()
    appointment = AppointmentObservation(box_id=f.box, patient_link_id=patient.id, external_id=str(uuid4()),
        source="synthetic", start_at=datetime.now(UTC), patient_label="Invented separate visit")
    f.s.add(appointment)
    f.s.commit()
    linked = ws.link_appointment(f.s, f.box, f.owner, f.w["id"], expected=saved["workspace"]["revision"],
        key="explicit-link-after-review", appointment=appointment.id, confirmed=True)
    assert linked["workspace"]["private_draft"]["state"] == "linked"
    assert f.s.scalar(text("SELECT google_calendar_source_current(:id)"), {"id": saved["entry_id"]}) is False
    replay = save(f)
    assert replay["source_withheld"] and replay["entry_id"] == saved["entry_id"]
    with pytest.raises(ws.WorkspaceError, match="google_calendar_private_notebook_required"):
        save(f, expected=linked["workspace"]["revision"], key="private-fresh-after-link")
    assert f.s.scalar(select(func.count()).select_from(WorkspaceNote)) == 0


@pytest.mark.parametrize("fault", ["owner", "acknowledgment", "content"])
def test_sql_private_custody_rejects_forgery_atomically(private_case, fault):
    f = private_case
    saved = save(f)
    row = f.s.scalar(select(GoogleCalendarPrivateSourceReview))
    with pytest.raises(DBAPIError), f.s.begin_nested():
        if fault == "owner":
            f.s.execute(text("UPDATE google_calendar_private_source_reviews SET owner_id=:owner WHERE id=:id"), {"owner": str(uuid4()), "id": row.id})
        elif fault == "acknowledgment":
            f.s.execute(text("UPDATE google_calendar_private_source_reviews SET reviewed_private_notebook=false WHERE id=:id"), {"id": row.id})
        else:
            f.s.execute(text("UPDATE workspace_entries SET content='Invented forged content' WHERE id=:id"), {"id": saved["entry_id"]})
    assert f.s.scalar(text("SELECT google_calendar_source_current(:id)"), {"id": saved["entry_id"]})


def test_clinical_review_contract_stays_patient_required(private_case):
    f = private_case
    with pytest.raises(ws.WorkspaceError, match="workspace_appointment_required"):
        save(f, reviewed_private_notebook=None, reviewed_visit=True)
    assert f.s.scalar(text("SELECT is_nullable FROM information_schema.columns WHERE table_name='google_calendar_source_reviews' AND column_name='patient_link_id'")) == "NO"
    assert f.s.scalar(select(func.count()).select_from(WorkspaceEntry)) == 0


def test_private_deferred_commitment_rejects_changed_digest(private_case, monkeypatch):
    f = private_case
    def forge(_mapper, _connection, row):
        row.content_sha256 = "f" * 64
    event.listen(GoogleCalendarPrivateSourceReview, "before_insert", forge)
    try:
        # Bypass only the Python response projection, leaving every actual SQL
        # insert and BEFORE/deferred trigger in place to prove the final fence.
        monkeypatch.setattr(calendar, "_selection_receipt", lambda *_args: {})
        monkeypatch.setattr(f.s, "commit", f.s.flush)
        with pytest.raises(DBAPIError, match="Private calendar commitment invalid"), f.s.begin_nested():
            save(f)
            f.s.execute(text("SET CONSTRAINTS google_calendar_private_commitment_guard IMMEDIATE"))
    finally:
        event.remove(GoogleCalendarPrivateSourceReview, "before_insert", forge)
    assert f.s.scalar(select(func.count()).select_from(GoogleCalendarPrivateSourceReview)) == 0


def test_signed_private_calendar_to_chief_keeps_private_context_and_exact_recovery(http_case, monkeypatch):
    f = http_case
    auth = {**f.headers, "X-Cosmas-Private-Draft": "1", "X-Cosmas-Model-Contract": "1"}
    before = counts(f.s)
    opened = f.client.post("/workspaces/private-drafts", headers=auth, json={"title": "Invented personal plan", "idempotency_key": "http-private-calendar"})
    assert opened.status_code == 200, opened.text
    draft = opened.json()
    status_path = "/connections/google/calendar-summaries"
    old_status = f.client.post(status_path, headers=auth, json={"action": "status"})
    opted = f.client.post(status_path, headers=auth, json={"action": "status", "include_private_notebook": True})
    assert old_status.status_code == opted.status_code == 200
    assert "private_notebook_review" not in old_status.json() and opted.json()["private_notebook_review"] is True
    observation = f.client.post(status_path, headers=auth, json={"action": "observe", "idempotency_key": "http-private-observe"}).json()
    event = observation["observation"]["items"][0]
    command = dict(expected_revision=draft["revision"], idempotency_key="http-private-review", observation_id=observation["observation_id"],
        observation_sha256=observation["source_sha256"], event_id=event["id"], event_sha256=calendar.event_hash(event),
        reviewed_private_notebook=True, reviewed_exact_summary=True, reviewed_untrusted_source=True)
    path = "/workspaces/" + draft["id"]
    saved = f.client.post(path + "/google-calendar/review", headers=auth, json=command)
    assert saved.status_code == 200, saved.text
    selected = saved.json()
    f.configuration.workspace_agent_tools_enabled = True
    f.configuration.workspace_llm_backend = "azure_gpt41"
    f.configuration.workspace_llm_api_key = SecretStr("invented-private-calendar-no-network")
    for module in (provider_team, conversation):
        monkeypatch.setattr(module, "runtime_settings", f.configuration)
    provider_team.save(f.s, f.box, f.actor, expected=0, key="private-calendar-team", configuration=provider_team.default_configuration())
    calls = []
    def reply(claim):
        calls.append(claim)
        source = next(item for item in claim.envelope["context"]["sources"] if item["entry_id"] == selected["entry_id"])
        return BotReply("Private planning draft; no booking or patient action.", (SourcePassage(**source),), "azure_gpt41", 20, 8)
    actual = conversation.ask
    monkeypatch.setattr(conversation, "ask", lambda *args, **kwargs: actual(*args, **{**kwargs, "dispatch": reply}))
    prompt = {"expected_revision": selected["workspace"]["revision"], "team_revision": 1,
        "idempotency_key": "private-calendar-chief", "role": "chief", "content": "Help organize this personal event; no patient is selected."}
    answer = f.client.post(path + "/conversation", headers=auth, json=prompt)
    assert answer.status_code == 200 and answer.json()["outcome"] == "saved", answer.text
    sources = calls[0].envelope["context"]["sources"]
    assert any(item["entry_id"] == selected["entry_id"] for item in sources)
    assert calls[0].envelope["tool_selection"]["operations"] == []
    reopened = f.client.get(path, headers=auth).json()
    assert reopened["appointment_id"] is None and reopened["private_draft"]["state"] == "unlinked"
    assert reopened["entries"][-1]["reply"]["content"].startswith("Private planning draft")
    assert counts(f.s) == before and len(calls) == 1 and len(f.port.calls) == 1
    recovered = f.client.post(path + "/conversation/resolve", headers=auth, json=prompt)
    assert recovered.status_code == 200 and recovered.json()["saved_entry"] == answer.json()["saved_entry"]
    assert len(calls) == 1
