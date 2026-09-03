from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident

import pytest
from sqlalchemy import event, func, select, text

from cosmas_os.adapters.local import FakeNotifyAdapter
from cosmas_os.application import services as svc
from cosmas_os.application.seed import SYNTH_CSV
from cosmas_os.db import make_session_factory
from cosmas_os.domain.enums import CapabilityKey, DecisionKind, OperationStatus, PrincipalType
from cosmas_os.domain.rules import AuthorizationError, DomainError, PolicyDenied
from cosmas_os.models import AuditEvent, Decision, Operation, Principal


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


def test_concurrent_edit_and_approve_serialize_on_current_revision(
    engine, clock, blob, monkeypatch
):
    """An approval waiting on an edit must reject the now-stale revision."""

    from cosmas_os.models import ActionRevision, Ticket

    monkeypatch.setattr("cosmas_os.config.settings.sync_worker", True)
    session_factory = make_session_factory(engine)
    setup_session = session_factory()
    setup = svc.Container(
        setup_session,
        clock=clock,
        blob=blob,
        notify=FakeNotifyAdapter(),
    )
    seeded = svc.provision_box(setup, "Concurrent workflow test")
    box_id = str(seeded["box_id"])
    owner_id = str(seeded["owner_id"])
    agents = seeded["agents"]
    assert isinstance(agents, dict)
    appointment_id = svc.import_schedule(setup, box_id, SYNTH_CSV)[0]
    link = svc.attest_patient_link(
        setup,
        box_id,
        owner_id,
        "csv:concurrent-jordan-lee",
        "Jordan Lee",
    )
    ticket = svc.detect_and_open_chase(
        setup,
        box_id,
        str(agents["chaser"]),
        appointment_id,
        link.id,
    )
    ticket_id = ticket.id
    original_revision_id = ticket.current_revision_id
    setup_session.close()

    lock_session = session_factory()
    lock_container = svc.Container(
        lock_session,
        clock=clock,
        blob=blob,
        notify=FakeNotifyAdapter(),
    )
    approval_select_started = Event()
    approval_thread_id: list[int] = []

    def note_approval_lock_query(
        _conn, _cursor, statement: str, _parameters, _context, _executemany
    ) -> None:
        if (
            approval_thread_id
            and get_ident() == approval_thread_id[0]
            and "FOR UPDATE" in statement.upper()
        ):
            approval_select_started.set()

    def approve_original_revision() -> object:
        approval_thread_id.append(get_ident())
        approval_session = session_factory()
        try:
            approval = svc.Container(
                approval_session,
                clock=clock,
                blob=blob,
                notify=FakeNotifyAdapter(),
            )
            return svc.decide(
                approval,
                ticket_id,
                owner_id,
                DecisionKind.APPROVE,
                expected_revision_id=original_revision_id,
            )
        except Exception as exc:  # return the competing request's result to the test thread
            return exc
        finally:
            approval_session.close()

    try:
        # Hold the row before the competing request begins, so the interleaving
        # is deterministic rather than dependent on thread scheduling.
        locked = lock_session.scalar(
            select(Ticket).where(Ticket.id == ticket_id).with_for_update()
        )
        assert locked is not None
        event.listen(engine, "before_cursor_execute", note_approval_lock_query)
        with ThreadPoolExecutor(max_workers=1) as pool:
            approval_result = pool.submit(approve_original_revision)
            assert approval_select_started.wait(timeout=5)
            revised = svc.edit_revision(
                lock_container,
                ticket_id,
                owner_id,
                "Concurrent synthetic edit wins the ticket lock.",
            )
            result = approval_result.result(timeout=5)

        assert isinstance(result, DomainError)
        assert str(result) == "stale revision"

        verification_session = session_factory()
        try:
            verification = svc.Container(
                verification_session,
                clock=clock,
                blob=blob,
                notify=FakeNotifyAdapter(),
            )
            current_ticket = verification_session.get(Ticket, ticket_id)
            original_revision = verification_session.get(
                ActionRevision, original_revision_id
            )
            assert current_ticket is not None
            assert current_ticket.state == "pending_approval"
            assert current_ticket.current_revision_id == revised.id
            assert original_revision is not None and original_revision.invalidated is True
            assert (
                verification_session.scalar(
                    select(func.count())
                    .select_from(Operation)
                    .where(Operation.ticket_id == ticket_id)
                )
                == 0
            )

            accepted = svc.decide(
                verification,
                ticket_id,
                owner_id,
                DecisionKind.APPROVE,
                expected_revision_id=revised.id,
            )
            operation = verification_session.get(Operation, accepted["operation_id"])
            assert operation is not None
            assert operation.action_revision_id == revised.id
            assert operation.status == OperationStatus.SUCCEEDED.value
        finally:
            verification_session.close()
    finally:
        event.remove(engine, "before_cursor_execute", note_approval_lock_query)
        lock_session.close()
        # This test uses independent committed sessions to exercise real row
        # locking, so clean its isolated Box explicitly.
        with engine.begin() as connection:
            for table_name in (
                "decisions",
                "operations",
                "artifacts",
                "audit_events",
                "action_revisions",
                "tickets",
                "appointment_observations",
                "patient_links",
                "external_identities",
                "capability_configs",
                "principals",
            ):
                connection.execute(
                    text(f"DELETE FROM {table_name} WHERE box_id = :box_id"),
                    {"box_id": box_id},
                )
            connection.execute(
                text("DELETE FROM box_contexts WHERE id = :box_id"),
                {"box_id": box_id},
            )


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


def test_async_publish_failure_can_be_retried_without_stranding_operation(
    monkeypatch, container, seeded
):
    from cosmas_os.config import settings
    from cosmas_os.worker.tasks import execute_operation_task

    chaser = seeded["agents"]["chaser"]
    appts = svc.import_schedule(container, seeded["box_id"], SYNTH_CSV)
    link = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    ticket = svc.detect_and_open_chase(
        container, seeded["box_id"], chaser, appts[0], link.id
    )
    published: list[str] = []

    def publish(operation_id: str) -> None:
        published.append(operation_id)
        if len(published) == 1:
            raise RuntimeError("synthetic broker unavailable")

    monkeypatch.setattr(settings, "sync_worker", False)
    monkeypatch.setattr(execute_operation_task, "delay", publish)

    with pytest.raises(RuntimeError, match="synthetic broker unavailable"):
        svc.decide(container, ticket.id, seeded["owner_id"], DecisionKind.APPROVE)

    operation = container.session.scalar(
        select(Operation).where(Operation.ticket_id == ticket.id)
    )
    assert operation is not None
    assert operation.status == OperationStatus.PENDING.value
    assert (
        container.session.scalar(
            select(func.count()).select_from(Decision).where(Decision.ticket_id == ticket.id)
        )
        == 1
    )

    retry = svc.decide(container, ticket.id, seeded["owner_id"], DecisionKind.APPROVE)

    assert retry == {"decision": "already_approved", "operation_id": operation.id}
    assert published == [operation.id, operation.id]
    assert (
        container.session.scalar(
            select(func.count()).select_from(Operation).where(Operation.ticket_id == ticket.id)
        )
        == 1
    )
    assert (
        container.session.scalar(
            select(func.count()).select_from(Decision).where(Decision.ticket_id == ticket.id)
        )
        == 1
    )


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
    receipts = svc.purge_due_artifacts(container, seeded["box_id"], seeded["owner_id"])
    assert len(receipts) == 2
    assert "artifact_id" in receipts[0]
    assert "patient" not in str(receipts).lower() or "jordan" not in str(receipts).lower()
    purge_audit = container.session.scalar(
        select(AuditEvent).where(
            AuditEvent.aggregate_id == receipts[0]["artifact_id"],
            AuditEvent.event_type == "artifact.purged",
        )
    )
    assert purge_audit is not None
    assert purge_audit.actor_principal_id == seeded["owner_id"]
    assert purge_audit.detail["owner_authorized"] is True
    timeline = svc.audit_timeline(container, seeded["box_id"], ticket.id)
    assert any(e["event_type"] == "decision.approved" for e in timeline)
    assert any(e["event_type"] == "ticket.closed" for e in timeline)


def test_non_owner_member_cannot_purge_box_artifacts(container, seeded):
    member = Principal(
        box_id=seeded["box_id"],
        principal_type=PrincipalType.HUMAN.value,
        display_name="Synth Member",
        is_owner=False,
        state="active",
    )
    container.session.add(member)
    container.session.commit()

    with pytest.raises(AuthorizationError, match="owner authority required"):
        svc.purge_due_artifacts(container, seeded["box_id"], member.id)


def test_cross_box_owner_cannot_purge_another_box(container, seeded):
    other_box = svc.provision_box(container, "Other Synthetic Clinic")

    with pytest.raises(AuthorizationError, match="outside the Box"):
        svc.purge_due_artifacts(
            container,
            seeded["box_id"],
            other_box["owner_id"],
        )


def test_disabled_chaser_cannot_open(container, seeded):
    chaser = seeded["agents"]["chaser"]
    svc.disable_agent(container, seeded["owner_id"], chaser)
    appts = svc.import_schedule(container, seeded["box_id"], SYNTH_CSV)
    link = svc.attest_patient_link(
        container, seeded["box_id"], seeded["owner_id"], "csv:jordan-lee", "Jordan Lee"
    )
    with pytest.raises(DomainError, match="disabled"):
        svc.detect_and_open_chase(container, seeded["box_id"], chaser, appts[0], link.id)
