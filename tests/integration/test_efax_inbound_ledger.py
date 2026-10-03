"""Synthetic real-PostgreSQL eFax inbox custody; no HTTP, accounts or patient data."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Literal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from cosmas_os.application import efax_inbound as ledger
from cosmas_os.application import services as svc
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.config import settings
from cosmas_os.efax_inbound_models import (
    EFaxInboundAcquisition,
    EFaxInboundGrant,
    EFaxInboundInvocation,
    EFaxInboundOutcome,
)
from cosmas_os.models import Decision, Operation, Principal, Ticket, WorkspaceNote
from cosmas_os.ports.efax_inbound import FaxMetadata, ImageReceipt, ListSnapshot
from cosmas_os.ports.vendor_connectors import ConnectionSelection, digest


@pytest.fixture
def inbound(session, seeded, monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "efax_inbound_enabled", True)
    # Deliberately independent of all outbound fax setup/IO flags.
    monkeypatch.setattr(settings, "vendor_work_enabled", False)
    monkeypatch.setattr(settings, "vendor_io_enabled", False)
    box, owner = seeded["box_id"], seeded["owner_id"]
    selection = ConnectionSelection(
        vendor="efax",
        connection_id=uuid4(),
        box_id=box,
        owner_id=owner,
        environment="production",
        remote_account_id="invented_efax_user",
        credential_ref=uuid4(),
        configuration_sha256="a" * 64,
    )
    installation = ledger.Installation(selection, "Invented eFax inbox", True, True)
    f = SimpleNamespace(
        s=session,
        box=box,
        owner=owner,
        installation=installation,
        active=True,
        fax_id=uuid4(),
        calls=0,
    )

    def current(s, retained):
        assert s is f.s
        expected = (
            retained.selection
            if isinstance(retained, ledger.Installation)
            else ConnectionSelection.model_validate(retained.selection)
        )
        return f.active and expected == f.installation.selection

    f.current = current
    return f


def granted(f, *, key="grant-key-1", image=True):
    return ledger.grant(
        f.s,
        f.box,
        f.owner,
        f.installation,
        key=key,
        reviewed_account=True,
        reviewed_mark_read=image,
        image_enabled=image,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        current=f.current,
    )


def observed(f, grant=None, *, key="observe-key-1"):
    g = grant or granted(f)
    now = datetime.now(UTC)
    reply, intent = ledger.reserve_observation(
        f.s,
        f.box,
        f.owner,
        g["grant_id"],
        key=key,
        starts_at=now - timedelta(days=7),
        ends_at=now,
        current=f.current,
    )
    assert not f.s.in_transaction()
    assert intent is not None
    item = FaxMetadata(
        fax_id=f.fax_id,
        size=512,
        duration=20,
        pages=1,
        image_downloaded=False,
        completed_timestamp=now - timedelta(minutes=1),
        destination_fax_number="15551234567",
        originating_fax_number="15557654321",
        originating_fax_tsid="Invented café source",
        fax_status=None,
    )
    values: dict[str, Any] = dict(
        request=intent.request,
        first_record=0,
        last_record=0,
        items=(item,),
        observed_at=now,
        raw_sha256="b" * 64,
    )
    provisional = ListSnapshot.model_construct(**values)
    snapshot = ListSnapshot.model_validate({**values, "source_sha256": provisional.commitment()})
    saved = ledger.settle_observation(f.s, intent, snapshot, current=f.current)
    return g, saved, snapshot, intent


def proposed(f, observation=None, *, key="propose-key-1"):
    g, saved, snapshot, _ = observation or observed(f)
    item = snapshot.items[0]
    result = ledger.propose_image(
        f.s,
        f.box,
        f.owner,
        key=key,
        grant_id=g["grant_id"],
        observation_id=saved["observation_id"],
        observation_sha256=snapshot.source_sha256,
        fax_id=str(item.fax_id),
        fax_sha256=digest("cosmas-efax-inbound-fax.v1", item.model_dump(mode="json")),
        current=f.current,
    )
    return result


def approved(f, proposal=None, *, key="decide-key-1"):
    p = proposal or proposed(f)
    result = ledger.decide_image(
        f.s,
        f.box,
        f.owner,
        key=key,
        ticket_id=p["ticket_id"],
        revision_id=p["revision_id"],
        expected_version=p["version"],
        choice="approve",
        reviewed_mark_read=True,
        current=f.current,
    )
    return p, result


def claimed(f, approval=None, *, key="acquire-key-1"):
    p, a = approval or approved(f)
    reply, invocation = ledger.claim_image(
        f.s,
        f.box,
        f.owner,
        key=key,
        ticket_id=p["ticket_id"],
        revision_id=p["revision_id"],
        expected_version=a["version"],
        approval_sha256=a["approval_sha256"],
        current=f.current,
    )
    assert not f.s.in_transaction()
    assert invocation is not None
    return reply, invocation


def received(
    invocation,
    *,
    state: Literal["not_attempted", "outcome_unconfirmed", "acquired", "needs_human"] = "acquired",
):
    now = datetime.now(UTC)
    if state != "acquired":
        return ImageReceipt(
            operation_id=invocation.command.operation_id,
            command_sha256=invocation.command.commitment(),
            selection_sha256=invocation.command.selection.commitment(),
            fax_id=invocation.command.fax_id,
            state=state,
            attempted=state != "not_attempted",
            provider_read_state="unchanged_by_this_attempt"
            if state == "not_attempted"
            else "may_have_changed",
            content_available=False,
            observed_at=now,
        ), None
    # Ledger tests exercise byte custody, not the separately qualified PDF parser.
    pdf = b"%PDF-1.4\nInvented ledger byte-custody fixture\n%%EOF\n"
    dh = hashlib.sha256(pdf).hexdigest()
    source = digest(
        "cosmas-efax-inbound-image.v1",
        {
            "command_sha256": invocation.command.commitment(),
            "list_source_sha256": invocation.snapshot.source_sha256,
            "fax_id": str(invocation.command.fax_id),
            "response_sha256": "c" * 64,
            "document_sha256": dh,
            "byte_length": len(pdf),
            "pages": 1,
        },
    )
    return ImageReceipt(
        operation_id=invocation.command.operation_id,
        command_sha256=invocation.command.commitment(),
        selection_sha256=invocation.command.selection.commitment(),
        fax_id=invocation.command.fax_id,
        state="acquired",
        attempted=True,
        provider_read_state="endpoint_reported_download",
        content_available=True,
        observed_at=now,
        response_sha256="c" * 64,
        document_sha256=dh,
        source_sha256=source,
        byte_length=len(pdf),
        pages=1,
    ), pdf


def test_independent_grant_actual_f8_private_pdf_commit_and_recovery(inbound):
    f = inbound
    note_count = f.s.scalar(select(func.count()).select_from(WorkspaceNote))
    reply, invocation = claimed(f)
    assert reply["scope"] == {"box_id": f.box, "owner_id": f.owner}
    assert reply["kind"] == "acquire" and reply["idempotency_key"] == "acquire-key-1"
    assert ledger.mark_invocation(f.s, invocation, current=f.current) is True
    assert not f.s.in_transaction()
    # Simulated provider boundary occurs only after durable pre-GET marker.
    marker = f.s.get(EFaxInboundInvocation, invocation.operation_id)
    assert marker is not None
    f.s.commit()
    receipt, pdf = received(invocation)
    assert pdf is not None
    saved = ledger.settle_image(f.s, invocation, receipt, pdf)
    assert saved["state"] == "acquired"
    assert ledger.document(f.s, f.box, f.owner, invocation.operation_id, current=f.current) == pdf
    reopened = ledger.resolve_image(f.s, f.box, f.owner, key="acquire-key-1", current=f.current)
    assert reopened["content_available"] is True
    assert reopened["document"] == {
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "byte_length": len(pdf),
        "pages": 1,
    }
    assert reopened["request_sha256"] == reply["request_sha256"]
    t = f.s.get(Ticket, reply["ticket_id"])
    op = f.s.get(Operation, invocation.operation_id)
    assert t is not None and op is not None
    assert t.patient_link_id is None and t.appointment_id is None
    assert op.adapter == ledger.ADAPTER and op.attempt_count == 1 and op.status == "succeeded"
    assert op.result_receipt_hash == saved["receipt_sha256"]
    assert f.s.scalar(select(func.count()).select_from(WorkspaceNote)) == note_count
    assert (
        f.s.scalar(select(func.count()).select_from(Decision).where(Decision.ticket_id == t.id))
        == 1
    )


def test_metadata_only_grant_does_not_permit_image_approval(inbound):
    f = inbound
    observation = observed(f, granted(f, image=False))
    with pytest.raises(WorkspaceError, match="efax_inbound_grant_changed"):
        proposed(f, observation)
    assert (
        f.s.scalar(
            select(func.count()).select_from(Operation).where(
                Operation.adapter == ledger.ADAPTER, Operation.box_id == f.box)
        )
        == 0
    )


@pytest.mark.parametrize("boundary", ["grant", "observe", "propose", "claim", "mark", "document"])
def test_runtime_authority_refuses_at_each_active_boundary(inbound, boundary):
    f = inbound
    g = granted(f) if boundary == "observe" else None
    obs = observed(f) if boundary == "propose" else None
    approval = approved(f) if boundary == "claim" else None
    invocation = claimed(f)[1] if boundary in {"mark", "document"} else None
    if boundary == "document":
        assert invocation is not None
        ledger.mark_invocation(f.s, invocation, current=f.current)
        receipt, pdf = received(invocation)
        ledger.settle_image(f.s, invocation, receipt, pdf)
    f.active = False
    with pytest.raises(WorkspaceError, match="efax_inbound_grant_unavailable"):
        if boundary == "grant":
            granted(f)
        elif boundary == "observe":
            observed(f, g)
        elif boundary == "propose":
            proposed(f, obs)
        elif boundary == "claim":
            claimed(f, approval)
        elif boundary == "mark":
            assert invocation is not None
            ledger.mark_invocation(f.s, invocation, current=f.current)
        else:
            assert invocation is not None
            ledger.document(f.s, f.box, f.owner, invocation.operation_id, current=f.current)


def test_committed_invocation_cannot_settle_as_not_attempted(inbound):
    f = inbound
    _, inv = claimed(f)
    ledger.mark_invocation(f.s, inv, current=f.current)
    receipt, _ = received(inv, state="not_attempted")
    with pytest.raises(WorkspaceError, match="efax_inbound_result_invalid"):
        ledger.settle_image(f.s, inv, receipt)
    f.s.rollback()
    recovered = ledger.resolve_image(f.s, f.box, f.owner, key="acquire-key-1", current=f.current)
    assert recovered["state"] == "outcome_unconfirmed"
    assert recovered["retry_allowed"] is False
    assert f.s.get(EFaxInboundOutcome, inv.operation_id) is None


def test_public_proposal_and_status_expiry_are_seconds_z_private_command_unchanged(inbound):
    f = inbound
    p = proposed(f)
    before = f.s.scalar(
        select(ledger.EFaxInboundImageRevision).where(
            ledger.EFaxInboundImageRevision.action_revision_id == p["revision_id"],
        )
    )
    assert before is not None
    private_command = dict(before.command)
    detail = ledger.proposal(f.s, f.box, f.owner, p["ticket_id"], current=f.current)
    expected = ledger.canonical_public_timestamp(private_command["expires_at"])
    assert detail["expires_at"] == p["expires_at"] == expected
    assert expected.endswith("Z") and "." not in expected
    assert before.command == private_command
    assert detail["command_sha256"] == before.command_sha256
    status = ledger.status(f.s, f.box, f.owner, current=f.current)
    assert status["grants"][0]["expires_at"].endswith("Z")
    assert "." not in status["grants"][0]["expires_at"]


@pytest.mark.parametrize("private_kind", ["grant", "observe"])
def test_canonical_public_timestamp_commitment_equal_offsets_preserves_private_record(private_kind):
    scope = {"box_id": str(uuid4()), "owner_id": str(uuid4())}
    common = (
        {
            "installation_id": str(uuid4()),
            "reviewed_account": True,
            "reviewed_mark_read": True,
            "image_enabled": True,
        }
        if private_kind == "grant"
        else {
            "grant_id": str(uuid4()),
            "limit": 25,
            "offset": 0,
        }
    )
    fields = ["expires_at"] if private_kind == "grant" else ["starts_at", "ends_at"]
    z = {**common, **{name: "2026-10-02T22:00:00Z" for name in fields}}
    offset = {**common, **{name: "2026-10-02T18:00:00-04:00" for name in fields}}
    # Private grant adds installation/label custody, which does not enter the public body.
    if private_kind == "grant":
        for value in (z, offset):
            value.update(
                installation_sha256="a" * 64, label="Invented account", metadata_enabled=True
            )

    def receipt(request):
        return SimpleNamespace(
            box_id=scope["box_id"],
            owner_id=scope["owner_id"],
            kind=private_kind,
            idempotency_key="canonical-key-1",
            id=str(uuid4()),
            request=request,
            request_sha256=ledger._request_sha(
                scope["box_id"], scope["owner_id"], private_kind, request
            ),
            result={
                "state": "granted" if private_kind == "grant" else "unconfirmed",
                "expires_at": "2026-10-02T18:00:00-04:00",
            }
            if private_kind == "grant"
            else {"state": "unconfirmed"},
        )

    first, second = receipt(z), receipt(offset)
    before_z, before_offset = dict(z), dict(offset)
    first_public, second_public = ledger._receipt(first), ledger._receipt(second)
    assert first_public["public_request_sha256"] == second_public["public_request_sha256"]
    assert first.request_sha256 != second.request_sha256
    assert first.request == before_z and second.request == before_offset
    assert second.result == (
        {"state": "granted", "expires_at": "2026-10-02T18:00:00-04:00"}
        if private_kind == "grant"
        else {"state": "unconfirmed"}
    )
    if private_kind == "grant":
        assert first_public["expires_at"] == second_public["expires_at"] == "2026-10-02T22:00:00Z"


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-02T22:00:00Z",
        "2026-10-02T18:00:00-04:00",
        "2026-10-03T03:45:00+05:45",
        datetime(2026, 10, 2, 22, 0, 0, tzinfo=UTC),
    ],
)
def test_canonical_public_timestamp_seconds_literal_z(value):
    assert ledger.canonical_public_timestamp(value) == "2026-10-02T22:00:00Z"


def test_canonical_public_timestamp_historical_fraction_does_not_extend_expiry():
    assert (
        ledger.canonical_public_timestamp("2026-10-02T18:00:00.999999-04:00")
        == "2026-10-02T22:00:00Z"
    )
    with pytest.raises(WorkspaceError, match="efax_inbound_request_invalid"):
        ledger.canonical_public_timestamp(datetime(2026, 10, 2, 22))


@pytest.mark.parametrize(
    "stage", ["not_found", "claimed", "invocation_started", "unconfirmed", "needs_human"]
)
def test_resolve_image_without_document_has_explicit_closed_defaults(inbound, stage):
    f = inbound
    if stage != "not_found":
        _, inv = claimed(f)
        if stage != "claimed":
            ledger.mark_invocation(f.s, inv, current=f.current)
        if stage in {"unconfirmed", "needs_human"}:
            receipt, _ = received(
                inv, state="outcome_unconfirmed" if stage == "unconfirmed" else "needs_human"
            )
            ledger.settle_image(f.s, inv, receipt)
    result = ledger.resolve_image(
        f.s,
        f.box,
        f.owner,
        key="missing-key-1" if stage == "not_found" else "acquire-key-1",
        current=f.current,
    )
    assert result["content_available"] is False and result["source_withheld"] is False
    assert result["document"] is None and result["retry_allowed"] is False
    if stage != "not_found":
        f.active = False
        masked = ledger.resolve_image(f.s, f.box, f.owner, key="acquire-key-1", current=f.current)
        assert masked["source_withheld"] is True and masked["content_available"] is False
        assert masked["document"] is None


def test_claim_before_mark_may_prove_not_dispatched_but_remains_one_shot(inbound):
    f = inbound
    _, inv = claimed(f)
    receipt, _ = received(inv, state="not_attempted")
    ledger.settle_image(f.s, inv, receipt)
    recovered = ledger.resolve_image(f.s, f.box, f.owner, key="acquire-key-1", current=f.current)
    assert recovered["state"] == "not_attempted" and recovered["retry_allowed"] is False
    with pytest.raises(WorkspaceError, match="efax_inbound_claim_fenced"):
        ledger.mark_invocation(f.s, inv, current=f.current)


def test_late_private_pdf_after_revocation_is_retained_without_disclosure(inbound):
    f = inbound
    reply, inv = claimed(f)
    ledger.mark_invocation(f.s, inv, current=f.current)
    ledger.revoke_grant(f.s, f.box, f.owner, inv.grant_id, key="revoke-key-1")
    r, pdf = received(inv)
    saved = ledger.settle_image(f.s, inv, r, pdf)
    assert saved["state"] == "acquired" and "document" not in saved
    recovered = ledger.resolve_image(f.s, f.box, f.owner, key="acquire-key-1", current=f.current)
    assert recovered["source_withheld"] is True and recovered["content_available"] is False
    assert recovered["document"] is None
    assert recovered["request_sha256"] == reply["request_sha256"]
    with pytest.raises(WorkspaceError, match="efax_inbound_grant_unavailable"):
        ledger.document(f.s, f.box, f.owner, inv.operation_id, current=f.current)


def test_recovery_preserves_approval_hash_and_hides_selected_metadata_when_revoked(inbound):
    f = inbound
    p, a = approved(f)
    detail = ledger.proposal(f.s, f.box, f.owner, p["ticket_id"], current=f.current)
    assert detail["fax"]["fax_id"] == str(f.fax_id)
    assert detail["source_withheld"] is False and "selection" not in detail
    grant = f.s.scalar(select(EFaxInboundGrant).where(EFaxInboundGrant.owner_id == f.owner))
    assert grant is not None
    ledger.revoke_grant(f.s, f.box, f.owner, grant.id, key="revoke-key-1")
    historical = ledger.recover(f.s, f.box, f.owner, key="decide-key-1")
    assert historical["historical"] is True
    assert historical["approval_sha256"] == a["approval_sha256"]
    detail = ledger.proposal(f.s, f.box, f.owner, p["ticket_id"], current=f.current)
    assert detail["source_withheld"] is True and "fax" not in detail


@pytest.mark.parametrize("state", ["outcome_unconfirmed", "needs_human"])
def test_uncertain_and_unsupported_pdf_stays_private_no_retry(inbound, state):
    f = inbound
    _, inv = claimed(f)
    ledger.mark_invocation(f.s, inv, current=f.current)
    receipt, _ = received(inv, state=state)
    ledger.settle_image(f.s, inv, receipt)
    replay, duplicate = ledger.claim_image(
        f.s,
        f.box,
        f.owner,
        key="acquire-key-1",
        ticket_id=f.s.get(Operation, inv.operation_id).ticket_id,
        revision_id=f.s.get(Operation, inv.operation_id).action_revision_id,
        expected_version=2,
        approval_sha256=f.s.get(EFaxInboundAcquisition, inv.operation_id).approval_sha256,
        current=f.current,
    )
    assert duplicate is None and replay["state"] == state and not replay["retry_allowed"]


def test_fresh_key_and_new_connection_cannot_erase_remote_fax_resource(inbound):
    f = inbound
    _, inv = claimed(f)
    ledger.mark_invocation(f.s, inv, current=f.current)
    r, _ = received(inv, state="outcome_unconfirmed")
    ledger.settle_image(f.s, inv, r)
    # New installed connection/configuration/credential, same remote user and fax.
    old = f.installation.selection
    f.installation = ledger.Installation(
        old.model_copy(
            update={
                "connection_id": uuid4(),
                "credential_ref": uuid4(),
                "configuration_sha256": "d" * 64,
            }
        ),
        "Invented eFax inbox replacement",
        True,
        True,
    )
    obs = observed(f, granted(f, key="grant-key-2"), key="observe-key-2")
    p = proposed(f, obs, key="propose-key-2")
    a = approved(f, p, key="decide-key-2")
    with pytest.raises(WorkspaceError, match="efax_inbound_acquisition_fenced"):
        claimed(f, a, key="acquire-key-2")
    assert f.s.scalar(select(func.count()).select_from(EFaxInboundAcquisition).where(
        EFaxInboundAcquisition.box_id == f.box)) == 1


def test_forged_snapshot_token_and_result_hash_refuse(inbound):
    f = inbound
    _, inv = claimed(f)
    bad = replace(inv, token=str(uuid4()))
    with pytest.raises(WorkspaceError, match="efax_inbound_claim_fenced"):
        ledger.mark_invocation(f.s, bad, current=f.current)
    fake = inv.snapshot.model_copy(update={"items": ()})
    with pytest.raises(WorkspaceError, match="efax_inbound_claim_fenced"):
        ledger.mark_invocation(f.s, replace(inv, snapshot=fake), current=f.current)
    ledger.mark_invocation(f.s, inv, current=f.current)
    r, pdf = received(inv)
    assert pdf is not None
    with pytest.raises(WorkspaceError, match="efax_inbound_result_invalid"):
        ledger.settle_image(f.s, inv, r, pdf + b"tamper")
    assert f.s.get(EFaxInboundOutcome, inv.operation_id) is None


def test_image_result_is_immutable_and_same_exact_result_replays(inbound):
    f = inbound
    _, inv = claimed(f)
    ledger.mark_invocation(f.s, inv, current=f.current)
    r, pdf = received(inv)
    first = ledger.settle_image(f.s, inv, r, pdf)
    assert ledger.settle_image(f.s, inv, r, pdf) == first
    alternative, _ = received(inv, state="needs_human")
    with pytest.raises(WorkspaceError, match="efax_inbound_result_conflict"):
        ledger.settle_image(f.s, inv, alternative)


def test_agent_and_foreign_owner_cannot_acquire_or_read(inbound):
    f = inbound
    _, inv = claimed(f)
    agent = f.s.scalar(
        select(Principal).where(Principal.box_id == f.box, Principal.principal_type == "agent")
    )
    assert agent is not None
    with pytest.raises(WorkspaceError, match="workspace_access_denied"):
        ledger.document(f.s, f.box, agent.id, inv.operation_id, current=f.current)
    other = Principal(
        box_id=f.box, principal_type="human", display_name="Invented other", is_owner=True
    )
    f.s.add(other)
    f.s.commit()
    with pytest.raises(WorkspaceError, match="efax_inbound_unavailable"):
        ledger.document(f.s, f.box, other.id, inv.operation_id, current=f.current)


def test_revocation_terminal_and_history_rows_immutable_in_database(inbound):
    f = inbound
    g, _, _, _ = observed(f)
    ledger.revoke_grant(f.s, f.box, f.owner, g["grant_id"], key="revoke-key-1")
    with pytest.raises(DBAPIError):
        with f.s.begin_nested():
            f.s.execute(
                text("UPDATE efax_inbound_grants SET revoked_at=NULL WHERE id=:id"),
                {"id": g["grant_id"]},
            )
    with pytest.raises(DBAPIError):
        with f.s.begin_nested():
            f.s.execute(
                text("UPDATE efax_inbound_observations SET payload='{}'::jsonb WHERE owner_id=:id"),
                {"id": f.owner},
            )


def test_direct_pdf_hash_corruption_is_rejected_by_database(inbound):
    f = inbound
    _, inv = claimed(f)
    ledger.mark_invocation(f.s, inv, current=f.current)
    r, pdf = received(inv)
    ledger.settle_image(f.s, inv, r, pdf)
    with pytest.raises(DBAPIError):
        with f.s.begin_nested():
            f.s.execute(
                text("UPDATE efax_inbound_outcomes SET document=:bad WHERE operation_id=:id"),
                {"bad": b"%PDF-tamper", "id": inv.operation_id},
            )


def test_saved_observation_replay_no_new_request_or_selection_leak(inbound):
    f = inbound
    _, saved, snapshot, intent = observed(f)
    restored = ledger.resolve_observation(
        f.s, f.box, f.owner, key="observe-key-1", current=f.current
    )
    assert saved["scope"] == restored["scope"] == {"box_id": f.box, "owner_id": f.owner}
    assert saved["kind"] == restored["kind"] == "observe"
    assert saved["idempotency_key"] == restored["idempotency_key"] == "observe-key-1"
    assert saved["public_request_sha256"] == restored["public_request_sha256"]
    assert restored["source_sha256"] == snapshot.source_sha256
    assert restored["snapshot"]["request"] == {
        k: (
            ledger.canonical_public_timestamp(intent.request.model_dump(mode="json")[k])
            if k in ("starts_at", "ends_at")
            else intent.request.model_dump(mode="json")[k]
        )
        for k in ("request_id", "starts_at", "ends_at", "limit", "offset")
    }
    assert "credential_ref" not in str(restored) and "remote_account_id" not in str(restored)
    f.active = False
    hidden = ledger.resolve_observation(f.s, f.box, f.owner, key="observe-key-1", current=f.current)
    assert hidden["source_withheld"] is True and "snapshot" not in hidden


def test_restarted_session_recovers_committed_uncertainty_and_no_claim_token(engine, monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "efax_inbound_enabled", True)
    with Session(engine) as s:
        seeded = svc.provision_box(svc.Container(s), "Invented restart inbox")
        selection = ConnectionSelection(
            vendor="efax",
            connection_id=uuid4(),
            box_id=seeded["box_id"],
            owner_id=seeded["owner_id"],
            environment="production",
            remote_account_id="invented_" + uuid4().hex,
            credential_ref=uuid4(),
            configuration_sha256="a" * 64,
        )
        f = SimpleNamespace(
            s=s,
            box=seeded["box_id"],
            owner=seeded["owner_id"],
            installation=ledger.Installation(selection, "Invented restart eFax", True, True),
            fax_id=uuid4(),
        )
        f.current = lambda current_s, _: current_s is f.s
        reply, inv = claimed(f)
        ledger.mark_invocation(s, inv, current=f.current)
        operation_id = inv.operation_id
    with Session(engine) as fresh:
        state = ledger.resolve_image(
            fresh, f.box, f.owner, key="acquire-key-1", current=lambda *_: True
        )
        assert state["state"] == "outcome_unconfirmed" and state["retry_allowed"] is False
        assert state["request_sha256"] == reply["request_sha256"]
        assert "token" not in str(state)
        assert fresh.get(EFaxInboundInvocation, operation_id) is not None
        operation = fresh.get(Operation, operation_id)
        assert operation is not None and operation.attempt_count == 1


def test_two_sessions_concurrent_same_remote_fax_only_one_claim(engine, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "efax_inbound_enabled", True)
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented concurrent eFax")
        selection = ConnectionSelection(
            vendor="efax",
            connection_id=uuid4(),
            box_id=seed["box_id"],
            owner_id=seed["owner_id"],
            environment="production",
            remote_account_id="invented_" + uuid4().hex,
            credential_ref=uuid4(),
            configuration_sha256="a" * 64,
        )
        f = SimpleNamespace(
            s=s,
            box=seed["box_id"],
            owner=seed["owner_id"],
            fax_id=uuid4(),
            installation=ledger.Installation(selection, "Invented concurrent inbox", True, True),
        )
        f.current = lambda *_: True
        obs = observed(f)
        first = approved(f, proposed(f, obs, key="propose-key-1"), key="decide-key-1")
        second = approved(f, proposed(f, obs, key="propose-key-2"), key="decide-key-2")
    barrier = Barrier(2)

    def compete(index):
        p, a = (first, second)[index]
        with Session(engine) as worker:
            barrier.wait(timeout=5)
            try:
                result, inv = ledger.claim_image(
                    worker,
                    f.box,
                    f.owner,
                    key=f"acquire-key-{index + 1}",
                    ticket_id=p["ticket_id"],
                    revision_id=p["revision_id"],
                    expected_version=a["version"],
                    approval_sha256=a["approval_sha256"],
                    current=lambda *_: True,
                )
                assert inv is not None and not worker.in_transaction()
                return result["operation_id"]
            except WorkspaceError as exc:
                assert exc.code == "efax_inbound_acquisition_fenced"
                worker.rollback()
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, (0, 1)))
    assert sum(item is not None for item in results) == 1
    with Session(engine) as verify:
        assert (
            verify.scalar(
                select(func.count())
                .select_from(EFaxInboundAcquisition)
                .where(
                    EFaxInboundAcquisition.box_id == f.box,
                )
            )
            == 1
        )
        assert (
            verify.scalar(
                select(func.count())
                .select_from(EFaxInboundInvocation)
                .where(
                    EFaxInboundInvocation.box_id == f.box,
                )
            )
            == 0
        )


def test_direct_invocation_without_operation_unknown_cannot_commit(inbound):
    f = inbound
    _, inv = claimed(f)
    with pytest.raises(DBAPIError):
        with f.s.begin_nested():
            f.s.execute(
                text(
                    "INSERT INTO efax_inbound_invocations(operation_id,box_id,owner_id,started_at) "
                    "VALUES(:op,:box,:owner,clock_timestamp())"
                ),
                {"op": inv.operation_id, "box": f.box, "owner": f.owner},
            )
            f.s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert f.s.get(EFaxInboundInvocation, inv.operation_id) is None
    op = f.s.get(Operation, inv.operation_id)
    assert op is not None and op.status == "running"


def test_direct_outcome_without_core_operation_receipt_cannot_commit(inbound):
    f = inbound
    _, inv = claimed(f)
    ledger.mark_invocation(f.s, inv, current=f.current)
    receipt, _ = received(inv, state="outcome_unconfirmed")
    payload = receipt.model_dump(mode="json")
    with pytest.raises(DBAPIError):
        with f.s.begin_nested():
            f.s.add(
                EFaxInboundOutcome(
                    operation_id=inv.operation_id,
                    box_id=f.box,
                    owner_id=f.owner,
                    state=receipt.state,
                    receipt=payload,
                    receipt_sha256=digest("cosmas-efax-inbound-receipt.v1", payload),
                )
            )
            f.s.flush()
            f.s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert f.s.get(EFaxInboundOutcome, inv.operation_id) is None
    op = f.s.get(Operation, inv.operation_id)
    assert op is not None and op.status == "unknown" and op.result_receipt_hash is None


def test_public_grant_commitment_exact_original_body_survives_recovery(inbound):
    f = inbound
    expiry = (datetime.now(UTC) + timedelta(days=1)).astimezone(UTC)
    body = {
        "installation_id": str(f.installation.selection.connection_id),
        "reviewed_account": True,
        "reviewed_mark_read": True,
        "image_enabled": True,
        "expires_at": ledger.canonical_public_timestamp(expiry),
        "idempotency_key": "grant-exact-1",
    }
    result = ledger.grant(
        f.s,
        f.box,
        f.owner,
        f.installation,
        key=body["idempotency_key"],
        reviewed_account=True,
        reviewed_mark_read=True,
        image_enabled=True,
        expires_at=expiry,
        current=f.current,
    )
    expected = digest(
        "cosmas-efax-inbound-api-command.v1",
        {
            "scope": {"box_id": f.box, "owner_id": f.owner},
            "kind": "grant",
            "request": body,
        },
    )
    assert result["public_request_sha256"] == expected
    assert result["request_sha256"] != expected
    restored = ledger.recover(f.s, f.box, f.owner, key=body["idempotency_key"])
    assert restored["public_request_sha256"] == expected
    assert "installation_sha256" not in restored and "selection" not in restored
    changed = {**body, "idempotency_key": "grant-exact-2"}
    assert expected != digest(
        "cosmas-efax-inbound-api-command.v1",
        {
            "scope": {"box_id": f.box, "owner_id": f.owner},
            "kind": "grant",
            "request": changed,
        },
    )


@pytest.mark.parametrize("prefix", ["", "+"])
def test_inbound_metadata_phone_prefix_is_optional_literal_plus(inbound, prefix):
    f = inbound
    g = granted(f)
    now = datetime.now(UTC)
    _, intent = ledger.reserve_observation(
        f.s,
        f.box,
        f.owner,
        g["grant_id"],
        key="observe-phone-1",
        starts_at=now - timedelta(days=7),
        ends_at=now,
        current=f.current,
    )
    assert intent is not None
    item = FaxMetadata(
        fax_id=f.fax_id,
        size=512,
        duration=20,
        pages=1,
        image_downloaded=False,
        completed_timestamp=now - timedelta(minutes=1),
        destination_fax_number=prefix + "15551234567",
        originating_fax_number=prefix + "15557654321",
        originating_fax_tsid="Invented fax",
        fax_status=None,
    )
    values: dict[str, Any] = {
        "request": intent.request,
        "first_record": 0,
        "last_record": 0,
        "items": (item,),
        "observed_at": now,
        "raw_sha256": "b" * 64,
    }
    provisional = ListSnapshot.model_construct(**values)
    snapshot = ListSnapshot.model_validate({**values, "source_sha256": provisional.commitment()})
    saved = ledger.settle_observation(f.s, intent, snapshot, current=f.current)
    assert saved["state"] == "observed"
    assert saved["snapshot"]["items"][0]["destination_fax_number"] == prefix + "15551234567"


def test_direct_acquired_pdf_cannot_have_null_byte_commitments(inbound):
    f = inbound
    _, inv = claimed(f)
    ledger.mark_invocation(f.s, inv, current=f.current)
    receipt, pdf = received(inv)
    assert pdf is not None
    payload = receipt.model_dump(mode="json")
    payload.update(document_sha256=None, byte_length=None, pages=None)
    with pytest.raises(DBAPIError):
        with f.s.begin_nested():
            f.s.add(
                EFaxInboundOutcome(
                    operation_id=inv.operation_id,
                    box_id=f.box,
                    owner_id=f.owner,
                    state="acquired",
                    receipt=payload,
                    receipt_sha256=digest("cosmas-efax-inbound-receipt.v1", payload),
                    document=pdf,
                    document_sha256=None,
                    byte_length=None,
                    pages=None,
                )
            )
            f.s.flush()
    assert f.s.get(EFaxInboundOutcome, inv.operation_id) is None
