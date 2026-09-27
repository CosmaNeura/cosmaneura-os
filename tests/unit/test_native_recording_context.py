import json
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from tests.unit.test_core_capture_admission import NOW, core_handler, selection

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_protocol import NativeRecordingContext, ReadOperation


def read_context(mutate=lambda value: None):
    selected, session_id, tenant_id, calls = selection(), uuid4(), uuid4(), []
    bootstrap = core_handler(selected, calls)
    receipt = NativeRecordingContext(schema_version="1.0", workspace_id=selected.workspace_id,
        tenant_id=tenant_id, session_id=session_id, status="created")

    def handler(request):
        if not request.url.path.endswith("/capture-operations"):
            return bootstrap(request)
        body = json.loads(request.content)
        assert body["operation"] == {"kind": "native_recording_context", "profile_receipt_id": None}
        assert "tenant_id" not in body and "session_id" not in body
        assert request.headers["Idempotency-Key"] == "native-context-read"
        calls.append(request)
        response = {"contract_version": "1", "binding_ref": body["binding_ref"],
            "workspace_id": body["workspace_id"], "request_nonce": body["request_nonce"],
            "checked_at": NOW.isoformat(), "operation": "native_recording_context",
            "receipt": receipt.model_dump(mode="json")}
        mutate(response)
        return httpx.Response(200, json=response,
            headers={"Cache-Control": "no-store", "X-Cosmaneura-Capture-Version": "1"})

    port = HttpCoreCaptureAdmission("https://core.example.invalid", lambda: "synthetic_PRIVATE_workload",
        transport=httpx.MockTransport(handler), now=lambda: NOW)
    try:
        token = port.exchange_context(selected, SecretStr("synthetic_PRIVATE_jwt"))
        credential = port.resolve_context(selected, token)
        binding = port.resolve_binding(selected, credential)
        result = port.perform_capture_operation(binding, credential, session_id,
            ReadOperation(kind="native_recording_context"), "native-context-read")
        assert result == receipt and len(calls) == 4
        # The Scribe UUID is supplied by the admitted Core context, not derived
        # from the separate Core authority-tenant reference.
        assert str(result.tenant_id) != selected.expected_tenant_ref
        return result
    finally:
        port.close()


def test_native_recording_context_uses_authenticated_core_envelope():
    assert read_context().status == "created"


@pytest.mark.parametrize("fault", ["workspace", "session", "tenant", "status", "nonce", "stale", "extra", "missing_version", "wrong_version"])
def test_unbound_or_malformed_context_is_not_released(fault):
    def mutate(value):
        if fault in {"workspace", "session"}:
            value["receipt"][fault + "_id"] = str(uuid4())
        elif fault == "tenant":
            value["receipt"]["tenant_id"] = "authority_tenant_" + "0" * 25 + "1"
        elif fault == "status":
            value["receipt"]["status"] = "uploaded"
        elif fault == "nonce":
            value["request_nonce"] = str(uuid4())
        elif fault == "stale":
            value["checked_at"] = (NOW - timedelta(minutes=1)).isoformat()
        elif fault == "missing_version":
            del value["receipt"]["schema_version"]
        elif fault == "wrong_version":
            value["receipt"]["schema_version"] = "2.0"
        else:
            value["receipt"]["private_sentinel"] = "unexpected"

    with pytest.raises(ConnectorUnavailable, match="^core_capture_receipt_invalid$"):
        read_context(mutate)
