import base64
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from tests.capture_source_fixture import source_packet
from tests.unit.test_core_capture_admission import NOW, core_handler, ref, selection

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_protocol import OPERATION_ADAPTER

KINDS = [
    "encryption_key",
    "capabilities",
    "bind_key",
    "issue_lease",
    "renew_lease",
    "reserve_chunks",
    "authorize_upload",
    "chunk_receipt",
    "register_chunk",
    "complete",
    "transcription_status",
    "transcript",
    "working_transcript",
    "correct_transcript",
    "recover_capture",
    "capture_recovery_state",
    "capture_source",
    "correct_capture_source",
]


def packet(kind, session):
    if kind in {"creator_review", "decide_translation"}:
        golden = json.loads((Path(__file__).parents[1] / "fixtures/creator_review.json").read_text())
        if kind == "creator_review":
            receipt = golden["waiting"]
            receipt["session_id"] = str(session)
            receipt["review_queue"]["session_id"] = str(session)
            return {"kind": kind}, receipt
        item = golden["waiting"]["review_queue"]["items"][0]
        decision = {
            "schema_version": "1.0", "expected_source_transcript_version": 1,
            "source_segment_id": item["source_segment_id"],
            "expected_source_segment_version": item["source_segment_version"],
            "translation_id": item["translation_id"],
            "expected_translation_version": item["translation_version"],
            "decision": "accepted",
        }
        return {"kind": kind, "payload": decision}, {
            "schema_version": "1.0", "session_id": str(session),
            "saved": True, "review_id": str(uuid4()),
        }
    if kind in {"capture_source", "correct_capture_source"}:
        return source_packet(kind, session)
    object_id, lease_id, tenant = str(uuid4()), str(uuid4()), str(uuid4())
    common = {"protocol_version": "1.0"}

    def reservation(number, object_id):
        aad = {
            "tenant_id": tenant,
            "session_id": str(session),
            "object_id": object_id,
            "sequence_number": number,
            "channel": "microphone",
        }
        return {
            **common,
            "object_id": object_id,
            "session_id": str(session),
            "channel": "microphone",
            "sequence_number": number,
            "additional_authenticated_data": base64.urlsafe_b64encode(
                json.dumps(aad, sort_keys=True, separators=(",", ":")).encode()
            )
            .decode()
            .rstrip("="),
            "created_at": NOW.isoformat(),
        }

    operation = {"kind": kind}
    if kind in {"recover_capture", "capture_recovery_state"}:
        golden = json.loads((Path(__file__).parents[1] / "fixtures/capture_recovery.json").read_text())
        recovered = golden["receipt"]
        recovered["session_id"] = str(session)
        recovered["lease"]["session_id"] = str(session)
        if kind == "recover_capture":
            operation["payload"] = golden["request"]
            receipt = recovered
        else:
            receipt = golden["state"]
            receipt["history"] = {"session_id": str(session), "recoveries": [recovered]}
            receipt["current_lease"]["session_id"] = str(session)
    elif kind in {"working_transcript", "correct_transcript"}:
        golden = json.loads((Path(__file__).parents[1] / "fixtures/capture_working.json").read_text())
        receipt = golden["base" if kind == "working_transcript" else "second"]
        if kind == "correct_transcript":
            operation["payload"] = golden["correction"]
    elif kind == "encryption_key":
        receipt = {
            "key_version": "synthetic",
            "algorithm": "RSA-OAEP-256",
            "public_jwk": {
                "kty": "RSA",
                "n": "A" * 512,
                "e": "AQAB",
                "alg": "RSA-OAEP-256",
                "ext": True,
                "key_ops": ["wrapKey"],
            },
        }
    elif kind == "capabilities":
        receipt = {
            **common,
            "media": {
                "media_type": "audio/wav",
                "encoding": "pcm_s16le",
                "channels": 1,
                "sample_rate_hz": 16000,
            },
            "target_chunk_duration_ms": 10000,
            "max_envelope_bytes": 327680,
            "max_chunks": 1000,
            "remaining_aggregate_plaintext_bytes": 67108864,
            "capture_lease_ttl_seconds": 900,
            "reservation_window_seconds": 900,
            "max_reservations_per_batch": 90,
            "upload_concurrency": 2,
        }
    elif kind == "bind_key":
        operation["payload"] = {"key_version": "synthetic", "wrapped_dek": "A" * 512}
        receipt = {
            "session_id": str(session),
            "key_version": "synthetic",
            "created_at": NOW.isoformat(),
        }
    elif kind == "transcription_status":
        receipt = {
            "session_id": str(session),
            "status": "completed",
            "transcript_available": True,
            "updated_at": NOW.isoformat(),
        }
    elif kind == "transcript":
        receipt = {
            "id": str(uuid4()),
            "session_id": str(session),
            "created_at": NOW.isoformat(),
            "language_code": "en",
            "stt_provider": "synthetic",
            "segments": [
                {
                    "content": "Invented speech. " * 4000,
                    "start_ms": i * 1000,
                    "end_ms": (i + 1) * 1000,
                    "speaker_id": "speaker-1",
                    "speaker_role": "clinician",
                    "confidence": None,
                }
                for i in range(3)
            ],
        }
    elif kind in {"issue_lease", "renew_lease"}:
        operation["payload"] = (
            common if kind == "issue_lease" else {**common, "expected_generation": 1}
        )
        if kind == "renew_lease":
            operation["lease_id"] = lease_id
        receipt = {
            **common,
            "receipt_id": str(uuid4()),
            "lease_id": lease_id,
            "session_id": str(session),
            "generation": 1 if kind == "issue_lease" else 2,
            "issued_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(minutes=15)).isoformat(),
        }
    elif kind == "reserve_chunks":
        operation["payload"] = {
            **common,
            "capture_lease_id": lease_id,
            "capture_lease_generation": 1,
            "channel": "microphone",
            "first_sequence_number": 0,
            "count": 90,
        }
        receipt = {
            **common,
            "batch_id": str(uuid4()),
            "session_id": str(session),
            "capture_authorized_until": (NOW + timedelta(minutes=15)).isoformat(),
            "reservations": [reservation(i, str(uuid4())) for i in range(90)],
        }
    elif kind == "authorize_upload":
        operation.update(object_id=object_id, payload=common)
        receipt = {
            **common,
            "authorization_receipt_id": str(uuid4()),
            "object_id": object_id,
            "additional_authenticated_data": reservation(0, object_id)[
                "additional_authenticated_data"
            ],
            "upload_url": "https://uploads.example.invalid/synthetic?grant=synthetic",
            "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        }
    elif kind == "chunk_receipt":
        operation["object_id"] = object_id
        receipt = {
            "reservation": reservation(0, object_id),
            "state": "reserved",
            "registration": None,
        }
    elif kind == "register_chunk":
        payload = {
            "sequence_number": 0,
            "channel": "microphone",
            "object_id": object_id,
            "sha256": "a" * 64,
            "ciphertext_size_bytes": 123,
        }
        operation["payload"] = payload
        receipt = {
            **payload,
            "id": str(uuid4()),
            "session_id": str(session),
            "registered_at": NOW.isoformat(),
        }
    else:
        operation["payload"] = {
            **common,
            "capture_lease_id": lease_id,
            "capture_lease_generation": 1,
            "channels": [{"channel": "microphone", "final_sequence_number": 0}],
        }
        receipt = {
            "id": str(session),
            "appointment_id": ref("appointment"),
            "practitioner_id": "synthetic-practitioner",
            "patient_id": "synthetic-patient",
            "consent_record_id": str(uuid4()),
            "modality": "in_person",
            "ingest_mode": "chunk_upload",
            "status": "uploaded",
            "created_at": NOW.isoformat(),
        }
    return operation, receipt


def exercise(kind, mutate=lambda value: None):
    selected, session, calls = selection(), uuid4(), []
    if kind in {"working_transcript", "correct_transcript"}:
        session = UUID("00000000-0000-4000-8000-000000000003")
    operation, expected = packet(kind, session)
    bootstrap = core_handler(selected, calls)

    def handler(request):
        if not request.url.path.endswith("/capture-operations"):
            return bootstrap(request)
        calls.append(request)
        request_body = json.loads(request.content)
        assert request_body["operation"] == OPERATION_ADAPTER.validate_python(operation).model_dump(
            mode="json"
        )
        assert "session_id" not in request_body
        response = {
            "contract_version": "1",
            "binding_ref": ref("scribe_capture_binding"),
            "workspace_id": str(selected.workspace_id),
            "request_nonce": request_body["request_nonce"],
            "operation": kind,
            "receipt": expected,
            "checked_at": NOW.isoformat(),
        }
        mutate(response)
        return httpx.Response(
            200,
            json=response,
            headers={"Cache-Control": "no-store", "X-Cosmaneura-Capture-Version": "1"},
        )

    port = HttpCoreCaptureAdmission(
        "https://core.example.invalid",
        lambda: "synthetic_PRIVATE_workload",
        transport=httpx.MockTransport(handler),
        now=lambda: NOW,
    )
    try:
        token = port.exchange_context(selected, SecretStr("synthetic_PRIVATE_jwt"))
        credential = port.resolve_context(selected, token)
        binding = port.resolve_binding(selected, credential)
        result = port.perform_capture_operation(
            binding,
            credential,
            session,
            OPERATION_ADAPTER.validate_python(operation),
            "synthetic-operation-key",
        )
        assert result.model_dump(mode="json") == json.loads(
            json.dumps(expected).replace("+00:00", "Z")
        )
        assert len(calls) == 4 and calls[-1].headers["Idempotency-Key"] == "synthetic-operation-key"
        return result
    finally:
        port.close()


@pytest.mark.parametrize("kind", KINDS)
def test_all_native_operation_contracts_and_large_reservation_batch(kind):
    result = exercise(kind)
    assert "PRIVATE" not in result.model_dump_json()


@pytest.mark.parametrize(
    "fault", ["binding", "workspace", "nonce", "kind", "version", "stale", "session", "extra"]
)
def test_wrong_operation_envelope_or_session_is_not_released(fault):
    def mutate(value):
        if fault == "binding":
            value["binding_ref"] = ref("scribe_capture_binding")[:-1] + "2"
        elif fault in {"workspace", "nonce"}:
            value["workspace_id" if fault == "workspace" else "request_nonce"] = str(uuid4())
        elif fault == "kind":
            value["operation"] = "capabilities"
        elif fault == "version":
            value["contract_version"] = "2"
        elif fault == "stale":
            value["checked_at"] = (NOW - timedelta(minutes=5)).isoformat()
        elif fault == "session":
            value["receipt"]["session_id"] = str(uuid4())
        else:
            value["receipt"]["private_sentinel"] = "not part of contract"

    with pytest.raises(ConnectorUnavailable):
        exercise("issue_lease", mutate)


@pytest.mark.parametrize("kind", ["transcription_status", "transcript"])
def test_transcription_receipt_must_belong_to_admitted_session(kind):
    with pytest.raises(ConnectorUnavailable):
        exercise(kind, lambda value: value["receipt"].update(session_id=str(uuid4())))


@pytest.mark.parametrize("fault", ["timing", "order", "content", "extra"])
def test_invalid_source_transcript_is_not_released(fault):
    def mutate(value):
        segments = value["receipt"]["segments"]
        if fault == "timing":
            segments[0]["end_ms"] = 0
        elif fault == "order":
            segments.reverse()
        elif fault == "content":
            segments[0]["content"] = "x" * 100001
        else:
            segments[0]["private_sentinel"] = "not a transcript field"

    with pytest.raises(ConnectorUnavailable):
        exercise("transcript", mutate)


@pytest.mark.parametrize("kind", ["creator_review", "decide_translation"])
def test_configured_review_uses_current_workspace_and_exact_operation(kind):
    exercise(kind)
    with pytest.raises(ConnectorUnavailable):
        exercise(kind, lambda value: value["receipt"].update(session_id=str(uuid4())))
