from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from tests.integration import test_workspace_capture as shared

from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, PatientLink
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_protocol import Capabilities, MediaCapabilities, SourceTranscript

capture_case = shared.capture_case
admit = shared.admit


def capabilities():
    return Capabilities(
        media=MediaCapabilities(
            media_type="audio/wav", encoding="pcm_s16le", channels=1, sample_rate_hz=16000
        ),
        target_chunk_duration_ms=10000,
        max_envelope_bytes=327680,
        max_chunks=1000,
        remaining_aggregate_plaintext_bytes=67108864,
        capture_lease_ttl_seconds=900,
        reservation_window_seconds=900,
        max_reservations_per_batch=90,
        upload_concurrency=2,
    )


def prepare(f, kind="capabilities"):
    result = admit(f)
    assert result.status_code == 200
    f.session_id = result.json()["session_id"]
    f.port.calls.clear()

    def operation(*args):
        f.port.step("operation")
        if kind == "transcript":
            return SourceTranscript.model_validate(
                {
                    "id": uuid4(),
                    "session_id": f.session_id,
                    "created_at": datetime.now(UTC),
                    "language_code": "en",
                    "stt_provider": "synthetic",
                    "segments": [
                        {
                            "content": "PRIVATE_CAPTURE_SENTINEL: invented speech only.",
                            "start_ms": 0,
                            "end_ms": 1000,
                            "speaker_id": "speaker-1",
                            "speaker_role": "clinician",
                            "confidence": None,
                        }
                    ],
                }
            )
        return capabilities()

    f.port.perform_capture_operation = operation


def perform(f, **changes):
    return f.client.post(
        f.path.replace("/admission", "/operations"),
        headers={"Authorization": "Bearer " + f.token()},
        json={
            "session_id": f.session_id,
            "idempotency_key": uuid4().hex,
            "operation": {"kind": "capabilities"},
            **changes,
        },
    )


def test_workspace_operation_rechecks_admission_and_keeps_no_store(capture_case):
    f = capture_case
    prepare(f)
    response = perform(f)
    assert response.status_code == 200
    assert response.json()["receipt"] == capabilities().model_dump(mode="json")
    assert response.json()["session_id"] == f.session_id
    assert response.headers["cache-control"] == "no-store"
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "operation"]


def test_upload_expiry_keeps_its_closed_recovery_code(capture_case):
    f = capture_case
    prepare(f)

    def expired(*args):
        f.port.calls.append("operation")
        raise ConnectorUnavailable("upload_authorization_expired")

    f.port.perform_capture_operation = expired
    response = perform(f)
    assert response.status_code == 409
    assert response.json() == {"detail": "upload_authorization_expired"}
    assert response.headers["cache-control"] == "no-store"
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "operation"]


def test_claimed_session_is_compared_before_any_capture_operation(capture_case):
    f = capture_case
    prepare(f)

    def mismatched_admission(*args, **kwargs):
        # Deliberately return the prior session. LocalCore's normal double
        # asserts the requested session before this application guard can run.
        f.port.step("admit")
        return f.port.saved

    f.port.admit_capture = mismatched_admission
    response = perform(f, session_id=str(uuid4()))
    assert response.status_code == 409
    assert response.json()["detail"] == "capture_session_changed"
    assert f.port.calls == ["exchange", "resolve", "binding", "admit"]


@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding", "admit", "operation"])
@pytest.mark.parametrize("target", ["identity", "account", "patient"])
@pytest.mark.parametrize("kind", ["capabilities", "transcript"])
def test_revocation_during_operation_pipeline_blocks_next_call_or_result(
    capture_case, phase, target, kind
):
    f = capture_case
    prepare(f, kind)

    def revoke(observed):
        if phase != observed:
            return
        with Session(f.engine) as session:
            model, key = {
                "identity": (ExternalIdentity, f.identity_id),
                "account": (CoreCaptureAccount, f.account_id),
                "patient": (PatientLink, f.patient_link_id),
            }[target]
            row = session.get(model, key)
            assert row is not None
            if isinstance(row, ExternalIdentity):
                row.active = False
            else:
                row.revoked_at = datetime.now(UTC)
            session.commit()

    f.port.after = revoke
    response = perform(f, operation={"kind": kind})
    assert response.status_code in {403, 404, 409}
    assert "receipt" not in response.text
    assert "PRIVATE_CAPTURE_SENTINEL" not in response.text
    assert (
        len(f.port.calls)
        == ["exchange", "resolve", "binding", "admit", "operation"].index(phase) + 1
    )


@pytest.mark.parametrize(
    "operation",
    [
        {"kind": "anything"},
        {"kind": "capabilities", "tenant_id": "private_sentinel"},
        {"kind": "reserve_chunks", "payload": {"count": 91}},
        {"kind": "bind_key", "payload": {"wrapped_dek": "private_sentinel" * 400}},
    ],
)
def test_invalid_operation_cannot_reach_core(capture_case, operation):
    f = capture_case
    prepare(f)
    response = perform(f, operation=operation)
    assert response.status_code == 422 and not f.port.calls
    assert "private_sentinel" not in response.text


def test_source_transcript_read_uses_signed_workspace_and_same_admission(capture_case):
    f = capture_case
    prepare(f, "transcript")
    response = perform(f, operation={"kind": "transcript"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["receipt"]["session_id"] == f.session_id
    assert response.json()["receipt"]["segments"][0]["speaker_role"] == "clinician"
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "operation"]
