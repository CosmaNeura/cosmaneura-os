from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from cosmas_os.application import services as svc
from cosmas_os.domain.enums import CoverageStatus, DecisionKind

SYNTH_CSV = """external_id,start_at,patient_label,source
appt-1001,2026-09-10T15:00:00+00:00,Jordan Lee,csv
appt-1002,2026-09-11T16:30:00+00:00,Riley Quinn,csv
"""

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "synthetic"


def seed_synth(session: Session) -> dict:
    c = svc.Container(session)
    # idempotent-ish: if a box exists, return first
    from sqlalchemy import select

    from cosmas_os.models import BoxContext, Principal

    existing = session.scalar(select(BoxContext).limit(1))
    if existing:
        owner = session.scalar(
            select(Principal).where(Principal.box_id == existing.id, Principal.is_owner.is_(True))
        )
        agents = {
            p.agent_key: p.id
            for p in session.scalars(
                select(Principal).where(
                    Principal.box_id == existing.id, Principal.principal_type == "agent"
                )
            )
            if p.agent_key
        }
        return {"box_id": existing.id, "owner_id": owner.id if owner else "", "agents": agents}

    return svc.provision_box(c, "Northside Synth Clinic")


def seed_synth_work_queue(session: Session) -> dict:
    """Create one reviewable synthetic chase without approving or sending it."""

    from sqlalchemy import select

    from cosmas_os.models import AppointmentObservation, Ticket

    c = svc.Container(session)
    seeded = seed_synth(session)
    existing = session.scalar(
        select(Ticket)
        .where(
            Ticket.box_id == seeded["box_id"],
            Ticket.state == "pending_approval",
        )
        .order_by(Ticket.created_at.asc())
    )
    if existing:
        return {**seeded, "ticket_id": existing.id}

    appointment = session.scalar(
        select(AppointmentObservation).where(
            AppointmentObservation.box_id == seeded["box_id"],
            AppointmentObservation.external_id == "appt-1001",
        )
    )
    if appointment is None:
        appointment_id = svc.import_schedule(c, seeded["box_id"], SYNTH_CSV)[0]
    else:
        # This endpoint is a repeatable synthetic demo reset. A prior demo may
        # have moved the fixed appointment to IMAGE_ON_FILE; return it to the
        # invented missing-artifact state before opening a fresh review item.
        appointment.coverage_status = CoverageStatus.MISSING.value
        session.commit()
        appointment_id = appointment.id
    link = svc.attest_patient_link(
        c,
        seeded["box_id"],
        seeded["owner_id"],
        source_pair_key="csv:jordan-lee",
        label="Jordan Lee",
    )
    ticket = svc.detect_and_open_chase(
        c,
        seeded["box_id"],
        seeded["agents"]["chaser"],
        appointment_id,
        link.id,
    )
    return {**seeded, "ticket_id": ticket.id}


def run_demo(session: Session) -> dict:
    c = svc.Container(session)
    seeded = seed_synth(session)
    box_id = seeded["box_id"]
    owner_id = seeded["owner_id"]
    chaser_id = seeded["agents"]["chaser"]

    appt_ids = svc.import_schedule(c, box_id, SYNTH_CSV)
    link = svc.attest_patient_link(
        c, box_id, owner_id, source_pair_key="csv:jordan-lee", label="Jordan Lee"
    )
    # bind first appointment to chase
    ticket = svc.detect_and_open_chase(c, box_id, chaser_id, appt_ids[0], link.id)
    decision = svc.decide(c, ticket.id, owner_id, DecisionKind.APPROVE)

    front = (FIXTURES / "insurance_front.png").read_bytes()
    back = (FIXTURES / "insurance_back.png").read_bytes()
    verified = svc.simulate_upload_and_verify(c, ticket.id, owner_id, front, back)
    closed = svc.close_ticket(c, ticket.id, owner_id)

    # advance clock and purge
    if hasattr(c.clock, "advance_days"):
        c.clock.advance_days(8)  # type: ignore[attr-defined]
    else:
        from datetime import timedelta

        from cosmas_os.adapters.local import InjectableClock

        c.clock = InjectableClock(c.clock.now() + timedelta(days=8))
    receipts = svc.purge_due_artifacts(c, box_id, owner_id)
    timeline = svc.audit_timeline(c, box_id, ticket.id)

    return {
        "box_id": box_id,
        "ticket_id": ticket.id,
        "operation_id": decision.get("operation_id"),
        "coverage": verified["coverage_status"],
        "ticket_state": closed.state,
        "purge_receipts": receipts,
        "timeline_events": len(timeline),
    }
