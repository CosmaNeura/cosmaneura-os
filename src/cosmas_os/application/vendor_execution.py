"""One irreversible admission to each connector invocation; durable explicit reads.

No worker scans this ledger or retries a claim. Private late evidence may settle
after foreground cancellation; disclosure always repeats current authorization.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from cosmas_os.adapters.vendor_connectors.documo import DocumoConnector
from cosmas_os.adapters.vendor_connectors.spruce import SpruceConnector
from cosmas_os.adapters.vendor_connectors.srfax import SRFaxConnector
from cosmas_os.adapters.vendor_connectors.transport import VendorRuntime, require_reference
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_work as work
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.models import EncounterWorkspace, Operation, Principal, Ticket
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError, VendorArtifactScope
from cosmas_os.vendor_models import (
    VendorCommandReceipt,
    VendorConnectionVersion,
    VendorProviderObservation,
    VendorReadClaim,
    VendorSubmitClaim,
    VendorWorkRevision,
)


@dataclass(frozen=True, repr=False)
class Invocation:
    operation_id: str
    claim_id: str
    token: str
    mode: str
    receipt_id: str
    box_id: str
    owner_id: str
    workspace_id: str
    command: private.VendorCommand
    approval: private.ApprovalBinding | None
    reference: private.ProviderReference | None
    core_checked: object = None


def _approval(s, r, command):
    row = s.scalar(
        select(VendorCommandReceipt).where(
            VendorCommandReceipt.action_revision_id == r.action_revision_id,
            VendorCommandReceipt.command_kind == "decide",
            VendorCommandReceipt.actor_id == r.owner_id,
            VendorCommandReceipt.public_request["choice"].as_string() == "approve",
        )
    )
    if row is None:
        work.error("vendor_revision_changed")
    return row, private.ApprovalBinding(
        operation_id=command.operation_id,
        revision_id=command.revision_id,
        action=command.intent.kind,
        approved_payload_sha256=command.commitment(),
        selection_sha256=command.selection.commitment(),
        expires_at=command.expires_at,
    )


def claim_submit(s, box, actor, wid, tid, request, *, core_checked=None):
    w = work._owner(s, box, actor, wid, writing=True)
    previous, digest = work._receipt(s, w, actor, "submit", request)
    if previous:
        if previous.ticket_id != tid:
            work.error("vendor_idempotency_conflict")
        return work.command_response(s, previous), None
    work._gate()
    if not settings.vendor_io_enabled:
        work.error("vendor_feature_disabled", 403)
    # Workspace serialization makes this immutable discovery stable. Configuration
    # locks must precede the Ticket/Operation locks used by _bound.
    candidate = s.get(VendorWorkRevision, request.revision_id)
    if (
        candidate is None
        or candidate.workspace_id != wid
        or candidate.owner_id != actor
        or candidate.ticket_id != tid
    ):
        work.error("vendor_work_unavailable", 404)
    config, correspondence = work._new_current(s, w, candidate, core_checked)
    _, t, r, command = work._bound(s, w, tid)
    work._check_bound(t, r, request)
    if t.state != "approved":
        work.error("vendor_revision_changed")
    op = work._operation(s, r)
    if op is None or s.get(VendorSubmitClaim, op.id) is not None or op.attempt_count != 0:
        work.error("vendor_submit_already_claimed")
    approval_row, approval = _approval(s, r, command)
    now = work._clock(s)
    if now >= command.expires_at:
        work.error("vendor_approval_expired")
    t.version += 1
    op.status, op.attempt_count, op.started_at = "running", 1, now
    receipt = work._record(s, w, actor, "submit", request, digest, t, r, "submit_claimed")
    token = str(uuid4())
    s.add(
        VendorSubmitClaim(
            operation_id=op.id,
            ticket_id=tid,
            action_revision_id=r.action_revision_id,
            box_id=box,
            owner_id=actor,
            workspace_id=wid,
            actor_id=actor,
            approval_receipt_id=approval_row.id,
            command_receipt_id=receipt.id,
            command_sha256=command.commitment(),
            source_sha256=r.source_proof_sha256,
            selection_sha256=config.private_sha256,
            correspondence_sha256=correspondence.private_sha256 if correspondence else None,
            request_sha256=digest,
            claim_token=token,
            claimed_at=now,
            deadline=now + timedelta(seconds=45),
        )
    )
    s.commit()
    return work.command_response(s, receipt), Invocation(
        op.id,
        op.id,
        token,
        "submit",
        receipt.id,
        box,
        actor,
        wid,
        command,
        approval,
        None,
        core_checked,
    )


def _reference(s, r, command):
    for row in s.scalars(
        select(VendorProviderObservation)
        .where(
            VendorProviderObservation.operation_id == r.intended_operation_id,
            VendorProviderObservation.private_reference.is_not(None),
        )
        .order_by(VendorProviderObservation.sequence.desc())
    ):
        ref = private.ProviderReference.model_validate(row.private_reference)
        try:
            return require_reference(
                command, ref, "conversation_item" if command.selection.vendor == "spruce" else "fax"
            )
        except private.VendorError:
            continue
    work.error("vendor_reference_unavailable")


def _historical_connection(s, w, r, command):
    config = s.scalar(
        select(VendorConnectionVersion)
        .where(
            VendorConnectionVersion.id == r.connection_version_id,
            VendorConnectionVersion.box_id == w.box_id,
            VendorConnectionVersion.owner_id == w.owner_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        config is None
        or config.revoked_at is not None
        or not config.read_enabled
        or private.ConnectionSelection.model_validate(config.private_selection) != command.selection
        or config.private_sha256 != command.selection.commitment()
    ):
        work.error("vendor_original_account_unavailable")
    try:
        work._managed_connection(s, w, config.id, mutating=False)
    except ws.WorkspaceError:
        work.error("vendor_original_account_unavailable")
    return config


def claim_read(s, box, actor, wid, tid, request):
    w = work._owner(s, box, actor, wid, writing=True)
    previous, digest = work._receipt(s, w, actor, "reconcile", request)
    if previous:
        if previous.ticket_id != tid:
            work.error("vendor_idempotency_conflict")
        return work.command_response(s, previous), None
    if not settings.vendor_io_enabled:
        work.error("vendor_feature_disabled", 403)
    candidate = s.get(VendorWorkRevision, request.revision_id)
    if (
        candidate is None
        or candidate.workspace_id != wid
        or candidate.owner_id != actor
        or candidate.ticket_id != tid
    ):
        work.error("vendor_work_unavailable", 404)
    candidate_command = private.VendorCommand.model_validate(candidate.private_command)
    _historical_connection(s, w, candidate, candidate_command)
    _, t, r, command = work._bound(s, w, tid)
    work._check_bound(t, r, request)
    if s.get(VendorSubmitClaim, r.intended_operation_id) is None:
        work.error("vendor_reference_unavailable")
    ref = _reference(s, r, command)
    now = work._clock(s)
    if s.scalar(
        select(VendorReadClaim.id).where(
            VendorReadClaim.operation_id == r.intended_operation_id,
            VendorReadClaim.completed_at.is_(None),
            VendorReadClaim.deadline > now,
        )
    ):
        work.error("vendor_read_in_progress")
    if (
        s.scalar(
            select(func.count())
            .select_from(VendorReadClaim)
            .where(VendorReadClaim.operation_id == r.intended_operation_id)
        )
        >= 100
    ):
        work.error("vendor_history_limit")
    t.version += 1
    receipt = work._record(s, w, actor, "reconcile", request, digest, t, r, "read_claimed")
    cid, token = str(uuid4()), str(uuid4())
    s.add(
        VendorReadClaim(
            id=cid,
            operation_id=r.intended_operation_id,
            ticket_id=tid,
            action_revision_id=r.action_revision_id,
            box_id=box,
            owner_id=actor,
            workspace_id=wid,
            actor_id=actor,
            idempotency_key=request.idempotency_key,
            command_receipt_id=receipt.id,
            connection_version_id=r.connection_version_id,
            private_reference=ref.model_dump(mode="json"),
            reference_sha256=private.digest(
                "cosmas-vendor-reference.v1", ref.model_dump(mode="json")
            ),
            request_sha256=digest,
            claim_token=token,
            admitted_at=now,
            deadline=now + timedelta(seconds=45),
        )
    )
    s.commit()
    return work.command_response(s, receipt), Invocation(
        r.intended_operation_id,
        cid,
        token,
        "reconcile",
        receipt.id,
        box,
        actor,
        wid,
        command,
        None,
        ref,
    )


def _internal(s, invocation):
    # Internal settlement preserves the original evidence even after human access
    # changes. It does not disclose it or admit a new provider invocation.
    s.scalar(select(Principal).where(Principal.id == invocation.owner_id).with_for_update())
    w = s.scalar(
        select(EncounterWorkspace)
        .where(EncounterWorkspace.id == invocation.workspace_id)
        .with_for_update()
    )
    r = s.get(VendorWorkRevision, str(invocation.command.revision_id))
    if (
        r is None
        or w is None
        or r.workspace_id != w.id
        or r.intended_operation_id != invocation.operation_id
    ):
        work.error("vendor_unavailable", 503)
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
    model = VendorSubmitClaim if invocation.mode == "submit" else VendorReadClaim
    key = VendorSubmitClaim.operation_id if invocation.mode == "submit" else VendorReadClaim.id
    claim = s.scalar(
        select(model)
        .where(key == invocation.claim_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        claim is None
        or claim.claim_token != invocation.token
        or claim.operation_id != r.intended_operation_id
        or private.VendorCommand.model_validate(r.private_command) != invocation.command
    ):
        work.error("vendor_unavailable", 503)
    return w, t, r, op, claim


def _append(
    s, invocation, t, r, *, kind, values, evidence, observed_at, reference=None, response_sha=None
):
    canonical_sha = private.digest("cosmas-vendor-observed-fact.v1", evidence)
    source = "submit" if invocation.mode == "submit" else "read"
    if kind == "dispatch":
        source = "internal_dispatch"
    existing = s.scalar(
        select(VendorProviderObservation).where(
            VendorProviderObservation.operation_id == invocation.operation_id,
            VendorProviderObservation.source == source,
            VendorProviderObservation.source_id == invocation.claim_id,
            VendorProviderObservation.kind == kind,
            VendorProviderObservation.canonical_sha256 == canonical_sha,
        )
    )
    if existing:
        return existing
    head = work._head(s, r)
    now = work._clock(s)
    oid = str(uuid4())
    value = {
        "id": oid,
        "sequence": head["sequence"] + 1,
        "operation_id": invocation.operation_id,
        "kind": kind,
        "observed_at": public.timestamp(observed_at),
        "recorded_at": public.timestamp(now),
        **values,
    }
    sha = public.public_digest("cosmas-vendor-public-observation.v1", value)
    value["sha256"] = sha
    value = public.Observation.model_validate(value).public()
    new_head = public.public_digest(
        "cosmas-vendor-observation-head.v1",
        {
            "operation_id": invocation.operation_id,
            "sequence": head["sequence"] + 1,
            "previous_sha256": head["sha256"],
            "observation_sha256": sha,
        },
    )
    row = VendorProviderObservation(
        id=oid,
        operation_id=invocation.operation_id,
        ticket_id=r.ticket_id,
        action_revision_id=r.action_revision_id,
        workspace_id=r.workspace_id,
        box_id=r.box_id,
        owner_id=r.owner_id,
        connection_version_id=r.connection_version_id,
        sequence=head["sequence"] + 1,
        source=source,
        source_id=invocation.claim_id,
        submit_claim_id=invocation.claim_id if invocation.mode == "submit" else None,
        read_claim_id=invocation.claim_id if invocation.mode == "reconcile" else None,
        kind=kind,
        observed_at=observed_at,
        recorded_at=now,
        body_sha256=response_sha,
        canonical_sha256=canonical_sha,
        private_reference=reference.model_dump(mode="json") if reference else None,
        public_observation=value,
        public_sha256=sha,
        head_sha256=new_head,
    )
    s.add(row)
    s.flush()
    return row


def mark_invocation(s, invocation):
    _, t, r, _, claim = _internal(s, invocation)
    if (
        invocation.mode != "submit"
        or claim.completed_at is not None
        or claim.dispatch != "not_started"
    ):
        work.error("vendor_submit_already_claimed")
    now = work._clock(s)
    if now >= claim.deadline:
        return False
    claim.dispatch, claim.invocation_started_at = "invocation_started", now
    _append(
        s,
        invocation,
        t,
        r,
        kind="dispatch",
        values={"dispatch": "invocation_started"},
        evidence={"dispatch": "invocation_started"},
        observed_at=now,
    )
    t.version += 1
    s.commit()
    return True


def _reopen(s, w, t, r, observation):
    t.version += 1
    t.state, t.closed_at = "approved", None
    fact = "observation-reopen:" + observation.id
    payload = {"observation_id": observation.id, "observation_sha256": observation.public_sha256}
    sha = private.digest("cosmas-vendor-system-fact.v1", payload)
    s.add(
        VendorCommandReceipt(
            box_id=w.box_id,
            workspace_id=w.id,
            owner_id=w.owner_id,
            origin="system",
            scope_kind="workspace",
            scope_id=w.id,
            command_kind="reopen",
            fact_key=fact,
            public_request=payload,
            request_sha256=sha,
            ticket_id=t.id,
            action_revision_id=r.action_revision_id,
            operation_id=r.intended_operation_id,
            effect_version=t.version,
            effect={"fact": "reopened", **payload},
            receipt_sha256=sha,
            recorded_at=work._clock(s),
        )
    )


def settle(s, invocation, *, observation=None, failure=None):
    w, t, r, op, claim = _internal(s, invocation)
    if claim.completed_at is not None:
        return
    before = work._states(s, t, r)
    now = work._clock(s)
    if invocation.mode == "submit":
        if isinstance(observation, private.SubmissionObservation):
            observation = private.SubmissionObservation.model_validate(
                observation.model_dump(mode="python")
            )
            if (
                observation.vendor,
                str(observation.connection_id),
                str(observation.operation_id),
                observation.request_sha256,
            ) != (
                invocation.command.selection.vendor,
                str(invocation.command.selection.connection_id),
                invocation.operation_id,
                invocation.command.commitment(),
            ):
                work.error("vendor_unavailable", 503)
            if observation.reference:
                require_reference(
                    invocation.command, observation.reference, observation.reference.kind
                )
            values = {"acceptance": observation.state}
            if observation.safe_error:
                values["safe_error"] = observation.safe_error
            row = _append(
                s,
                invocation,
                t,
                r,
                kind="submission",
                values=values,
                evidence=observation.model_dump(mode="json"),
                observed_at=observation.observed_at,
                reference=observation.reference,
                response_sha=observation.response_sha256,
            )
            claim.dispatch = (
                "response_observed" if observation.state != "unconfirmed" else "unconfirmed"
            )
            op.status = {"accepted": "succeeded", "rejected": "failed", "unconfirmed": "unknown"}[
                observation.state
            ]
        else:
            failure = (
                failure
                if isinstance(failure, private.VendorError)
                else private.VendorError("transport_unconfirmed", attempted=True)
            )
            dispatch = "unconfirmed" if failure.attempted else "proved_not_dispatched"
            row = _append(
                s,
                invocation,
                t,
                r,
                kind="dispatch",
                values={"dispatch": dispatch, "safe_error": failure.code},
                evidence={"dispatch": dispatch, "safe_error": failure.code},
                observed_at=now,
            )
            claim.dispatch, claim.safe_error = dispatch, failure.code
            op.status = "unknown" if failure.attempted else "failed"
        op.completed_at = now
        op.result_receipt_hash = row.public_sha256
    else:
        if isinstance(observation, private.DeliveryObservation):
            observation = private.DeliveryObservation.model_validate(
                observation.model_dump(mode="python")
            )
            if observation.reference != invocation.reference:
                work.error("vendor_unavailable", 503)
            values: dict = {
                "transport": {
                    "pending": "pending",
                    "transport_delivered": "delivered",
                    "transport_failed": "failed",
                    "unknown": "unknown",
                }[observation.state]
            }
            # A missing delivered count is an omitted observation, never zero.
            if observation.pages_total is not None and observation.pages_delivered is not None:
                values.update(
                    pages_total=observation.pages_total, pages_delivered=observation.pages_delivered
                )
            row = _append(
                s,
                invocation,
                t,
                r,
                kind="transport",
                values=values,
                evidence=observation.model_dump(mode="json"),
                observed_at=observation.observed_at,
                reference=observation.reference,
                response_sha=observation.response_sha256,
            )
            claim.state = "settled"
        else:
            failure = (
                failure
                if isinstance(failure, private.VendorError)
                else private.VendorError("transport_unconfirmed", attempted=True)
            )
            row = _append(
                s,
                invocation,
                t,
                r,
                kind="transport",
                values={"transport": "unknown", "safe_error": failure.code},
                evidence={"transport": "unknown", "safe_error": failure.code},
                observed_at=now,
            )
            claim.state = "unknown"
    claim.completed_at = now
    t.version += 1
    s.flush()
    after = work._states(s, t, r)
    if t.state == "closed" and after["conflicting_evidence"] and not before["conflicting_evidence"]:
        _reopen(s, w, t, r, row)
    s.commit()


class VendorExecution:
    """Explicitly injected application runtime. No env-based credential discovery."""

    def __init__(
        self,
        session_factory,
        credentials,
        *,
        artifact_store=None,
        transport=None,
        identity_current=None,
    ):
        self.sessions, self.credentials = session_factory, credentials
        self.artifact_store, self.transport = artifact_store, transport
        self.identity_current = identity_current
        self._pending = set()

    async def authorize(self, invocation, selection, command, approval, mutating):
        if (
            not settings.vendor_io_enabled
            or self.identity_current is None
            or await self.identity_current() is not True
        ):
            return False
        if (
            command != invocation.command
            or selection != invocation.command.selection
            or mutating != (invocation.mode == "submit")
        ):
            return False
        return await asyncio.to_thread(
            self._authorize_current, invocation, command, approval, mutating
        )

    def _authorize_current(self, invocation, command, approval, mutating):
        try:
            with self.sessions() as s:
                from cosmas_os.application.vendor_settings_admission import runtime_matches

                if not runtime_matches(s, command.selection.connection_id, self):
                    return False
                w = work._owner(
                    s, invocation.box_id, invocation.owner_id, invocation.workspace_id, writing=True
                )
                r = s.get(VendorWorkRevision, str(command.revision_id))
                if mutating:
                    work._new_current(s, w, r, invocation.core_checked)
                else:
                    _historical_connection(s, w, r, command)
                _, t, r, _ = work._bound(s, w, r.ticket_id)
                claim = (
                    s.get(VendorSubmitClaim, invocation.operation_id)
                    if mutating
                    else s.get(VendorReadClaim, invocation.claim_id)
                )
                if (
                    claim is None
                    or claim.claim_token != invocation.token
                    or claim.completed_at is not None
                    or work._clock(s) >= claim.deadline
                    or mutating
                    and (t.state != "approved" or approval != invocation.approval)
                ):
                    return False
                return True
        except (ws.WorkspaceError, ValueError):
            return False

    async def _invoke(self, invocation, deadline):
        observation, failure = None, None
        try:
            if time.monotonic() >= deadline:
                raise private.VendorError("authority_required")
            if invocation.mode == "submit":
                if not await asyncio.to_thread(self._mark, invocation):
                    raise private.VendorError("authority_required")
            document = None
            if invocation.mode == "submit" and isinstance(
                invocation.command.intent, (private.MediaUploadIntent, private.FaxIntent)
            ):
                if self.artifact_store is None:
                    raise private.VendorError("artifact_changed")
                scope = VendorArtifactScope(
                    box_id=invocation.box_id,
                    workspace_id=invocation.workspace_id,
                    owner_id=invocation.owner_id,
                    document=invocation.command.intent.document,
                )
                document = await asyncio.to_thread(
                    self.artifact_store.read_verified, scope, deadline=deadline
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise private.VendorError("authority_required")
            runtime = VendorRuntime(
                invocation.command.selection,
                self.credentials,
                enabled=settings.vendor_io_enabled,
                transport=self.transport,
                authorize=lambda *args: self.authorize(invocation, *args),
                timeout_seconds=min(30, remaining),
            )
            connector = {
                "spruce": SpruceConnector,
                "srfax": SRFaxConnector,
                "documo": DocumoConnector,
            }[invocation.command.selection.vendor](runtime)
            if invocation.mode == "submit":
                observation = await connector.submit(
                    invocation.command, invocation.approval, document
                )
            else:
                observation = await connector.observe(invocation.command, invocation.reference)
        except private.VendorError as exc:
            failure = exc
        except ArtifactStoreError:
            failure = private.VendorError("artifact_changed")
        except asyncio.CancelledError:
            # Process shutdown retains a spent, unresolved claim. No retry job.
            raise
        except Exception:
            failure = private.VendorError("transport_unconfirmed", attempted=True)
        finally:
            if observation is not None or failure is not None:
                await asyncio.to_thread(self._settle, invocation, observation, failure)

    def _mark(self, invocation):
        with self.sessions() as s:
            return mark_invocation(s, invocation)

    def _settle(self, invocation, observation, failure):
        with self.sessions() as s:
            settle(s, invocation, observation=observation, failure=failure)

    async def invoke(self, invocation, *, deadline=None):
        deadline = (
            min(deadline, time.monotonic() + 45) if deadline is not None else time.monotonic() + 45
        )
        task = asyncio.create_task(self._invoke(invocation, deadline))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        # Foreground timeout must not erase a later complete provider response.
        return await asyncio.shield(task)
