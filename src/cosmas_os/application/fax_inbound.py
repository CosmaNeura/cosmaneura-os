"""Saved multi-provider read permissions and exact F8 image approvals.

Transport receives only commands rebuilt from current retained custody. Private
locators never enter generic action content, and recovery never dispatches I/O.
"""

import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import func, select

from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.fax_inbound_models import (
    FaxInboundAttempt,
    FaxInboundCommand,
    FaxInboundDispatch,
    FaxInboundGrant,
    FaxInboundImage,
    FaxInboundObservation,
    FaxInboundOutcome,
)
from cosmas_os.models import ActionRevision, Decision, Operation, Ticket
from cosmas_os.ports.fax_inbound import (
    ImageApproval,
    MetadataPage,
    ReadScope,
    ReceivedFax,
)
from cosmas_os.ports.vendor_connectors import ConnectionSelection

_public_command = ContextVar("fax_inbound_public_command", default=None)


@contextmanager
def public_command(value):
    token = _public_command.set(value)
    try:
        yield
    finally:
        _public_command.reset(token)


LANE = "account_fax_inbound"
ADAPTER = "fax_inbound_once"


def commitment(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def fail(code="fax_inbound_unavailable", status=409) -> NoReturn:
    raise ws.WorkspaceError(code, status)


@dataclass(frozen=True, repr=False)
class Installation:
    selection: ConnectionSelection
    label: str
    image_enabled: bool = False
    account_timezone: str | None = None
    account_date_format: str | None = None
    received_status: str | None = None
    conversation_id: str | None = None
    internal_endpoint_id: str | None = None

    def __post_init__(self):
        if (
            type(self.selection) is not ConnectionSelection
            or self.selection.vendor not in {"srfax", "documo", "spruce"}
            or type(self.label) is not str
            or not 1 <= len(self.label) <= 80
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in self.label)
            or type(self.image_enabled) is not bool
            or self.selection.vendor == "spruce"
            and self.image_enabled
        ):
            fail("fax_inbound_installation_invalid")
        # Validate provider setup before advertising the account as usable.
        from cosmas_os.application.fax_inbound_provider import adapter

        now = datetime.now(UTC)
        adapter(self.selection.vendor).list_plan(
            self.scope(now - timedelta(minutes=1), now, uuid4(), 1)
        )

    def scope(self, start, end, request_id, limit):
        return ReadScope(
            self.selection,
            start,
            end,
            request_id,
            limit,
            self.account_timezone,
            self.account_date_format,
            self.received_status,
            self.conversation_id,
            self.internal_endpoint_id,
        )

    def value(self):
        return {**asdict(self), "selection": self.selection.model_dump(mode="json")}

    def key(self):
        return commitment(self.value())


def installation(value):
    return Installation(
        **{**value, "selection": ConnectionSelection.model_validate(value["selection"])}
    )


def now(s):
    return s.scalar(select(func.clock_timestamp())).astimezone(UTC)


def owner(s, box, actor, *, writing=False):
    if not settings.workspace_enabled:
        fail(status=403)
    p = ws._human(s, box, actor, creating=writing)
    if not p.is_owner:
        fail(status=404)
    return p


def account_key(item):
    v = item.selection
    return commitment(
        {
            "box": str(v.box_id),
            "vendor": v.vendor,
            "environment": v.environment,
            "account": v.remote_account_id,
        }
    )


def grant_current(s, box, actor, gid, current, *, image=False):
    owner(s, box, actor, writing=True)
    g = s.scalar(
        select(FaxInboundGrant)
        .where(
            FaxInboundGrant.id == gid,
            FaxInboundGrant.box_id == box,
            FaxInboundGrant.owner_id == actor,
        )
        .with_for_update()
    )
    if (
        g is None
        or g.revoked_at
        or g.expires_at <= now(s)
        or current is None
        or current(installation(g.installation)) is not True
        or image
        and not g.image_enabled
        or commitment(g.installation) != g.installation_sha256
    ):
        fail("fax_inbound_permission_unavailable", 403)
    return g


def previous(s, box, actor, kind, key, request):
    owner(s, box, actor, writing=True)  # serializes owner commands, including first insert
    if type(key) is not str or re.fullmatch(r"[A-Za-z0-9:_-]{8,100}", key) is None:
        fail("fax_inbound_request_invalid", 400)
    sha = commitment({"kind": kind, "request": request})
    old = s.scalar(
        select(FaxInboundCommand).where(
            FaxInboundCommand.box_id == box,
            FaxInboundCommand.owner_id == actor,
            FaxInboundCommand.idempotency_key == key,
        )
    )
    if old and (old.kind != kind or old.request_sha256 != sha or old.request != request):
        fail("fax_inbound_command_changed")
    return old, sha


def record(s, box, actor, kind, key, request, result):
    old, sha = previous(s, box, actor, kind, key, request)
    if old:
        return old
    c = FaxInboundCommand(
        id=str(uuid4()),
        box_id=box,
        owner_id=actor,
        kind=kind,
        idempotency_key=key,
        request=request,
        request_sha256=sha,
        public_request=_public_command.get() or {"idempotency_key": key, **request},
        result={"contract_version": 1, "kind": kind, "idempotency_key": key, **result},
    )
    c.result.update(
        scope={"box_id": box, "owner_id": actor}, request_sha256=sha, source_withheld=False
    )
    c.result["receipt_sha256"] = commitment(c.result)
    s.add(c)
    s.flush()
    return c


def grant(s, box, actor, item, *, key, expires_at, reviewed_account, image_enabled, current):
    if (
        str(item.selection.box_id) != box
        or str(item.selection.owner_id) != actor
        or current(item) is not True
        or reviewed_account is not True
        or type(image_enabled) is not bool
        or image_enabled
        and not item.image_enabled
        or type(expires_at) is not datetime
        or expires_at.tzinfo is None
    ):
        fail("fax_inbound_permission_invalid", 403)
    request = {
        "installation_sha256": item.key(),
        "expires_at": expires_at.isoformat(),
        "image_enabled": image_enabled,
        "reviewed_account": reviewed_account,
    }
    old, _ = previous(s, box, actor, "grant", key, request)
    if old:
        return dict(old.result)
    stamp = now(s)
    if not stamp < expires_at <= stamp + timedelta(days=1):
        fail("fax_inbound_permission_invalid")
    g = FaxInboundGrant(
        id=str(uuid4()),
        box_id=box,
        owner_id=actor,
        installation=item.value(),
        installation_sha256=item.key(),
        account_sha256=account_key(item),
        label=item.label,
        image_enabled=image_enabled,
        reviewed_by=actor,
        reviewed_at=stamp,
        expires_at=expires_at,
    )
    s.add(g)
    c = record(
        s,
        box,
        actor,
        "grant",
        key,
        request,
        {
            "state": "granted",
            "grant_id": g.id,
            "label": g.label,
            "vendor": item.selection.vendor,
            "image_enabled": image_enabled,
            "expires_at": expires_at.isoformat(),
        },
    )
    s.commit()
    return dict(c.result)


def revoke(s, box, actor, gid, *, key):
    request = {"grant_id": gid}
    old, _ = previous(s, box, actor, "revoke", key, request)
    if old:
        return dict(old.result)
    g = s.scalar(
        select(FaxInboundGrant)
        .where(
            FaxInboundGrant.id == gid,
            FaxInboundGrant.box_id == box,
            FaxInboundGrant.owner_id == actor,
        )
        .with_for_update()
    )
    if g is None:
        fail(status=404)
    g.revoked_at = g.revoked_at or now(s)
    c = record(s, box, actor, "revoke", key, request, {"grant_id": gid, "state": "revoked"})
    s.commit()
    return dict(c.result)


def scope_from(value):
    return ReadScope(
        **{
            **value,
            "selection": ConnectionSelection.model_validate(value["selection"]),
            "starts_at": datetime.fromisoformat(value["starts_at"]),
            "ends_at": datetime.fromisoformat(value["ends_at"]),
            "request_id": UUID(value["request_id"]),
        }
    )


def scope_value(scope):
    return {
        **asdict(scope),
        "selection": scope.selection.model_dump(mode="json"),
        "starts_at": scope.starts_at.isoformat(),
        "ends_at": scope.ends_at.isoformat(),
        "request_id": str(scope.request_id),
    }


def source_from(value):
    return ReceivedFax(
        **{
            **value,
            "locator": tuple(value["locator"]),
            "received_at": datetime.fromisoformat(value["received_at"]),
        }
    )


def snapshot_value(page):
    return {
        "scope": scope_value(page.scope),
        "items": [
            {
                **asdict(item),
                "locator": list(item.locator),
                "received_at": item.received_at.isoformat(),
            }
            for item in page.items
        ],
        "continuation": page.continuation,
        "raw_sha256": page.raw_sha256,
        "inbox_complete": False,
    }


def public_snapshot(obs):
    return {
        "observation_id": obs.id,
        "source_sha256": obs.source_sha256,
        "inbox_complete": False,
        "items": [
            {
                "ordinal": ordinal,
                "sender_label": v.get("sender_label")
                or v.get("sender_number")
                or "Sender not provided",
                "sender_number": v.get("sender_number"),
                "sender_identity": "provider_reported_unverified",
                "source_sha256": source_from(v).key(),
                "received_at": v["received_at"],
                "pages": v["pages"],
                "viewed": v["viewed"],
                "image_available": v["image_available"],
                "image_block_reason": v["image_block_reason"],
            }
            for ordinal, v in enumerate(obs.snapshot["items"], 1)
        ],
    }


def reserve_observation(s, box, actor, gid, *, key, starts_at, ends_at, limit, current):
    g = grant_current(s, box, actor, gid, current)
    request = {
        "grant_id": gid,
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "limit": limit,
    }
    old, _ = previous(s, box, actor, "observe", key, request)
    if old:
        return resolve(s, box, actor, key=key, current=current), None
    if ends_at > now(s) + timedelta(seconds=5):
        fail("fax_inbound_request_invalid")
    scope = installation(g.installation).scope(starts_at, ends_at, uuid4(), limit)
    c = record(
        s,
        box,
        actor,
        "observe",
        key,
        request,
        {"state": "outcome_unconfirmed", "grant_id": gid, "retry_allowed": False},
    )
    cid = c.id
    s.commit()
    return dict(c.result), (cid, gid, scope)


def settle_observation(s, box, actor, intent, page, *, current):
    cid, gid, scope = intent
    grant_current(s, box, actor, gid, current)
    c = s.get(FaxInboundCommand, cid)
    if (
        c is None
        or c.box_id != box
        or c.owner_id != actor
        or page.scope != scope
        or type(page) is not MetadataPage
    ):
        fail("fax_inbound_source_changed")
    if s.get(FaxInboundObservation, cid) is None:
        value = snapshot_value(page)
        s.add(
            FaxInboundObservation(
                id=cid,
                box_id=box,
                owner_id=actor,
                grant_id=gid,
                snapshot=value,
                source_sha256=commitment(value),
            )
        )
    s.commit()
    return resolve(s, box, actor, key=c.idempotency_key, current=current)


def source(s, box, actor, obsid, sha):
    obs = s.scalar(
        select(FaxInboundObservation).where(
            FaxInboundObservation.id == obsid,
            FaxInboundObservation.box_id == box,
            FaxInboundObservation.owner_id == actor,
        )
    )
    if obs is None or commitment(obs.snapshot) != obs.source_sha256:
        fail("fax_inbound_source_unavailable")
    matches = [source_from(v) for v in obs.snapshot["items"] if source_from(v).key() == sha]
    if len(matches) != 1:
        fail("fax_inbound_source_changed")
    return obs, scope_from(obs.snapshot["scope"]), matches[0]


def propose(
    s, box, actor, *, key, grant_id, observation_id, observation_sha256, source_sha256, current
):
    request = dict(
        grant_id=grant_id,
        observation_id=observation_id,
        observation_sha256=observation_sha256,
        source_sha256=source_sha256,
    )
    old, _ = previous(s, box, actor, "propose", key, request)
    if old:
        return dict(old.result)
    g = grant_current(s, box, actor, grant_id, current, image=True)
    obs, scope, fax = source(s, box, actor, observation_id, source_sha256)
    stamp = now(s)
    if (
        obs.grant_id != g.id
        or obs.source_sha256 != observation_sha256
        or not fax.image_available
        or not 1 <= fax.pages <= 50
        or obs.created_at < stamp - timedelta(minutes=5)
        or scope.selection != installation(g.installation).selection
    ):
        fail("fax_inbound_source_unavailable")
    p = owner(s, box, actor)
    iid, tid, rid, oid = (str(uuid4()) for _ in range(4))
    payload = {"contract_version": 1, "fax_inbound_image_id": iid, "source_sha256": source_sha256}
    sha = payload_hash(payload)
    t = Ticket(
        id=tid,
        box_id=box,
        created_by_principal_id=actor,
        lane=LANE,
        state="pending_approval",
        version=1,
        current_revision_id=rid,
    )
    s.add(t)
    s.flush()
    s.add(
        ActionRevision(
            id=rid,
            ticket_id=tid,
            box_id=box,
            revision_number=1,
            action_type="fax_inbound_image",
            target_ref="private-inbound-fax",
            content="Open this exact received fax PDF without changing its viewed status.",
            payload=payload,
            payload_hash=sha,
            automation_class="hitl_required",
            created_by_principal_id=actor,
            policy_version=p.policy_version,
            charter_version=p.charter_version,
            config_version=p.config_version,
        )
    )
    s.flush()
    s.add(
        FaxInboundImage(
            id=iid,
            box_id=box,
            owner_id=actor,
            grant_id=g.id,
            observation_id=obs.id,
            source_sha256=source_sha256,
            ticket_id=tid,
            revision_id=rid,
            payload_sha256=sha,
            operation_id=oid,
            expires_at=min(g.expires_at, stamp + timedelta(minutes=5)),
        )
    )
    c = record(
        s,
        box,
        actor,
        "propose",
        key,
        request,
        {"state": "pending_approval", "ticket_id": tid, "revision_id": rid, "version": 1},
    )
    s.commit()
    return dict(c.result)


def image_current(s, box, actor, tid, rid, current):
    p = owner(s, box, actor, writing=True)
    i = s.scalar(
        select(FaxInboundImage).where(
            FaxInboundImage.ticket_id == tid,
            FaxInboundImage.revision_id == rid,
            FaxInboundImage.box_id == box,
            FaxInboundImage.owner_id == actor,
        )
    )
    t = s.scalar(select(Ticket).where(Ticket.id == tid, Ticket.box_id == box).with_for_update())
    a = s.get(ActionRevision, rid)
    if (
        i is None
        or t is None
        or a is None
        or t.lane != LANE
        or t.created_by_principal_id != actor
        or t.current_revision_id != rid
        or a.invalidated
        or a.action_type != "fax_inbound_image"
        or a.payload
        != {"contract_version": 1, "fax_inbound_image_id": i.id, "source_sha256": i.source_sha256}
        or a.payload_hash != payload_hash(a.payload)
        or a.payload_hash != i.payload_sha256
        or (a.policy_version, a.charter_version, a.config_version)
        != (p.policy_version, p.charter_version, p.config_version)
    ):
        fail("fax_inbound_approval_changed")
    g = grant_current(s, box, actor, i.grant_id, current, image=True)
    obs, scope, fax = source(s, box, actor, i.observation_id, i.source_sha256)
    if obs.grant_id != g.id or scope.selection != installation(g.installation).selection:
        fail("fax_inbound_source_changed")
    return i, t, a, g, scope, fax


def decide(
    s,
    box,
    actor,
    *,
    key,
    ticket_id,
    revision_id,
    expected_version,
    choice,
    reviewed_exact_fax,
    current,
):
    request = dict(
        ticket_id=ticket_id,
        revision_id=revision_id,
        expected_version=expected_version,
        choice=choice,
        reviewed_exact_fax=reviewed_exact_fax,
    )
    old, sha = previous(s, box, actor, "decide", key, request)
    if old:
        return dict(old.result)
    i, t, _, _, _, _ = image_current(s, box, actor, ticket_id, revision_id, current)
    if (
        t.state != "pending_approval"
        or t.version != expected_version
        or i.expires_at <= now(s)
        or choice not in {"approve", "reject"}
        or choice == "approve"
        and reviewed_exact_fax is not True
    ):
        fail("fax_inbound_approval_changed")
    d = Decision(
        id=str(uuid4()),
        box_id=box,
        ticket_id=t.id,
        action_revision_id=revision_id,
        actor_principal_id=actor,
        kind=choice,
    )
    s.add(d)
    t.state, t.version = ("approved" if choice == "approve" else "rejected"), t.version + 1
    if choice == "approve":
        s.add(
            Operation(
                id=i.operation_id,
                box_id=box,
                ticket_id=t.id,
                action_revision_id=revision_id,
                idempotency_key="fax-inbound:" + i.operation_id,
                adapter=ADAPTER,
                status="pending",
                attempt_count=0,
            )
        )
    c = record(
        s,
        box,
        actor,
        "decide",
        key,
        request,
        {
            "ticket_id": t.id,
            "revision_id": revision_id,
            "version": t.version,
            "state": t.state,
            "decision_id": d.id,
            "approval_sha256": sha if choice == "approve" else None,
        },
    )
    s.commit()
    return dict(c.result)


def claim(
    s, box, actor, *, key, ticket_id, revision_id, expected_version, approval_sha256, current
):
    request = dict(
        ticket_id=ticket_id,
        revision_id=revision_id,
        expected_version=expected_version,
        approval_sha256=approval_sha256,
    )
    old, _ = previous(s, box, actor, "acquire", key, request)
    if old:
        return resolve(s, box, actor, key=key, current=current), None
    from cosmas_os.application.fax_inbound_document import cipher

    cipher()  # Fail before the one-shot claim when protected custody is unavailable.
    i, t, _, g, scope, fax = image_current(s, box, actor, ticket_id, revision_id, current)
    op = s.scalar(select(Operation).where(Operation.id == i.operation_id).with_for_update())
    approved = s.scalar(
        select(FaxInboundCommand).where(
            FaxInboundCommand.box_id == box,
            FaxInboundCommand.owner_id == actor,
            FaxInboundCommand.kind == "decide",
            FaxInboundCommand.request_sha256 == approval_sha256,
        )
    )
    d = s.get(Decision, approved.result["decision_id"]) if approved else None
    stamp = now(s)
    if (
        t.state != "approved"
        or t.version != expected_version
        or op is None
        or op.adapter != ADAPTER
        or op.status != "pending"
        or op.attempt_count != 0
        or i.expires_at <= stamp
        or d is None
        or d.kind != "approve"
        or d.actor_principal_id != actor
        or d.ticket_id != t.id
        or d.action_revision_id != revision_id
        or approved.request.get("reviewed_exact_fax") is not True
    ):
        fail("fax_inbound_approval_changed")
    locator_sha = commitment({"locator": fax.locator})
    if s.scalar(
        select(FaxInboundAttempt.operation_id).where(
            FaxInboundAttempt.account_sha256 == g.account_sha256,
            FaxInboundAttempt.locator_sha256 == locator_sha,
        )
    ):
        fail("fax_inbound_already_attempted")
    token = secrets.token_hex(32)
    deadline = min(stamp + timedelta(seconds=45), i.expires_at)
    s.add(
        FaxInboundAttempt(
            operation_id=op.id,
            ticket_id=t.id,
            image_id=i.id,
            box_id=box,
            owner_id=actor,
            account_sha256=g.account_sha256,
            locator_sha256=locator_sha,
            token_sha256=commitment(token),
            approval_sha256=approval_sha256,
            created_at=stamp,
            deadline=deadline,
        )
    )
    op.status, op.attempt_count, op.started_at = "running", 1, stamp
    t.version += 1
    c = record(
        s,
        box,
        actor,
        "acquire",
        key,
        request,
        {
            "state": "outcome_unconfirmed",
            "operation_id": op.id,
            "ticket_id": t.id,
            "revision_id": revision_id,
            "version": t.version,
            "grant_id": g.id,
            "retry_allowed": False,
        },
    )
    invocation = (
        op.id,
        token,
        scope,
        fax,
        ImageApproval(scope.key(), fax.key(), UUID(actor), deadline),
    )
    s.commit()  # permanent one-shot fence before any credential/provider operation
    return dict(c.result), invocation


def authorize(s, box, actor, invocation, *, current):
    oid, token, scope, fax, approval = invocation
    owner(s, box, actor)
    attempt = s.get(FaxInboundAttempt, oid)
    if (
        attempt is None
        or attempt.box_id != box
        or attempt.owner_id != actor
        or attempt.token_sha256 != commitment(token)
        or attempt.deadline <= now(s)
        or s.get(FaxInboundOutcome, oid) is not None
    ):
        fail("fax_inbound_attempt_unavailable")
    i = s.get(FaxInboundImage, attempt.image_id)
    _, t, _, _, retained_scope, retained_fax = image_current(
        s, box, actor, i.ticket_id, i.revision_id, current
    )
    op = s.get(Operation, oid)
    if (
        t.state != "approved"
        or op.status != "running"
        or op.attempt_count != 1
        or scope != retained_scope
        or fax != retained_fax
    ):
        fail("fax_inbound_attempt_unavailable")
    approval.check(scope, fax, now(s))
    return True


def mark_dispatch(s, box, actor, invocation, *, current):
    authorize(s, box, actor, invocation, current=current)
    oid = invocation[0]
    if s.get(FaxInboundDispatch, oid):
        fail("fax_inbound_already_attempted")
    s.add(FaxInboundDispatch(operation_id=oid, box_id=box, owner_id=actor))
    op = s.get(Operation, oid)
    op.status, op.completed_at = "unknown", now(s)
    attempt = s.get(FaxInboundAttempt, oid)
    t = s.get(Ticket, attempt.ticket_id)
    t.state, t.version = "needs_verify", t.version + 1
    s.commit()  # Process loss after this point is already terminal, never running.
    return True


def settle(s, box, actor, invocation, document, *, current):
    # Retain a validated late reply privately, even after revocation. This does
    # not restore source access or approval; document() independently checks both.
    oid, token, scope, fax, approval = invocation
    attempt = s.get(FaxInboundAttempt, oid)
    if (
        attempt is None
        or (attempt.box_id, attempt.owner_id) != (box, actor)
        or attempt.token_sha256 != commitment(token)
    ):
        fail("fax_inbound_attempt_unavailable")
    if s.get(FaxInboundOutcome, oid):
        return
    i = s.get(FaxInboundImage, attempt.image_id)
    obs, retained_scope, retained_fax = source(s, box, actor, i.observation_id, i.source_sha256)
    if retained_scope != scope or retained_fax != fax:
        fail("fax_inbound_source_changed")
    if document is not None and (type(document) is not bytes or not 1 <= len(document) <= 1048576
                                 or not document.startswith(b"%PDF-")):
        fail("fax_inbound_document_invalid")
    sha = hashlib.sha256(document).hexdigest() if document is not None else None
    state = "acquired" if document is not None else "outcome_unconfirmed"
    from cosmas_os.application.fax_inbound_document import protect

    protected = protect(document, attempt, i, s.get(FaxInboundGrant, i.grant_id), fax.pages) if document is not None else {}
    s.add(
        FaxInboundOutcome(
            operation_id=oid,
            box_id=box,
            owner_id=actor,
            state=state,
            **protected,
        )
    )
    op = s.get(Operation, oid)
    op.status, op.completed_at, op.result_receipt_hash = (
        ("succeeded" if document is not None else "unknown"),
        now(s),
        sha,
    )
    t = s.get(Ticket, i.ticket_id)
    t.state, t.version = "needs_verify", t.version + 1
    s.commit()


def resolve(s, box, actor, *, key, current):
    owner(s, box, actor)
    c = s.scalar(
        select(FaxInboundCommand).where(
            FaxInboundCommand.box_id == box,
            FaxInboundCommand.owner_id == actor,
            FaxInboundCommand.idempotency_key == key,
        )
    )
    if c is None:
        return {"contract_version": 1, "state": "not_found", "idempotency_key": key}
    result = dict(c.result)
    gid = result.get("grant_id") or c.request.get("grant_id")
    if c.kind == "observe":
        grant_current(s, box, actor, gid, current)
        obs = s.get(FaxInboundObservation, c.id)
        if obs:
            result.update(state="observed", **public_snapshot(obs))
    elif c.kind == "acquire":
        available = True
        try:
            grant_current(s, box, actor, gid, current, image=True)
        except ws.WorkspaceError:
            available = False
        outcome = s.get(FaxInboundOutcome, result["operation_id"])
        if outcome:
            if available and outcome.state == "acquired":
                try:
                    document(s, box, actor, result["operation_id"], current=current)
                except ws.WorkspaceError:
                    available = False
            result.update(
                state=outcome.state,
                document_sha256=outcome.document_sha256 if available else None,
                pages=outcome.pages if available else None,
                source_withheld=not available,
            )
    result["public_request_sha256"] = commitment(c.public_request)
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = commitment(result)
    return result


def proposal(s, box, actor, ticket_id, revision_id, *, current):
    i, t, a, g, scope, fax = image_current(s, box, actor, ticket_id, revision_id, current)
    stamp = now(s)
    result = {
        "contract_version": 1,
        "scope": {"box_id": box, "owner_id": actor},
        "ticket_id": ticket_id,
        "revision_id": revision_id,
        "version": t.version,
        "state": t.state,
        "expires_at": i.expires_at.isoformat(),
        "expired": i.expires_at <= stamp,
        "label": g.label,
        "vendor": scope.selection.vendor,
        "source_sha256": fax.key(),
        "fax": {
            "received_at": fax.received_at.isoformat(),
            "pages": fax.pages,
            "viewed": fax.viewed,
            "sender_label": fax.sender_label or fax.sender_number or "Sender not provided",
            "sender_number": fax.sender_number,
            "sender_identity": "provider_reported_unverified",
            "image_available": fax.image_available,
        },
        "payload_sha256": a.payload_hash,
        "source_withheld": False,
    }
    result["receipt_sha256"] = commitment(result)
    return result


def document(s, box, actor, oid, *, current):
    owner(s, box, actor)
    attempt = s.scalar(
        select(FaxInboundAttempt).where(
            FaxInboundAttempt.operation_id == oid,
            FaxInboundAttempt.box_id == box,
            FaxInboundAttempt.owner_id == actor,
        )
    )
    if attempt is None:
        fail(status=404)
    i = s.get(FaxInboundImage, attempt.image_id)
    _, _, _, grant, _, _ = image_current(s, box, actor, i.ticket_id, i.revision_id, current)
    o = s.get(FaxInboundOutcome, oid)
    if (
        o is None
        or o.state != "acquired"
    ):
        fail("fax_inbound_document_unavailable", 404)
    from cosmas_os.application.fax_inbound_document import open_document

    return open_document(o, attempt, i, grant)
