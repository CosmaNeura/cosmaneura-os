import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.core_visit_prep import HttpCoreVisitPrep
from cosmas_os.application.core_record_deadline import RecordDeadline
from cosmas_os.ports.core_visit_prep import CoreVisitPrepRead, CoreVisitPrepReceipt


def wire():
    value = json.loads((Path(__file__).parents[1] / "fixtures/visit-prep-ready.json").read_text())
    value["checked_at"] = datetime.now(UTC).isoformat()
    return value


def request(value):
    return CoreVisitPrepRead(
        preparation_ref=value["preparation_ref"],
        connection_sha256=value["connection_sha256"],
        workspace_id=value["workspace_id"],
        request_nonce=value["request_nonce"],
        expected_actor_ref="authority_actor_" + "0" * 25 + "1",
        expected_tenant_ref="authority_tenant_" + "0" * 25 + "1",
    )


def test_exact_chart_free_receipt_uses_only_dual_auth_endpoint():
    value = wire()
    calls = []

    def reply(req):
        calls.append(req)
        assert req.url.path == "/service/v1/companion/visit-prep/package"
        assert req.headers["Authorization"] == "Bearer invented-workload"
        assert req.headers["X-Cosmaneura-Provider-Authorization"] == "Bearer invented-physician"
        return httpx.Response(
            200,
            json=value,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Cosmaneura-Visit-Prep-Version": "1",
            },
        )

    port = HttpCoreVisitPrep(
        "https://core.example.invalid",
        lambda: "invented-workload",
        RecordDeadline(15),
        transport_factory=lambda: httpx.MockTransport(reply),
    )
    try:
        receipt = port.read(request(value), SecretStr("invented-physician"))
        assert receipt.model_dump(mode="json")["package"] == value["package"]
        assert receipt.package.sources.preparation.patient_id is None
        assert len(calls) == 1
    finally:
        port.close()


def test_choice_citation_uses_displayed_label_not_coded_value():
    value = wire()
    topic = value["package"]["sources"]["topics"][2]
    topic.update(
        response_kind="answered",
        answer="yes",
        initial_response_kind="answered",
        initial_answer="yes",
    )
    value["package"]["sources"]["skipped_question_keys"] = ["medications"]
    value["package"]["brief"]["medication_and_adherence"] = [
        {
            "text": "Recipient reports taking medications as prescribed.",
            "evidence": [
                {"source_ref": topic["original_response_id"], "quote": "Yes, as prescribed"}
            ],
        }
    ]
    CoreVisitPrepReceipt.model_validate_json(json.dumps(value), strict=True)


@pytest.mark.parametrize("change", ["extra", "nonce", "citation", "old_brief", "answer", "clock"])
def test_wrong_or_malformed_receipts_are_not_renderable(change):
    value = wire()
    if change == "extra":
        value["credential"] = "invented-private"
    elif change == "nonce":
        value["request_nonce"] = "not-a-uuid"
    elif change == "citation":
        value["package"]["brief"]["headline"]["evidence"][0]["quote"] = "not patient words"
    elif change == "old_brief":
        value["package"]["status"] = "stale"
    elif change == "answer":
        value["package"]["sources"]["topics"][0]["answer"] = None
    else:
        value["checked_at"] = "not-a-date"
    with pytest.raises(ValueError):
        CoreVisitPrepReceipt.model_validate_json(json.dumps(value), strict=True)
