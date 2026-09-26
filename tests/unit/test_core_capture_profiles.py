import base64
import json
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from tests.capture_profile_fixture import profile_packet
from tests.unit.test_core_capture_admission import NOW, core_handler, ref, selection
from tests.unit.test_core_capture_operations import packet

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.config import Settings
from cosmas_os.ports import capture_protocol as p
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable


def exercise(operation, receipt, session, *, profile=None, expected_calls=1):
    selected, calls, operation_calls = selection(), [], []
    bootstrap = core_handler(selected, calls)

    def handler(request):
        if not request.url.path.endswith("/capture-operations"):
            return bootstrap(request)
        operation_calls.append(request)
        body = json.loads(request.content)
        assert body["operation"] == operation.model_dump(mode="json")
        assert "session_id" not in body
        return httpx.Response(200, json={
            "contract_version": "1", "binding_ref": ref("scribe_capture_binding"),
            "workspace_id": str(selected.workspace_id), "request_nonce": body["request_nonce"],
            "operation": operation.kind, "receipt": receipt, "checked_at": NOW.isoformat(),
        }, headers={"Cache-Control": "no-store", "X-Cosmaneura-Capture-Version": "1"})

    port = HttpCoreCaptureAdmission("https://core.example.invalid", lambda: "synthetic_PRIVATE_workload",
        transport=httpx.MockTransport(handler), now=lambda: NOW)
    try:
        token = port.exchange_context(selected, SecretStr("synthetic_PRIVATE_jwt"))
        credential = port.resolve_context(selected, token)
        binding = port.resolve_binding(selected, credential)
        return port.perform_capture_operation(binding, credential, session, operation,
            "synthetic-profile-operation", capture_profile=profile)
    finally:
        port.close()
        assert len(operation_calls) == expected_calls


@pytest.mark.parametrize("channels", [[], ["microphone", "microphone"], ["mixed", "microphone"],
    ["system_audio", "mixed"], ["microphone", "system_audio", "mixed"], ["unknown"]])
def test_profile_track_selection_is_closed(channels):
    with pytest.raises(ValidationError):
        p.CaptureProfileRequest(profile_id="visit-60m-v1", channels=channels)


def test_profile_canonical_hash_matches_receiver_and_feature_defaults_off():
    value = profile_packet(uuid4(), channels=("system_audio", "microphone"), now=NOW)
    value["request"]["channels"].reverse()
    selected = p.CaptureProfileReceipt.model_validate(value)
    assert selected.request.channels == ("microphone", "system_audio")
    assert p.profile_request_sha256(selected.request) == value["request_sha256"]
    assert not Settings(_env_file=None).workspace_capture_long_visits_enabled


@pytest.mark.parametrize("kind", ["capture_profile", "select_capture_profile"])
def test_profile_selection_and_recovery_validate_the_scoped_receipt(kind):
    session = uuid4()
    value = profile_packet(session, now=NOW)
    operation = p.OPERATION_ADAPTER.validate_python({"kind": kind,
        **({"payload": value["request"]} if kind == "select_capture_profile" else {})})
    result = exercise(operation, value, session)
    assert isinstance(result, p.CaptureProfileReceipt)
    assert str(result.receipt_id) == value["receipt_id"]


@pytest.mark.parametrize("fault", ["session", "hash", "future", "budget", "chunks", "channel_chunks",
    "duration", "missing_budget", "extra", "different_selection"])
def test_invalid_profile_receipt_is_not_released(fault):
    session = uuid4()
    value = profile_packet(session, now=NOW)
    operation = p.SelectCaptureProfile(kind="select_capture_profile", payload=value["request"])
    if fault == "session":
        value["session_id"] = str(uuid4())
    elif fault == "hash":
        value["request_sha256"] = "0" * 64
    elif fault == "future":
        value["created_at"] = (NOW + timedelta(seconds=6)).isoformat()
    elif fault == "missing_budget":
        del value["maximum_aggregate_plaintext_bytes"]
    elif fault == "extra":
        value["untrusted"] = "PRIVATE_SENTINEL"
    elif fault == "different_selection":
        value = profile_packet(session, channels=("system_audio",), now=NOW)
    else:
        field = {"budget": "maximum_aggregate_plaintext_bytes", "chunks": "maximum_chunks",
            "channel_chunks": "maximum_chunks_per_channel", "duration": "maximum_track_duration_ms"}[fault]
        value[field] += 1
    with pytest.raises(ConnectorUnavailable, match="^core_capture_receipt_invalid$"):
        exercise(operation, value, session)


@pytest.mark.parametrize("acknowledged", [False, True])
def test_capability_contract_cannot_switch_profiles(acknowledged):
    session = uuid4()
    profile = p.CaptureProfileReceipt.model_validate(profile_packet(session, now=NOW))
    operation, value = packet("capabilities", session)
    if acknowledged:
        operation["profile_receipt_id"] = str(profile.receipt_id)
    else:
        value.update(max_chunks=720, remaining_aggregate_plaintext_bytes=268435456)
    with pytest.raises(ConnectorUnavailable):
        exercise(p.OPERATION_ADAPTER.validate_python(operation), value, session,
            profile=profile if acknowledged else None)


def test_long_capability_and_final_per_channel_window_require_exact_acknowledgment():
    session = uuid4()
    profile = p.CaptureProfileReceipt.model_validate(profile_packet(session, now=NOW))
    operation, value = packet("capabilities", session)
    operation["profile_receipt_id"] = str(profile.receipt_id)
    value.update(max_chunks=720, remaining_aggregate_plaintext_bytes=268435456)
    result = exercise(p.OPERATION_ADAPTER.validate_python(operation), value, session, profile=profile)
    assert isinstance(result, p.LongVisitCapabilities)
    operation, value = packet("reserve_chunks", session)
    operation.update(profile_receipt_id=str(profile.receipt_id))
    operation["payload"].update(first_sequence_number=270, count=90)
    for item in value["reservations"]:
        item["sequence_number"] += 270
        aad = json.loads(base64.urlsafe_b64decode(item["additional_authenticated_data"] + "=="))
        aad["sequence_number"] = item["sequence_number"]
        item["additional_authenticated_data"] = base64.urlsafe_b64encode(
            json.dumps(aad, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    assert isinstance(exercise(p.OPERATION_ADAPTER.validate_python(operation), value, session,
        profile=profile), p.ReservationReceipt)


@pytest.mark.parametrize("fault", ["sequence", "channel", "session", "duplicate", "count"])
def test_profile_reservation_response_matches_exact_selected_window(fault):
    session = uuid4()
    profile = p.CaptureProfileReceipt.model_validate(profile_packet(session, now=NOW))
    operation, value = packet("reserve_chunks", session)
    operation["profile_receipt_id"] = str(profile.receipt_id)
    if fault == "count":
        value["reservations"].pop()
    else:
        field, replacement = {
            "sequence": ("sequence_number", 359), "channel": ("channel", "system_audio"),
            "session": ("session_id", str(uuid4())),
            "duplicate": ("object_id", value["reservations"][1]["object_id"]),
        }[fault]
        value["reservations"][0][field] = replacement
    with pytest.raises(ConnectorUnavailable):
        exercise(p.OPERATION_ADAPTER.validate_python(operation), value, session, profile=profile)


@pytest.mark.parametrize("fault", ["missing", "id", "session", "hash", "future", "channel", "overrun", "unacknowledged"])
def test_invalid_retained_profile_is_denied_before_remote_operation(fault):
    session = uuid4()
    value = profile_packet(session, now=NOW)
    profile = p.CaptureProfileReceipt.model_validate(value)
    operation, receipt = packet("reserve_chunks", session)
    operation["profile_receipt_id"] = str(profile.receipt_id)
    if fault == "missing":
        profile = None
    elif fault == "id":
        operation["profile_receipt_id"] = str(uuid4())
    elif fault == "session":
        profile = profile.model_copy(update={"session_id": uuid4()})
    elif fault == "hash":
        profile = profile.model_copy(update={"request_sha256": "0" * 64})
    elif fault == "future":
        profile = profile.model_copy(update={"created_at": NOW + timedelta(seconds=6)})
    elif fault == "channel":
        operation["payload"]["channel"] = "system_audio"
    elif fault == "overrun":
        operation["payload"]["first_sequence_number"] = 271
    elif fault == "unacknowledged":
        del operation["profile_receipt_id"]
    with pytest.raises(ConnectorUnavailable):
        exercise(p.OPERATION_ADAPTER.validate_python(operation), receipt, session,
            profile=profile, expected_calls=0)


@pytest.mark.parametrize("kind", ["capture_profile", "transcript", "encryption_key", "capture_source"])
def test_profile_acknowledgment_cannot_be_attached_to_other_reads(kind):
    with pytest.raises(ValidationError):
        p.OPERATION_ADAPTER.validate_python({"kind": kind, "profile_receipt_id": str(uuid4())})
