"""Actual Scribe-source, native review and note revision services; invented data.

Speech recognition, remote consent and translation production are not simulated
as successful network operations. The supplied creator-review receipt is an
invented boundary fixture; local persistence and review are real application code.
"""

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.application import conversation, note_review, scribe_source, workspace
from cosmas_os.config import settings
from cosmas_os.models import WorkspaceEntry, WorkspaceNote, WorkspaceNoteReview, WorkspaceReply
from cosmas_os.ports.core_capture import CoreConsentAttestation
from cosmas_os.ports.core_encounters import RecordPatient
from cosmas_os.ports.creator_review import CreatorReviewView, ProviderEncounter
from lab.store import LabError

SCENARIOS = ("transcript_without_notebook", "draft_revision_review", "source_revision_change",
             "stale_snapshot", "missing_dob_consent", "translation_lineage", "prep_sources")
PLAN = "Clinician: The outside records have not been reviewed. Plan: request the outside records."
REPORT = "Patient: I report no chest pain today. My date of birth is not available right now."
CORRECTED = "Clinician correction: The outside records have not been reviewed. Plan: request records next week."


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@contextmanager
def _native_only():
    old = settings.workspace_llm_backend
    try:
        settings.workspace_llm_backend = "disabled"
        yield
    finally:
        settings.workspace_llm_backend = old


def transcript(*, prior=None, translated=False, corrected=False):
    """Invented, typed creator-review input, not audio/ASR acceptance evidence."""
    if translated:
        fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/creator_review.json"
        value = json.loads(fixture.read_text())["ready"]
        return CreatorReviewView.model_validate(value)
    session_id = prior.session_id if prior else uuid4()
    working_id = prior.working.working_transcript_id if prior else uuid4()
    version = prior.source.source_transcript_version + 1 if prior else 1
    originals, working = [], []
    for index, (role, content) in enumerate((("patient", REPORT), ("clinician", CORRECTED if corrected else PLAN))):
        source_id = prior.source.segments[index].source_segment_id if prior else uuid4()
        speaker_id = prior.source.segments[index].speaker_id if prior else uuid4()
        origin = {"source_segment_id": source_id, "source_segment_version": version,
                  "source_locale": "en-US", "speaker_id": speaker_id, "speaker_role": role,
                  "start_ms": index * 1000, "end_ms": (index + 1) * 1000}
        originals.append({**origin, "content": content, "locale_confidence": 1.0})
        working.append({**origin, "resolution": "english_source", "content": content})
    return CreatorReviewView.model_validate({"schema_version": "1.0", "session_id": session_id,
        "status": "transcript_ready", "source": {"schema_version": "1.0",
            "source_transcript_version": version, "language_mode": "en-US",
            "transcription_adapter_id": "invented_typed_fixture", "transcription_model_profile_id": "no_asr_model",
            "normalization_profile_id": "invented_fixture", "duration_ms": 2000, "segments": originals},
        "working": {"schema_version": "1.0", "working_transcript_id": working_id,
            "working_transcript_version": version, "source_transcript_version": version,
            "segments": working, "blockers": [], "note_ready": True},
        "review_queue": {"schema_version": "1.0", "session_id": session_id,
            "source_transcript_version": version, "working_transcript_id": working_id,
            "working_transcript_version": version, "status": "complete", "items": []}})


def _source_artifacts(s, ids):
    artifacts = []
    for identity in ids:
        row = s.get(WorkspaceEntry, identity)
        if row is None:
            raise LabError("saved_transcript_entry_missing")
        artifacts.append({"kind": "reviewed_transcript_snapshot", "record_id": row.id, "revision": row.revision,
            "sha256": _sha(row.content), "content": row.content,
            "review_state": "transcript_snapshot_shared; not_note_reviewed"})
    return artifacts


def _note_artifact(note, stage):
    return {"kind": "draft_note", "stage": stage, "record_id": note["id"], "revision": note["version"],
            "sha256": _sha(note["content"]), "content_hash": note["content_hash"],
            "source_fingerprint": note["source_fingerprint"], "content": note["content"],
            "review_state": "privately_reviewed" if note["review"] else "unreviewed",
            "review_id": note["review"]["id"] if note["review"] else None}


def _deny(checks, check_name, expected_error, operation, *args, **kwargs):
    try:
        operation(*args, **kwargs)
    except workspace.WorkspaceError as error:
        args[0].rollback()
        if error.code != expected_error:
            raise LabError(check_name + "_wrong_failure_reason") from error
        checks[check_name] = True
    else:
        raise LabError(check_name + "_unexpectedly_allowed")


def exercise(app, store, episode, scenario="transcript_without_notebook"):
    if scenario not in SCENARIOS:
        raise LabError("unknown_documentation_scenario")
    with _native_only():
        return _exercise(app, store.root / episode / "documentation" / scenario, scenario)


def _exercise(app, root, scenario):
    checks, artifacts, steps = {}, [], []
    scope = app.box, app.owner, app.workspace
    view = transcript(translated=scenario == "translation_lineage")
    chosen = scribe_source.selection(view)
    assert chosen is not None and view.working is not None
    checked = ProviderEncounter(schema_version="1.0", status="available", review=view)
    with Session(app.engine) as s:
        snapshot = workspace.read(s, *scope)
        before = snapshot["revision"]
        saved = scribe_source.save_snapshot(s, box=app.box, owner=app.owner, workspace_id=app.workspace,
            expected=before, key="documentation-source", selected=chosen, checked=checked)
        source_ids = [entry["entry_id"] for entry in saved["entries"]]
        artifacts.extend(_source_artifacts(s, source_ids))
        recovered = scribe_source.saved_snapshot(s, box=app.box, owner=app.owner, workspace_id=app.workspace,
            expected=before, key="documentation-source", selected=chosen)
        assert recovered is not None
        checks["saved_source_replay_is_exact"] = recovered["entries"] == saved["entries"]
        steps.append({"role": "simulated_provider", "action": "share_reviewed_transcript_snapshot",
                      "record_ids": source_ids, "snapshot_sha256": chosen.snapshot_sha256,
                      "source_transcript_version": chosen.source_transcript_version,
                      "working_transcript_version": chosen.working_transcript_version})
        if scenario == "prep_sources":
            prep_text = ("AI-prepared Session Prep; derived summary, not the underlying note. "
                         "Freshness: stale. Coverage: partial. Patient-reported: DOB unavailable. "
                         "Open thread: outside records not yet reviewed. Talking point: confirm the plan to request records.")
            prep = workspace.append(s, *scope, expected=saved["entry_revision"], key="documentation-prep",
                kind="evidence", content=prep_text, source_label="Invented derived Session Prep")
            artifacts.append({"kind": "derived_preparation", "record_id": prep["entry_id"],
                "revision": prep["entry_revision"], "sha256": _sha(prep_text), "content": prep_text,
                "review_state": "derived_summary; not_underlying_clinician_note"})
        current = workspace.read(s, *scope)
        question = "Review the supplied transcript and preparation without changing reported facts or plans."
        reply = conversation.ask(s, *scope, expected=current["revision"], team_revision=app.team_revision,
            key="documentation-native-review", role="scribe", content=question)
        row = s.get(WorkspaceReply, reply["entry_id"])
        assert row is not None
        citation_ids = {item["entry_id"] for item in row.citations}
        checks["native_scribe_uses_saved_transcript_without_notebook"] = bool(citation_ids.intersection(source_ids))
        checks["native_lookup_is_not_generated_note_or_signoff"] = (
            row.backend == "local_source_review_v1" and "not a generated or reviewed clinical note" in row.content)
        combined_source = "\n".join(item["content"] for item in artifacts if item["record_id"] in source_ids)
        expected_text = view.working.segments[0].content
        assert expected_text is not None
        checks["speaker_report_and_exact_source_text_preserved"] = expected_text in combined_source
        checks["source_segment_versions_available_for_corrections"] = all(
            str(item.source_segment_id) in combined_source
            and f"version {item.source_segment_version}; source language:" in combined_source
            for item in view.working.segments)
        artifacts.append({"kind": "native_scribe_review", "record_id": row.entry_id,
            "sha256": _sha(row.content), "content": row.content, "citations": row.citations,
            "review_state": "source_lookup; not_generated_clinical_note"})
        if scenario == "prep_sources":
            checks["derived_preparation_reaches_native_scribe"] = prep["entry_id"] in citation_ids and prep_text in row.content
        if scenario == "translation_lineage":
            segment = view.working.segments[0]
            checks["reviewed_translation_keeps_exact_lineage"] = (
                str(segment.translation_review_id) in combined_source
                and "resolution: spanish_translation" in combined_source)
        if scenario == "missing_dob_consent":
            patient = RecordPatient(patient_ref="patient_" + "0" * 25 + "1", display_name="Invented Cypress")
            checks["missing_dob_does_not_block_saved_encounter_documentation"] = (
                "date_of_birth" not in patient.model_dump() and reply["entry_id"] is not None)
            consent = {"modality": "in_person", "participant_regions": (), "method": "verbal_attestation",
                       "all_parties_consented": True, "granted_at": datetime.now(UTC)}
            CoreConsentAttestation.model_validate(consent)
            for invalid in (False, None, 1):
                try:
                    CoreConsentAttestation.model_validate({**consent, "all_parties_consented": invalid})
                except ValidationError:
                    continue
                raise LabError("implicit_recording_consent_accepted")
            checks["missing_dob_does_not_waive_explicit_consent"] = True
        draft_text = ("SYNTHETIC draft for review. Patient reports no chest pain today. "
                      "DOB is not available. Records have not been reviewed. Plan: request outside records.")
        if scenario == "translation_lineage":
            draft_text = "SYNTHETIC draft for review. Patient statement in reviewed translation: I do not have a fever."
        current = workspace.read(s, *scope)
        drafted = note_review.save(s, *scope, expected=current["revision"], key="documentation-note",
            base_note_id=None, source_reply_id=None, content=draft_text)["workspace"]
        note = drafted["note"]["latest"]
        artifacts.append(_note_artifact(note, "initial_draft"))
        steps.append({"role": "simulated_provider", "action": "save_draft_from_exact_sources",
            "record_id": note["id"], "content_hash": note["content_hash"],
            "source_fingerprint": note["source_fingerprint"], "source_record_ids": source_ids})
        _deny(checks, "agent_cannot_review_clinical_note", "workspace_access_denied", note_review.review,
            s, app.box, app.agent_id("scribe"), app.workspace, note["id"], expected=drafted["revision"],
            key="documentation-agent-review-denied", content_hash=note["content_hash"], source_hash=note["source_fingerprint"])
        reviewed = note_review.review(s, *scope, note["id"], expected=drafted["revision"], key="documentation-review",
            content_hash=note["content_hash"], source_hash=note["source_fingerprint"])["workspace"]
        artifacts.append(_note_artifact(reviewed["note"]["latest"], "initial_private_review"))
        checks["review_is_exact_and_human_owned"] = reviewed["note"]["latest"]["review"]["reviewer_id"] == app.owner
        steps.append({"role": "simulated_provider", "action": "private_note_review", "record_id": note["id"],
            "review_id": reviewed["note"]["latest"]["review"]["id"], "content_hash": note["content_hash"],
            "meaning": "simulated human private review; not clinical sign-off"})
        if scenario == "draft_revision_review":
            revision_text = draft_text + " Clarify who will request the records and the target date; neither is confirmed."
            steps.append({"role": "simulated_reviewer", "action": "request_revision", "record_id": note["id"],
                "content_hash": note["content_hash"], "request": "Preserve unknown owner and target date as questions."})
            revised = note_review.save(s, *scope, expected=reviewed["revision"], key="documentation-note-revision",
                base_note_id=note["id"], source_reply_id=None, content=revision_text)["workspace"]
            latest = revised["note"]["latest"]
            artifacts.append(_note_artifact(latest, "requested_revision"))
            checks["editing_requires_new_exact_review"] = latest["review"] is None and latest["version"] == 2
            final_review = note_review.review(s, *scope, latest["id"], expected=revised["revision"],
                key="documentation-review-revision", content_hash=latest["content_hash"],
                source_hash=latest["source_fingerprint"])["workspace"]
            artifacts.append(_note_artifact(final_review["note"]["latest"], "revised_private_review"))
            steps.append({"role": "simulated_provider", "action": "private_revision_review",
                "record_id": latest["id"], "content_hash": latest["content_hash"],
                "review_id": final_review["note"]["latest"]["review"]["id"], "supersedes_note_id": note["id"]})
        if scenario in {"source_revision_change", "stale_snapshot"}:
            changed_view = transcript(prior=view, corrected=True)
            changed_selected = scribe_source.selection(changed_view)
            assert changed_selected is not None
            changed_checked = ProviderEncounter(schema_version="1.0", status="available", review=changed_view)
            current = workspace.read(s, *scope)
            _deny(checks, "stale_transcript_selection_cannot_be_saved", "scribe_source_changed", scribe_source.save_snapshot,
                s, box=app.box, owner=app.owner, workspace_id=app.workspace, expected=current["revision"],
                key="documentation-stale-source", selected=chosen, checked=changed_checked)
            changed = scribe_source.save_snapshot(s, box=app.box, owner=app.owner, workspace_id=app.workspace,
                expected=current["revision"], key="documentation-corrected-source", selected=changed_selected,
                checked=changed_checked)
            changed_ids = [entry["entry_id"] for entry in changed["entries"]]
            artifacts.extend(_source_artifacts(s, changed_ids))
            latest = workspace.read(s, *scope)["note"]["latest"]
            checks["corrected_transcript_marks_previous_note_sources_changed"] = latest["sources_changed"]
            _deny(checks, "old_note_review_cannot_be_reused_for_new_source", "note_sources_or_content_changed", note_review.review,
                s, *scope, note["id"], expected=changed["entry_revision"], key="documentation-stale-note-review",
                content_hash=note["content_hash"], source_hash=note["source_fingerprint"])
            steps.append({"role": "simulated_provider", "action": "share_corrected_transcript_snapshot",
                "record_ids": changed_ids, "snapshot_sha256": changed_selected.snapshot_sha256,
                "supersedes_source_snapshot_sha256": chosen.snapshot_sha256,
                "note_re_review_required": True})
        state = workspace.read(s, *scope)
        last_note = state["note"]["latest"]
        expected_note = (last_note["id"], last_note["content_hash"], last_note["source_fingerprint"], last_note["sources_changed"])
        persisted_ids = set(s.scalars(select(WorkspaceNote.id).where(WorkspaceNote.workspace_id == app.workspace)))
        checks["note_versions_are_persisted_records"] = all(
            item["record_id"] in persisted_ids for item in artifacts if item["kind"] == "draft_note")
    app.engine.dispose()
    with Session(app.engine) as s:
        reopened = workspace.read(s, *scope)
        last = reopened["note"]["latest"]
        checks["note_source_review_state_survives_reopen"] = expected_note == (
            last["id"], last["content_hash"], last["source_fingerprint"], last["sources_changed"])
        checks["all_reported_reviews_exist"] = all(s.get(WorkspaceNoteReview, item["review_id"]) is not None
            for item in artifacts if item.get("review_id"))
    root.mkdir(parents=True, exist_ok=True)
    result = {"capability": "documentation", "scenario": scenario, "passed": all(checks.values()),
        "checks": checks, "workspace_id": app.workspace, "persistent_artifacts": artifacts, "review_steps": steps,
        "source_selection": chosen.model_dump(mode="json"), "final_note_id": last["id"],
        "material": last["content"],
        "evidence_level": "Real local source custody, native bot review, note revisions and private review; invented typed transcript and scripted humans.",
        "limits": ["No audio or transcription model was run.", "Missing-DOB check covers saved encounter documentation and consent contract, not device capture.",
                   "Private note review is not clinical sign-off. No external record, diagnosis, treatment or message was changed."]}
    (root / "documentation-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
