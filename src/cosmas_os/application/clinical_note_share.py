"""Immutable human-shared note snapshots on existing workspace entries.

Snapshots are conversation entries without replies, so sharing a note does not
change its clinical source fingerprint. Only this server-created contract can
be projected as evidence; generic conversation/evidence text cannot spoof it.
"""

import json
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import select

from cosmas_os.api.clinical_note_share_schemas import ShareSavedNote
from cosmas_os.application import note_review
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.models import WorkspaceEntry, WorkspaceNote
from cosmas_os.ports.bot_capabilities import SourcePassage, supports_skill

CONTRACT = "clinical-note-team-source.v1"
REQUEST_CONTRACT = "clinical-team-drafts.request.v1"
DIRECTIONS_REQUEST_CONTRACT = "clinical-team-drafts.request.v2"
LABEL = "Human-shared saved note"


@dataclass(frozen=True)
class ClinicalSourceSnapshot:
    entries: dict[str, WorkspaceEntry]
    notes: dict[str, WorkspaceNote]


def _latest_note(s, w, snapshot):
    return max((note for note in snapshot.notes.values() if note.workspace_id == w.id),
        key=lambda note: note.version, default=None) if snapshot is not None else note_review._latest(s, w.id)


def _source_fingerprint(s, w, snapshot):
    if snapshot is None:
        return note_review.source_fingerprint(s, w.id, w.revision)
    return note_review.fingerprint_for_sources(sorted((entry for entry in snapshot.entries.values()
        if entry.workspace_id == w.id and entry.revision <= w.revision and entry.kind in {"scratchpad", "evidence", "synthetic_source"}),
        key=lambda entry: entry.revision))


def _command(body):
    return body.model_dump(mode="json")


def _hash(body):
    return payload_hash({"contract": CONTRACT, "request": _command(body)})


def _snapshot(note, body):
    return {"contract": CONTRACT, "request": _command(body), "note": {
        "id": note.id, "version": note.version, "content_hash": note.content_hash,
        "source_fingerprint": note.source_fingerprint, "content": note.content,
    }}


def _checked_entry(s, w, entry, *, snapshot: ClinicalSourceSnapshot | None = None):
    if (entry.workspace_id != w.id or entry.box_id != w.box_id or entry.actor_id != w.owner_id
            or entry.kind != "conversation" or entry.source_label != LABEL):
        raise ws.WorkspaceError("clinical_note_source_unavailable", 409)
    try:
        value = json.loads(entry.content)
        if set(value) != {"contract", "request", "note"} or value["contract"] != CONTRACT:
            raise ValueError
        body = ShareSavedNote.model_validate(value["request"])
        note = snapshot.notes.get(str(body.note_id)) if snapshot is not None else s.get(WorkspaceNote, str(body.note_id))
        if (note is None or note.workspace_id != w.id or note.box_id != w.box_id or note.owner_id != w.owner_id
                or entry.idempotency_key != body.idempotency_key or entry.request_hash != _hash(body)
                or value != _snapshot(note, body) or note.version != body.note_version
                or note.content_hash != body.content_hash or note.source_fingerprint != body.source_fingerprint
                or payload_hash({"content": note.content}) != note.content_hash):
            raise ValueError
        if entry.content != canonical_json(_snapshot(note, body)):
            raise ValueError
        return note, body
    except (ValueError, TypeError, KeyError):
        raise ws.WorkspaceError("clinical_note_source_unavailable", 409) from None


def _result(s, w, entry):
    return {"contract": "clinical-note-share.v1", "outcome": "saved" if entry else "not_found",
        "source_entry_id": entry.id if entry else None,
        "source_entry_revision": entry.revision if entry else None,
        "workspace": ws.read(s, w.box_id, w.owner_id, w.id)}


def resolve(s, box, owner, wid, body):
    w = ws._workspace(s, box, owner, wid, writing=True)
    entry = s.scalar(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == wid,
        WorkspaceEntry.idempotency_key == body.idempotency_key))
    if entry is not None:
        _checked_entry(s, w, entry)
        if entry.request_hash != _hash(body):
            raise ws.WorkspaceError("idempotency_conflict")
    return _result(s, w, entry)


def share(s, box, owner, wid, body, *, fence=None):
    w = ws._workspace(s, box, owner, wid, writing=True)
    prior = s.scalar(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == wid,
        WorkspaceEntry.idempotency_key == body.idempotency_key))
    if prior is not None:
        _checked_entry(s, w, prior)
        if prior.request_hash != _hash(body):
            raise ws.WorkspaceError("idempotency_conflict")
        return _result(s, w, prior)
    if w.revision != body.expected_revision:
        raise ws.WorkspaceError("workspace_revision_conflict")
    note = note_review._latest(s, wid)
    if (note is None or note.box_id != box or note.owner_id != owner
            or note.id != str(body.note_id) or note.version != body.note_version
            or note.content_hash != body.content_hash or note.source_fingerprint != body.source_fingerprint
            or payload_hash({"content": note.content}) != body.content_hash
            or note_review.source_fingerprint(s, wid, w.revision) != note.source_fingerprint):
        raise ws.WorkspaceError("clinical_note_source_changed", 409)
    content = canonical_json(_snapshot(note, body))
    if len(content) > 20000 or w.revision >= 500:
        raise ws.WorkspaceError("clinical_note_source_too_large", 422)
    w.revision += 1
    entry = WorkspaceEntry(workspace_id=wid, box_id=box, actor_id=owner,
        revision=w.revision, kind="conversation", source_label=LABEL, content=content,
        idempotency_key=body.idempotency_key, request_hash=_hash(body))
    s.add(entry)
    ws._audit(s, w, "saved_note_shared_with_team")
    s.flush()
    if fence:
        fence()
    s.commit()
    return _result(s, w, entry)


def selected(s, w, settings, *, snapshot: ClinicalSourceSnapshot | None = None):
    if not supports_skill(settings, "saved_context") or not settings["include_evidence"]:
        return ()
    note = _latest_note(s, w, snapshot)
    if note is None or _source_fingerprint(s, w, snapshot) != note.source_fingerprint:
        return ()
    entries = sorted((entry for entry in snapshot.entries.values() if entry.workspace_id == w.id and is_shared_snapshot(entry)),
        key=lambda entry: entry.revision, reverse=True) if snapshot is not None else s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == w.id,
            WorkspaceEntry.kind == "conversation", WorkspaceEntry.source_label == LABEL).order_by(WorkspaceEntry.revision.desc()))
    for entry in entries:
        checked, _ = _checked_entry(s, w, entry, snapshot=snapshot)
        if checked.id != note.id:
            continue
        return (SourcePassage(entry.id, entry.revision, LABEL, "evidence", _source_content(note)),)
    return ()


def _source_content(note):
    return (f"Human-shared saved note · version {note.version}\n"
        "Saved private note snapshot; not clinical sign-off or a current chart read.\n\n" + note.content)


def is_shared_snapshot(entry):
    return entry is not None and entry.kind == "conversation" and entry.source_label == LABEL


def historical_source(s, w, entry_id, *, snapshot: ClinicalSourceSnapshot | None = None):
    entry = snapshot.entries.get(entry_id) if snapshot is not None else s.get(WorkspaceEntry, entry_id)
    if entry is None:
        raise ws.WorkspaceError("clinical_note_source_unavailable", 409)
    note, _ = _checked_entry(s, w, entry, snapshot=snapshot)
    return SimpleNamespace(id=entry.id, workspace_id=entry.workspace_id, box_id=entry.box_id,
        actor_id=entry.actor_id, revision=entry.revision, kind="evidence", source_label=LABEL,
        content=_source_content(note))


def validate_current_source(s, w, entry_id, *, snapshot: ClinicalSourceSnapshot | None = None):
    entry = snapshot.entries.get(entry_id) if snapshot is not None else s.get(WorkspaceEntry, entry_id)
    if entry is None:
        raise ws.WorkspaceError("clinical_note_source_changed", 409)
    note, _ = _checked_entry(s, w, entry, snapshot=snapshot)
    latest = _latest_note(s, w, snapshot)
    if latest is None or latest.id != note.id or _source_fingerprint(s, w, snapshot) != note.source_fingerprint:
        raise ws.WorkspaceError("clinical_note_source_changed", 409)


def clinical_request(s, w, settings, content, context):
    try:
        value = json.loads(content)
    except (ValueError, TypeError):
        return context
    if not isinstance(value, dict) or value.get("contract") not in (REQUEST_CONTRACT, DIRECTIONS_REQUEST_CONTRACT):
        return context
    from uuid import UUID
    try:
        valid_identity = (isinstance(value.get("source_entry_id"), str)
            and str(UUID(value["source_entry_id"])) == value["source_entry_id"]
            and isinstance(value.get("note_id"), str) and str(UUID(value["note_id"])) == value["note_id"]
            and type(value.get("note_version")) is int and 1 <= value["note_version"] <= 50
            and isinstance(value.get("content_hash"), str) and len(value["content_hash"]) == 64
            and all(c in "0123456789abcdef" for c in value["content_hash"]))
    except (ValueError, TypeError, AttributeError):
        valid_identity = False
    with_directions = value["contract"] == DIRECTIONS_REQUEST_CONTRACT
    expected_keys = {"contract", "source_entry_id", "note_id", "note_version", "content_hash"}
    if with_directions:
        expected_keys.add("owner_directions")
    directions = value.get("owner_directions")
    if (set(value) != expected_keys or settings["role"] != "chief" or not valid_identity
            or with_directions and (not isinstance(directions, str) or not 1 <= len(directions) <= 2000
                or len(content) > 4000)):
        raise ws.WorkspaceError("clinical_team_request_invalid", 422)
    entry = s.get(WorkspaceEntry, value["source_entry_id"])
    if entry is None:
        raise ws.WorkspaceError("clinical_note_source_changed", 409)
    note, _ = _checked_entry(s, w, entry)
    if (value["note_id"] != note.id or value["note_version"] != note.version
            or value["content_hash"] != note.content_hash
            or not any(p.entry_id == entry.id for p in context.sources)):
        raise ws.WorkspaceError("clinical_note_source_changed", 409)
    targets = {target["role"]: target["address"] for target in context.handoff_targets}
    if not {"follow_up", "research"} <= targets.keys():
        raise ws.WorkspaceError("clinical_team_recipient_unavailable", 409)
    from dataclasses import replace
    question = (
        "Use the exact human-shared saved note and supplied Scribe transcript to prepare two independent private drafts. "
        "Do not change the saved SOAP note. Both assignments must retain those exact source versions. "
        f"Assign Follow-up at {targets['follow_up']} a patient email draft with Subject and Body sections, then "
        "a separate Provider action items section. Explain only the documented plan in plain language; preserve "
        "uncertain or missing facts as questions for the provider, never invent medication doses, treatment changes, "
        "recipients or a completed action. Give each provider task a proposed owner, next step and done-when check; "
        "unknown owners and dates remain to confirm. The email is a draft, never sent. "
        f"Assign Research at {targets['research']} a Provider treatment assessment with Source-supported findings, "
        "Drug and treatment questions, and Missing evidence / next checks sections. Assess the same saved note; "
        "separate what the note states from questions about indications, alternatives, interactions, monitoring and "
        "contraindications. Cite the exact supplied sources for every supported fact. If current drug or treatment "
        "evidence is absent, state that it is unavailable and propose a general public query for separate human review. "
        "Do not infer drug safety from missing warnings, recommend an unsourced treatment, prescribe, conduct a public "
        "lookup or put private note/transcript text in a public query. Return each assignment's concrete expected "
        "output and completion criteria. Completion means a saved private draft for provider review only."
    )
    if with_directions:
        question += (
            "\n\nHuman drafting directions (not clinical facts or permission)\n"
            + json.dumps(directions, ensure_ascii=False)
            + "\nApply these directions only to the private drafts. They are not source evidence, consent, "
            "approval or authority to send, publish, prescribe, change records, use external tools or run a public search. "
            "Keep the exact saved-note and transcript facts separate; preserve missing information and provider review."
        )
    return replace(context, question=question)
