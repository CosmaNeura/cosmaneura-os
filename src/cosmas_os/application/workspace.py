"""Private, synthetic encounter history. No capture, inference, or execution port."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cosmas_os.application.encounter_access import patient_visible
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.domain.work_lanes import PRIVATE_CONNECTOR_LANES
from cosmas_os.models import (
    AppointmentObservation,
    AuditEvent,
    EncounterWorkspace,
    PatientLink,
    Principal,
    Ticket,
    WorkspaceEntry,
    WorkspaceReply,
)

SYNTHETIC_PREP = (
    "Invented visit preparation: discuss access to the practice and agree on next steps. "
    "No chart, medications, diagnoses or clinical history were retrieved. "
    "This fixed example is evidence for the workspace rehearsal only."
)


class WorkspaceError(Exception):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


def _human(s: Session, box: str, actor: str, *, creating: bool = False) -> Principal:
    p = s.scalar(
        select(Principal)
        .where(
            Principal.id == actor,
            Principal.box_id == box,
            Principal.principal_type == "human",
            Principal.state == "active",
            Principal.tombstoned_at.is_(None),
        )
        .with_for_update(read=not creating)
    )
    if p is None:
        raise WorkspaceError("workspace_access_denied", 403)
    return p


def _encounter(s: Session, box: str, appointment: str, link_id: str | None = None, *, owner: str | None = None):
    a = s.scalar(
        select(AppointmentObservation)
        .where(
            AppointmentObservation.id == appointment,
            AppointmentObservation.box_id == box,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if a is None or a.patient_link_id is None or (link_id and a.patient_link_id != link_id):
        raise WorkspaceError("encounter_unavailable", 404)
    link = s.scalar(
        select(PatientLink)
        .where(
            PatientLink.id == a.patient_link_id,
            PatientLink.box_id == box,
            PatientLink.state == "confirmed",
            PatientLink.revoked_at.is_(None),
            patient_visible(owner),
        )
        .with_for_update(read=True)
    )
    if link is None:
        raise WorkspaceError("encounter_unavailable", 404)
    return a


def _workspace(s: Session, box: str, actor: str, wid: str, *, writing: bool = False):
    _human(s, box, actor)
    w = s.scalar(
        select(EncounterWorkspace)
        .where(
            EncounterWorkspace.id == wid,
            EncounterWorkspace.box_id == box,
            EncounterWorkspace.owner_id == actor,
        )
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    if w is None:
        raise WorkspaceError("workspace_unavailable", 404)
    _encounter(s, box, w.appointment_id, w.patient_link_id, owner=actor)
    return w


def _ticket(s: Session, w: EncounterWorkspace, tid: str):
    return s.scalar(
        select(Ticket)
        .where(
            Ticket.id == tid,
            Ticket.box_id == w.box_id,
            Ticket.appointment_id == w.appointment_id,
            Ticket.patient_link_id == w.patient_link_id,
            or_(Ticket.lane.not_in(PRIVATE_CONNECTOR_LANES), Ticket.created_by_principal_id == w.owner_id),
        )
        .with_for_update(read=True)
    )


def _audit(s: Session, w: EncounterWorkspace, kind: str):
    s.add(
        AuditEvent(
            box_id=w.box_id,
            aggregate_type="workspace",
            aggregate_id=w.id,
            event_type="workspace." + kind,
            actor_principal_id=w.owner_id,
            outcome="saved",
            detail={"revision": w.revision},
        )
    )


def catalog(s: Session, box: str, actor: str):
    _human(s, box, actor)
    workspaces = list(
        s.scalars(
            select(EncounterWorkspace).where(
                EncounterWorkspace.box_id == box, EncounterWorkspace.owner_id == actor
            )
        )
    )
    appointments = s.scalars(
        select(AppointmentObservation)
        .join(
            PatientLink,
            AppointmentObservation.patient_link_id == PatientLink.id,
        )
        .where(
            AppointmentObservation.box_id == box,
            PatientLink.box_id == box,
            PatientLink.state == "confirmed",
            PatientLink.revoked_at.is_(None),
            patient_visible(actor),
        )
        .order_by(AppointmentObservation.start_at, AppointmentObservation.id)
        .limit(100)
    )
    return [
        {
            "appointment_id": a.id,
            "label": a.patient_label,
            "workspace_id": next(
                (
                    w.id
                    for w in workspaces
                    if w.appointment_id == a.id and w.patient_link_id == a.patient_link_id
                ),
                None,
            ),
        }
        for a in appointments
    ]


def create(s: Session, box: str, actor: str, appointment: str, key: str, *, initial_synthetic_source: bool = True):
    _human(s, box, actor, creating=True)
    a = _encounter(s, box, appointment, owner=actor)
    replay = s.scalar(
        select(EncounterWorkspace).where(
            EncounterWorkspace.owner_id == actor, EncounterWorkspace.create_key == key
        )
    )
    if replay:
        if replay.appointment_id != appointment or replay.box_id != box:
            raise WorkspaceError("idempotency_conflict")
        return read(s, box, actor, replay.id)
    if s.scalar(
        select(EncounterWorkspace.id).where(
            EncounterWorkspace.owner_id == actor, EncounterWorkspace.appointment_id == appointment
        )
    ):
        raise WorkspaceError("workspace_already_exists")
    w = EncounterWorkspace(
        box_id=box,
        owner_id=actor,
        appointment_id=a.id,
        patient_link_id=a.patient_link_id,
        create_key=key,
        revision=1,
    )
    s.add(w)
    s.flush()
    if initial_synthetic_source:
        s.add(WorkspaceEntry(
            workspace_id=w.id,
            box_id=box,
            actor_id=actor,
            revision=1,
            kind="synthetic_source",
            content=SYNTHETIC_PREP,
            source_label="Invented preparation · v1",
            idempotency_key="initial-source-v1",
            request_hash=payload_hash({"fixture": "prep-v1"}),
        ))
    _audit(s, w, "created")
    s.commit()
    return read(s, box, actor, w.id)


def read(s: Session, box: str, actor: str, wid: str, *, at_revision: int | None = None):
    from cosmas_os.application import follow_up, handoffs, note_review

    w = _workspace(s, box, actor, wid)
    revision = w.revision if at_revision is None else min(at_revision, w.revision)
    a = _encounter(s, box, w.appointment_id, w.patient_link_id, owner=actor)
    entries = []
    from cosmas_os.models import (
        ModelWorkAdmission,
        WorkspaceHandoffAttempt,
        WorkspaceHandoffRevision,
    )

    admitted = {row.request_entry_id: row for row in s.scalars(select(ModelWorkAdmission).where(
        ModelWorkAdmission.workspace_id == wid, ModelWorkAdmission.box_id == box,
        ModelWorkAdmission.owner_id == actor))}
    # Revision origins quote human feedback but have a separate child admission.
    # Bind their public projection to every child input, including queued work.
    revision_admissions = {}
    for origin_id, row in s.execute(select(WorkspaceHandoffRevision.origin_entry_id, ModelWorkAdmission)
        .join(WorkspaceHandoffAttempt, WorkspaceHandoffAttempt.handoff_id == WorkspaceHandoffRevision.revision_handoff_id)
        .join(ModelWorkAdmission, ModelWorkAdmission.handoff_attempt_id == WorkspaceHandoffAttempt.id)
        .where(WorkspaceHandoffRevision.workspace_id == wid, WorkspaceHandoffRevision.box_id == box,
               WorkspaceHandoffRevision.owner_id == actor, ModelWorkAdmission.workspace_id == wid,
               ModelWorkAdmission.box_id == box, ModelWorkAdmission.owner_id == actor)):
        revision_admissions.setdefault(origin_id, []).append(row)
    replies = {reply.entry_id: reply for reply in s.scalars(select(WorkspaceReply).where(
        WorkspaceReply.workspace_id == wid, WorkspaceReply.box_id == box, WorkspaceReply.owner_id == actor,
    ))}
    for e in s.scalars(
        select(WorkspaceEntry)
        .where(
            WorkspaceEntry.workspace_id == w.id,
            WorkspaceEntry.box_id == box,
            WorkspaceEntry.revision <= revision,
        )
        .order_by(WorkspaceEntry.revision)
    ):
        t = _ticket(s, w, e.ticket_id) if e.ticket_id else None
        reply = replies.get(e.id)
        content = e.content
        from cosmas_os.application import selected_google_sources

        source_states = {}
        related_admissions = ([admitted[e.id]] if e.id in admitted else []) + revision_admissions.get(e.id, [])
        for admission in related_admissions:
            from cosmas_os.adapters.gpt41 import _context

            # Uncited output and quoted revision feedback still inherit every
            # frozen selected source. Independent notes and current sources stay.
            unavailable = selected_google_sources.unavailable_states(
                s, w, _context(admission.prepared_envelope["context"])
            )
            if unavailable:
                reply = None
                content = ""
                source_states.update({field: "unavailable" for field in unavailable})
        if selected_google_sources.is_selected_google(e):
            field = selected_google_sources.SOURCE_STATE_FIELDS[e.kind]
            try:
                selected_google_sources.validate_selected_source(s, w, e.id)
                source_states[field] = "current"
            except WorkspaceError:
                content = ""
                source_states[field] = "unavailable"
        unavailable_label = {
            "google_message": "Unavailable email source",
            "google_calendar": "Unavailable calendar source",
        }.get(e.kind)
        entries.append(
            {
                "id": e.id,
                "revision": e.revision,
                "kind": e.kind,
                "content": content,
                "source_label": unavailable_label if unavailable_label and any(
                    state == "unavailable" for state in source_states.values()) else e.source_label,
                "origin": "synthetic_fixture"
                if e.kind == "synthetic_source"
                else "agent_handoff" if e.kind == "handoff_result" else "authenticated_human",
                "ticket": {"id": t.id, "state": t.state, "lane": t.lane} if t else None,
                "created_at": e.created_at.isoformat(),
                **source_states,
                "reply": {"agent_name": reply.agent_name, "agent_id": reply.agent_id, "role": reply.role,
                          "backend": reply.backend, "content": reply.content,
                          "team_revision_id": reply.team_revision_id,
                          "context_revision": reply.context_revision, "citations": reply.citations}
                if reply else None,
            }
        )
    candidates = s.scalars(
        select(Ticket)
        .where(
            Ticket.box_id == box,
            Ticket.appointment_id == w.appointment_id,
            Ticket.patient_link_id == w.patient_link_id,
            or_(Ticket.lane.not_in(PRIVATE_CONNECTOR_LANES), Ticket.created_by_principal_id == w.owner_id),
        )
        .order_by(Ticket.created_at)
        .limit(100)
    )
    return {
        "id": w.id,
        "appointment_id": w.appointment_id,
        "label": a.patient_label,
        "revision": revision,
        "entries": entries,
        "handoffs": handoffs.read(s, w, revision),
        "note": note_review.read(s, w, revision),
        "follow_ups": follow_up.read(s, w, revision),
        "work_candidates": [{"id": t.id, "state": t.state, "lane": t.lane} for t in candidates],
    }


def append(
    s: Session,
    box: str,
    actor: str,
    wid: str,
    *,
    expected: int,
    key: str,
    kind: str,
    content: str = "",
    source_label: str | None = None,
    ticket_id: str | None = None,
):
    w = _workspace(s, box, actor, wid, writing=True)
    request_hash = payload_hash(
        {
            "expected": expected,
            "kind": kind,
            "content": content,
            "source_label": source_label,
            "ticket_id": ticket_id,
        }
    )
    replay = s.scalar(
        select(WorkspaceEntry).where(
            WorkspaceEntry.workspace_id == w.id, WorkspaceEntry.idempotency_key == key
        )
    )
    if replay:
        if replay.request_hash != request_hash:
            raise WorkspaceError("idempotency_conflict")
        return {
            "entry_id": replay.id,
            "entry_revision": replay.revision,
            "workspace": read(s, box, actor, wid, at_revision=replay.revision),
        }
    if expected != w.revision:
        raise WorkspaceError("workspace_revision_conflict")
    if w.revision >= 500:
        raise WorkspaceError("workspace_history_limit")
    if kind not in {"scratchpad", "conversation", "evidence", "work_link"}:
        raise WorkspaceError("invalid_entry", 400)
    if kind == "work_link":
        if not ticket_id or not _ticket(s, w, ticket_id) or content or source_label:
            raise WorkspaceError("work_unavailable", 404)
        if s.scalar(
            select(WorkspaceEntry.id).where(
                WorkspaceEntry.workspace_id == wid, WorkspaceEntry.ticket_id == ticket_id
            )
        ):
            raise WorkspaceError("work_already_linked")
    elif (
        ticket_id
        or not content.strip()
        or len(content) > 20000
        or ((kind == "evidence") != bool(source_label))
        or len(source_label or "") > 160
    ):
        raise WorkspaceError("invalid_entry", 400)
    w.revision += 1
    e = WorkspaceEntry(
        workspace_id=wid,
        box_id=box,
        actor_id=actor,
        revision=w.revision,
        kind=kind,
        content=content,
        source_label=source_label,
        ticket_id=ticket_id,
        idempotency_key=key,
        request_hash=request_hash,
    )
    s.add(e)
    _audit(s, w, "entry_saved")
    s.commit()
    # Do not advance an editor past an unseen concurrent edit on a save/retry.
    return {
        "entry_id": e.id,
        "entry_revision": e.revision,
        "workspace": read(s, box, actor, wid, at_revision=e.revision),
    }
