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


def test_cross_box_denied_with_second_box(enabled_case, session, monkeypatch):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-cross-box")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    other = svc.provision_box(svc.Container(session), "Invented other practice")
    other_box = session.get(BoxContext, other["box_id"])
    assert other_box is not None
    other_box.independent_recording_transcription_enabled = True
    session.commit()
    # Process switch stays on via enabled_case monkeypatch; second Box is opted in.
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
    assert err.value.code == "private_recording_access_denied"
    assert err.value.status == 403


def test_delete_own_account_removes_transcription_blob(enabled_case, monkeypatch):
    from cosmas_os.application.account_deletion import CONFIRM_PHRASE, delete_own_account
    from cosmas_os.domain.enums import PrincipalState
    from cosmas_os.models import Principal

    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-account-del")
    uploaded = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload = c["session"].get(IndependentRecordingAudioUpload, uploaded["upload_id"])
    assert upload is not None and upload.blob_key is not None
    blob_key = upload.blob_key
    assert c["blob"].get_bytes(blob_key)

    class FakeClerk:
        def require_user(self, subject: str) -> dict:
            return {"id": subject}

        def delete_user(self, subject: str) -> None:
            return None

    monkeypatch.setattr(svc, "settings", c["f"].configuration.model_copy(
        update={"blob_root": str(c["blob"].root)}
    ))
    delete_own_account(
        c["session"],
        box_id=c["f"].box,
        principal_id=c["f"].actor,
        external_identity_id=c["external"],
        confirm=CONFIRM_PHRASE,
        clerk=FakeClerk(),
    )
    c["session"].commit()
    actor = c["session"].get(Principal, c["f"].actor)
    assert actor is not None and actor.state == PrincipalState.TOMBSTONED.value
    assert c["session"].scalars(select(IndependentRecordingAudioUpload)).first() is None
    assert c["session"].scalars(select(IndependentRecordingTranscriptionJob)).first() is None
    with pytest.raises(FileNotFoundError):
        c["blob"].get_bytes(blob_key)


def test_wipe_owner_raises_when_blob_delete_fails(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-wipe-fail")
    uploaded = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload = c["session"].get(IndependentRecordingAudioUpload, uploaded["upload_id"])
    assert upload is not None and upload.blob_key is not None

    class BoomBlob(LocalBlobAdapter):
        def delete(self, key: str) -> None:
            raise RuntimeError("storage unavailable")

    with pytest.raises(ws.WorkspaceError) as err:
        tx.wipe_owner_transcription_data(
            c["session"], box_id=c["f"].box, owner_id=c["f"].actor, blob=BoomBlob(c["blob"].root)
        )
    assert err.value.code == "independent_transcription_unavailable"
    assert err.value.status == 503
    c["session"].rollback()
    c["session"].refresh(upload)
    assert upload.blob_key is not None
    assert c["blob"].get_bytes(upload.blob_key)


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


def test_http_purge_owner_and_non_owner(enabled_case, session):
    from cosmas_os.models import ExternalIdentity, Principal

    c = enabled_case
    f, draft, row = c["f"], c["draft"], c["row"]
    now = datetime.now(UTC)
    audio = b"tone-purge-http"
    body = {
        "operation_id": str(uuid4()),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "duration_ms": 1000,
        "language": "en-US",
        "lease_expires_at": (now + timedelta(hours=1)).isoformat(),
        "consent": independent_consent(now),
        "audio_base64": base64.b64encode(audio).decode(),
    }
    assert f.client.post(
        f"{base(draft)}/{row['recording_id']}/audio", headers=headers(f), json=body
    ).status_code == 200
    purged = f.client.post(
        f"/workspaces/{draft['id']}/private-recordings/audio-purge",
        headers=headers(f),
    )
    assert purged.status_code == 200, purged.text
    assert "receipts" in purged.json()

    peer = Principal(
        box_id=f.box, principal_type="human", display_name="Invented purge peer",
        state="active", is_owner=False,
    )
    session.add(peer)
    session.flush()
    session.add(ExternalIdentity(
        box_id=f.box, principal_id=peer.id, provider="clerk",
        issuer=f.configuration.clerk_issuer, subject="user_purge_peer",
        organization_id=f.configuration.clerk_organization_id,
        reviewed_by="Invented reviewer", evidence_ref="test:purge-peer",
    ))
    session.commit()
    peer_headers = {**headers(f), "Authorization": "Bearer " + f.token(sub="user_purge_peer")}
    denied = f.client.post(
        f"/workspaces/{draft['id']}/private-recordings/audio-purge",
        headers=peer_headers,
    )
    assert denied.status_code == 404


def test_http_switch_and_route_refusals(recording, monkeypatch, tmp_path):
    f, draft, body, row = attached(recording)
    configuration = f.configuration.model_copy(
        update={"independent_recording_transcription_enabled": False, "blob_root": str(tmp_path / "off")}
    )
    monkeypatch.setattr(tx, "settings", configuration)
    from cosmas_os.api import app as api_module

    monkeypatch.setattr(api_module, "settings", configuration)
    monkeypatch.setattr(svc, "settings", configuration)
    now = datetime.now(UTC)
    audio = b"tone-switch-off"
    upload_body = {
        "operation_id": str(uuid4()),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "duration_ms": 1000,
        "language": "en-US",
        "lease_expires_at": (now + timedelta(hours=1)).isoformat(),
        "consent": independent_consent(now),
        "audio_base64": base64.b64encode(audio).decode(),
    }
    oid = upload_body["operation_id"]
    assert f.client.post(
        f"{base(draft)}/{row['recording_id']}/audio", headers=headers(f), json=upload_body
    ).status_code == 403
    assert f.client.post(
        f"{base(draft)}/{row['recording_id']}/transcription",
        headers=headers(f),
        json={"operation_id": oid},
    ).status_code == 403
    assert f.client.get(
        f"{base(draft)}/{row['recording_id']}/transcription",
        headers=headers(f),
        params={"operation_id": oid},
    ).status_code == 403
    assert f.client.get(
        f"{base(draft)}/{row['recording_id']}/transcript",
        headers=headers(f),
        params={"operation_id": oid},
    ).status_code == 403


def test_recent_claim_refuses_second_start(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-claim-lease")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload = c["session"].scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.operation_id == payload["operation_id"]
        )
    )
    assert upload is not None
    job = tx._claim_job(c["session"], upload=upload, now=now)
    assert job.state == "claimed" and job.attempts == 1
    c["session"].commit()
    with pytest.raises(ws.WorkspaceError) as err:
        tx.start_transcription(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            {"operation_id": payload["operation_id"]},
            external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_unavailable"
    assert err.value.status == 503


def test_revoke_during_processing_finishes_revoked(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-revoke-race")
    uploaded = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload = c["session"].get(IndependentRecordingAudioUpload, uploaded["upload_id"])
    assert upload is not None
    job = tx._claim_job(c["session"], upload=upload, now=now)
    claim_attempt = job.attempts
    c["session"].commit()
    revoked = tx.revoke_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert revoked["status"] == "revoked"
    from cosmas_os.ports.recording_transcription import TranscriptionRequest

    outcome = FakeTranscriptionProcessor().transcribe(
        TranscriptionRequest(
            audio=b"tone-revoke-race",
            sha256=payload["sha256"],
            duration_ms=1000,
            language="en-US",
            operation_id=payload["operation_id"],
            synthetic=True,
        )
    )
    with pytest.raises(ws.WorkspaceError) as err:
        tx._finish_transcription(
            c["session"],
            c=svc.Container(c["session"], clock=c["clock"], blob=c["blob"]),
            upload_id=upload.id,
            box_id=c["f"].box,
            owner_id=c["f"].actor,
            wid=c["draft"]["id"],
            rid=c["row"]["recording_id"],
            operation_id=payload["operation_id"],
            outcome=outcome,
            now=c["clock"].now(),
            claim_attempt=claim_attempt,
        )
    assert err.value.code == "independent_transcription_revoked"
    assert err.value.status == 409


def test_revoke_works_when_process_switch_off(enabled_case, monkeypatch):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-revoke-off")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    monkeypatch.setattr(
        tx, "settings", c["f"].configuration.model_copy(
            update={"independent_recording_transcription_enabled": False}
        )
    )
    revoked = tx.revoke_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert revoked["status"] == "revoked"
    assert revoked["audio_outcome"] == "purged"


def test_unbound_recording_fails_closed_outside_synthetic(enabled_case, monkeypatch):
    from cosmas_os.config import Settings

    c = enabled_case
    # Build through Settings(...) so a drifted field name fails closed at construct time.
    configured = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        data_mode="authorized_beta",
        independent_recording_transcription_enabled=True,
        blob_root=str(c["blob"].root),
    )
    monkeypatch.setattr(tx, "settings", configured)
    with pytest.raises(ws.WorkspaceError) as err:
        tx._derive_recording_class(c["session"], c["f"].box, c["row"]["recording_id"])
    assert err.value.code == "real_patient_recording_refused"
    assert err.value.status == 403


def test_attempts_exhausted_commits_terminal_before_raise(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-attempts-x")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload = c["session"].scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.operation_id == payload["operation_id"]
        )
    )
    assert upload is not None
    job = IndependentRecordingTranscriptionJob(
        id=str(uuid4()),
        upload_id=upload.id,
        recording_id=upload.recording_id,
        workspace_id=upload.workspace_id,
        box_id=upload.box_id,
        owner_id=upload.owner_id,
        operation_id=upload.operation_id,
        state="pending",
        attempts=tx.MAX_JOB_ATTEMPTS,
    )
    c["session"].add(job)
    c["session"].commit()
    with pytest.raises(ws.WorkspaceError) as err:
        tx._claim_job(c["session"], upload=upload, now=now)
    assert err.value.code == "independent_transcription_failed"
    c["session"].expire_all()
    stored = c["session"].get(IndependentRecordingTranscriptionJob, job.id)
    assert stored is not None
    assert stored.state == "failed_terminal"
    assert stored.error_kind == "attempts_exhausted"


def test_upload_put_fails_once_then_retry_leaves_readable_blob(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-put-retry")

    class FlakyBlob(LocalBlobAdapter):
        def __init__(self, root):
            super().__init__(root)
            self.failures_left = 1

        def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
            if self.failures_left > 0:
                self.failures_left -= 1
                raise RuntimeError("injected put failure")
            return super().put_bytes(key, data, content_type)

    flaky = FlakyBlob(c["blob"].root)
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            payload, external=c["external"], blob=flaky, clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_unavailable"
    assert err.value.status == 503
    row = c["session"].scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.operation_id == payload["operation_id"]
        )
    )
    assert row is not None and row.blob_key is not None
    with pytest.raises(FileNotFoundError):
        flaky.get_bytes(row.blob_key)

    retried = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=flaky, clock=c["clock"],
    )
    assert retried["duplicate"] is True
    assert flaky.get_bytes(row.blob_key) == payload["audio"]
    started = tx.start_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=flaky, clock=c["clock"],
    )
    assert started["status"] == "ready"


def test_duplicate_after_recording_class_change_refuses_without_put(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-dup-class")
    uploaded = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload = c["session"].get(IndependentRecordingAudioUpload, uploaded["upload_id"])
    assert upload is not None and upload.blob_key is not None
    upload.recording_class = "real"
    c["session"].commit()

    puts: list[str] = []
    original_put = c["blob"].put_bytes

    def counting_put(key: str, data: bytes, content_type: str) -> str:
        puts.append(key)
        return original_put(key, data, content_type)

    c["blob"].put_bytes = counting_put  # type: ignore[method-assign]
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            payload, external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_transcription_recording_class_mismatch"
    assert puts == []


def test_duplicate_fence_raise_refuses_without_put(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-dup-fence")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    puts: list[str] = []
    original_put = c["blob"].put_bytes

    def counting_put(key: str, data: bytes, content_type: str) -> str:
        puts.append(key)
        return original_put(key, data, content_type)

    c["blob"].put_bytes = counting_put  # type: ignore[method-assign]

    def boom_fence() -> None:
        raise ws.WorkspaceError("independent_transcription_fence", 503)

    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            payload, external=c["external"], blob=c["blob"], clock=c["clock"], fence=boom_fence,
        )
    assert err.value.code == "independent_transcription_fence"
    assert puts == []


def test_healthy_duplicate_skips_put_and_audit(enabled_case):
    from cosmas_os.models import AuditEvent

    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-dup-healthy")
    first = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    audits_before = c["session"].scalars(
        select(AuditEvent).where(
            AuditEvent.aggregate_id == first["upload_id"],
            AuditEvent.event_type == "recording_audio.uploaded",
        )
    ).all()
    assert len(audits_before) == 1

    puts: list[str] = []
    original_put = c["blob"].put_bytes

    def counting_put(key: str, data: bytes, content_type: str) -> str:
        puts.append(key)
        return original_put(key, data, content_type)

    c["blob"].put_bytes = counting_put  # type: ignore[method-assign]
    second = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert second["duplicate"] is True
    assert puts == []
    audits_after = c["session"].scalars(
        select(AuditEvent).where(
            AuditEvent.aggregate_id == first["upload_id"],
            AuditEvent.event_type == "recording_audio.uploaded",
        )
    ).all()
    assert len(audits_after) == 1


def test_unavailable_processor_failure_is_retryable(enabled_case):
    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-unavailable")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    failing = FakeTranscriptionProcessor(
        fail_operations={payload["operation_id"]: "unavailable"}
    )
    with pytest.raises(ws.WorkspaceError) as err:
        tx.start_transcription(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            {"operation_id": payload["operation_id"]},
            external=c["external"], blob=c["blob"], clock=c["clock"], processor=failing,
        )
    assert err.value.code == "independent_transcription_unavailable"
    assert err.value.status == 503
    job = c["session"].scalar(
        select(IndependentRecordingTranscriptionJob).where(
            IndependentRecordingTranscriptionJob.operation_id == payload["operation_id"]
        )
    )
    assert job is not None and job.state == "failed_retryable" and job.error_kind == "unavailable"
    recovered = tx.start_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
        processor=FakeTranscriptionProcessor(),
    )
    assert recovered["status"] == "ready"


def test_finish_lock_timeout_returns_503(enabled_case, engine):
    """Hold the upload row from a second PG backend; finish must map the real lock timeout to 503."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from cosmas_os.ports.recording_transcription import TranscriptionRequest

    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-lock-to")
    uploaded = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload = c["session"].get(IndependentRecordingAudioUpload, uploaded["upload_id"])
    assert upload is not None
    job = tx._claim_job(c["session"], upload=upload, now=now)
    claim_attempt = job.attempts
    c["session"].commit()
    # Nested-savepoint commits are invisible to other backends; persist so the
    # holder connection can take the real row lock. owned_database_isolation
    # truncates committed rows before the next test on the workspace profile.
    outer = c["session"].connection()
    outer.commit()
    outer.begin()

    upload_id = upload.id
    box_id, owner_id = c["f"].box, c["f"].actor
    wid, rid, oid = c["draft"]["id"], c["row"]["recording_id"], payload["operation_id"]
    held, release = Event(), Event()
    holder_pid: list[int] = []

    def hold_upload_row() -> None:
        with Session(engine) as holder:
            holder.execute(text("SET LOCAL lock_timeout = '30s'"))
            holder_pid.append(holder.scalar(text("SELECT pg_backend_pid()")))
            locked = holder.get(IndependentRecordingAudioUpload, upload_id, with_for_update=True)
            assert locked is not None
            held.set()
            assert release.wait(30), "finish never finished waiting on the held upload lock"
            holder.rollback()

    outcome = FakeTranscriptionProcessor().transcribe(
        TranscriptionRequest(
            audio=b"tone-lock-to",
            sha256=payload["sha256"],
            duration_ms=1000,
            language="en-US",
            operation_id=oid,
            synthetic=True,
        )
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(hold_upload_row)
        assert held.wait(5), "second connection never locked the upload row"
        with Session(engine) as finish_session:
            finish_pid = finish_session.scalar(text("SELECT pg_backend_pid()"))
            assert finish_pid != holder_pid[0]
            with pytest.raises(ws.WorkspaceError) as err:
                tx._finish_transcription(
                    finish_session,
                    c=svc.Container(finish_session, clock=c["clock"], blob=c["blob"]),
                    upload_id=upload_id,
                    box_id=box_id,
                    owner_id=owner_id,
                    wid=wid,
                    rid=rid,
                    operation_id=oid,
                    outcome=outcome,
                    now=now,
                    claim_attempt=claim_attempt,
                )
            assert err.value.code == "independent_transcription_unavailable"
            assert err.value.status == 503
            assert err.value.__cause__ is not None
            assert tx._is_lock_timeout(err.value.__cause__)
        release.set()
        pending.result(timeout=35)


def test_start_and_finish_lock_upload_before_job(enabled_case):
    from sqlalchemy import event

    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-lock-order")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    statements: list[str] = []
    bind = c["session"].connection()

    def before(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    def lock_targets(rows: list[str]) -> list[str]:
        ordered: list[str] = []
        for statement in rows:
            upper = statement.upper()
            if "FOR UPDATE" not in upper:
                continue
            if "INDEPENDENT_RECORDING_AUDIO_UPLOADS" in upper:
                ordered.append("upload")
            elif "INDEPENDENT_RECORDING_TRANSCRIPTION_JOBS" in upper:
                ordered.append("job")
        return ordered

    start_locks: list[str] = []

    class CaptureProcessor(FakeTranscriptionProcessor):
        def transcribe(self, request):  # type: ignore[override]
            start_locks[:] = lock_targets(statements)
            return super().transcribe(request)

    event.listen(bind, "before_cursor_execute", before)
    try:
        started = tx.start_transcription(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            {"operation_id": payload["operation_id"]},
            external=c["external"], blob=c["blob"], clock=c["clock"],
            processor=CaptureProcessor(),
        )
    finally:
        event.remove(bind, "before_cursor_execute", before)
    assert started["status"] == "ready"
    assert start_locks[:2] == ["upload", "job"]
    finish_locks = lock_targets(statements)[len(start_locks):]
    assert finish_locks[:2] == ["upload", "job"]


def test_delete_own_account_blob_failure_rolls_back(enabled_case, monkeypatch):
    from cosmas_os.adapters.local import LocalBlobAdapter
    from cosmas_os.application.account_deletion import CONFIRM_PHRASE, delete_own_account
    from cosmas_os.domain.enums import PrincipalState
    from cosmas_os.models import Principal

    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-acct-boom")
    uploaded = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload_id = uploaded["upload_id"]

    def boom_delete(self, key: str) -> None:
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(LocalBlobAdapter, "delete", boom_delete)
    monkeypatch.setattr(svc, "settings", c["f"].configuration.model_copy(
        update={"blob_root": str(c["blob"].root)}
    ))

    class FakeClerk:
        def require_user(self, subject: str) -> dict:
            return {"id": subject}

        def delete_user(self, subject: str) -> None:
            raise AssertionError("Clerk delete must not run after wipe failure")

    with pytest.raises(ws.WorkspaceError) as err:
        delete_own_account(
            c["session"],
            box_id=c["f"].box,
            principal_id=c["f"].actor,
            external_identity_id=c["external"],
            confirm=CONFIRM_PHRASE,
            clerk=FakeClerk(),
        )
    assert err.value.status == 503
    actor = c["session"].get(Principal, c["f"].actor)
    assert actor is not None and actor.state == PrincipalState.ACTIVE.value
    remaining = c["session"].get(IndependentRecordingAudioUpload, upload_id)
    assert remaining is not None and remaining.blob_key is not None


def test_box_switch_off_refuses_while_process_switch_on(enabled_case):
    c = enabled_case
    box = c["session"].get(BoxContext, c["f"].box)
    assert box is not None
    box.independent_recording_transcription_enabled = False
    c["session"].commit()
    now = c["clock"].now()
    with pytest.raises(ws.WorkspaceError) as err:
        tx.upload_audio(
            c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
            independent_payload(now, b"tone-box-off"),
            external=c["external"], blob=c["blob"], clock=c["clock"],
        )
    assert err.value.code == "independent_recording_transcription_disabled"
    assert err.value.status == 403


def test_http_revoke_on_and_with_switch_off(enabled_case, monkeypatch):
    from cosmas_os.api import app as api_module

    c = enabled_case
    f, draft, row = c["f"], c["draft"], c["row"]
    now = datetime.now(UTC)
    audio = b"tone-http-revoke"
    body = {
        "operation_id": str(uuid4()),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "duration_ms": 1000,
        "language": "en-US",
        "lease_expires_at": (now + timedelta(hours=1)).isoformat(),
        "consent": independent_consent(now),
        "audio_base64": base64.b64encode(audio).decode(),
    }
    assert f.client.post(
        f"{base(draft)}/{row['recording_id']}/audio", headers=headers(f), json=body
    ).status_code == 200
    revoked = f.client.post(
        f"{base(draft)}/{row['recording_id']}/transcription/revoke",
        headers=headers(f),
        json={"operation_id": body["operation_id"]},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"

    audio2 = b"tone-http-rev2"
    body2 = {
        "operation_id": str(uuid4()),
        "sha256": hashlib.sha256(audio2).hexdigest(),
        "duration_ms": 1000,
        "language": "en-US",
        "lease_expires_at": (now + timedelta(hours=1)).isoformat(),
        "consent": independent_consent(now),
        "audio_base64": base64.b64encode(audio2).decode(),
    }
    assert f.client.post(
        f"{base(draft)}/{row['recording_id']}/audio", headers=headers(f), json=body2
    ).status_code == 200
    off = f.configuration.model_copy(
        update={"independent_recording_transcription_enabled": False, "blob_root": str(c["blob"].root)}
    )
    monkeypatch.setattr(tx, "settings", off)
    monkeypatch.setattr(api_module, "settings", off)
    monkeypatch.setattr(svc, "settings", off)
    revoked_off = f.client.post(
        f"{base(draft)}/{row['recording_id']}/transcription/revoke",
        headers=headers(f),
        json={"operation_id": body2["operation_id"]},
    )
    assert revoked_off.status_code == 200, revoked_off.text
    assert revoked_off.json()["status"] == "revoked"


def test_worker_task_purges_expired_rows(enabled_case, monkeypatch):
    from cosmas_os.worker import tasks as worker_tasks

    c = enabled_case
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-worker-purge")
    uploaded = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload = c["session"].get(IndependentRecordingAudioUpload, uploaded["upload_id"])
    assert upload is not None
    c["clock"].set(upload.audio_expires_at)
    monkeypatch.setattr(
        svc, "settings",
        c["f"].configuration.model_copy(update={
            "blob_root": str(c["blob"].root),
            "cosmas_clock_now": c["clock"].now().isoformat(),
            "independent_recording_transcription_enabled": True,
        }),
    )

    class BoundSession:
        def __init__(self, session):
            self._session = session

        def __getattr__(self, name):
            return getattr(self._session, name)

        def close(self):
            return None

    monkeypatch.setattr(worker_tasks, "SessionLocal", lambda: BoundSession(c["session"]))
    count = worker_tasks.purge_independent_recording_audio_task(box_id=c["f"].box)
    assert count >= 1
    c["session"].refresh(upload)
    assert upload.blob_key is None and upload.audio_purged_at is not None


def test_http_purge_with_injected_clock_actually_purges(enabled_case, monkeypatch):
    from cosmas_os.api import app as api_module

    c = enabled_case
    f, draft = c["f"], c["draft"]
    now = c["clock"].now()
    payload = independent_payload(now, b"tone-http-clock")
    uploaded = tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    upload = c["session"].get(IndependentRecordingAudioUpload, uploaded["upload_id"])
    assert upload is not None and upload.blob_key is not None
    purge_at = upload.audio_expires_at
    configuration = f.configuration.model_copy(update={
        "independent_recording_transcription_enabled": True,
        "blob_root": str(c["blob"].root),
        "cosmas_clock_now": purge_at.isoformat(),
    })
    monkeypatch.setattr(tx, "settings", configuration)
    monkeypatch.setattr(api_module, "settings", configuration)
    monkeypatch.setattr(svc, "settings", configuration)
    purged = f.client.post(
        f"/workspaces/{draft['id']}/private-recordings/audio-purge",
        headers=headers(f),
    )
    assert purged.status_code == 200, purged.text
    receipts = purged.json()["receipts"]
    assert any(item["upload_id"] == upload.id and item["outcome"] == "purged" for item in receipts)
    c["session"].refresh(upload)
    assert upload.blob_key is None and upload.audio_purged_at is not None
