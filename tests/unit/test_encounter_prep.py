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
from cosmas_os.ports.encounter_prep import CorePrepReceipt


def receipt(appointment=None):
    value = {
        "appointment_ref": appointment or ref("appointment"),
        "sources": [
            {
                "source_ref": ref("intake"),
                "appointment_ref": appointment or ref("appointment"),
                "kind": "patient_intake_summary",
                "label": "Patient intake · AI summary",
                "source_at": NOW.isoformat().replace("+00:00", "Z"),
                "content_sha256": "a" * 64,
                "content": "Invented intake — check this.",
                "truncated": False,
            }
        ],
        "additional_notes_available": False,
    }
    value["snapshot_sha256"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return value


def exercise(mutate=lambda value: None):
    selected = selection()
    calls = []
    base = core_handler(selected, calls)

    def handler(request):
        if not request.url.path.endswith("encounter-context"):
            return base(request)
        body = json.loads(request.content)
        assert set(body) == {"binding_ref", "workspace_id", "request_nonce"}
        value = {
            **body,
            "contract_version": "1",
            "checked_at": NOW.isoformat(),
            "receipt": receipt(selected.appointment_ref),
        }
        mutate(value)
        return httpx.Response(
            200,
            json=value,
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
        result = port.encounter_context(port.resolve_binding(selected, credential), credential)
        assert len(calls) == 3
        return result
    finally:
        port.close()


def test_actual_context_transport_without_admission():
    assert exercise() == CorePrepReceipt.model_validate(receipt())


@pytest.mark.parametrize(
    "fault", ["workspace", "nonce", "binding", "stale", "content", "hash", "extra", "oversized"]
)
def test_substituted_context_is_withheld(fault):
    def mutate(value):
        if fault in {"workspace", "nonce"}:
            value["workspace_id" if fault == "workspace" else "request_nonce"] = str(uuid4())
        elif fault == "binding":
            value["binding_ref"] = ref("scribe_capture_binding")[:-1] + "2"
        elif fault == "stale":
            value["checked_at"] = (NOW - timedelta(minutes=2)).isoformat()
        elif fault == "hash":
            value["receipt"]["snapshot_sha256"] = "0" * 64
        elif fault == "extra":
            value["receipt"]["patient_id"] = "private sentinel"
        else:
            value["receipt"]["sources"][0]["content"] = (
                "private sentinel" if fault == "content" else "x" * 300000
            )

    with pytest.raises(ConnectorUnavailable) as error:
        exercise(mutate)
    assert "private sentinel" not in str(error.value)
