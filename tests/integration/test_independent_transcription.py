"""T2a independent transcription: fake processor, purge, jobs, gates; synthetic only."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from tests.integration.conftest import independent_consent, independent_payload
from tests.integration.test_private_recordings import attached, base, headers

from cosmas_os.adapters.local import InjectableClock, LocalBlobAdapter
from cosmas_os.application import independent_transcription as tx
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import BoxContext
from cosmas_os.ports.recording_transcription import FakeTranscriptionProcessor
from cosmas_os.private_recording_models import (
    IndependentRecordingAudioPurgeReceipt,
    IndependentRecordingAudioUpload,
    IndependentRecordingTranscript,
    IndependentRecordingTranscriptionJob,
)


def test_enabled_get_false_by_default(recording, session):
    f, draft, body = recording
    response = f.client.get(
        f"/workspaces/{draft['id']}/private-recordings/transcription-enabled",
        headers=headers(f),
    )
    assert response.status_code == 200
    assert response.json() == {"enabled": False}
    box = session.get(BoxContext, f.box)
    assert box is not None
    assert box.independent_recording_transcription_enabled is False


def test_switches_off_refuse_and_write_no_blob(recording, session, tmp_path, monkeypatch):
    f, draft, body, row = attached(recording)
    blob = LocalBlobAdapter(tmp_path / "off-blobs")
    monkeypatch.setattr(tx, "settings", f.configuration)
    monkeypatch.setattr(svc, "settings", f.configuration.model_copy(update={"blob_root": str(tmp_path / "off-blobs")}))
    now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    payload = independent_payload(now)
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            session, f.box, f.actor, draft["id"], row["recording_id"], payload,
            external=f.binding.id, blob=blob, clock=InjectableClock(now),
        )
    assert err.value.code == "independent_recording_transcription_disabled"
    assert not any(p.is_file() and p.suffix != ".meta" for p in (tmp_path / "off-blobs").rglob("*"))


def test_upload_process_read_duplicate_and_lost_receipt(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    audio = b"tone-synth-abcd"
    payload = independent_payload(now, audio)
    first = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert first["duplicate"] is False
    upload = c["session"].get(IndependentRecordingAudioUpload, first["upload_id"])
    assert upload is not None and upload.blob_key is not None
    assert first["upload_id"] in upload.blob_key and payload["sha256"] in upload.blob_key
    dup = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert dup["duplicate"] is True and dup["upload_id"] == first["upload_id"]
    started = tx.start_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert started["status"] == "ready"
    assert started["transcript"]["label"] == "SYNTHETIC TRANSCRIPT"
    job = c["session"].scalar(
        select(IndependentRecordingTranscriptionJob).where(
            IndependentRecordingTranscriptionJob.operation_id == payload["operation_id"]
        )
    )
    assert job is not None and job.state == "ready" and job.attempts == 1
    recovered = tx.start_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert recovered["recovered"] is True
    assert recovered["transcript"]["transcript_id"] == started["transcript"]["transcript_id"]


def test_corrupt_truncated_consent_lease_and_class_mismatch(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    bad = independent_payload(now, b"tone-synth", sha256="0" * 64)
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            bad, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_corrupt"
    short = independent_payload(now, b"ab")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        short, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    with pytest.raises(ws.WorkspaceError) as err:
        tx.start_transcription(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            {"operation_id": short["operation_id"]},
            external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_truncated"
    expired_lease = independent_payload(now, lease_expires_at=(now - timedelta(seconds=1)).isoformat())
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            expired_lease, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_lease_expired"
    too_long = independent_payload(now, lease_expires_at=(now + timedelta(hours=48)).isoformat())
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            too_long, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_lease_too_long"
    no_consent = independent_payload(now, consent={**independent_consent(now), "all_parties_consented": False})
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            no_consent, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_consent_required"
    mismatch = independent_payload(now, b"tone-class-xx", recording_class="real")
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            mismatch, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_recording_class_mismatch"


def test_processor_crash_recovery_retryable_and_revocation(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-crash-ok")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    crashing = FakeTranscriptionProcessor(crash_operations=frozenset({payload["operation_id"]}))
    with pytest.raises(ws.WorkspaceError) as err:
        tx.start_transcription(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            {"operation_id": payload["operation_id"]},
            external=c["external"], blob=c["blob"], clock=c["clock"], processor=crashing,
        )
    assert err.value.code == "independent_transcription_processor_crash"
    assert err.value.status == 503
    recovered = tx.start_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
        processor=FakeTranscriptionProcessor(),
    )
    assert recovered["status"] == "ready"

    retryable_payload = independent_payload(now, b"tone-retryable")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        retryable_payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    retrying = FakeTranscriptionProcessor(
        fail_operations={retryable_payload["operation_id"]: "retryable"}
    )
    with pytest.raises(ws.WorkspaceError) as err:
        tx.start_transcription(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            {"operation_id": retryable_payload["operation_id"]},
            external=c["external"], blob=c["blob"], clock=c["clock"], processor=retrying,
        )
    assert err.value.code == "independent_transcription_retryable"
    assert err.value.status == 503

    payload2 = independent_payload(now, b"tone-revoke-xx")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload2, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    started = tx.start_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload2["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    revoked = tx.revoke_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload2["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert revoked["audio_outcome"] == "purged"
    poll = tx.read_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        external=c["external"], operation_id=payload2["operation_id"],
    )
    assert poll["status"] == "ready" and poll.get("revoked") is True
    assert poll["transcript"]["transcript_id"] == started["transcript"]["transcript_id"]
    upload = c["session"].scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.operation_id == payload2["operation_id"]
        )
    )
    assert upload is not None and upload.blob_key is None and upload.audio_purged_at is not None


def test_purge_48h_boundary_receipts_transcripts_survive_and_failed_retry(enabled_case):
    c = enabled_case
    start = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    c["clock"].set(start)
    keep_payload = independent_payload(start, b"tone-keep-audio")
    purge_payload = independent_payload(start, b"tone-purge-audio")
    for payload in (keep_payload, purge_payload):
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            payload, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
        tx.start_transcription(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            {"operation_id": payload["operation_id"]},
            external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    keep = c["session"].scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.operation_id == keep_payload["operation_id"]
        )
    )
    purge_row = c["session"].scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.operation_id == purge_payload["operation_id"]
        )
    )
    assert keep is not None and purge_row is not None
    c["clock"].set(keep.audio_expires_at - timedelta(seconds=1))
    container = svc.Container(c["session"], clock=c["clock"], blob=c["blob"])
    assert tx.purge_due_recording_audio(container, c["f"].box, c["f"].actor) == []
    c["clock"].set(purge_row.audio_expires_at)
    receipts = tx.purge_due_recording_audio(container, c["f"].box, c["f"].actor)
    assert len(receipts) == 2
    for receipt in receipts:
        assert set(receipt) == {"upload_id", "retention_rule", "deleted_at", "outcome"}
        assert receipt["outcome"] == "purged"
    transcripts = c["session"].scalars(select(IndependentRecordingTranscript)).all()
    assert len(transcripts) == 2

    # Failed delete keeps blob_key and records failed for retry.
    fail_start = c["clock"].now()
    fail_payload = independent_payload(fail_start, b"tone-fail-del")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        fail_payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    fail_row = c["session"].scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.operation_id == fail_payload["operation_id"]
        )
    )
    assert fail_row is not None and fail_row.blob_key is not None
    c["clock"].set(fail_row.audio_expires_at)

    class BoomBlob(LocalBlobAdapter):
        def delete(self, key: str) -> None:
            raise RuntimeError("storage unavailable")

    boom = BoomBlob(c["blob"].root)
    failed = tx.purge_due_recording_audio(
        svc.Container(c["session"], clock=c["clock"], blob=boom), c["f"].box, c["f"].actor
    )
    assert any(item["outcome"] == "failed" for item in failed)
    c["session"].refresh(fail_row)
    assert fail_row.blob_key is not None and fail_row.audio_purged_at is None
    # Worker sweep with no switch gate / no actor still retries.
    retried = tx.purge_due_recording_audio(
        svc.Container(c["session"], clock=c["clock"], blob=c["blob"]), box_id=None, actor_id=None
    )
    assert any(item["upload_id"] == fail_row.id and item["outcome"] == "purged" for item in retried)
    c["session"].refresh(fail_row)
    assert fail_row.blob_key is None and fail_row.audio_purged_at is not None


def test_expired_audio_cannot_return_after_reupload(enabled_case):
    c = enabled_case
    start = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    c["clock"].set(start)
    payload = independent_payload(start, b"tone-expire-xx")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    row = c["session"].scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.operation_id == payload["operation_id"]
        )
    )
    assert row is not None
    c["clock"].set(row.audio_expires_at)
    container = svc.Container(c["session"], clock=c["clock"], blob=c["blob"])
    tx.purge_due_recording_audio(container, c["f"].box, c["f"].actor)
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            payload, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_audio_expired"


def test_cross_box_denied_with_second_box(enabled_case, session):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-cross-box")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    other = svc.provision_box(svc.Container(session), "Invented other practice")
    with pytest.raises(ws.WorkspaceError) as err:
        tx.read_transcription(
            c["session"],
            other["box_id"],
            other["owner_id"],
            c["draft"]["id"],
            c["row"]["recording_id"],
            external=c["external"],
            operation_id=payload["operation_id"],
        )
    assert err.value.status in {403, 404}


def test_account_delete_removes_blobs_uploads_transcripts_receipts(enabled_case, session, monkeypatch):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-account-del")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    tx.start_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload = c["session"].scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.operation_id == payload["operation_id"]
        )
    )
    assert upload is not None and upload.blob_key is not None
    c["clock"].set(upload.audio_expires_at)
    tx.purge_due_recording_audio(
        svc.Container(c["session"], clock=c["clock"], blob=c["blob"]), c["f"].box, c["f"].actor
    )
    assert c["session"].scalars(select(IndependentRecordingAudioPurgeReceipt)).first() is not None
    assert c["session"].scalars(select(IndependentRecordingTranscript)).first() is not None

    tx.wipe_owner_transcription_data(
        c["session"], box_id=c["f"].box, owner_id=c["f"].actor, blob=c["blob"]
    )
    c["session"].commit()
    assert c["session"].scalars(select(IndependentRecordingAudioUpload)).first() is None
    assert c["session"].scalars(select(IndependentRecordingTranscript)).first() is None
    assert c["session"].scalars(select(IndependentRecordingAudioPurgeReceipt)).first() is None
    assert c["session"].scalars(select(IndependentRecordingTranscriptionJob)).first() is None


def test_http_upload_and_enabled_true(enabled_case):
    c = enabled_case
    f, draft, row = c["f"], c["draft"], c["row"]
    enabled = f.client.get(
        f"/workspaces/{draft['id']}/private-recordings/transcription-enabled",
        headers=headers(f),
    )
    assert enabled.status_code == 200 and enabled.json() == {"enabled": True}
    now = datetime.now(UTC)
    audio = b"tone-http-body"
    body = {
        "operation_id": str(uuid4()),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "duration_ms": 1000,
        "language": "en-US",
        "lease_expires_at": (now + timedelta(hours=1)).isoformat(),
        "consent": independent_consent(now),
        "audio_base64": base64.b64encode(audio).decode(),
    }
    response = f.client.post(
        f"{base(draft)}/{row['recording_id']}/audio",
        headers=headers(f),
        json=body,
    )
    assert response.status_code == 200, response.text
    started = f.client.post(
        f"{base(draft)}/{row['recording_id']}/transcription",
        headers=headers(f),
        json={"operation_id": body["operation_id"]},
    )
    assert started.status_code == 200, started.text
    assert started.json()["transcript"]["segments"][0]["text"].startswith("SYNTHETIC TRANSCRIPT")
    polled = f.client.get(
        f"{base(draft)}/{row['recording_id']}/transcription",
        headers=headers(f),
        params={"operation_id": body["operation_id"]},
    )
    assert polled.status_code == 200, polled.text
    assert polled.json()["status"] == "ready"


def test_malformed_http_bodies_refused(enabled_case):
    c = enabled_case
    f, draft, row = c["f"], c["draft"], c["row"]
    bad = f.client.post(
        f"{base(draft)}/{row['recording_id']}/audio",
        headers=headers(f),
        json={"operation_id": "not-a-uuid", "sha256": "0" * 64},
    )
    assert bad.status_code == 422
    bad_poll = f.client.get(
        f"{base(draft)}/{row['recording_id']}/transcription",
        headers=headers(f),
        params={"operation_id": "not-a-uuid"},
    )
    assert bad_poll.status_code == 422
