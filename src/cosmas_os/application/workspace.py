"""Private, synthetic encounter history. No capture, inference, or execution port."""

from __future__ import annotations

from sqlalchemy import func, or_, select
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
    WorkspaceAppointmentLink,
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


def _encounter(s: Session, box: str, appointment: str | None, link_id: str | None = None, *, owner: str | None = None):
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


def _workspace(s: Session, box: str, actor: str, wid: str, *, writing: bool = False, allow_private: bool = False):
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
    if w.appointment_id is None:
        if not allow_private or w.patient_link_id is not None or w.draft_title is None:
            raise WorkspaceError("workspace_appointment_required")
    else:
        _encounter(s, box, w.appointment_id, w.patient_link_id, owner=actor)
    return w


def _ticket(s: Session, w: EncounterWorkspace, tid: str):
    if w.appointment_id is None:
        return None
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
            "start_at": a.start_at.isoformat() if a.start_at is not None else None,
            "source": a.source,
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


def _draft_request(title, key):
    import re

    if (not isinstance(title, str) or not title.strip() or title != title.strip() or len(title) > 160
            or not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9:_-]{8,100}", key) is None):
        raise WorkspaceError("invalid_private_draft_request", 422)
    return payload_hash({"contract": "private-workspace-create.v1", "title": title})


def resolve_private_draft(s: Session, box: str, actor: str, title: str, key: str):
    _human(s, box, actor, creating=True)  # Wait behind an in-flight exact-owner create before not_found.
    digest = _draft_request(title, key)
    row = s.scalar(select(EncounterWorkspace).where(
        EncounterWorkspace.owner_id == actor, EncounterWorkspace.create_key == key))
    if row is None:
        return {"contract_version": 1, "outcome": "not_found", "workspace": None}
    if row.box_id != box or row.create_request_hash != digest or row.draft_title != title:
        raise WorkspaceError("idempotency_conflict")
    return {"contract_version": 1, "outcome": "saved", "workspace": read(s, box, actor, row.id)}


def create_private_draft(s: Session, box: str, actor: str, title: str, key: str, *, fence=None):
    _human(s, box, actor, creating=True)  # Same-owner creates serialize, including exact-key races.
    found = resolve_private_draft(s, box, actor, title, key)
    if fence:
        fence()
    if found["outcome"] == "saved":
        return found["workspace"]
    count = s.scalar(select(func.count()).select_from(EncounterWorkspace).where(
        EncounterWorkspace.box_id == box, EncounterWorkspace.owner_id == actor,
        EncounterWorkspace.draft_title.is_not(None)))
    if count is not None and count >= 100:
        raise WorkspaceError("private_draft_limit")
    row = EncounterWorkspace(box_id=box, owner_id=actor, appointment_id=None, patient_link_id=None,
        draft_title=title, create_request_hash=_draft_request(title, key), create_key=key, revision=1)
    s.add(row)
    s.flush()
    _audit(s, row, "private_draft_created")
    s.flush()
    if fence:
        fence()
    s.commit()
    return read(s, box, actor, row.id)


def private_drafts(s: Session, box: str, actor: str):
    _human(s, box, actor)
    rows = s.scalars(select(EncounterWorkspace).where(
        EncounterWorkspace.box_id == box, EncounterWorkspace.owner_id == actor,
        EncounterWorkspace.draft_title.is_not(None)).order_by(
        EncounterWorkspace.created_at.desc(), EncounterWorkspace.id.desc()).limit(100))
    items = []
    for row in rows:
        if row.appointment_id is not None:
            try:
                _encounter(s, box, row.appointment_id, row.patient_link_id, owner=actor)
            except WorkspaceError:
                continue  # Revocation withholds both linked content and identifying catalog metadata.
        items.append({"workspace_id": row.id, "title": row.draft_title, "revision": row.revision,
            "created_at": row.created_at.isoformat(), "link_state": "unlinked" if row.appointment_id is None else "linked",
            "appointment_id": row.appointment_id})
    return {"contract_version": 1, "drafts": items[:50], "has_more": len(items) > 50}


def _link_digest(expected, appointment, confirmed):
    if confirmed is not True or isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise WorkspaceError("invalid_private_draft_request", 422)
    return payload_hash({"contract": "private-workspace-link.v1", "expected_revision": expected,
        "appointment_id": appointment, "appointment_link_confirmed": True})


def resolve_appointment_link(s: Session, box: str, actor: str, wid: str, *, expected: int,
                             key: str, appointment: str, confirmed: bool):
    _human(s, box, actor, creating=True)  # Serialize against the original one-way link transaction.
    w = _workspace(s, box, actor, wid, allow_private=True)
    digest = _link_digest(expected, appointment, confirmed)
    row = s.scalar(select(WorkspaceAppointmentLink).where(WorkspaceAppointmentLink.workspace_id == wid))
    if row is None:
        return {"contract_version": 1, "outcome": "not_found", "link_receipt_id": None, "workspace": None}
    if row.idempotency_key != key or row.request_hash != digest:
        raise WorkspaceError("idempotency_conflict")
    return {"contract_version": 1, "outcome": "saved", "link_receipt_id": row.id,
            "workspace": read(s, box, actor, w.id)}


def link_appointment(s: Session, box: str, actor: str, wid: str, *, expected: int,
                     key: str, appointment: str, confirmed: bool, fence=None):
    _human(s, box, actor, creating=True)
    w = _workspace(s, box, actor, wid, writing=True, allow_private=True)
    found = resolve_appointment_link(s, box, actor, wid, expected=expected, key=key,
        appointment=appointment, confirmed=confirmed)
    if fence:
        fence()
    if found["outcome"] == "saved":
        return {"entry_revision": found["workspace"]["revision"],
                "link_receipt_id": found["link_receipt_id"], "workspace": found["workspace"]}
    if w.draft_title is None or w.appointment_id is not None:
        raise WorkspaceError("workspace_already_linked")
    if expected != w.revision or w.revision >= 500:
        raise WorkspaceError("workspace_revision_conflict")
    a = _encounter(s, box, appointment, owner=actor)
    if s.scalar(select(EncounterWorkspace.id).where(EncounterWorkspace.owner_id == actor,
            EncounterWorkspace.appointment_id == appointment)):
        raise WorkspaceError("workspace_already_exists")
    entries = list(s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == wid)
        .order_by(WorkspaceEntry.revision)))
    row = WorkspaceAppointmentLink(workspace_id=wid, box_id=box, owner_id=actor,
        appointment_id=a.id, patient_link_id=a.patient_link_id, expected_revision=expected,
        workspace_revision=expected + 1, idempotency_key=key,
        request_hash=_link_digest(expected, appointment, confirmed),
        appointment_sha256=payload_hash({"appointment_id": a.id, "patient_link_id": a.patient_link_id,
            "source": a.source, "source_sha256": a.source_sha256, "label": a.patient_label,
            "start_at": a.start_at.isoformat() if a.start_at else None}),
        draft_sha256=payload_hash({"workspace_id": wid, "title": w.draft_title, "revision": expected,
            "entries": [{"id": e.id, "revision": e.revision, "request_hash": e.request_hash} for e in entries]}))
    s.add(row)
    s.flush()  # The immutable receipt must exist before the one-way association update.
    w.appointment_id, w.patient_link_id, w.revision = a.id, a.patient_link_id, expected + 1
    _audit(s, w, "appointment_linked")
    s.flush()
    if fence:
        fence()
    s.commit()
    return {"entry_revision": w.revision, "link_receipt_id": row.id, "workspace": read(s, box, actor, wid)}


def read(s: Session, box: str, actor: str, wid: str, *, at_revision: int | None = None):
    return _read(s, box, actor, wid, at_revision=at_revision, include_handoffs=True, include_research_markers=True)


def _read_model_context(s: Session, box: str, actor: str, wid: str):
    # Model contexts consume entries and follow-up state, not the handoff review
    # display. Keep identical ownership and source masking on every fresh read.
    return _read(s, box, actor, wid, at_revision=None, include_handoffs=False)


def _read(s: Session, box: str, actor: str, wid: str, *, at_revision: int | None, include_handoffs: bool,
          include_research_markers: bool = False):
    from cosmas_os.application import follow_up, handoffs, note_review

    w = _workspace(s, box, actor, wid, allow_private=True)
    revision = w.revision if at_revision is None else min(at_revision, w.revision)
    a = _encounter(s, box, w.appointment_id, w.patient_link_id, owner=actor) if w.appointment_id is not None else None
    link = s.scalar(select(WorkspaceAppointmentLink).where(WorkspaceAppointmentLink.workspace_id == wid))
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
    visible_entries = list(s.scalars(
        select(WorkspaceEntry)
        .where(
            WorkspaceEntry.workspace_id == w.id,
            WorkspaceEntry.box_id == box,
            WorkspaceEntry.revision <= revision,
        )
        .order_by(WorkspaceEntry.revision)
    ))
    research_markers = {}
    if include_research_markers:
        from cosmas_os.application import research

        research_markers = research.saved_packet_markers(s, box, actor, w.id, visible_entries)
    for e in visible_entries:
        t = _ticket(s, w, e.ticket_id) if e.ticket_id else None
        reply = replies.get(e.id)
        content = e.content
        from cosmas_os.application import selected_connector_sources

        source_states = {}
        related_admissions = ([admitted[e.id]] if e.id in admitted else []) + revision_admissions.get(e.id, [])
        for admission in related_admissions:
            from cosmas_os.adapters.gpt41 import _context

            # Uncited output and quoted revision feedback still inherit every
            # frozen selected source. Independent notes and current sources stay.
            unavailable = selected_connector_sources.unavailable_states(
                s, w, _context(admission.prepared_envelope["context"])
            )
            if unavailable:
                reply = None
                content = ""
                source_states.update({field: "unavailable" for field in unavailable})
        if selected_connector_sources.is_selected_connector(e):
            field = selected_connector_sources.SOURCE_STATE_FIELDS[e.kind]
            try:
                selected_connector_sources.validate_selected_source(s, w, e.id)
                source_states[field] = "current"
            except WorkspaceError:
                content = ""
                source_states[field] = "unavailable"
        unavailable_label = {
            "google_message": "Unavailable email source",
            "microsoft_message": "Unavailable email source",
            "google_calendar": "Unavailable calendar source",
            "efax_inbound_source": "Unavailable received-fax source",
            "fax_inbound_source": "Unavailable received practice-fax source",
            "ehr_read_source": "Unavailable EHR source",
            "calendar_import_source": "Unavailable calendar import",
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
                **({"research_packet": research_markers[e.id]} if e.id in research_markers else {}),
                "reply": {"agent_name": reply.agent_name, "agent_id": reply.agent_id, "role": reply.role,
                          "backend": reply.backend, "content": reply.content,
                          "team_revision_id": reply.team_revision_id,
                          "context_revision": reply.context_revision, "citations": reply.citations}
                if reply else None,
            }
        )
    candidates = [] if a is None else s.scalars(
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
    from cosmas_os.application import notebook_metadata

    return {
        "id": w.id,
        "appointment_id": w.appointment_id,
        "label": a.patient_label if a else w.draft_title,
        **({"notebook": notebook_metadata.display(s, w)} if w.draft_title is not None else {}),
        "revision": revision,
        "entries": entries,
        "handoffs": handoffs.read(s, w, revision) if include_handoffs else [],
        "note": note_review.read(s, w, revision),
        "follow_ups": follow_up.read(s, w, revision),
        "work_candidates": [{"id": t.id, "state": t.state, "lane": t.lane} for t in candidates],
        **({"private_draft": {"title": w.draft_title, "state": "linked" if a else "unlinked",
            "link_receipt_id": link.id if link else None, "linked_at": link.created_at.isoformat() if link else None}}
            if w.draft_title is not None else {}),
    }


def _entry_key_available(s, wid, key):
    """File-import command keys cannot later become ordinary entry commands."""
    from cosmas_os.calendar_import_models import CalendarImportRequest, CalendarImportRevocation

    for table in (CalendarImportRequest, CalendarImportRevocation):
        if s.scalar(select(table.id).where(table.workspace_id == wid, table.idempotency_key == key)):
            raise WorkspaceError("idempotency_conflict")


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
    w = _workspace(s, box, actor, wid, writing=True, allow_private=True)
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
    _entry_key_available(s, wid, key)
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
        or source_label == "Human-shared saved note"
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
