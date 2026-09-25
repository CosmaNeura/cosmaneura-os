"""One-ever Stripe request creation and explicit payment status observations."""

import asyncio
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from cosmas_os.adapters.vendor_connectors.stripe import StripeConnector
from cosmas_os.adapters.vendor_connectors.transport import VendorRuntime, require_reference
from cosmas_os.api import finance_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import finance_work as work
from cosmas_os.application import vendor_work as common
from cosmas_os.application import workspace as ws
from cosmas_os.finance_models import (
    FinanceConnectionVersion,
    FinanceObservation,
    FinanceReadClaim,
    FinanceReceipt,
    FinanceReopenFact,
    FinanceSubmitClaim,
    FinanceWorkRevision,
)
from cosmas_os.models import EncounterWorkspace, Operation, Principal, Ticket
from cosmas_os.ports import vendor_connectors as private


@dataclass(frozen=True, repr=False)
class FinanceInvocation:
    mode: str
    operation_id: str
    claim_id: str
    token: str
    box_id: str
    owner_id: str
    workspace_id: str
    command: private.VendorCommand
    approval: private.ApprovalBinding | None
    reference: private.ProviderReference | None
    core_checked: object = None


def current(s, w, r, checked=None):
    proposal = schema.FinanceProposal.model_validate(r.public_proposal)
    work.source(s, w, proposal.source, checked)
    work.selected(s, w, proposal.connection, proposal.customer)


def historical_connection(s, w, r, command):
    c = s.scalar(
        select(FinanceConnectionVersion)
        .where(
            FinanceConnectionVersion.id == r.connection_version_id,
            FinanceConnectionVersion.box_id == w.box_id,
            FinanceConnectionVersion.owner_id == w.owner_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        c is None
        or c.revoked_at
        or not c.read_enabled
        or private.ConnectionSelection.model_validate(c.private_selection) != command.selection
        or c.private_sha256 != command.selection.commitment()
    ):
        work.error("finance_original_account_unavailable")
    return c


def claim_submit(
    s, box, actor, wid, tid, request, *, policy=work.DEFAULT_POLICY, core_checked=None
):
    w = work.owner(s, box, actor, wid, writing=True)
    old, digest = work.receipt(s, w, actor, "submit", request)
    if old:
        if old.ticket_id != tid:
            work.error("finance_idempotency_conflict")
        work.final_authority(s)
        return work.response(s, old), None
    if not policy.enabled or not policy.io_enabled:
        work.error("finance_feature_disabled", 403)
    r = s.get(FinanceWorkRevision, request.revision_id)
    if r is None or (r.workspace_id, r.owner_id, r.ticket_id) != (wid, actor, tid):
        work.error("finance_work_unavailable", 404)
    current(s, w, r, core_checked)
    t, r, command = work.bound(s, w, tid)
    work.check_bound(t, r, request)
    if t.state != "approved":
        work.error("finance_revision_changed")
    op = s.scalar(
        select(Operation).where(Operation.id == r.intended_operation_id).with_for_update()
    )
    if op is None or op.attempt_count != 0 or s.get(FinanceSubmitClaim, op.id):
        work.error("finance_submit_already_claimed")
    approved = s.scalar(
        select(FinanceReceipt).where(
            FinanceReceipt.action_revision_id == r.action_revision_id,
            FinanceReceipt.command_kind == "decide",
            FinanceReceipt.actor_id == actor,
            FinanceReceipt.public_request["choice"].as_string() == "approve",
        )
    )
    now = common._clock(s)
    if approved is None or now >= command.expires_at:
        work.error("finance_approval_expired")
    approval = private.ApprovalBinding(
        operation_id=command.operation_id,
        revision_id=command.revision_id,
        action=command.intent.kind,
        approved_payload_sha256=command.commitment(),
        selection_sha256=command.selection.commitment(),
        expires_at=command.expires_at,
    )
    t.version += 1
    op.status, op.attempt_count, op.started_at = "running", 1, now
    saved = work.record(s, w, actor, "submit", request, digest, t, r, "submit_claimed")
    token = str(uuid4())
    s.add(
        FinanceSubmitClaim(
            operation_id=op.id,
            ticket_id=tid,
            action_revision_id=r.action_revision_id,
            box_id=box,
            owner_id=actor,
            workspace_id=wid,
            actor_id=actor,
            command_receipt_id=saved.id,
            approval_receipt_id=approved.id,
            command_sha256=command.commitment(),
            claim_token=token,
            admitted_at=now,
            deadline=now + timedelta(seconds=45),
        )
    )
    s.commit()
    return work.response(s, saved), FinanceInvocation(
        "submit", op.id, op.id, token, box, actor, wid, command, approval, None, core_checked
    )


def reference(s, r, command):
    row = s.scalar(
        select(FinanceObservation)
        .where(
            FinanceObservation.operation_id == r.intended_operation_id,
            FinanceObservation.kind == "creation",
            FinanceObservation.private_reference.is_not(None),
        )
        .order_by(FinanceObservation.sequence.desc())
        .limit(1)
    )
    if row is None:
        work.error("finance_reference_unavailable")
    try:
        return require_reference(
            command,
            private.ProviderReference.model_validate(row.private_reference),
            "payment_intent",
        )
    except private.VendorError:
        work.error("finance_reference_unavailable")


def claim_read(s, box, actor, wid, tid, request, *, policy=work.DEFAULT_POLICY):
    w = work.owner(s, box, actor, wid, writing=True)
    old, digest = work.receipt(s, w, actor, "reconcile", request)
    if old:
        if old.ticket_id != tid:
            work.error("finance_idempotency_conflict")
        work.final_authority(s)
        return work.response(s, old), None
    if not policy.io_enabled:
        work.error("finance_feature_disabled", 403)
    t, r, command = work.bound(s, w, tid)
    work.check_bound(t, r, request)
    historical_connection(s, w, r, command)
    ref = reference(s, r, command)
    now = common._clock(s)
    if s.scalar(
        select(FinanceReadClaim.id).where(
            FinanceReadClaim.operation_id == r.intended_operation_id,
            FinanceReadClaim.completed_at.is_(None),
            FinanceReadClaim.deadline > now,
        )
    ):
        work.error("finance_read_in_progress")
    if (
        s.scalar(
            select(func.count())
            .select_from(FinanceReadClaim)
            .where(FinanceReadClaim.operation_id == r.intended_operation_id)
        )
        >= 100
    ):
        work.error("finance_history_limit")
    t.version += 1
    saved = work.record(s, w, actor, "reconcile", request, digest, t, r, "read_claimed")
    cid, token = str(uuid4()), str(uuid4())
    s.add(
        FinanceReadClaim(
            id=cid,
            operation_id=r.intended_operation_id,
            ticket_id=tid,
            action_revision_id=r.action_revision_id,
            box_id=box,
            owner_id=actor,
            workspace_id=wid,
            actor_id=actor,
            command_receipt_id=saved.id,
            claim_token=token,
            admitted_at=now,
            deadline=now + timedelta(seconds=45),
            private_reference=ref.model_dump(mode="json"),
        )
    )
    s.commit()
    return work.response(s, saved), FinanceInvocation(
        "reconcile", r.intended_operation_id, cid, token, box, actor, wid, command, None, ref
    )


def internal(s, invocation):
    s.scalar(select(Principal).where(Principal.id == invocation.owner_id).with_for_update())
    w = s.scalar(
        select(EncounterWorkspace)
        .where(EncounterWorkspace.id == invocation.workspace_id)
        .with_for_update()
    )
    r = s.get(FinanceWorkRevision, str(invocation.command.revision_id))
    if (
        r is None
        or w is None
        or (r.workspace_id, r.owner_id, r.intended_operation_id)
        != (w.id, invocation.owner_id, invocation.operation_id)
    ):
        work.error("finance_unavailable", 503)
    t = s.scalar(
        select(Ticket)
        .where(Ticket.id == r.ticket_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    op = s.scalar(
        select(Operation)
        .where(Operation.id == invocation.operation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    model = FinanceSubmitClaim if invocation.mode == "submit" else FinanceReadClaim
    key = FinanceSubmitClaim.operation_id if invocation.mode == "submit" else FinanceReadClaim.id
    claim = s.scalar(
        select(model)
        .where(key == invocation.claim_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        t is None
        or op is None
        or claim is None
        or claim.claim_token != invocation.token
        or private.VendorCommand.model_validate(r.private_command) != invocation.command
    ):
        work.error("finance_unavailable", 503)
    return w, t, r, op, claim


def append_observation(s, invocation, r, kind, values, *, ref=None):
    h = work.head(s, r)
    now, oid = common._clock(s), str(uuid4())
    value = {
        "id": oid,
        "sequence": h["sequence"] + 1,
        "operation_id": invocation.operation_id,
        "kind": kind,
        "recorded_at": public.timestamp(now),
        **values,
    }
    sha = public.public_digest("cosmas-finance-public-observation.v1", value)
    next_head = public.public_digest(
        "cosmas-finance-observation-head.v1",
        {
            "operation_id": invocation.operation_id,
            "sequence": h["sequence"] + 1,
            "previous_sha256": h["sha256"],
            "observation_sha256": sha,
        },
    )
    row = FinanceObservation(
        id=oid,
        operation_id=invocation.operation_id,
        action_revision_id=r.action_revision_id,
        ticket_id=r.ticket_id,
        box_id=r.box_id,
        owner_id=r.owner_id,
        workspace_id=r.workspace_id,
        sequence=h["sequence"] + 1,
        kind=kind,
        submit_claim_id=invocation.operation_id if invocation.mode == "submit" else None,
        read_claim_id=invocation.claim_id if invocation.mode != "submit" else None,
        private_reference=ref.model_dump(mode="json") if ref else None,
        public_observation={**value, "sha256": sha},
        public_sha256=sha,
        head_sha256=next_head,
        recorded_at=now,
    )
    s.add(row)
    s.flush()
    return row


def mark_invocation(s, invocation):
    _, t, r, _, claim = internal(s, invocation)
    if invocation.mode != "submit" or claim.completed_at or claim.dispatch != "not_started":
        work.error("finance_submit_already_claimed")
    now = common._clock(s)
    if now >= claim.deadline:
        return False
    claim.dispatch, claim.invocation_started_at = "invocation_started", now
    append_observation(s, invocation, r, "dispatch", {"dispatch": "invocation_started"})
    t.version += 1
    s.commit()
    return True


def settle(s, invocation, *, observation=None, failure=None):
    w, t, r, op, claim = internal(s, invocation)
    if claim.completed_at:
        return
    now, before = common._clock(s), work.summary(s, t, r)
    if invocation.mode == "submit":
        if isinstance(observation, private.SubmissionObservation):
            observed = private.SubmissionObservation.model_validate(
                observation.model_dump(mode="python")
            )
            if (
                observed.vendor,
                str(observed.connection_id),
                str(observed.operation_id),
                observed.request_sha256,
            ) != (
                "stripe",
                str(invocation.command.selection.connection_id),
                invocation.operation_id,
                invocation.command.commitment(),
            ):
                work.error("finance_unavailable", 503)
            if observed.reference:
                require_reference(invocation.command, observed.reference, "payment_intent")
            row = append_observation(
                s,
                invocation,
                r,
                "creation",
                {
                    "acceptance": observed.state,
                    **({"safe_error": observed.safe_error} if observed.safe_error else {}),
                },
                ref=observed.reference,
            )
            claim.dispatch = (
                "unconfirmed" if observed.state == "unconfirmed" else "response_observed"
            )
            op.status = {"accepted": "succeeded", "rejected": "failed", "unconfirmed": "unknown"}[
                observed.state
            ]
        else:
            failure = (
                failure
                if isinstance(failure, private.VendorError)
                else private.VendorError("transport_unconfirmed", attempted=True)
            )
            claim.dispatch = "unconfirmed" if failure.attempted else "proved_not_dispatched"
            claim.safe_error = failure.code
            row = append_observation(
                s,
                invocation,
                r,
                "dispatch",
                {"dispatch": claim.dispatch, "safe_error": failure.code},
            )
            op.status = "unknown" if failure.attempted else "failed"
        op.completed_at, op.result_receipt_hash = now, row.public_sha256
    else:
        if isinstance(observation, private.PaymentObservation):
            observed = private.PaymentObservation.model_validate(
                observation.model_dump(mode="python")
            )
            if (
                observed.reference != invocation.reference
                or (observed.amount, observed.currency, observed.livemode)
                != (r.amount, r.currency, invocation.command.selection.environment == "production")
                or observed.amount_received > r.amount
                or observed.state == "succeeded"
                and observed.amount_received != r.amount
            ):
                work.error("finance_unavailable", 503)
            row = append_observation(
                s,
                invocation,
                r,
                "payment",
                {
                    "payment_state": observed.state,
                    "amount_received": observed.amount_received,
                    "amount": observed.amount,
                    "currency": observed.currency,
                    "livemode": observed.livemode,
                },
                ref=observed.reference,
            )
            claim.state = "settled"
        else:
            failure = (
                failure
                if isinstance(failure, private.VendorError)
                else private.VendorError("transport_unconfirmed", attempted=True)
            )
            row = append_observation(
                s,
                invocation,
                r,
                "payment",
                {
                    "payment_state": "unknown",
                    "amount_received": 0,
                    "amount": r.amount,
                    "currency": r.currency,
                    "safe_error": failure.code,
                },
            )
            claim.state = "unknown"
    claim.completed_at = now
    t.version += 1
    after = work.summary(s, t, r)
    new_contradiction = (
        after["conflicting_evidence"]
        and not before["conflicting_evidence"]
        or after["payment_state"] == "canceled"
        and before["payment_state"] != "canceled"
        or after["creation"] == "rejected"
        and before["creation"] != "rejected"
    )
    if t.state == "closed" and new_contradiction:
        t.state, t.closed_at, t.version = "approved", None, t.version + 1
        s.add(
            FinanceReopenFact(
                box_id=w.box_id,
                owner_id=w.owner_id,
                workspace_id=w.id,
                ticket_id=t.id,
                action_revision_id=r.action_revision_id,
                operation_id=r.intended_operation_id,
                observation_id=row.id,
                observation_sha256=row.public_sha256,
                effect_version=t.version,
                recorded_at=now,
            )
        )
    s.commit()


class FinanceExecution:
    def __init__(
        self,
        sessions,
        credentials,
        *,
        policy=work.DEFAULT_POLICY,
        transport=None,
        identity_current=None,
    ):
        self.sessions, self.credentials, self.policy = sessions, credentials, policy
        self.transport, self.identity_current = transport, identity_current
        self.pending = set()

    async def authorize(self, invocation, selection, command, approval, mutating):
        if (
            not self.policy.io_enabled
            or self.identity_current is None
            or await self.identity_current() is not True
        ):
            return False
        if (
            command != invocation.command
            or selection != command.selection
            or mutating != (invocation.mode == "submit")
        ):
            return False
        return await asyncio.to_thread(
            self.current_authority, invocation, command, approval, mutating
        )

    def current_authority(self, invocation, command, approval, mutating):
        try:
            with self.sessions() as s:
                w = work.owner(
                    s, invocation.box_id, invocation.owner_id, invocation.workspace_id, writing=True
                )
                r = s.get(FinanceWorkRevision, str(command.revision_id))
                if r is None:
                    return False
                if mutating:
                    current(s, w, r, invocation.core_checked)
                else:
                    historical_connection(s, w, r, command)
                t, _, _ = work.bound(s, w, r.ticket_id)
                claim = (
                    s.get(FinanceSubmitClaim, invocation.operation_id)
                    if mutating
                    else s.get(FinanceReadClaim, invocation.claim_id)
                )
                return bool(
                    claim
                    and claim.claim_token == invocation.token
                    and claim.completed_at is None
                    and common._clock(s) < claim.deadline
                    and (not mutating or t.state == "approved" and approval == invocation.approval)
                )
        except (ws.WorkspaceError, ValueError):
            return False

    def mark(self, invocation):
        with self.sessions() as s:
            return mark_invocation(s, invocation)

    def retain(self, invocation, observation, failure):
        with self.sessions() as s:
            settle(s, invocation, observation=observation, failure=failure)

    async def execute(self, invocation, deadline):
        observation, failure = None, None
        try:
            if time.monotonic() >= deadline:
                raise private.VendorError("authority_required")
            if invocation.mode == "submit" and not await asyncio.to_thread(self.mark, invocation):
                raise private.VendorError("authority_required")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise private.VendorError("authority_required")
            runtime = VendorRuntime(
                invocation.command.selection,
                self.credentials,
                enabled=self.policy.io_enabled,
                transport=self.transport,
                authorize=lambda *args: self.authorize(invocation, *args),
                timeout_seconds=min(remaining, 30),
            )
            connector = StripeConnector(runtime)
            observation = (
                await connector.submit(invocation.command, invocation.approval)
                if invocation.mode == "submit"
                else await connector.observe(invocation.command, invocation.reference)
            )
        except private.VendorError as error:
            failure = error
        except asyncio.CancelledError:
            raise
        except Exception:
            failure = private.VendorError("transport_unconfirmed", attempted=True)
        finally:
            if observation is not None or failure is not None:
                await asyncio.to_thread(self.retain, invocation, observation, failure)

    async def invoke(self, invocation, *, deadline=None):
        limit = (
            min(deadline, time.monotonic() + 45) if deadline is not None else time.monotonic() + 45
        )
        task = asyncio.create_task(self.execute(invocation, limit))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)
        return await asyncio.shield(task)
