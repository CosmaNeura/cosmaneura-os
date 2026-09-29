import json
from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr
from tests.unit.test_core_capture_admission import selection
from tests.unit.test_core_session_prep import NOW, TURN, receipt

from cosmas_os.adapters.core_session_prep_connection import BoundedSessionPrepConnection
from cosmas_os.adapters.core_session_prep_flow import HttpCoreSessionPrepFlow
from cosmas_os.application.capture_deadline import CaptureBudget, CaptureDeadlineExceeded
from cosmas_os.application.session_prep import public_brief
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_session_prep import CoreSessionPrepReceipt


def handler(selected, calls, mutate=lambda phase, body, headers: None, state="ready"):
    def send(request):
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        calls.append(request)
        headers = {"Cache-Control": "no-store", "Content-Type": "application/json"}
        phase = path.rsplit("/", 1)[-1]
        if phase == "exchange":
            assert request.headers["Authorization"] == "Bearer synthetic_PRIVATE_user"
            assert body == {
                "requested_surface": "provider_assistant",
                "record_ref": selected.appointment_ref,
            }
            response = {
                "context_token": "synthetic_PRIVATE_mount",
                "token_type": "Bearer",
                "issued_at": NOW.isoformat(),
                "refresh_after": (NOW + timedelta(minutes=1)).isoformat(),
                "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
            }
            headers["X-Cosmaneura-Embed-Version"] = "1.0"
            status = 201
        else:
            assert request.headers["Authorization"] == "Bearer synthetic_PRIVATE_prep"
            assert request.headers["X-Cosmaneura-Mount-Context"] == "synthetic_PRIVATE_mount"
            assert request.headers["X-Cosmaneura-Client-Turn-ID"] == str(TURN)
            headers["X-Cosmaneura-Client-Turn-ID"] = str(TURN)
            if phase == "resolve":
                assert body is None
                response = {
                    "surface": "provider_assistant",
                    "auth_tier": "provider",
                    "capabilities": ["session-prep:read"],
                    "actor_id": selected.expected_actor_ref,
                    "tenant_id": selected.expected_tenant_ref,
                }
                headers.update(
                    {
                        "X-Cosmaneura-Interaction-Ref": "interaction_invented_current",
                        "X-Cosmaneura-Session-Prep-Context": "context_invented_current",
                    }
                )
                status = 200
            elif phase == "write":
                phase = body["phase"]
                assert (
                    request.headers["X-Cosmaneura-Interaction-Ref"]
                    == "interaction_invented_current"
                )
                if phase == "user_accepted":
                    assert body == {
                        "phase": "user_accepted",
                        "ingress_kind": "provider_ui_action",
                        "action_code": "session-prep.open",
                        "message": {"content_type": "text/plain", "content": "Open Session Prep"},
                    }
                else:
                    assert body["outcome"] == (
                        "completed" if state in {"ready", "refreshing"} else "unavailable"
                    )
                    assert "Invented reviewed" not in json.dumps(body)
                response = {
                    "client_turn_id": str(TURN),
                    "turn_ref": "conversation_turn_invented_current",
                    "phase": phase,
                    "state": "accepted" if phase == "user_accepted" else "completed",
                    "recorded_at": NOW.isoformat(),
                }
                headers["Idempotency-Replayed"] = "false"
                status = 201
            else:
                assert path == "/service/v1/companion/session-prep/brief"
                assert body["arguments"]["source_turn_ref"] == "conversation_turn_invented_current"
                assert body["arguments"]["context_snapshot_ref"] == "context_invented_current"
                response = receipt(state)
                headers["Idempotency-Replayed"] = "false"
                status = 200
        mutate(phase, response, headers)
        return httpx.Response(status, json=response, headers=headers)

    return send


def run(port, selected):
    token = port.exchange_context(selected, SecretStr("synthetic_PRIVATE_user"))
    context = port.resolve_context(selected, token, TURN)
    request = port.accept_action(context)
    result = port.read_brief(request)
    port.complete_action(request, result)
    return result


@pytest.mark.parametrize("state", ["ready", "pending", "refreshing", "unavailable"])
def test_canonical_provider_action_and_brief_use_only_dedicated_bounded_transport(state):
    selected, calls = selection(), []
    port = BoundedSessionPrepConnection(
        "https://core.example.invalid",
        lambda: "synthetic_PRIVATE_prep",
        CaptureBudget(10),
        transport_factory=lambda: httpx.MockTransport(handler(selected, calls, state=state)),
        now=lambda: NOW,
    )
    try:
        assert run(port, selected).result.state == state
        assert len(calls) == 5
        assert (
            len(
                {
                    call.headers["Idempotency-Key"]
                    for call in calls
                    if "Idempotency-Key" in call.headers
                }
            )
            == 3
        )
        for forbidden in (
            "/service/v1/scribe/capture/admit",
            "/service/v1/agent/tools/invoke",
        ):
            with pytest.raises(ConnectorUnavailable):
                with port._client.stream(
                    "POST", "https://core.example.invalid" + forbidden, headers={}
                ):
                    pytest.fail("Session Prep must not reach capture or generic tools")
        assert len(calls) == 5
    finally:
        port.close()


@pytest.mark.parametrize(
    "phase,fault",
    [
        ("resolve", "actor"),
        ("resolve", "capability"),
        ("resolve", "context"),
        ("user_accepted", "turn"),
        ("final_response", "source_turn"),
        ("final_response", "future"),
        ("exchange", "cache"),
    ],
)
def test_mismatched_authority_or_unconfirmed_canonical_phase_stops_the_flow(phase, fault):
    selected, calls = selection(), []

    def mutate(observed, body, headers):
        if observed != phase:
            return
        if fault == "actor":
            body["actor_id"] = "authority_actor_" + "0" * 25 + "2"
        elif fault == "capability":
            body["capabilities"] = []
        elif fault == "context":
            del headers["X-Cosmaneura-Session-Prep-Context"]
        elif fault == "turn":
            body["client_turn_id"] = "00000000-0000-4000-8000-000000000002"
        elif fault == "source_turn":
            body["turn_ref"] = "conversation_turn_other"
        elif fault == "future":
            body["recorded_at"] = (NOW + timedelta(minutes=1)).isoformat()
        else:
            headers["Cache-Control"] = "public"

    port = HttpCoreSessionPrepFlow(
        "https://core.example.invalid",
        lambda: "synthetic_PRIVATE_prep",
        transport=httpx.MockTransport(handler(selected, calls, mutate)),
        now=lambda: NOW,
    )
    try:
        with pytest.raises(ConnectorUnavailable) as error:
            run(port, selected)
        assert "PRIVATE" not in str(error.value)
        assert (
            len(calls)
            == {"exchange": 1, "resolve": 2, "user_accepted": 3, "final_response": 5}[phase]
        )
    finally:
        port.close()


def test_cancelled_identity_cannot_dispatch_a_late_session_prep_phase():
    selected, calls, budget = selection(), [], CaptureBudget(10)

    def token():
        budget.cancel()
        return "synthetic_PRIVATE_prep"

    port = BoundedSessionPrepConnection(
        "https://core.example.invalid",
        token,
        budget,
        transport_factory=lambda: httpx.MockTransport(handler(selected, calls)),
        now=lambda: NOW,
    )
    try:
        with pytest.raises((ConnectorUnavailable, CaptureDeadlineExceeded)):
            run(port, selected)
        assert len(calls) == 1
    finally:
        port.close()


@pytest.mark.parametrize(
    "text", ["Private link intake_" + "0" * 25 + "1", "synthetic_PRIVATE_token", "\0"]
)
def test_brief_projection_withholds_private_access_material(text):
    value = receipt()
    value["result"]["prepared_brief"]["recap"]["text"] = text
    with pytest.raises(WorkspaceError, match="session_prep_receipt_invalid"):
        public_brief(
            CoreSessionPrepReceipt.model_validate(value),
            private_tokens=("synthetic_PRIVATE_token",),
        )
