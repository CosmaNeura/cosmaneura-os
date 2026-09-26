"""Native start/stop is the same scoped Core operation through OS."""

import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from tests.unit.test_core_capture_admission import NOW, core_handler, ref, selection

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_protocol import OPERATION_ADAPTER


def exchange(action, fault=None):
    selected, session, calls = selection(), uuid4(), []
    payload = {
        "schema_version": "1.0", "attempt_id": str(uuid4()), "source": "ios_microphone",
        "owner_proof": "a" * 64, "lease_id": str(uuid4()), "lease_receipt_id": str(uuid4()),
        "lease_generation": 2, "capture_authorized_until": (NOW + timedelta(minutes=5)).isoformat(),
        "first_sequence_number": 4,
    }
    operation = {"kind": "source_start", "action": "stop" if action == "unstarted" else action, "payload": payload}
    state = {"prepare": "prepared", "authorize": "issued", "cancel": "cancelled", "stop": "stopped", "unstarted": "unstarted"}[action]
    receipt = {key: value for key, value in payload.items() if key != "owner_proof"}
    receipt.update(session_id=str(session), creator_actor_id=selected.expected_actor_ref,
                   consent_record_id=str(uuid4()), state=state)
    if action == "unstarted":
        receipt.update(retirement_id=str(uuid4()), retired_at=NOW.isoformat(),
                       owner_proof_sha256=hashlib.sha256(payload["owner_proof"].encode()).hexdigest())
    else:
        receipt.update(source_start_id=str(uuid4()), capability_id=str(uuid4()),
                       preparation_expires_at=(NOW + timedelta(seconds=90)).isoformat(), issued_at=None, expires_at=None)
        if action in {"authorize", "stop"}:
            issued = NOW if action == "authorize" else NOW - timedelta(seconds=20)
            receipt.update(issued_at=issued.isoformat(), expires_at=(issued + timedelta(seconds=10)).isoformat())
    if fault == "session":
        receipt["session_id"] = str(uuid4())
    elif fault == "actor":
        receipt["creator_actor_id"] = ref("authority_actor")[:-1] + "2"
    elif fault == "lease":
        receipt["lease_generation"] = 1
    elif fault == "position":
        receipt["first_sequence_number"] = 0
    elif fault == "unstarted_proof":
        receipt["owner_proof_sha256"] = "b" * 64
    wire = {"receipt": receipt, "secret": "b" * 64 if fault == "proof" else payload["owner_proof"]} if action == "authorize" else receipt
    bootstrap = core_handler(selected, calls)

    def handler(request):
        if not request.url.path.endswith("/capture-operations"):
            return bootstrap(request)
        body = json.loads(request.content)
        assert body["operation"] == OPERATION_ADAPTER.validate_python(operation).model_dump(mode="json")
        assert request.headers["Idempotency-Key"] == "native-owner-original-key"
        assert "session_id" not in body
        return httpx.Response(200, json={
            "contract_version": "1", "workspace_id": str(selected.workspace_id),
            "binding_ref": ref("scribe_capture_binding"), "request_nonce": body["request_nonce"],
            "operation": "source_start", "receipt": wire, "checked_at": NOW.isoformat(),
        }, headers={"Cache-Control": "no-store", "X-Cosmaneura-Capture-Version": "1"})

    port = HttpCoreCaptureAdmission("https://core.example.invalid", lambda: "synthetic_PRIVATE_workload",
                                    transport=httpx.MockTransport(handler), now=lambda: NOW)
    try:
        token = port.exchange_context(selected, SecretStr("synthetic_PRIVATE_jwt"))
        credential = port.resolve_context(selected, token)
        binding = port.resolve_binding(selected, credential)
        return port.perform_capture_operation(binding, credential, session,
            OPERATION_ADAPTER.validate_python(operation), "native-owner-original-key")
    finally:
        port.close()


@pytest.mark.parametrize("action", ["prepare", "authorize", "cancel", "stop", "unstarted"])
def test_scoped_native_lifecycle_and_stop_after_expired_start_capability(action):
    result = exchange(action)
    assert "PRIVATE" not in str(result) and "a" * 64 not in str(result)


@pytest.mark.parametrize("fault", ["session", "actor", "lease", "position", "proof"])
def test_another_owner_or_lease_never_supplies_native_authority(fault):
    with pytest.raises(ConnectorUnavailable):
        exchange("authorize", fault)


def test_unstarted_retirement_requires_original_proof():
    with pytest.raises(ConnectorUnavailable):
        exchange("unstarted", "unstarted_proof")
