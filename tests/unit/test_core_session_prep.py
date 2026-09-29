import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.core_session_prep import HttpCoreSessionPrep
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_capture import CoreInteractionCredential
from cosmas_os.ports.core_session_prep import CoreSessionPrepRead

NOW = datetime(2026, 9, 29, 13, tzinfo=UTC)
TURN = UUID("a0260929-0000-4000-8000-000000000001")
SOURCE = "source_invented_finalized_note"


def selected():
    return CoreSessionPrepRead(
        credential=CoreInteractionCredential(
            mount_context_token=SecretStr("synthetic_PRIVATE_mount_token"),
            interaction_ref="interaction_invented_current",
            client_turn_id=TURN,
        ),
        source_turn_ref="conversation_turn_invented_0001",
        context_snapshot_ref="provider_record_context_invented",
        idempotency_key="session_prep_invented_action_0001",
    )


def receipt(state="ready"):
    stamp = NOW.isoformat()
    result = {
        "schema_version": "1.0.0",
        "state": state,
        "detail": "brief",
        "freshness": "current",
        "completeness": "complete",
        "current_through": stamp,
        "snapshot_ref": "snapshot_invented_0001",
        "snapshot_version": 1,
        "snapshot_generated_at": stamp,
        "snapshot_supersedes_ref": None,
        "source_version_digest": "sha256_" + "a" * 64,
        "brief_ref": "brief_invented_0001",
        "brief_version": 1,
        "brief_generated_at": stamp,
        "brief_supersedes_ref": None,
        "brief_generator_version": "session_prep_generator_v1",
        "brief_prompt_version": "session_prep_prompt_v1",
        "brief_model_profile": None,
        "source_count": 1,
        "provenance": [
            {
                "source_class": "clinician_finalized_note",
                "included": True,
                "source_ref": SOURCE,
                "source_version": 1,
                "source_at": stamp,
                "author_class": "clinician",
                "reason_code": "eligible_finalized_note",
            }
        ],
        "prepared_brief": {
            "recap": {"text": "Invented reviewed visit summary.", "source_refs": [SOURCE]},
            "trajectory_and_material_changes": [],
            "open_threads": [],
            "cautions": [],
            "talking_points": [{"text": "Discuss the saved concern.", "source_refs": [SOURCE]}],
            "suggested_outline": [{"text": "Review the prior visit.", "source_refs": [SOURCE]}],
            "patient_reported": None,
        },
        "supporting_context": None,
        "retry_after_seconds": None,
        "reason_code": None,
    }
    if state in {"pending", "unavailable"}:
        for key in (
            "current_through",
            "snapshot_ref",
            "snapshot_version",
            "snapshot_generated_at",
            "source_version_digest",
            "brief_ref",
            "brief_version",
            "brief_generated_at",
            "brief_generator_version",
            "brief_prompt_version",
            "prepared_brief",
        ):
            result[key] = None
        result.update(
            freshness="none",
            completeness="none",
            source_count=0,
            provenance=[],
            retry_after_seconds=5 if state == "pending" else None,
            reason_code="generation_pending" if state == "pending" else "no_eligible_sources",
        )
    elif state == "refreshing":
        result.update(freshness="stale", reason_code="refresh_in_progress", retry_after_seconds=5)
    return {
        "tool_call_ref": "prep_read_invented_0001",
        "tool_name": "session-prep.context.read",
        "tool_version": "1.0.0",
        "status": "completed",
        "approval_ref": None,
        "access_intent_ref": None,
        "access_outcome_ref": None,
        "result_classification": "phi_possible",
        "result": result,
        "recorded_at": stamp,
    }


def headers():
    return {
        "Cache-Control": "no-store",
        "Content-Type": "application/json",
        "X-Cosmaneura-Client-Turn-ID": str(TURN),
        "Idempotency-Replayed": "false",
    }


def read(response=None, *, handler=None, selection=None, token=None, now=lambda: NOW):
    calls = []

    def send(request):
        calls.append(request)
        return (
            handler(request)
            if handler
            else response or httpx.Response(200, json=receipt(), headers=headers())
        )

    port = HttpCoreSessionPrep(
        "https://core.example.invalid",
        token or (lambda: "synthetic_PRIVATE_prep_identity"),
        transport=httpx.MockTransport(send),
        now=now,
    )
    try:
        result = port.read_brief(selection or selected())
        return result, calls
    finally:
        port.close()


@pytest.mark.parametrize("state", ["ready", "pending", "unavailable", "refreshing"])
def test_exact_brief_request_preserves_authorized_turn_and_core_result_state(state):
    result, calls = read(httpx.Response(200, json=receipt(state), headers=headers()))
    assert len(calls) == 1  # Pending does not start a second action or poll automatically.
    request = calls[0]
    assert (
        request.method == "POST"
        and str(request.url) == "https://core.example.invalid/service/v1/agent/tools/invoke"
    )
    assert request.headers["Authorization"] == "Bearer synthetic_PRIVATE_prep_identity"
    assert request.headers["X-Cosmaneura-Mount-Context"] == "synthetic_PRIVATE_mount_token"
    assert request.headers["X-Cosmaneura-Client-Turn-ID"] == str(TURN)
    assert request.headers["X-Cosmaneura-Interaction-Ref"] == selected().credential.interaction_ref
    assert request.headers["Idempotency-Key"] == selected().idempotency_key
    assert json.loads(request.content) == {
        "tool_name": "session-prep.context.read",
        "tool_version": "1.0.0",
        "subject_ref": None,
        "arguments": {
            "source_turn_ref": selected().source_turn_ref,
            "context_snapshot_ref": selected().context_snapshot_ref,
            "purpose": "session_prep",
            "detail": "brief",
        },
    }
    assert result.result.state == state
    assert "Invented reviewed" not in str(result) + repr(result)


@pytest.mark.parametrize("partial", [False, True])
def test_patient_reported_content_keeps_its_own_provenance_and_partial_status(partial):
    value = receipt()
    result = value["result"]
    patient_ref = "source_invented_patient_report"
    result["source_count"] = 2
    result["provenance"].append(
        {
            "source_class": "patient_reported_visit_prep",
            "included": True,
            "source_ref": patient_ref,
            "source_version": 1,
            "source_at": NOW.isoformat(),
            "author_class": "patient",
            "reason_code": "eligible_patient_visit_prep",
        }
    )
    result["prepared_brief"]["patient_reported"] = {
        "label": "Patient-reported Visit Prep",
        "summary": "Invented patient-reported concern.",
        "source_refs": [patient_ref],
    }
    if partial:
        result["completeness"] = "partial"
        result["provenance"].append(
            {
                "source_class": "clinician_finalized_note",
                "included": False,
                "source_ref": None,
                "source_version": None,
                "source_at": None,
                "author_class": None,
                "reason_code": "source_temporarily_unavailable",
            }
        )
    actual, _ = read(httpx.Response(200, json=value, headers=headers()))
    assert actual.result.completeness == ("partial" if partial else "complete")
    assert actual.result.prepared_brief.patient_reported.source_refs == (patient_ref,)


@pytest.mark.parametrize(
    "fault",
    [
        "draft",
        "citation",
        "duplicate",
        "count",
        "patient_citation",
        "chronology",
        "predecessor",
        "pending_content",
        "empty_ready",
        "raw_context",
        "extra",
        "version",
        "oversized",
    ],
)
def test_invalid_source_lineage_or_wider_content_is_withheld(fault):
    value = receipt("pending" if fault == "pending_content" else "ready")
    result = value["result"]
    if fault == "draft":
        result["provenance"][0]["source_class"] = "generated_visit_note"
    elif fault == "citation":
        result["prepared_brief"]["recap"]["source_refs"] = ["source_other_patient"]
    elif fault == "duplicate":
        result["provenance"].append(result["provenance"][0])
    elif fault == "count":
        result["source_count"] = True
    elif fault == "patient_citation":
        result["prepared_brief"]["patient_reported"] = {
            "label": "Patient-reported Visit Prep",
            "summary": "Private sentinel",
            "source_refs": [SOURCE],
        }
    elif fault == "chronology":
        result["snapshot_generated_at"] = (NOW - timedelta(days=1)).isoformat()
    elif fault == "predecessor":
        result["brief_version"] = 2
    elif fault == "pending_content":
        result["prepared_brief"] = receipt()["result"]["prepared_brief"]
    elif fault == "empty_ready":
        result["prepared_brief"] = None
    elif fault == "raw_context":
        result["supporting_context"] = [{"content": "Private sentinel"}]
    elif fault == "extra":
        value["patient_id"] = "Private sentinel"
    elif fault == "version":
        value["tool_version"] = "2.0.0"
    else:
        result["prepared_brief"]["recap"]["text"] = "Private sentinel" * 30_000
    with pytest.raises(ConnectorUnavailable, match="session_prep_receipt_invalid") as error:
        read(httpx.Response(200, json=value, headers=headers()))
    assert "Private sentinel" not in str(error.value)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "access_unavailable"),
        (403, "access_unavailable"),
        (404, "access_unavailable"),
        (409, "request_conflict"),
        (503, "request_unconfirmed"),
        (302, "request_unconfirmed"),
    ],
)
def test_failures_and_redirects_are_fixed_errors_without_retries_or_body_reads(status, code):
    calls = []

    class Unreadable(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("Failure body must not be read")
            yield b""

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            stream=Unreadable(),
            headers={"Location": "https://other.example.invalid/private"},
        )

    with pytest.raises(ConnectorUnavailable, match="session_prep_" + code):
        read(handler=handler)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "fault",
    ["other_turn", "cache", "replay_header", "duplicate_json", "future", "naive", "pending_retry"],
)
def test_invalid_envelope_is_withheld(fault):
    value, envelope = receipt(), headers()
    if fault == "other_turn":
        envelope["X-Cosmaneura-Client-Turn-ID"] = str(uuid4())
    elif fault == "cache":
        envelope["Cache-Control"] = "public"
    elif fault == "replay_header":
        del envelope["Idempotency-Replayed"]
    elif fault == "future":
        value["recorded_at"] = (NOW + timedelta(minutes=5)).isoformat()
    elif fault == "naive":
        value["recorded_at"] = "2026-09-29T13:00:00"
    elif fault == "pending_retry":
        value = receipt("pending")
        value["result"]["retry_after_seconds"] = 0
    raw = json.dumps(value)
    if fault == "duplicate_json":
        raw = raw[:-1] + ',"tool_name":"session-prep.context.read"}'
    with pytest.raises(ConnectorUnavailable, match="session_prep_receipt_invalid"):
        read(httpx.Response(200, content=raw, headers=envelope))


def test_invalid_selection_is_rejected_before_obtaining_a_workload_token():
    calls = []
    wrong = selected().model_copy(update={"source_turn_ref": "invalid"})
    with pytest.raises(ConnectorUnavailable, match="session_prep_scope_invalid"):
        read(selection=wrong, token=lambda: calls.append("token"))
    assert not calls


def test_network_and_identity_errors_never_disclose_transport_secrets():
    def fail(_request):
        raise httpx.ReadTimeout("synthetic_PRIVATE_transport")

    with pytest.raises(ConnectorUnavailable, match="session_prep_request_unconfirmed") as error:
        read(handler=fail)
    assert "PRIVATE" not in str(error.value)
    with pytest.raises(ConnectorUnavailable, match="session_prep_identity_unavailable"):
        read(token=lambda: "invalid token with spaces")


@pytest.mark.parametrize(
    "origin",
    [
        "http://core.example.invalid",
        "https://user:secret@core.example.invalid",
        "https://core.example.invalid/other",
        "https://core.example.invalid?query=1",
    ],
)
def test_configured_origin_cannot_redirect_credentials(origin):
    with pytest.raises(ValueError, match="configured HTTPS origin"):
        HttpCoreSessionPrep(origin, lambda: "unused")
