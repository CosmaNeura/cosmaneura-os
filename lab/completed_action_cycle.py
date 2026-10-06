"""Reusable current-session plugin → reviewed bot action → local receiver cycle.

The caller supplies actual signed API/session and admitted-worker hooks. This
module never fabricates a review, model response, credential, source or receipt.
Virtual personas/plans are authored inputs; only returned API/SQL/receiver facts
can advance the cycle. No real provider or paid model is called by this runner.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from cosmas_os.api import vendor_work_schemas as schema
from cosmas_os.plugins.runtime import PluginRuntime
from lab.completed_action_sandbox import CompletedActionSandbox, digest


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    temporary.replace(path)


def body_response(response):
    if not isinstance(response, httpx.Response) or response.status_code != 200:
        raise AssertionError("signed_product_request_unavailable")
    return response.json()


def bound(detail, key, **extra):
    summary = detail["summary"]
    return {"expected_version": summary["version"], "operation_id": summary["operation_id"],
            "revision_id": summary["revision_id"], "payload_hash": summary["payload_hash"],
            "idempotency_key": key, **extra}


def run_completed_action_cycle(*, runtime: PluginRuntime, human_request, scenario, scope,
                              accepted_source, plan, run_follow_up, reopen, acknowledge,
                              sandbox: CompletedActionSandbox, output: Path, lose_reply=False):
    """Execute one authored administrative message with actual supplied hooks.

    run_follow_up(handle, key) must reserve/claim/dispatch the real v8 FollowUp
    admission and return {state, execution, admission, tool_receipts}; its execute
    tool receives only four handle fields. reopen() returns fresh signed
    workspace/vendor facts and independently exported SQL claim counts.
    acknowledge(receiver_receipt, scenario) produces a new virtual-patient
    response only after seeing the exact durable receiver evidence.
    """
    output.mkdir(parents=True, exist_ok=False)
    initial_counters = sandbox.counters()
    wid = scope["workspace_id"]
    for key in ("workspace_id", "box_id", "owner_id", "follow_up_bot_id"):
        if str(UUID(scope[key])) != scope[key]:
            raise ValueError("canonical_scope_required")
    source_sha = hashlib.sha256(accepted_source["content"].encode()).hexdigest()
    if (accepted_source["content_sha256"] != source_sha or accepted_source["reviewed"] is not True
            or plan["source_sha256"] != source_sha or plan["scenario_id"] != scenario["scenario_id"]
            or plan["author_agent_id"] == "" or scenario["synthetic_only"] is not True
            or plan["consent"]["state"] != "confirmed"):
        raise ValueError("reviewed_authored_source_binding_required")
    message = plan["action"]["content"]
    if not isinstance(message, str) or not 1 <= len(message) <= 4000:
        raise ValueError("bounded_authored_administrative_message_required")
    message_sha = hashlib.sha256(message.encode()).hexdigest()
    prefix = "cycle-" + uuid4().hex
    proposal = {"expected_workspace_revision": accepted_source["workspace_revision"],
        "idempotency_key": prefix + "-proposal", "proposed_operation_id": str(uuid4()),
        "action": "spruce_secure_message", "connection": scope["connection"],
        "correspondence": scope["correspondence"], "source": accepted_source["vendor_source"],
        "due_date": plan["action"]["due_date"], "expected_outcome": plan["action"]["expected_outcome"],
        "share_to_practice": False, "message": message}
    # The current-session real plugin owns schema/path checks and signed API
    # discovery. This is preparation, never an approval or completed send.
    created = runtime.call("spruce_prepare_delivery", {"workspace_id": wid, "request": proposal})
    prepared = schema.CommandResponse.model_validate(created["result"]).public()
    if prepared["outcome"] != "recorded" or prepared["summary"]["effect"] != "proposed":
        raise AssertionError("proposal_not_saved")
    tid = prepared["effect"]["ticket_id"]
    detail = runtime.call("vendor_work_inspect_work", {"workspace_id": wid, "ticket_id": tid})["result"]
    action = {"kind": "vendor_delivery", "action": "spruce_secure_message", **{key: detail["summary"][key]
              for key in ("ticket_id", "revision_id", "operation_id", "payload_hash")},
        "content_sha256": message_sha, "source_sha256": source_sha,
        "agent_id": scope["follow_up_bot_id"]}
    if sandbox.counters() != initial_counters:
        raise AssertionError("preapproval_dispatch")
    approval_request = bound(detail, prefix + "-human-approval", review_sha256=detail["review_sha256"],
        choice="approve", administrative_delivery_confirmed=True, follow_up_bot_id=scope["follow_up_bot_id"])
    approval = body_response(human_request("POST", f"/workspaces/{wid}/vendor-work/{tid}/decide",
        headers={"X-Cosmas-Vendor-Contract": "1"}, json=approval_request))
    if approval["summary"]["effect"] != "approved" or sandbox.counters() != initial_counters:
        raise AssertionError("review_must_precede_dispatch")
    handle = {key: action[key] for key in ("ticket_id", "revision_id", "operation_id", "payload_hash")}
    write(output / "INPUT.json", {"scenario": scenario, "source": accepted_source, "plan": plan,
        "scope": scope, "proposal": proposal, "human_approval": approval_request})
    observed_reply = None
    try:
        observed_reply = run_follow_up(handle, prefix + "-execute")
        if lose_reply:
            # Discard only after the actual worker returned its durable result.
            # This simulates lost client disclosure, not unsent provider work.
            observed_reply = None
            raise httpx.ReadTimeout("simulated lost foreground reply after worker settlement")
    except httpx.ReadTimeout:
        write(output / "LOST_REPLY.json", {"state": "response_unconfirmed", "automatic_retry": False,
            "handle": handle, "next_step": "read_saved_result", "provider_resubmit": False})
    # Reopen through the supplied fresh signed API/SQL reader, never execute a
    # second action merely to recover a client response.
    fresh = reopen(action)
    actual_receiver = sandbox.receipt(action["operation_id"])
    if actual_receiver["content_sha256"] != message_sha or actual_receiver["state"] != "received":
        raise AssertionError("receiver_content_binding_changed")
    before_replay = sandbox.counters()
    saved = runtime.call("vendor_work_inspect_work", {"workspace_id": wid, "ticket_id": tid})["result"]
    replay = run_follow_up(handle, prefix + "-same-action-readback")
    after_replay = sandbox.counters()
    if after_replay != before_replay or fresh["submit_claim_count"] != 1 or fresh["attempt_count"] != 1:
        raise AssertionError("recovery_repeated_provider_dispatch")
    patient = acknowledge(actual_receiver, scenario)
    if (patient["actor"] != "virtual_patient" or patient["receiver_receipt_id"] != actual_receiver["id"]
            or patient["after_receiver"] is not True or not patient["content"].strip()):
        raise AssertionError("patient_response_without_receiver_proof")
    records = {stage: {"payload": fresh[stage], "sha256": digest(fresh[stage])}
               for stage in ("approval", "plugin", "publisher", "reopen")}
    records["receiver"] = {"payload": actual_receiver, "sha256": digest(actual_receiver)}
    records["patient_ack"] = {"payload": patient, "sha256": digest(patient)}
    # The plan is an authored input. Team identities and accepted draft states
    # must come from fresh product/SQL exports, never from that input alone.
    actual_source, actual_team, actual_drafts = fresh["source"], fresh["team"], fresh["drafts"]
    if actual_source["content_sha256"] != source_sha:
        raise AssertionError("fresh_source_binding_changed")
    result = {"contract": "cosmabot.completed-action-evidence.v1", "scenario_id": scenario["scenario_id"],
        "platform": scenario["platform"], "scope": {key: scope[key] for key in ("workspace_id", "box_id", "owner_id")},
        "source": actual_source, "referral_packet": actual_source.get("referral_packet"), "team": actual_team, "drafts": actual_drafts, "action": action, "records": records,
        "consent": {**plan["consent"], "source_sha256": source_sha,
                    "receipt_id": approval["effect"]["receipt_id"], "before_dispatch": True},
        "counters": {"pre_consent_submissions": 0,
            "submission_requests": after_replay["submission_requests"] - initial_counters["submission_requests"],
            "receiver_items": after_replay["receiver_items"] - initial_counters["receiver_items"],
            "replay_new_submissions": after_replay["submission_requests"] - before_replay["submission_requests"]},
        "worker_reply": observed_reply,
        "recovered_worker_reply": replay, "fresh_api_detail": saved,
        "provenance": {"model": "Codex-authored plan through actual admitted workers; no paid model",
                       "provider": "real Spruce adapter to owned local HTTP substitute",
                       "auth": "actual signed local product API/current-session plugin; no JWT file",
                       "source": accepted_source["provenance"]}}
    write(output / "RESULT.json", result)
    return result
