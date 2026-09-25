"""Once-ever portal invocation claims and explicit status reads. No automatic retries."""

import asyncio
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from cosmas_os.adapters.vendor_connectors.transport import require_reference
from cosmas_os.api import portal_work_schemas as schema
from cosmas_os.api.vendor_work_schemas import public_digest, timestamp
from cosmas_os.application import portal_setup as setup
from cosmas_os.application import portal_work as work
from cosmas_os.application.capture_deadline import CaptureBudget, capture_budget
from cosmas_os.models import EncounterWorkspace, Operation, Principal
from cosmas_os.portal_work_models import (
    PortalWorkClaim,
    PortalWorkObservation,
    PortalWorkReceipt,
    PortalWorkReopen,
)
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.ports.vendor_artifacts import VendorArtifactScope


@dataclass(frozen=True, repr=False)
class Invocation:
    box_id: str
    owner_id: str
    workspace_id: str
    ticket_id: str
    claim_id: str
    mode: str
    command: private.VendorCommand
    approval: private.ApprovalBinding | None
    reference: private.ProviderReference | None
    core_checked: object = None


def reference(s, r, command):
    row = s.scalar(
        select(PortalWorkObservation)
        .where(
            PortalWorkObservation.ticket_id == r.ticket_id,
            PortalWorkObservation.kind == "submission",
        )
        .order_by(PortalWorkObservation.sequence.desc())
        .limit(1)
    )
    if row is None:
        work.error("portal_work_reference_unavailable")
    observed = private.SubmissionObservation.model_validate(row.private_observation)
    if observed.state != "accepted" or observed.reference is None:
        work.error("portal_work_reference_unavailable")
    return require_reference(command, observed.reference, "portal_referral")


def claim(
    s,
    box,
    actor,
    wid,
    tid,
    mode,
    request,
    *,
    catalog=setup.EMPTY_CATALOG,
    policy=work.DEFAULT_POLICY,
    core_checked=None,
):
    if mode not in {"submit", "status"}:
        work.error("invalid_portal_work_request", 422)
    request = schema.Bound.model_validate(request.public())
    w = work.owner(s, box, actor, wid, True)
    old, sha = work.old_receipt(s, w, mode, request)
    if old:
        if old.ticket_id != tid:
            work.error("portal_work_idempotency_conflict")
        return work.response(old), None
    work.gate(policy)
    if not policy.io_enabled:
        work.error("portal_work_io_disabled", 403)
    t, r, command = work.bound(s, w, tid, request)
    work.current(s, w, r, catalog, core_checked, reading=mode == "status")
    op = s.get(Operation, r.operation_id)
    now = work.clock(s)
    if op is None:
        work.error("portal_work_not_approved")
    approval = None
    ref = None
    if mode == "submit":
        if (
            t.state != "approved"
            or op.attempt_count != 0
            or s.scalar(
                select(PortalWorkClaim.id).where(
                    PortalWorkClaim.operation_id == op.id, PortalWorkClaim.mode == "submit"
                )
            )
        ):
            work.error("portal_work_submit_already_claimed")
        approved = s.scalar(
            select(PortalWorkReceipt).where(
                PortalWorkReceipt.ticket_id == tid,
                PortalWorkReceipt.command_kind == "decide",
                PortalWorkReceipt.request["choice"].as_string() == "approve",
            )
        )
        if approved is None:
            work.error("portal_work_not_approved")
        approval = private.ApprovalBinding(
            operation_id=command.operation_id,
            revision_id=command.revision_id,
            action=command.intent.kind,
            approved_payload_sha256=command.commitment(),
            selection_sha256=command.selection.commitment(),
            expires_at=command.expires_at,
        )
        op.status = "running"
        op.attempt_count = 1
        op.started_at = now
    else:
        if r.action != "referral.submit" or not work.states(s, r)["submit_claimed"]:
            work.error("portal_work_reference_unavailable")
        if s.scalar(
            select(PortalWorkClaim.id).where(
                PortalWorkClaim.operation_id == op.id,
                PortalWorkClaim.mode == "status",
                PortalWorkClaim.completed_at.is_(None),
                PortalWorkClaim.deadline > now,
            )
        ):
            work.error("portal_work_read_in_progress")
        if (
            s.scalar(
                select(func.count())
                .select_from(PortalWorkClaim)
                .where(PortalWorkClaim.operation_id == op.id, PortalWorkClaim.mode == "status")
            )
            >= 100
        ):
            work.error("portal_work_history_limit")
        ref = reference(s, r, command)
    t.version += 1
    receipt = work.record(s, w, mode, request, sha, t, r, mode + "_claimed")
    cid = str(uuid4())
    s.add(
        PortalWorkClaim(
            id=cid,
            box_id=box,
            owner_id=actor,
            workspace_id=wid,
            ticket_id=tid,
            operation_id=op.id,
            receipt_id=receipt.id,
            mode=mode,
            dispatch="claimed",
            claimed_at=now,
            deadline=now + timedelta(seconds=45),
        )
    )
    s.flush()
    work.fence(s)
    s.commit()
    return work.response(receipt), Invocation(
        box, actor, wid, tid, cid, mode, command, approval, ref, core_checked
    )


def internal(s, inv):
    s.scalar(
        select(Principal)
        .where(Principal.id == inv.owner_id, Principal.box_id == inv.box_id)
        .with_for_update()
    )
    w = s.scalar(
        select(EncounterWorkspace)
        .where(
            EncounterWorkspace.id == inv.workspace_id,
            EncounterWorkspace.box_id == inv.box_id,
            EncounterWorkspace.owner_id == inv.owner_id,
        )
        .with_for_update()
    )
    if w is None:
        work.error("portal_work_integrity", 503)
    t, r, command = work.bound(s, w, inv.ticket_id)
    row = s.scalar(
        select(PortalWorkClaim)
        .where(PortalWorkClaim.id == inv.claim_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or (row.box_id, row.owner_id, row.workspace_id, row.ticket_id, row.operation_id, row.mode)
        != (
            inv.box_id,
            inv.owner_id,
            inv.workspace_id,
            inv.ticket_id,
            str(inv.command.operation_id),
            inv.mode,
        )
        or command != inv.command
    ):
        work.error("portal_work_integrity", 503)
    return w, t, r, s.get(Operation, r.operation_id), row


def mark(s, inv, *, catalog, policy):
    work.gate(policy)
    if not policy.io_enabled:
        return False
    w = work.owner(s, inv.box_id, inv.owner_id, inv.workspace_id, True)
    _, r, _ = work.bound(s, w, inv.ticket_id)
    work.current(s, w, r, catalog, inv.core_checked, reading=inv.mode == "status")
    w, t, r, op, row = internal(s, inv)
    if (
        row.dispatch != "claimed"
        or row.completed_at is not None
        or work.clock(s) >= row.deadline
        or inv.mode == "submit"
        and t.state != "approved"
    ):
        return False
    if inv.mode == "submit":
        if inv.approval is None:
            return False
        inv.approval.require_command(inv.command, work.clock(s))
    row.dispatch = "invoking"
    s.commit()
    return True


def settle(s, inv, *, observation=None, failure=None):
    w, t, r, op, row = internal(s, inv)
    if row.completed_at is not None:
        return
    if row.dispatch not in {"claimed", "invoking"}:
        work.error("portal_work_integrity", 503)
    kind = "failure"
    state = "unknown"
    private_value = {"safe_error": "transport_unconfirmed"}
    try:
        if inv.mode == "submit" and isinstance(observation, private.SubmissionObservation):
            observed = private.SubmissionObservation.model_validate(
                observation.model_dump(mode="python")
            )
            if (
                observed.vendor,
                str(observed.connection_id),
                str(observed.operation_id),
                observed.request_sha256,
            ) != (
                "portal",
                str(inv.command.selection.connection_id),
                str(inv.command.operation_id),
                inv.command.commitment(),
            ):
                raise ValueError
            if observed.reference:
                require_reference(
                    inv.command,
                    observed.reference,
                    "portal_document" if r.action == "document.upload" else "portal_referral",
                )
            if observed.state == "accepted" and observed.reference is None:
                raise ValueError
            kind = "submission"
            state = observed.state
            private_value = observed.model_dump(mode="json")
        elif inv.mode == "status" and isinstance(observation, private.PortalObservation):
            observed = private.PortalObservation.model_validate(
                observation.model_dump(mode="python")
            )
            if observed.reference != inv.reference:
                raise ValueError
            require_reference(inv.command, observed.reference, "portal_referral")
            kind = "status"
            state = observed.state
            private_value = observed.model_dump(mode="json")
        elif failure is not None:
            private_value = {
                "safe_error": failure.code
                if isinstance(failure, private.VendorError)
                else "transport_unconfirmed"
            }
    except (ValueError, private.VendorError):
        private_value = {"safe_error": "response_invalid"}
    now = work.clock(s)
    h = work.head(s, r)
    oid = str(uuid4())
    sequence = h["sequence"] + 1
    public = {
        "id": oid,
        "sequence": sequence,
        "operation_id": r.operation_id,
        "kind": kind,
        "mode": inv.mode,
        "state": state,
        "observed_at": timestamp(now),
    }
    sha = public_digest("cosmas-portal-work-observation.v1", public)
    public["sha256"] = sha
    head_sha = public_digest(
        "cosmas-portal-work-head.v1",
        {
            "operation_id": r.operation_id,
            "sequence": sequence,
            "previous_sha256": h["sha256"],
            "observation_sha256": sha,
        },
    )
    item = PortalWorkObservation(
        id=oid,
        box_id=inv.box_id,
        owner_id=inv.owner_id,
        workspace_id=inv.workspace_id,
        ticket_id=inv.ticket_id,
        claim_id=inv.claim_id,
        sequence=sequence,
        kind=kind,
        private_observation=private_value,
        public_observation=public,
        public_sha256=sha,
        head_sha256=head_sha,
        observed_at=now,
    )
    s.add(item)
    s.flush()
    row.dispatch = "settled"
    row.completed_at = now
    if inv.mode == "submit":
        op.status = "succeeded" if kind == "submission" and state == "accepted" else "failed"
        op.completed_at = now
        op.result_receipt_hash = sha
        op.error_message = None if op.status == "succeeded" else "portal_outcome_unconfirmed"
    if t.state == "closed":
        t.state = "approved"
        t.closed_at = None
        t.version += 1
        s.flush()
        s.add(
            PortalWorkReopen(
                box_id=inv.box_id,
                owner_id=inv.owner_id,
                workspace_id=inv.workspace_id,
                ticket_id=inv.ticket_id,
                observation_id=oid,
                version=t.version,
                recorded_at=now,
            )
        )
    s.commit()


class PortalWorkExecution:
    """Reviewed portal execution owned by an installed service or local harness."""

    def __init__(
        self,
        session_factory,
        *,
        catalog=setup.EMPTY_CATALOG,
        artifact_store=None,
        identity_current=None,
        policy_current=lambda: work.DEFAULT_POLICY,
    ):
        self.sessions = session_factory
        self.catalog = catalog
        self.store = artifact_store
        self.identity_current = identity_current
        self.policy_current = policy_current
        self.pending = set()

    def _mark(self, inv):
        with self.sessions() as s:
            return mark(s, inv, catalog=self.catalog, policy=self.policy_current())

    def _ready(self, inv):
        with self.sessions() as s:
            policy = self.policy_current()
            work.gate(policy)
            if not policy.io_enabled:
                return False
            w = work.owner(s, inv.box_id, inv.owner_id, inv.workspace_id, True)
            _, r, _ = work.bound(s, w, inv.ticket_id)
            work.current(s, w, r, self.catalog, inv.core_checked, reading=inv.mode == "status")
            _, t, _, _, claim = internal(s, inv)
            return (
                claim.dispatch == "invoking"
                and claim.completed_at is None
                and work.clock(s) < claim.deadline
                and (inv.mode != "submit" or t.state == "approved")
            )

    def _settle(self, inv, observation, failure):
        # Settlement records only this existing claim. A canceled request must
        # not discard an already received provider result or permit a replay.
        with capture_budget(CaptureBudget(5)), self.sessions() as s:
            settle(s, inv, observation=observation, failure=failure)

    async def _run(self, inv, deadline):
        observation = None
        failure = None
        try:
            data = None
            if inv.mode == "submit" and isinstance(
                inv.command.intent, private.PortalDocumentIntent
            ):
                if self.store is None:
                    raise private.VendorError("artifact_changed")
                artifact_scope = VendorArtifactScope(
                    box_id=inv.box_id,
                    owner_id=inv.owner_id,
                    workspace_id=inv.workspace_id,
                    document=inv.command.intent.document,
                )
                data = await asyncio.to_thread(
                    self.store.read_verified, artifact_scope, deadline=deadline
                )
            if (
                time.monotonic() >= deadline
                or self.identity_current is None
                or await self.identity_current() is not True
            ):
                raise private.VendorError("authority_required")
            if not await asyncio.to_thread(self._mark, inv):
                return
            command = inv.command
            adapter = self.catalog.registry.resolve(
                command.selection,
                command.intent.portal_id,
                command.intent.kind if inv.mode == "submit" else "referral.read",
            )
            if inv.mode == "submit":
                prepared = self.catalog.registry.prepare(command, data)
                # Preparation is pure; the last application gate follows it.
                if (
                    time.monotonic() >= deadline
                    or not self.policy_current().io_enabled
                    or await self.identity_current() is not True
                    or not await asyncio.to_thread(self._ready, inv)
                ):
                    raise private.VendorError("authority_required")
                observation = await adapter.submit(prepared, inv.approval)
            else:
                if (
                    time.monotonic() >= deadline
                    or not self.policy_current().io_enabled
                    or not await asyncio.to_thread(self._ready, inv)
                ):
                    raise private.VendorError("authority_required")
                observation = await adapter.observe(command, inv.reference)
        except asyncio.CancelledError:
            raise
        except private.VendorError as exc:
            failure = exc
        except Exception:
            failure = private.VendorError("transport_unconfirmed", attempted=True)
        finally:
            if observation is not None or failure is not None:
                await asyncio.to_thread(self._settle, inv, observation, failure)

    async def run_owned(self, inv, *, deadline=None):
        deadline = (
            min(deadline, time.monotonic() + 45) if deadline is not None else time.monotonic() + 45
        )
        try:
            async with asyncio.timeout_at(deadline):
                await self._run(inv, deadline)
        except TimeoutError:
            await asyncio.to_thread(
                self._settle,
                inv,
                None,
                private.VendorError("transport_unconfirmed", attempted=True),
            )

    async def invoke(self, inv, *, deadline=None):
        task = asyncio.create_task(self.run_owned(inv, deadline=deadline))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)
        # Caller timeout/cancellation must retain a later complete provider result.
        return await asyncio.shield(task)
