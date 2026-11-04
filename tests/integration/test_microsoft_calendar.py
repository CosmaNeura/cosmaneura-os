"""Invented Outlook events through real DB custody and Chief model context."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_note_review import prepare

from cosmas_os.application import conversation, handoffs, model_work, provider_team
from cosmas_os.application import microsoft_calendar as calendar
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.microsoft_calendar_models import MicrosoftCalendarObservationRequest
from cosmas_os.microsoft_connection_models import MicrosoftConnectionCredential
from cosmas_os.models import EncounterWorkspace, ExternalIdentity, WorkspaceEntry
from cosmas_os.ports.microsoft_calendar import (
    MicrosoftCalendarAccount,
    MicrosoftCalendarBinding,
    MicrosoftCalendarEvent,
    MicrosoftCalendarObservation,
    MicrosoftCalendarRead,
)


class InventedCalendar:
    def __init__(self, account, connected):
        self.account, self.connected, self.grant, self.calls = account, connected, "b" * 64, []
        self.session = None

    def calendar_binding(self, identity, *, session=None):
        assert session is not None and identity.external_identity_id == self.account
        return MicrosoftCalendarBinding(account_id=self.account, binding_digest="a" * 64,
            connected_at=self.connected, grant_sha256=self.grant)

    def calendar_observation(self, identity, *, window):
        assert self.session is not None and not self.session.in_transaction()
        self.calls.append("one-bounded-Graph-calendarView-GET")
        return MicrosoftCalendarRead(observation=MicrosoftCalendarObservation(kind="calendar",
            account=MicrosoftCalendarAccount(label="Invented clinic Outlook", email="clinician@example.invalid"),
            items=tuple(MicrosoftCalendarEvent(id=identifier, subject=subject,
                starts_at=(window.starts_at + timedelta(hours=2)).isoformat(),
                ends_at=(window.starts_at + timedelta(hours=3)).isoformat(), all_day=False, cancelled=False)
                for identifier, subject in (("AAMk+/selected==", "Invented selected visit planning"),
                    ("AAMk+/unrelated==", "Invented unrelated event"))),
            more=True, observed_at=datetime.now(UTC), window=window),
            custody=self.calendar_binding(identity, session=self.session))


@pytest.fixture
def outlook_case(engine, monkeypatch):
    config = Settings(_env_file=None, workspace_enabled=True, workspace_authenticated_enabled=True,  # pyright: ignore[reportCallIssue]
        auth_mode="clerk_jwt", synth_seed=False, clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json", clerk_audience="cosmas-workspace-local",
        clerk_organization_id="org_invented", clerk_authorized_parties="http://localhost:5173",
        cors_allowed_origins="http://localhost:5173", workspace_microsoft_connection_enabled=True,
        workspace_microsoft_calendar_enabled=True, workspace_llm_backend="azure_gpt41",
        workspace_llm_api_key=SecretStr("invented-model-fixture-only"))
    for module in (provider_team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", config)
    with Session(engine) as s:
        seeded = svc.provision_box(svc.Container(s), "Invented Outlook calendar practice")
        config.beta_box_id = seeded["box_id"]
        box, actor, current, patient = prepare(s, seeded)
        provider_team.save(s, box, actor, expected=0, key="outlook-calendar-team", configuration=provider_team.default_configuration())
        now = datetime.now(UTC)
        account = ExternalIdentity(box_id=box, principal_id=actor, issuer="https://clerk-" + str(uuid4()) + ".example.invalid",
            subject="invented-owner", organization_id="org_invented", reviewed_by="Invented owner", evidence_ref="invented:calendar")
        s.add(account)
        s.flush()
        s.add(MicrosoftConnectionCredential(account_id=account.id, binding_digest="a" * 64, status="ready",
            sealed=b"i" * 40, connected_at=now, expires_at=now + timedelta(hours=1)))
        s.commit()
        case = SimpleNamespace(engine=engine, box=box, actor=actor, wid=current["id"], patient=patient,
            account=account.id, port=InventedCalendar(account.id, now), config=config)
    with calendar.install_binding_reader(lambda s, a: case.port.calendar_binding(calendar._scoped_identity(a), session=s)):
        yield case


def observe(case, key="outlook-observe-1"):
    with Session(case.engine) as s:
        case.port.session = s
        return calendar.observe(s, case.box, case.actor, case.account, key=key, port=case.port)


def review(case, observed, **changes):
    with Session(case.engine) as s:
        w = ws.read(s, case.box, case.actor, case.wid)
        event = observed["observation"]["items"][0]
        body = dict(expected=w["revision"], key="outlook-review-1", observation_id=observed["observation_id"],
            observation_sha256=observed["source_sha256"], event_id=event["id"], event_sha256=calendar.event_hash(event),
            reviewed_visit=True, reviewed_exact_summary=True, reviewed_untrusted_source=True,
            port=case.port, external_identity_id=case.account)
        body.update(changes)
        return calendar.select_review(s, case.box, case.actor, case.wid, **body)


def test_selected_event_explicitly_saved_to_linked_visit_then_chief_receives_only_saved_source(outlook_case):
    f = outlook_case
    observed = observe(f)
    with Session(f.engine) as s:
        assert not list(s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == f.wid,
            WorkspaceEntry.kind == "microsoft_calendar")))
    saved = review(f, observed)
    assert saved["source_withheld"] is False and len(f.port.calls) == 1
    source = next(e for e in saved["workspace"]["entries"] if e["id"] == saved["entry_id"])
    assert source["microsoft_calendar_source_state"] == "current"
    assert "Invented selected visit planning" in source["content"] and "Invented unrelated event" not in source["content"]
    assert saved["workspace"]["note"]["latest"] is None
    with Session(f.engine) as s:
        w = ws.read(s, f.box, f.actor, f.wid)
        admission, _ = model_work.reserve_conversation(s, f.box, f.actor, f.wid, expected=w["revision"],
            team_revision=1, key="outlook-chief-review", role="chief", content="Prepare questions about the saved calendar summary.")
        claimed = model_work.claim(s, f.box, f.actor, admission)
        assert claimed is not None
        selected = [p for p in claimed.envelope["context"]["sources"] if p["entry_id"] == saved["entry_id"]]
        assert len(selected) == 1 and selected[0]["kind"] == "evidence" and selected[0]["content"] == source["content"]
        model_work.settle(s, claimed, RuntimeError("invented terminal model refusal; no provider call"))
    assert len(f.port.calls) == 1


@pytest.mark.parametrize("change,code", [("event", "microsoft_calendar_not_observed"),
    ("hash", "microsoft_calendar_source_changed"), ("revision", "workspace_revision_conflict"),
    ("grant", "microsoft_calendar_grant_changed"), ("account", "microsoft_calendar_observation_unavailable"),
    ("ack", "invalid_microsoft_calendar_review")])
def test_selection_fails_closed_without_current_exact_review(outlook_case, change, code):
    f = outlook_case
    observed = observe(f)
    changes = {"event": {"event_id": "AAMk+/foreign=="}, "hash": {"observation_sha256": "c" * 64},
        "revision": {"expected": 999}, "account": {"external_identity_id": str(uuid4())},
        "ack": {"reviewed_exact_summary": False}, "grant": {}}[change]
    if change == "grant":
        f.port.grant = "d" * 64
    with pytest.raises(ws.WorkspaceError, match=code):
        review(f, observed, **changes)
    with Session(f.engine) as s:
        assert not list(s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == f.wid,
            WorkspaceEntry.kind == "microsoft_calendar")))


def test_exact_review_retry_reuses_saved_entry_and_lost_read_resolution_does_not_replay_graph(outlook_case):
    f = outlook_case
    observed = observe(f)
    first = review(f, observed)
    second = review(f, observed, expected=first["entry_revision"] - 1)
    assert first["entry_id"] == second["entry_id"] and len(f.port.calls) == 1
    with Session(f.engine) as s:
        resolved = calendar.resolve_observation(s, f.box, f.actor, f.account, key="outlook-observe-1", port=f.port)
        assert resolved["observation_id"] == observed["observation_id"]
    assert len(f.port.calls) == 1


def test_saved_source_withheld_after_new_observation_or_account_revocation(outlook_case):
    f = outlook_case
    observed = observe(f)
    first = review(f, observed)
    observe(f, "outlook-new-summary")
    with Session(f.engine) as s:
        w = ws.read(s, f.box, f.actor, f.wid)
        source = next(e for e in w["entries"] if e["id"] == first["entry_id"])
        assert source["microsoft_calendar_source_state"] == "unavailable" and source["content"] == ""
        assert calendar.selected_entries(s, s.get(EncounterWorkspace, f.wid),
            provider_team.default_configuration()["bots"][0], w["revision"]) == []
        credential = s.get(MicrosoftConnectionCredential, f.account)
        credential.status, credential.sealed = "disconnected", None
        s.commit()
        with pytest.raises(ws.WorkspaceError, match="microsoft_calendar_grant_unavailable"):
            calendar.inspect_observation(s, f.box, f.actor, f.account, observation_id=observed["observation_id"], port=f.port)


def test_direct_unreviewed_entry_and_snapshot_mutation_are_rejected_by_database(outlook_case):
    f = outlook_case
    observed = observe(f)
    with Session(f.engine) as s:
        w = s.get(EncounterWorkspace, f.wid)
        w.revision += 1
        s.add(WorkspaceEntry(workspace_id=f.wid, box_id=f.box, actor_id=f.actor, revision=w.revision,
            kind="microsoft_calendar", content="Invented forged source", source_label="Outlook calendar: forged",
            idempotency_key="outlook-forged-source", request_hash="a" * 64))
        with pytest.raises(DBAPIError):
            s.commit()
        s.rollback()
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE microsoft_calendar_observation_requests SET ordinal=ordinal+1 WHERE id=:id"),
                {"id": observed["observation_id"]})
            s.commit()
        s.rollback()
        assert s.get(MicrosoftCalendarObservationRequest, observed["observation_id"]).ordinal == 1


@pytest.mark.parametrize("scope", ["box", "owner", "workspace"])
def test_calendar_review_rejects_cross_scope_without_saving(outlook_case, scope):
    f = outlook_case
    observed = observe(f)
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.actor, f.wid)
        event = observed["observation"]["items"][0]
        with pytest.raises(ws.WorkspaceError):
            calendar.select_review(s, str(uuid4()) if scope == "box" else f.box,
                str(uuid4()) if scope == "owner" else f.actor,
                str(uuid4()) if scope == "workspace" else f.wid,
                expected=current["revision"], key="outlook-cross-scope", observation_id=observed["observation_id"],
                observation_sha256=observed["source_sha256"], event_id=event["id"], event_sha256=calendar.event_hash(event),
                reviewed_visit=True, reviewed_exact_summary=True, reviewed_untrusted_source=True,
                port=f.port, external_identity_id=f.account)
        s.rollback()
        assert not list(s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == f.wid,
            WorkspaceEntry.kind == "microsoft_calendar")))
    assert len(f.port.calls) == 1
