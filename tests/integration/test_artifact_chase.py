from __future__ import annotations

import pytest
from sqlalchemy import select

from cosmas_os.application import services as svc
from cosmas_os.application.seed import SYNTH_CSV
from cosmas_os.domain.enums import CapabilityKey, DecisionKind, OperationStatus, PrincipalType
from cosmas_os.domain.rules import AuthorizationError, DomainError, PolicyDenied
from cosmas_os.models import Operation, Principal


def test_provision_and_agents(seeded):
    assert seeded["owner_id"]
    assert set(seeded["agents"]) == {"scribe", "chief", "chaser"}


def test_agent_self_approve_rejected(container, seeded):
    chaser = seeded["agents"]["chaser"]
    appts = svc.import_schedule(container, seeded["box_id"], SYNTH_CSV)
    link = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    ticket = svc.detect_and_open_chase(
        container, seeded["box_id"], chaser, appts[0], link.id
    )
    with pytest.raises(AuthorizationError):
        svc.decide(container, ticket.id, chaser, DecisionKind.APPROVE)


def test_unconfirmed_patient_link_blocks(container, seeded):
    chaser = seeded["agents"]["chaser"]
    appts = svc.import_schedule(container, seeded["box_id"], SYNTH_CSV)
    from cosmas_os.models import PatientLink

    link = PatientLink(
        box_id=seeded["box_id"],
        source_pair_key="csv:unconfirmed",
        label="Unconfirmed",
        state="unconfirmed",
    )
    container.session.add(link)
    container.session.commit()
    with pytest.raises(DomainError, match="unconfirmed"):
        svc.detect_and_open_chase(container, seeded["box_id"], chaser, appts[0], link.id)


def test_patient_link_reuse_without_reclick(container, seeded):
    link1 = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    link2 = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    assert link1.id == link2.id


def test_edit_invalidates_and_approve_executes_once(container, seeded):
    chaser = seeded["agents"]["chaser"]
    appts = svc.import_schedule(container, seeded["box_id"], SYNTH_CSV)
    link = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    ticket = svc.detect_and_open_chase(container, seeded["box_id"], chaser, appts[0], link.id)
    old_rev = ticket.current_revision_id
    rev = svc.edit_revision(container, ticket.id, seeded["owner_id"], "Updated neutral notice.")
    assert rev.id != old_rev
    d1 = svc.decide(container, ticket.id, seeded["owner_id"], DecisionKind.APPROVE)
    d2 = svc.decide(container, ticket.id, seeded["owner_id"], DecisionKind.APPROVE)
    assert d1["operation_id"] == d2["operation_id"]
    assert container.notify.attempts.get(d1["operation_id"], 0) == 1
    ops = container.session.scalars(
        select(Operation).where(Operation.ticket_id == ticket.id)
    ).all()
    assert len(ops) == 1
    assert ops[0].status == OperationStatus.SUCCEEDED.value


def test_worker_retry_reuses_operation(container, seeded):
    chaser = seeded["agents"]["chaser"]
    appts = svc.import_schedule(container, seeded["box_id"], SYNTH_CSV)
    link = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    ticket = svc.detect_and_open_chase(container, seeded["box_id"], chaser, appts[0], link.id)
    d = svc.decide(container, ticket.id, seeded["owner_id"], DecisionKind.APPROVE)
    op_id = d["operation_id"]
    # Retry execute — should no-op success
    op = svc.execute_operation(container, op_id)
    assert op.status == OperationStatus.SUCCEEDED.value
    assert container.notify.attempts[op_id] == 1


def test_unknown_reconcile_not_blind_retry(container, seeded, notify):
    chaser = seeded["agents"]["chaser"]
    appts = svc.import_schedule(container, seeded["box_id"], SYNTH_CSV)
    link = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    ticket = svc.detect_and_open_chase(container, seeded["box_id"], chaser, appts[0], link.id)
    from cosmas_os.config import settings
    from cosmas_os.domain.hashing import payload_hash
    from cosmas_os.models import ActionRevision, Operation, Ticket

    settings.sync_worker = False
    # Manually approve + create operation without executing
    ticket_row = container.session.get(Ticket, ticket.id)
    rev = container.session.get(ActionRevision, ticket_row.current_revision_id)
    assert ticket_row and rev
    ticket_row.state = "approved"
    op = Operation(
        box_id=ticket_row.box_id,
        ticket_id=ticket_row.id,
        action_revision_id=rev.id,
        idempotency_key=f"op:{rev.id}",
        adapter="notify",
        status=OperationStatus.PENDING.value,
    )
    container.session.add(op)
    container.session.commit()
    settings.sync_worker = True
    notify.unknown_ops.add(op.id)
    executed = svc.execute_operation(container, op.id)
    assert executed.status == OperationStatus.UNKNOWN.value
    # No receipt cached as success → reconcile leaves UNKNOWN (no blind retry success)
    assert op.id not in notify.sent
    op2 = svc.reconcile_unknown(container, op.id)
    assert op2.status == OperationStatus.UNKNOWN.value
    _ = payload_hash  # keep import used if needed


def test_last_owner_cannot_be_removed(container, seeded):
    with pytest.raises(DomainError, match="last active owner"):
        svc.remove_principal(container, seeded["owner_id"], seeded["owner_id"])


def test_owner_transfer_and_remove_old(container, seeded):
    from cosmas_os.domain.enums import PrincipalState
    from cosmas_os.models import Principal

    successor = Principal(
        box_id=seeded["box_id"],
        principal_type=PrincipalType.HUMAN.value,
        display_name="Sam Successor",
        is_owner=False,
        state=PrincipalState.ACTIVE.value,
    )
    container.session.add(successor)
    container.session.commit()
    svc.transfer_owner(container, seeded["box_id"], seeded["owner_id"], successor.id)
    svc.remove_principal(container, successor.id, seeded["owner_id"])
    old = container.session.get(Principal, seeded["owner_id"])
    assert old.state == PrincipalState.TOMBSTONED.value


def test_disable_agent_retains_identity(container, seeded):
    chaser = seeded["agents"]["chaser"]
    svc.disable_agent(container, seeded["owner_id"], chaser)
    p = container.session.get(Principal, chaser)
    assert p.state == "disabled"
    assert p.display_name == "Chaser"


def test_dark_capability(container, seeded):
    with pytest.raises(PolicyDenied):
        svc.reject_dark_capability(container, seeded["box_id"], CapabilityKey.ATHENA)


def test_reject_and_escalate(container, seeded):
    chaser = seeded["agents"]["chaser"]
    appts = svc.import_schedule(container, seeded["box_id"], SYNTH_CSV)
    link = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    t1 = svc.detect_and_open_chase(container, seeded["box_id"], chaser, appts[0], link.id)
    svc.decide(container, t1.id, seeded["owner_id"], DecisionKind.REJECT)
    t2 = svc.detect_and_open_chase(container, seeded["box_id"], chaser, appts[1], link.id)
    svc.decide(container, t2.id, seeded["owner_id"], DecisionKind.ESCALATE)


def test_upload_verify_close_purge(container, seeded):
    chaser = seeded["agents"]["chaser"]
    appts = svc.import_schedule(container, seeded["box_id"], SYNTH_CSV)
    link = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    ticket = svc.detect_and_open_chase(container, seeded["box_id"], chaser, appts[0], link.id)
    svc.decide(container, ticket.id, seeded["owner_id"], DecisionKind.APPROVE)
    front = b"\x89PNG\r\n\x1a\nfront"
    back = b"\x89PNG\r\n\x1a\nback"
    verified = svc.simulate_upload_and_verify(
        container, ticket.id, seeded["owner_id"], front, back
    )
    assert verified["coverage_status"] == "image_on_file"
    closed = svc.close_ticket(container, ticket.id, seeded["owner_id"])
    assert closed.state == "closed"
    container.clock.advance_days(8)
    receipts = svc.purge_due_artifacts(container, seeded["box_id"])
    assert len(receipts) == 2
    assert "artifact_id" in receipts[0]
    assert "patient" not in str(receipts).lower() or "jordan" not in str(receipts).lower()
    timeline = svc.audit_timeline(container, seeded["box_id"], ticket.id)
    assert any(e["event_type"] == "decision.approved" for e in timeline)
    assert any(e["event_type"] == "ticket.closed" for e in timeline)


def test_disabled_chaser_cannot_open(container, seeded):
    chaser = seeded["agents"]["chaser"]
    svc.disable_agent(container, seeded["owner_id"], chaser)
    appts = svc.import_schedule(container, seeded["box_id"], SYNTH_CSV)
    link = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    with pytest.raises(DomainError, match="disabled"):
        svc.detect_and_open_chase(container, seeded["box_id"], chaser, appts[0], link.id)
