"""Calendar lineage through real product admission/tools/review; invented upstreams."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration import test_google_message_model_work as gmail
from tests.integration import test_product_agent_tool_workflow as product

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.application import google_calendar as calendar
from cosmas_os.application import handoff_review as reviews
from cosmas_os.application import handoff_revision as revisions
from cosmas_os.application import model_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.google_connection_models import GoogleConnectionCredential
from cosmas_os.models import (
    EncounterWorkspace,
    ModelUsageObservation,
    ModelWorkAdmission,
    Principal,
    WorkspaceHandoffReview,
    WorkspaceNote,
    WorkspaceReply,
)
from cosmas_os.ports.google_calendar import (
    GoogleCalendarAccount,
    GoogleCalendarBinding,
    GoogleCalendarEvent,
    GoogleCalendarObservation,
    GoogleCalendarRead,
)

google_case = gmail.google_case


class InventedCalendar:
    def __init__(self, f):
        self.session, self.account, self.connected = None, f.account, f.port.connected
        self.grant, self.calls = "b" * 64, []
        self.subject = "Invented calendar café coordination"
        self.all_day = False
        self.short_seconds = None

    def calendar_binding(self, identity, *, session=None):
        assert session is not None and identity.external_identity_id == self.account
        return GoogleCalendarBinding(
            account_id=self.account,
            binding_digest="a" * 64,
            connected_at=self.connected,
            grant_sha256=self.grant,
        )

    def calendar_observation(self, identity, *, window):
        assert self.session is not None and not self.session.in_transaction()
        self.calls.append("primary_7day_summary")
        event = GoogleCalendarEvent(
            id="invented-calendar-event",
            subject=self.subject,
            starts_at=(window.starts_at.date() + timedelta(days=2)).isoformat()
            if self.all_day
            else (window.starts_at + timedelta(hours=2)).isoformat(),
            ends_at=(window.starts_at.date() + timedelta(days=4)).isoformat()
            if self.all_day
            else (window.starts_at + timedelta(hours=3)).isoformat(),
            all_day=self.all_day,
            cancelled=False,
        )
        if self.short_seconds is not None:
            event = GoogleCalendarEvent(
                id=event.id,
                subject=event.subject,
                starts_at=(window.starts_at - timedelta(seconds=1)).isoformat(),
                ends_at=(window.starts_at + timedelta(seconds=self.short_seconds)).isoformat(),
                all_day=False,
                cancelled=False,
            )
        return GoogleCalendarRead(
            observation=GoogleCalendarObservation(
                kind="calendar",
                account=GoogleCalendarAccount(
                    label="Invented calendar account", email="owner@example.invalid"
                ),
                items=(event,),
                more=True,
                observed_at=datetime.now(UTC),
                window=window,
            ),
            custody=self.calendar_binding(identity, session=self.session),
        )


@pytest.fixture
def calendar_case(google_case, monkeypatch):
    f = google_case
    monkeypatch.setattr(team.runtime_settings, "workspace_google_calendar_enabled", True)
    assert team.runtime_settings.workspace_google_calendar_available
    port = InventedCalendar(f)
    with calendar.install_binding_reader(
        lambda s, a: port.calendar_binding(calendar._scoped_identity(a), session=s)
    ):
        f.calendar_port = port
        f.calendar_selected = select_calendar(f, "initial")
        yield f


def select_calendar(f, key):
    with Session(f.engine) as s:
        f.calendar_port.session = s
        observed = calendar.observe(
            s, f.box, f.owner, f.account, key="calendar-observe-" + key, port=f.calendar_port
        )
        observation = observed["observation"]
        event = observation["items"][0]
        current = ws.read(s, f.box, f.owner, f.wid)
        return calendar.select_review(
            s,
            f.box,
            f.owner,
            f.wid,
            expected=current["revision"],
            key="calendar-review-" + key,
            observation_id=observed["observation_id"],
            observation_sha256=observed["source_sha256"],
            event_id=event["id"],
            event_sha256=calendar.event_hash(GoogleCalendarEvent.model_validate(event)),
            reviewed_visit=True,
            reviewed_exact_summary=True,
            reviewed_untrusted_source=True,
            port=f.calendar_port,
            external_identity_id=f.account,
        )


def reserve(f, key, role="chief"):
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        admission, _ = work.reserve_conversation(
            s,
            f.box,
            f.owner,
            f.wid,
            expected=current["revision"],
            team_revision=1,
            key=key,
            role=role,
            content="Use the reviewed calendar and email to prepare a private administrative draft with Follow-up.",
        )
        claimed = work.claim(s, f.box, f.owner, admission)
        assert claimed is not None
        return claimed


def model_http(f, claimed, *, offer=False, cited=True, change=None):
    context = _context(claimed.envelope["context"])
    source = next(p for p in context.sources if p.entry_id == f.calendar_selected["entry_id"])
    handle = next(
        h for h in claimed.envelope["tool_selection"]["sources"] if h["entry_id"] == source.entry_id
    )
    assert source.kind == handle["kind"] == "evidence"
    assert handle["sha256"] == hashlib.sha256(source.content.encode()).hexdigest()
    calls = []

    def respond(request):
        assert str(request.url) == ENDPOINT
        body = json.loads(request.content)
        calls.append(body)
        with Session(f.engine) as check:
            assert check.scalar(
                select(Principal).where(Principal.id == f.owner).with_for_update(nowait=True)
            )
        if change and len(calls) == 1:
            change()
        if len(calls) == 1:
            supplied = json.loads(body["messages"][1]["content"])["sources"]
            assert any(
                p["source_id"] == source.entry_id and p["text"] == source.content for p in supplied
            )
            return httpx.Response(200, json=product.response(calls=[product.read_call(handle)]))
        result = json.loads(body["messages"][-1]["content"])
        assert result["data"]["content"] == source.content
        answer = "Invented calendar café coordination; human readiness check required. No scheduling or clinical approval."
        output = {
            "answer": answer,
            "source_ids": [
                p.entry_id for p in context.sources if cited or p.entry_id != source.entry_id
            ],
        }
        if claimed.envelope["baseline"]["flags"]["work_status"]:
            output["intent"] = "conversation"
        if claimed.envelope["baseline"]["flags"]["can_handoff"]:
            output["handoffs"] = (
                [
                    {
                        "role": "follow_up",
                        "intended_role": "follow_up",
                        "brief": "Prepare calendar café coordination draft; state uncertainty and human ownership.",
                        "requirements": REQUIREMENTS,
                    }
                ]
                if offer
                else []
            )
        return httpx.Response(200, json=product.response(output))

    return httpx.MockTransport(respond), calls


def finish_handoff(f, *, cited=True):
    claimed = reserve(f, "calendar-chief")
    transport, calls = model_http(f, claimed, offer=True, cited=cited)
    assert (
        product.dispatch_and_settle(f.engine, claimed, transport)[0] == "completed"
        and len(calls) == 2
    )
    with Session(f.engine) as s:
        child = s.scalar(
            select(ModelWorkAdmission).where(
                ModelWorkAdmission.workspace_id == f.wid,
                ModelWorkAdmission.kind == "private_handoff",
            )
        )
        assert child is not None
        claimed = work.claim(s, f.box, f.owner, child.id)
        assert claimed is not None
    transport, calls = model_http(f, claimed, cited=cited)
    assert (
        product.dispatch_and_settle(f.engine, claimed, transport)[0] == "completed"
        and len(calls) == 2
    )
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        handoff = current["handoffs"][0]
        reply = s.get(WorkspaceReply, handoff["result_entry_id"])
        assert reply is not None
        return {
            "expected": current["revision"],
            "key": "calendar-human-review",
            "attempt_id": handoff["attempt_id"],
            "result_entry_id": reply.entry_id,
            "result_sha256": hashlib.sha256(reply.content.encode()).hexdigest(),
            "decision": "changes_requested",
            "feedback": "Invented calendar café fact: add an explicit done-when.",
        }, handoff


def invalidate(f, fault):
    if fault == "superseded":
        f.calendar_port.subject = "Invented replacement summary"
        f.calendar_replacement = select_calendar(f, "replacement")
    elif fault == "unconfirmed_new_observation":
        original = f.calendar_port.calendar_observation
        f.calendar_port.calendar_observation = lambda *a, **k: (_ for _ in ()).throw(
            TimeoutError("invented")
        )
        with Session(f.engine) as s:
            f.calendar_port.session = s
            with pytest.raises(ws.WorkspaceError):
                calendar.observe(
                    s,
                    f.box,
                    f.owner,
                    f.account,
                    key="calendar-observe-unconfirmed",
                    port=f.calendar_port,
                )
        f.calendar_port.calendar_observation = original
    elif fault == "grant_changed":
        f.calendar_port.grant = "d" * 64
    else:
        with Session(f.engine) as s:
            credential = s.get(GoogleConnectionCredential, f.account)
            assert credential is not None
            if fault == "reconnect":
                credential.connected_at += timedelta(seconds=1)
            else:
                credential.status = "disconnected"
            s.commit()


def test_calendar_and_gmail_real_tool_context_human_revision_acceptance_preserves_note(
    calendar_case,
):
    f = calendar_case
    command, handoff = finish_handoff(f)
    with Session(f.engine) as s:
        saved = reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        review = next(h for h in saved["workspace"]["handoffs"] if h["id"] == handoff["id"])[
            "review"
        ]
        revised = revisions.reserve(
            s,
            f.box,
            f.owner,
            f.wid,
            handoff["id"],
            expected=saved["workspace"]["revision"],
            key="calendar-revised-assignment",
            review_id=review["id"],
        )
        child = next(
            h for h in revised["workspace"]["handoffs"] if h["id"] == revised["revision_handoff_id"]
        )
        admission = s.scalar(
            select(ModelWorkAdmission).where(
                ModelWorkAdmission.handoff_attempt_id == child["attempt_id"]
            )
        )
        assert admission is not None
        claimed = work.claim(s, f.box, f.owner, admission.id)
        assert claimed is not None
    transport, calls = model_http(f, claimed)
    assert (
        product.dispatch_and_settle(f.engine, claimed, transport)[0] == "completed"
        and len(calls) == 2
    )
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        child = next(h for h in current["handoffs"] if h["id"] == revised["revision_handoff_id"])
        reply = s.get(WorkspaceReply, child["result_entry_id"])
        assert reply is not None
        accepted = reviews.review(
            s,
            f.box,
            f.owner,
            f.wid,
            child["id"],
            expected=current["revision"],
            key="calendar-revised-accepted",
            attempt_id=child["attempt_id"],
            result_entry_id=reply.entry_id,
            result_sha256=hashlib.sha256(reply.content.encode()).hexdigest(),
            decision="accepted",
        )
        assert accepted["workspace"]["note"]["latest"] == f.note_before
        sources = {e["id"]: e for e in accepted["workspace"]["entries"]}
        assert sources[f.selected["entry_id"]]["google_source_state"] == "current"
        assert sources[f.calendar_selected["entry_id"]]["calendar_source_state"] == "current"
        assert (
            "does not establish current availability"
            in sources[f.calendar_selected["entry_id"]]["content"]
        )
        assert "partial" in sources[f.calendar_selected["entry_id"]]["content"]


@pytest.mark.parametrize(
    "fault",
    ["disconnect", "reconnect", "grant_changed", "superseded", "unconfirmed_new_observation"],
)
def test_uncited_calendar_derived_feedback_and_revision_privacy_after_authority_loss(
    calendar_case, fault
):
    f = calendar_case
    command, handoff = finish_handoff(f, cited=False)
    with Session(f.engine) as s:
        saved = reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        review = next(h for h in saved["workspace"]["handoffs"] if h["id"] == handoff["id"])[
            "review"
        ]
        revisions.reserve(
            s,
            f.box,
            f.owner,
            f.wid,
            handoff["id"],
            expected=saved["workspace"]["revision"],
            key="calendar-uncited-revision",
            review_id=review["id"],
        )
    invalidate(f, fault)
    with Session(f.engine) as s:
        replay = reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        assert (
            replay["entry_revision"] == saved["entry_revision"]
            and replay["request_sha256"] == saved["request_sha256"]
        )
        assert (
            replay["feedback_withheld"] and replay["workspace"]["note"]["latest"] == f.note_before
        )
        assert (
            gmail.private_fact_paths(
                replay, ["calendar café", "Google calendar: Invented calendar"]
            )
            == []
        )
        source = next(
            e for e in replay["workspace"]["entries"] if e["id"] == f.calendar_selected["entry_id"]
        )
        assert (
            source["calendar_source_state"] == "unavailable"
            and source["content"] == ""
            and source["source_label"] == "Unavailable calendar source"
        )
        w = s.get(EncounterWorkspace, f.wid)
        assert calendar.historical_source(s, w, source["id"]).content.startswith(
            "Google calendar summary"
        )
        if fault in ("superseded", "unconfirmed_new_observation", "grant_changed"):
            email = next(
                e for e in replay["workspace"]["entries"] if e["id"] == f.selected["entry_id"]
            )
            assert email["google_source_state"] == "current" and email["content"] == f.port.text
        with pytest.raises(ws.WorkspaceError):
            revisions.reserve(
                s,
                f.box,
                f.owner,
                f.wid,
                handoff["id"],
                expected=replay["workspace"]["revision"],
                key="calendar-stale-revision",
                review_id=review["id"],
            )
        s.rollback()
        child = s.scalar(
            select(ModelWorkAdmission).where(
                ModelWorkAdmission.workspace_id == f.wid, ModelWorkAdmission.state == "reserved"
            )
        )
        assert child is not None and work.claim(s, f.box, f.owner, child.id) is None
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkspaceHandoffReview)
                .where(WorkspaceHandoffReview.workspace_id == f.wid)
            )
            == 1
        )


@pytest.mark.parametrize("fault", ["disconnect", "grant_changed", "unconfirmed_new_observation"])
def test_calendar_authority_loss_between_provider_rounds_prevents_tool_disclosure(
    calendar_case, fault
):
    f = calendar_case
    claimed = reserve(f, "calendar-midread-" + fault)
    transport, calls = model_http(f, claimed, change=lambda: invalidate(f, fault))
    state, result_id, _ = product.dispatch_and_settle(f.engine, claimed, transport)
    assert state == "failed" and result_id is None and len(calls) == 1


def test_calendar_derived_scribe_cannot_replace_independent_clinical_note(
    calendar_case, monkeypatch
):
    f = calendar_case
    monkeypatch.setattr(work, "_google_message_passages", lambda *args: ())
    claimed = reserve(f, "calendar-scribe-note-block", role="scribe")
    context = _context(claimed.envelope["context"])
    source = next(p for p in context.sources if p.entry_id == f.calendar_selected["entry_id"])

    def respond(request):
        return httpx.Response(
            200,
            json=product.response(
                {"answer": "Invented Scribe:\n" + source.content, "source_ids": [source.entry_id]}
            ),
        )

    state, result_id, _ = product.dispatch_and_settle(
        f.engine, claimed, httpx.MockTransport(respond)
    )
    assert state == "completed" and result_id
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        count = s.scalar(
            select(func.count())
            .select_from(WorkspaceNote)
            .where(WorkspaceNote.workspace_id == f.wid)
        )
        with pytest.raises(ws.WorkspaceError, match="google_calendar_note_import_unavailable"):
            notes.save(
                s,
                f.box,
                f.owner,
                f.wid,
                expected=current["revision"],
                key="never-import-calendar-note",
                base_note_id=f.note_before["id"],
                source_reply_id=result_id,
                content=source.content,
            )
        s.rollback()
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkspaceNote)
                .where(WorkspaceNote.workspace_id == f.wid)
            )
            == count
        )
        assert ws.read(s, f.box, f.owner, f.wid)["note"]["latest"] == f.note_before


def test_sql_calendar_model_current_guard_rejects_dispatch_after_new_observation(calendar_case):
    f = calendar_case
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        admission, _ = work.reserve_conversation(
            s,
            f.box,
            f.owner,
            f.wid,
            expected=current["revision"],
            team_revision=1,
            key="calendar-db-current-guard",
            role="chief",
            content="Prepare a private calendar summary draft.",
        )
    invalidate(f, "unconfirmed_new_observation")
    with Session(f.engine) as s:
        with pytest.raises(DBAPIError) as failure:
            s.execute(
                text(
                    "UPDATE model_work_admissions SET state='running',dispatch_id=gen_random_uuid(),started_at=clock_timestamp(),lease_ends_at=clock_timestamp()+interval '30 seconds' WHERE id=:id"
                ),
                {"id": admission},
            )
            s.commit()
        assert getattr(failure.value.orig, "sqlstate", None) == "23514"


def test_real_exclusive_event_end_masks_source_and_refuses_reserved_work(calendar_case):
    f = calendar_case
    f.calendar_port.short_seconds = 3
    f.calendar_selected = select_calendar(f, "short-event")
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        admission, _ = work.reserve_conversation(
            s,
            f.box,
            f.owner,
            f.wid,
            expected=current["revision"],
            team_revision=1,
            key="calendar-expiring-reservation",
            role="chief",
            content="Prepare a private draft from the reviewed calendar summary.",
        )
        # Await the real PostgreSQL authority clock, bounded to 3.2 seconds. No
        # provider call, time-travel fixture, or immutable custody rewrite.
        remaining = s.scalar(
            text(
                "SELECT greatest(0,extract(epoch FROM valid_until-clock_timestamp())) FROM google_calendar_source_reviews WHERE entry_id=:id"
            ),
            {"id": f.calendar_selected["entry_id"]},
        )
        assert remaining is not None and float(remaining) <= 3
        s.execute(text("SELECT pg_sleep(:seconds)"), {"seconds": float(remaining) + 0.05})
        assert (
            s.scalar(
                text("SELECT public.google_calendar_source_current(:id)"),
                {"id": f.calendar_selected["entry_id"]},
            )
            is False
        )
        projected = ws.read(s, f.box, f.owner, f.wid)
        source = next(e for e in projected["entries"] if e["id"] == f.calendar_selected["entry_id"])
        assert source["calendar_source_state"] == "unavailable" and source["content"] == ""
        assert source["source_label"] == "Unavailable calendar source"
        assert projected["note"]["latest"] == f.note_before
        email = next(e for e in projected["entries"] if e["id"] == f.selected["entry_id"])
        assert email["google_source_state"] == "current" and email["content"] == f.port.text
        assert work.claim(s, f.box, f.owner, admission) is None
        saved_admission = s.get(ModelWorkAdmission, admission)
        assert saved_admission is not None and saved_admission.reason == "source_changed"
    assert f.calendar_port.calls == ["primary_7day_summary", "primary_7day_summary"]


def test_expiry_at_completed_sql_flush_recovers_unknown_with_paid_usage_and_no_resend(
    calendar_case,
):
    f = calendar_case
    f.calendar_port.short_seconds = 3
    f.calendar_selected = select_calendar(f, "settle-race")
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        command = dict(
            expected=current["revision"],
            team_revision=1,
            key="calendar-final-flush-race",
            role="chief",
            content="Prepare a private draft from the reviewed calendar summary.",
        )
        admission, _ = work.reserve_conversation(s, f.box, f.owner, f.wid, **command)
        claimed = work.claim(s, f.box, f.owner, admission)
        assert claimed is not None
    transport, calls = model_http(f, claimed)
    result = work.dispatch_claim(
        claimed, session_factory=lambda: Session(f.engine), transport=transport
    )
    assert len(calls) == 2 and result.input_tokens is not None
    delayed = []

    def expire_before_completed_update(s, flush_context, instances):
        if not any(
            isinstance(row, ModelWorkAdmission) and row.id == admission and row.state == "completed"
            for row in s.dirty
        ):
            return
        assert not delayed
        remaining = s.scalar(
            text(
                "SELECT extract(epoch FROM valid_until-clock_timestamp()) FROM google_calendar_source_reviews WHERE entry_id=:id"
            ),
            {"id": f.calendar_selected["entry_id"]},
        )
        # Real source expiry occurs only after settle's last application check.
        # The existing immutable 90s model lease is recovered through its clock seam below.
        assert remaining is not None and 0 < float(remaining) <= 3
        s.execute(text("SELECT pg_sleep(:seconds)"), {"seconds": float(remaining) + 0.05})
        delayed.append(float(remaining))

    with Session(f.engine) as s:
        event.listen(s, "before_flush", expire_before_completed_update)
        try:
            with pytest.raises(DBAPIError) as failure:
                work.settle(s, claimed, result)
            assert getattr(failure.value.orig, "sqlstate", None) == "23514"
            assert getattr(getattr(failure.value.orig, "diag", None), "message_primary", None) == (
                "selected Google model source unavailable"
            )
        finally:
            event.remove(s, "before_flush", expire_before_completed_update)
            s.rollback()
        row = s.get(ModelWorkAdmission, admission)
        assert row is not None and row.state == "running" and row.result_entry_id is None
        assert s.get(WorkspaceReply, row.request_entry_id) is None
        assert (
            s.scalar(
                select(func.count())
                .select_from(ModelUsageObservation)
                .where(ModelUsageObservation.admission_id == admission)
            )
            == 0
        )
        lease_end = row.lease_ends_at
        assert lease_end is not None
        assert ws.read(s, f.box, f.owner, f.wid)["note"]["latest"] == f.note_before
    assert len(delayed) == 1

    # Reopen and reconcile the already captured result after the original lease.
    # This runs no provider/model I/O and never retries the refused publication.
    recovery_time = lease_end + timedelta(milliseconds=1)
    with Session(f.engine) as s:
        work.settle(s, claimed, result, clock=lambda: recovery_time)
    with Session(f.engine) as s:
        observed = work.resolve_conversation(
            s, f.box, f.owner, f.wid, clock=lambda: recovery_time, **command
        )
        assert observed["outcome"] == "unknown" and observed["saved_entry"] is None
        assert observed["admission"]["usage"] == "verified"
        assert (observed["admission"]["input_tokens"], observed["admission"]["output_tokens"]) == (
            result.input_tokens,
            result.output_tokens,
        )
        usage = list(
            s.scalars(
                select(ModelUsageObservation).where(ModelUsageObservation.admission_id == admission)
            )
        )
        assert {item.kind for item in usage} == {"terminal", "late_usage"}
        assert next(item for item in usage if item.kind == "terminal").usage == "unknown"
        assert next(item for item in usage if item.kind == "late_usage").usage == "verified"
        # Same-key reservation/settle/claim retries cannot admit or resend work.
        replay_id, replay = work.reserve_conversation(
            s, f.box, f.owner, f.wid, clock=lambda: recovery_time, **command
        )
        assert replay_id is None and replay is not None and replay["outcome"] == "unknown"
        assert replay["admission"]["id"] == admission
        work.settle(s, claimed, result, clock=lambda: recovery_time)
        assert work.claim(s, f.box, f.owner, admission, clock=lambda: recovery_time) is None
        assert (
            s.scalar(
                select(func.count())
                .select_from(ModelUsageObservation)
                .where(ModelUsageObservation.admission_id == admission)
            )
            == 2
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(ModelWorkAdmission)
                .where(ModelWorkAdmission.workspace_id == f.wid)
            )
            == 1
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkspaceReply)
                .where(WorkspaceReply.workspace_id == f.wid)
            )
            == 0
        )
        projected = ws.read(s, f.box, f.owner, f.wid)
        assert projected["note"]["latest"] == f.note_before
        assert (
            gmail.private_fact_paths(
                projected, ["calendar café", "Google calendar: Invented calendar"]
            )
            == []
        )
    assert len(calls) == 2 and f.calendar_port.calls == [
        "primary_7day_summary",
        "primary_7day_summary",
    ]
