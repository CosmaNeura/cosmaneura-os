"""Real operational services, synthetic actors/providers, and exact next-step evidence."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.api import finance_work_schemas as fp
from cosmas_os.api import membership_work_schemas as mp
from cosmas_os.api import vendor_work_schemas as vp
from cosmas_os.application import (
    appointment_execution,
    appointment_work,
    finance_execution,
    finance_setup,
    finance_work,
    follow_up,
    membership_work,
    note_review,
    operations_status,
    workspace,
)
from cosmas_os.models import (
    EncounterWorkspace,
    ExternalIdentity,
    Operation,
    SchedulingAccount,
    SchedulingPatientAccount,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import AvailabilitySlot, GoogleCalendarCoverage
from cosmas_os.ports.scheduling_actions import (
    AppointmentIntent,
    AppointmentResult,
    AppointmentSelection,
    AppointmentSnapshot,
)
from cosmas_os.ports.vendor_connectors import ConnectionSelection
from lab.application import Approval, Proposal
from lab.fax_sandbox import vendor_gates
from lab.inbox_sandbox import exercise_inbox
from lab.store import LabError

SCENARIOS = ("follow_up_review", "follow_up_source_change", "inbox_review", "scheduling_recovery",
             "scheduling_expired", "membership_review", "membership_source_change", "payment_lost_reply")
scenarios = SCENARIOS
MEMBERSHIP = membership_work.MembershipPolicy(True, True)
FINANCE = finance_work.FinancePolicy(True, True, False)


def note(s, app):
    scope = app.box, app.owner, app.workspace
    w = workspace.read(s, *scope)
    w = note_review.save(s, *scope, expected=w["revision"], key="ops-note", base_note_id=None,
        source_reply_id=None, content="SYNTHETIC administrative plan: review scheduling, follow-up and membership questions.")["workspace"]
    n = w["note"]["latest"]
    return note_review.review(s, *scope, n["id"], expected=w["revision"], key="ops-note-review",
        content_hash=n["content_hash"], source_hash=n["source_fingerprint"])["workspace"]


def change_note(s, app):
    w = workspace.read(s, app.box, app.owner, app.workspace)
    return note_review.save(s, app.box, app.owner, app.workspace, expected=w["revision"], key="ops-revise-note",
        base_note_id=w["note"]["latest"]["id"], source_reply_id=None,
        content="SYNTHETIC revised plan: clinician must review the changed request.")


def status(s, app, kind, record_id, **kwargs):
    return operations_status.read(s, app.box, app.owner, app.workspace, kind=kind, record_id=record_id,
                                  membership_policy=MEMBERSHIP, **kwargs)


def source(w):
    n = w["note"]["latest"]
    return vp.ReviewedSource.model_validate({"kind": "reviewed_note", "note_id": n["id"], "content_sha256": n["content_hash"],
            "source_fingerprint": n["source_fingerprint"]})


def bound(d, key, **values):
    x = d["summary"]
    return {"ticket_id": x["ticket_id"], "expected_version": x["version"], "revision_id": x["revision_id"],
            "payload_hash": x["payload_hash"], "idempotency_key": key, **values}


def followup_case(app, changed):
    checks, stages = {}, []
    with Session(app.engine) as s:
        scope = app.box, app.owner, app.workspace
        w = note(s, app)
        request = Proposal(expected=w["revision"], key="ops-follow-propose", note_id=w["note"]["latest"]["id"],
            body="SYNTHETIC ask the patient to confirm the next visit.", due_date=datetime.now(UTC).date(),
            expected_outcome="Synthetic provider records the reviewed outcome.", share=True)
        saved = follow_up.propose(s, *scope, **request)
        item = saved["workspace"]["follow_ups"][0]
        tid = item["ticket_id"]
        stages.append(status(s, app, "follow_up", tid))
        replay = follow_up.propose(s, *scope, **request)
        checks["same_proposal_reuses_ticket"] = replay["workspace"]["follow_ups"][0]["ticket_id"] == tid
        command = Approval(revision_id=item["revision_id"], digest=item["payload_hash"], choice="approve")
        try:
            follow_up.decide(s, app.box, app.agent_id("follow_up"), app.workspace, tid, **command)
        except workspace.WorkspaceError:
            s.rollback()
            checks["bot_cannot_approve"] = True
        else:
            checks["bot_cannot_approve"] = False
        if changed:
            change_note(s, app)
            stages.append(status(s, app, "follow_up", tid))
            checks["changed_source_requires_review"] = stages[-1]["next_step"]["code"] == "review_updated_source"
        else:
            follow_up.decide(s, *scope, tid, **command, defer_delivery=True)
            stages.append(status(s, app, "follow_up", tid))
            for _ in range(2):
                follow_up.decide(s, *scope, tid, **command)
            stages.append(status(s, app, "follow_up", tid))
            for _ in range(2):
                follow_up.complete(s, *scope, tid, revision_id=item["revision_id"], digest=item["payload_hash"],
                    key="ops-follow-complete", evidence="SYNTHETIC human reviewed the local outcome.")
            stages.append(status(s, app, "follow_up", tid))
            checks["stages_preserve_review_delivery_and_outcome"] = [v["next_step"]["code"] for v in stages] == [
                "review_and_approve", "review_delivery_action", "record_human_outcome", "review_complete"]
            checks["one_operation_after_repeated_actions"] = s.scalar(select(func.count()).select_from(Operation)
                .where(Operation.box_id == app.box)) == 1
            checks["closed_work_never_claims_external_delivery"] = stages[-1]["evidence"]["external_outcome"] == "synthetic_only"
    return "follow_up", tid, checks, stages


def membership_case(app, changed):
    checks, stages = {}, []
    with Session(app.engine) as s:
        scope = app.box, app.owner, app.workspace
        w = note(s, app)
        current_workspace = s.get(EncounterWorkspace, app.workspace)
        assert current_workspace is not None
        proposal = mp.Proposal(expected_workspace_revision=w["revision"], idempotency_key="ops-membership-propose",
            source=source(w), patient_link_id=current_workspace.patient_link_id,
            purpose="failed_payment_follow_up", due_date=datetime.now(UTC).date().isoformat(),
            expected_outcome="Review the synthetic billing question.", instructions="Prepare local review; do not enroll or charge.")
        created = membership_work.propose(s, *scope, proposal, policy=MEMBERSHIP)
        tid = created["effect"]["ticket_id"]
        checks["same_membership_proposal_reuses_ticket"] = membership_work.propose(s, *scope, proposal,
            policy=MEMBERSHIP)["effect"]["ticket_id"] == tid
        stages.append(status(s, app, "membership", tid))
        d = membership_work.detail(s, *scope, tid, policy=MEMBERSHIP)
        decision = mp.Decision(**bound(d, "ops-membership-approve"), review_sha256=d["review_sha256"],
                              choice="approve", reviewed_patient=True, reviewed_local_only_authority=True)
        membership_work.command(s, *scope, tid, "decide", decision, policy=MEMBERSHIP)
        stages.append(status(s, app, "membership", tid))
        if changed:
            change_note(s, app)
            stages.append(status(s, app, "membership", tid))
            checks["changed_source_requires_review"] = stages[-1]["next_step"]["code"] == "review_updated_source"
        else:
            d = membership_work.detail(s, *scope, tid, policy=MEMBERSHIP)
            request = mp.Result(**bound(d, "ops-membership-result"), disposition="local_preparation_ready",
                evidence="SYNTHETIC account information prepared; membership status remains unconfirmed.")
            for _ in range(2):
                membership_work.command(s, *scope, tid, "result", request, policy=MEMBERSHIP)
            stages.append(status(s, app, "membership", tid))
            d = membership_work.detail(s, *scope, tid, policy=MEMBERSHIP)
            request = mp.Verify(**bound(d, "ops-membership-verify"),
                result_receipt_id=d["latest_result"]["receipt_id"], result_receipt_sha256=d["latest_result"]["receipt_sha256"],
                evidence_classification=d["summary"]["evidence_classification"], reviewed_patient=True,
                reviewed_result=True, reviewed_evidence_limits=True, confirm_review_completion=True)
            for _ in range(2):
                membership_work.command(s, *scope, tid, "verify", request, policy=MEMBERSHIP)
            stages.append(status(s, app, "membership", tid))
            checks["membership_review_has_actionable_stages"] = [v["next_step"]["code"] for v in stages] == [
                "review_and_approve", "prepare_review_result", "verify_local_review", "review_complete"]
            checks["closed_review_does_not_establish_membership"] = stages[-1]["evidence"]["external_outcome"] == "membership_not_established"
        checks["no_charge_or_membership_operation_created"] = s.scalar(select(func.count()).select_from(Operation)
            .where(Operation.box_id == app.box)) == 0
    return "membership", tid, checks, stages


class SchedulingTwin:
    """One invented receiver journal, with lost acceptance and separate calendar sync."""
    def __init__(self, now):
        self.now, self.calls, self.saved = now, [], None

    def result(self, operation):
        intent = operation.intent
        if self.saved is None:
            self.saved = AppointmentSnapshot(id=uuid4(), version=1, status="booked", starts_at=intent.slot.starts_at,
                ends_at=intent.slot.ends_at, **{key: getattr(intent.selection, key)
                for key in ("practitioner_id", "location_id", "appointment_type_id", "patient_id")})
        return AppointmentResult(operation_id=operation.operation_id, request_hash=operation.request_hash(),
            appointment=self.saved, observed_at=self.now, calendar_state="pending")

    def submit(self, operation):
        self.calls.append("submit")
        self.result(operation)
        raise ConnectorUnavailable("synthetic_reply_lost")

    def reconcile(self, operation):
        self.calls.append("reconcile")
        return self.result(operation)


def scheduling_case(app, expired):
    checks, stages, now = {}, [], datetime.now(UTC)
    with Session(app.engine) as s:
        scope = app.box, app.owner, app.workspace
        w = s.get(EncounterWorkspace, app.workspace)
        assert w is not None
        identity = ExternalIdentity(box_id=app.box, principal_id=app.owner, provider="clerk",
            issuer="https://clerk.example.invalid", subject="synthetic_" + str(uuid4()), organization_id="synthetic_practice",
            reviewed_by="Synthetic owner", evidence_ref="synthetic:operations-lab")
        s.add(identity)
        s.flush()
        account = SchedulingAccount(external_identity_id=identity.id, **{key: str(uuid4()) for key in
            ("practice_id", "actor_id", "practitioner_id", "location_id", "appointment_type_id")},
            label="Synthetic scheduling", reviewed_by="Synthetic owner", evidence_ref="synthetic:operations-lab", reviewed_at=now)
        s.add(account)
        s.flush()
        patient = SchedulingPatientAccount(box_id=app.box, patient_link_id=w.patient_link_id,
            practice_id=account.practice_id, patient_id=str(uuid4()), reviewed_by="Synthetic owner",
            evidence_ref="synthetic:operations-lab", reviewed_at=now)
        s.add(patient)
        s.commit()
        chosen = AppointmentSelection.model_validate(dict(box_id=app.box, owner_id=app.owner, patient_link_id=w.patient_link_id,
            practice_id=account.practice_id, expected_actor_id=account.actor_id, practitioner_id=account.practitioner_id,
            location_id=account.location_id, appointment_type_id=account.appointment_type_id, patient_id=patient.patient_id))
        intent = AppointmentIntent(action="book", selection=chosen, expires_at=now + timedelta(minutes=2),
            slot=AvailabilitySlot(starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, minutes=30)),
            google=GoogleCalendarCoverage(provider="google", calendar_id="primary", connection_id=uuid4(),
                connected_at=now - timedelta(days=1), checked_at=now))
        item = appointment_work.propose(s, *scope, external_identity_id=identity.id, intent=intent, key="ops-book", share=True, now=now)
        tid = item["ticket_id"]
        stages.append(status(s, app, "scheduling", tid, now=now))
        if expired:
            stages.append(status(s, app, "scheduling", tid, now=now + timedelta(minutes=3)))
            checks["expired_proposal_requires_fresh_review"] = stages[-1]["next_step"]["code"] == "review_updated_source"
            checks["expired_proposal_has_no_saved_booking"] = stages[-1]["evidence"]["external_outcome"] == "unconfirmed"
            # Reopen uses the same explicit observation instant below.
        else:
            approved = appointment_work.decide(s, *scope, tid, external_identity_id=identity.id,
                revision_id=item["revision_id"], digest=item["payload_hash"], choice="approve", now=now)
            stages.append(status(s, app, "scheduling", tid, now=now))
            twin = SchedulingTwin(now)
            request = dict(external_identity_id=identity.id, reauthenticate=lambda: None, port=twin,
                operation_id=approved["operation_id"], revision_id=item["revision_id"], digest=item["payload_hash"], clock=lambda: now)
            appointment_execution.run(s, *scope, tid, mode="submit", **request)
            stages.append(status(s, app, "scheduling", tid, now=now))
            appointment_execution.run(s, *scope, tid, mode="reconcile", **request)
            stages.append(status(s, app, "scheduling", tid, now=now))
            checks["lost_reply_reconciles_without_second_booking"] = twin.calls == ["submit", "reconcile"]
            checks["booking_and_calendar_sync_stay_separate"] = [v["next_step"]["code"] for v in stages] == [
                "review_and_approve", "review_booking_action", "check_existing_operation", "check_calendar_sync"]
            checks["pending_calendar_never_claimed_synced"] = stages[-1]["evidence"]["external_outcome"] == "appointment_saved_calendar_unconfirmed"
    return "scheduling", tid, checks, stages


def payment_case(app):
    checks, stages, calls = {}, [], []
    factory = sessionmaker(app.engine, expire_on_commit=False)
    with factory() as s:
        scope = app.box, app.owner, app.workspace
        w = note(s, app)
        current_workspace = s.get(EncounterWorkspace, app.workspace)
        assert current_workspace is not None
        selected = ConnectionSelection(vendor="stripe", connection_id=uuid4(), box_id=app.box, owner_id=app.owner,
            environment="sandbox", remote_account_id="acct_Synthetic", credential_ref=uuid4(), configuration_sha256="a" * 64)
        connection = finance_setup.review_connection(s, app.box, app.owner, selected,
            label="Synthetic Stripe", write_enabled=True, read_enabled=True)
        customer = finance_setup.review_customer(s, app.box, app.owner, connection["id"],
            current_workspace.patient_link_id, "cus_Synthetic", label="Synthetic billing account")
        request = fp.FinanceProposal.model_validate(dict(expected_workspace_revision=w["revision"], idempotency_key="ops-payment-propose",
            proposed_operation_id=str(uuid4()), source=source(w),
            connection={k: connection[k] for k in ("id", "revision", "public_sha256")},
            customer={k: customer[k] for k in ("id", "revision", "public_sha256")}, amount=2500, currency="usd",
            due_date=datetime.now(UTC).date().isoformat(), expected_outcome="Synthetic payment-request preparation only."))
        tid = finance_work.propose(s, *scope, request, policy=FINANCE)["effect"]["ticket_id"]
        stages.append(status(s, app, "payment", tid))
        d = finance_work.detail(s, *scope, tid)
        def payment_bound(detail, key):
            values = bound(detail, key)
            values.pop("ticket_id")
            return {**values, "operation_id": detail["summary"]["operation_id"]}
        finance_work.decide(s, *scope, tid, fp.FinanceDecision(**payment_bound(d, "ops-payment-approve"),
            review_sha256=d["review_sha256"], choice="approve"), policy=FINANCE)
        d = finance_work.detail(s, *scope, tid)
        request = vp.BoundCommand(**payment_bound(d, "ops-payment-submit"))
        _, invocation = finance_execution.claim_submit(s, *scope, tid, request, policy=FINANCE)
        if invocation is None:
            raise LabError("payment_not_admitted")
    async def credentials(selection):
        if selection != selected:
            raise LabError("foreign_payment_credential")
        return Credential(selection_sha256=selection.commitment(), credential_ref=str(selection.credential_ref),
                          secret=SecretStr("sk_test_synthetic_only"))
    async def current():
        app.check_agent("follow_up")
        return True
    def lost(request):
        if str(request.url) != "https://api.stripe.com/v1/payment_intents" or request.method != "POST":
            raise LabError("unexpected_payment_route")
        calls.append("create_unconfirmed")
        raise httpx.ReadTimeout("synthetic response lost")
    executor = finance_execution.FinanceExecution(factory, credentials, policy=FINANCE,
        transport=httpx.MockTransport(lost), identity_current=current)
    asyncio.run(executor.invoke(invocation))
    with factory() as s:
        _, duplicate = finance_execution.claim_submit(s, *scope, tid, request, policy=FINANCE)
        checks["duplicate_request_never_creates_second_payment"] = duplicate is None and calls == ["create_unconfirmed"]
        stages.append(status(s, app, "payment", tid))
        checks["lost_payment_reply_has_recovery_step_not_done"] = stages[-1]["next_step"]["code"] == "check_existing_payment"
        checks["payment_and_membership_remain_unconfirmed"] = stages[-1]["evidence"]["external_outcome"] == "unconfirmed"
    return "payment", tid, checks, stages


def exercise(app, store, episode, scenario):
    if scenario not in SCENARIOS:
        raise LabError("unknown_operations_scenario")
    with vendor_gates():
        if scenario == "inbox_review":
            stages = []
            def observed(s, iid, registry, policy, stage):
                value = status(s, app, "inbox", iid, inbox_registry=registry, inbox_policy=policy)
                stages.append({"stage": stage, **value})
            result = exercise_inbox(app, observe=observed)
            checks = {**result["checks"], "inbox_steps_follow_current_source": [v["next_step"]["code"] for v in stages] == [
                "review_incoming_source", "provider_review", "review_complete", "review_complete"],
                "local_inbox_review_never_claims_external_action": all(v["evidence"]["external_outcome"] == "no_external_action" for v in stages)}
            kind, tid = "inbox", stages[-1]["record_id"]
        else:
            if scenario.startswith("follow_up"):
                kind, tid, checks, stages = followup_case(app, scenario.endswith("source_change"))
            elif scenario.startswith("membership"):
                kind, tid, checks, stages = membership_case(app, scenario.endswith("source_change"))
            elif scenario.startswith("scheduling"):
                kind, tid, checks, stages = scheduling_case(app, scenario.endswith("expired"))
            else:
                kind, tid, checks, stages = payment_case(app)
            app.engine.dispose()
            with Session(app.engine) as s:
                reopened = status(s, app, kind, tid, now=datetime.fromisoformat(stages[-1]["observed_at"]))
                checks["same_evidence_and_next_step_survive_reopen"] = reopened == stages[-1]
                try:
                    operations_status.read(s, app.box, str(uuid4()), app.workspace, kind=kind, record_id=tid,
                                           membership_policy=MEMBERSHIP)
                except workspace.WorkspaceError:
                    s.rollback()
                    checks["foreign_owner_cannot_read_private_status"] = True
                else:
                    checks["foreign_owner_cannot_read_private_status"] = False
        store.event(episode, "operations", "current_next_step_verified", scenario=scenario,
                    record_id=tid, evidence_commitment=stages[-1]["evidence"]["commitment"], passed=all(checks.values()))
    return {"scenario": scenario, "role": "inbox" if kind == "inbox" else "scheduling" if kind == "scheduling" else
            "membership_billing" if kind in {"membership", "payment"} else "follow_up",
            "passed": all(checks.values()), "checks": checks, "stages": stages,
            "evidence_level": "Real saved application transitions and status reads; scripted humans, offline provider twins; no model inference or live actions."}
