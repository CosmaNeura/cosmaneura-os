"""T2a independent transcription: fake processor, purge, gates; synthetic only."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from tests.integration.test_private_recordings import attached, base, headers
from tests.integration.test_private_recordings import recording as _recording
from tests.integration.test_private_recordings import signed_workspace as _signed_workspace

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
)

recording = _recording
signed_workspace = _signed_workspace


@pytest.fixture
def enabled_case(recording, session, monkeypatch, tmp_path):
    f, draft, body, row = attached(recording)
    box = session.get(BoxContext, f.box)
    assert box is not None
    box.independent_recording_transcription_enabled = True
    session.commit()
    configuration = f.configuration.model_copy(
        update={"independent_recording_transcription_enabled": True, "blob_root": str(tmp_path / "blobs")}
    )
    monkeypatch.setattr(tx, "settings", configuration)
    monkeypatch.setattr(svc, "settings", configuration)
    from cosmas_os.api import app as api_module

    monkeypatch.setattr(api_module, "settings", configuration)
    clock = InjectableClock(datetime(2026, 11, 19, 12, 0, tzinfo=UTC))
    blob = LocalBlobAdapter(tmp_path / "blobs")
    tx.set_processor_override(FakeTranscriptionProcessor())
    try:
        yield {
            "f": f,
            "draft": draft,
            "row": row,
            "session": session,
            "clock": clock,
            "blob": blob,
            "external": f.binding.id,
        }
    finally:
        tx.set_processor_override(None)


def _consent(now: datetime) -> dict:
    return {
        "modality": "in_person",
        "participant_regions": [],
        "method": "verbal_attestation",
        "all_parties_consented": True,
        "granted_at": (now - timedelta(seconds=1)).isoformat(),
    }


def _payload(now: datetime, audio: bytes = b"tone-synth", **changes) -> dict:
    body = {
        "operation_id": str(uuid4()),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "duration_ms": 1000,
        "language": "en-US",
        "recording_class": "synthetic",
        "lease_expires_at": (now + timedelta(hours=1)).isoformat(),
        "consent": _consent(now),
        "audio": audio,
    }
    body.update(changes)
    return body


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
    payload = _payload(now)
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            session, f.box, f.actor, draft["id"], row["recording_id"], payload,
            external=f.binding.id, blob=blob, clock=InjectableClock(now),
        )
    assert err.value.code == "independent_recording_transcription_disabled"
    assert list((tmp_path / "off-blobs").rglob("*")) == [] or not any(
        p.is_file() and p.suffix != ".meta" for p in (tmp_path / "off-blobs").rglob("*")
    )


def test_upload_process_read_duplicate_and_lost_receipt(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    audio = b"tone-synth-abcd"
    payload = _payload(now, audio)
    first = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert first["duplicate"] is False
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
    assert started["transcript"]["segments"][0]["text"].startswith("SYNTHETIC TRANSCRIPT")
    recovered = tx.start_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert recovered["recovered"] is True
    assert recovered["transcript"]["transcript_id"] == started["transcript"]["transcript_id"]


def test_corrupt_truncated_consent_lease(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    bad = _payload(now, b"tone-synth", sha256="0" * 64)
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            bad, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_corrupt"
    short = _payload(now, b"ab")
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
    expired_lease = _payload(now, lease_expires_at=(now - timedelta(seconds=1)).isoformat())
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            expired_lease, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_lease_expired"
    no_consent = _payload(now, consent={**_consent(now), "all_parties_consented": False})
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            no_consent, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_consent_required"


def test_processor_crash_recovery_and_revocation(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = _payload(now, b"tone-crash-ok")
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
    recovered = tx.start_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
        processor=FakeTranscriptionProcessor(),
    )
    assert recovered["status"] == "ready"

    payload2 = _payload(now, b"tone-revoke-xx")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload2, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    tx.revoke_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload2["operation_id"]},
        external=c["external"], clock=c["clock"],
    )
    with pytest.raises(ws.WorkspaceError) as err:
        tx.start_transcription(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            {"operation_id": payload2["operation_id"]},
            external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_revoked"


def test_purge_48h_boundary_receipts_transcripts_survive(enabled_case):
    c = enabled_case
    start = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    c["clock"].set(start)
    keep_payload = _payload(start, b"tone-keep-audio")
    purge_payload = _payload(start, b"tone-purge-audio")
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
    # 47:59:59 — still kept
    c["clock"].set(keep.audio_expires_at - timedelta(seconds=1))
    container = svc.Container(c["session"], clock=c["clock"], blob=c["blob"])
    assert tx.purge_due_recording_audio(container, c["f"].box, c["f"].actor) == []
    # Exactly 48:00:00 — purge
    c["clock"].set(purge_row.audio_expires_at)
    receipts = tx.purge_due_recording_audio(container, c["f"].box, c["f"].actor)
    assert len(receipts) == 2
    for receipt in receipts:
        assert set(receipt) == {"upload_id", "retention_rule", "deleted_at", "outcome"}
        assert receipt["retention_rule"] == "audio_plus_48h"
        assert "patient" not in str(receipt).lower()
        assert "/" not in receipt["upload_id"]
        assert "sha256" not in receipt
        assert "blob" not in receipt
    stored = c["session"].scalars(select(IndependentRecordingAudioPurgeReceipt)).all()
    assert len(stored) == 2
    assert all(r.detail is None for r in stored)
    transcripts = c["session"].scalars(select(IndependentRecordingTranscript)).all()
    assert len(transcripts) == 2
    for row in c["session"].scalars(select(IndependentRecordingAudioUpload)).all():
        assert row.audio_purged_at is not None
        assert row.blob_key is None


def test_expired_audio_cannot_return_after_reupload(enabled_case):
    c = enabled_case
    start = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    c["clock"].set(start)
    payload = _payload(start, b"tone-expire-xx")
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


def test_real_patient_refused_without_gate(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = _payload(now, b"tone-real-xxxx", recording_class="real")
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            payload, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "real_patient_recording_refused"


def test_cross_box_denied(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = _payload(now, b"tone-cross-box")
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], str(uuid4()), c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            payload, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.status in {403, 404}


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
        "recording_class": "synthetic",
        "lease_expires_at": (now + timedelta(hours=1)).isoformat(),
        "consent": _consent(now),
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

