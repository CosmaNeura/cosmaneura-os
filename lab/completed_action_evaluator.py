"""Cross-check exported product/SQL and independent sandbox receiver evidence.

This evaluator does not turn authored prose into proof or attest receipt origin.
The runner must export the actual API/SQL records and sandbox files. Canonical
hashes detect drift; exact joins detect wrong-workspace/source/action evidence.
Spruce's posted-item observation alone is not patient delivery or acknowledgment.
"""
from __future__ import annotations

import hashlib
import json
from base64 import b64decode
from datetime import datetime
from io import BytesIO

from pypdf import PdfReader

CONTRACT = "cosmabot.completed-action-evidence.v1"
ROLES = ("scribe", "visit_prep", "research", "follow_up", "chief")
ACTION_KEYS = ("ticket_id", "revision_id", "operation_id", "payload_hash")
SCOPE_KEYS = ("workspace_id", "box_id", "owner_id")
STAGES = ("approval", "plugin", "publisher", "receiver", "reopen", "patient_ack")


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def text_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def seal(payload):
    """For the runner's additive export envelope; do not alter product records."""
    return {"payload": payload, "sha256": digest(payload)}


def _nonempty(value):
    return type(value) is str and bool(value.strip())


def _time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed


def evaluate_completed_action(evidence, scenario):
    """Return a closed completion verdict; malformed/unknown evidence stays open.

    records[stage] is {payload,sha256}. API/SQL payloads retain their raw product
    record under `raw` and expose exact scope/action joins beside it. Receiver
    payload is the unmodified independent sandbox receipt. Patient acknowledgment
    is a *later* virtual-patient receipt, never the scenario's template text.
    """
    checks = {}

    def check(name, value):
        checks[name] = value is True

    try:
        check("contract", evidence["contract"] == CONTRACT)
        check("scenario", evidence["scenario_id"] == scenario["scenario_id"]
              and evidence["platform"] == scenario["platform"])
        scope, action, source = (evidence[key] for key in ("scope", "action", "source"))
        check("scope_complete", all(_nonempty(scope[key]) for key in SCOPE_KEYS))
        check("action_complete", all(_nonempty(action[key]) for key in ACTION_KEYS)
              and action["action"] == "spruce_secure_message")
        check("source_reviewed", source["reviewed"] is True and bool(source["entry_ids"])
              and source["content_sha256"] == text_digest(source["content"]))
        check("source_input_disclosed", source["input_mode"] in {
            "recognized_speech", "simulated_asr", "human_reviewed_typed"})
        team = evidence["team"]
        check("distinct_bot_identities", set(team) == set(ROLES)
              and all(_nonempty(value) for value in team.values()) and len(set(team.values())) == len(ROLES))
        drafts = evidence["drafts"]
        check("accepted_team_outputs", set(drafts) == set(ROLES) and all(
            row["state"] == "accepted" and row["agent_id"] == team[role]
            and row["source_sha256"] == source["content_sha256"]
            and row["content_sha256"] == text_digest(row["content"])
            and _nonempty(row["acceptance_receipt_id"]) and _nonempty(row["revision_id"])
            for role, row in drafts.items() if role != "chief"))
        chief = drafts["chief"]
        check("chief_saved_result", chief["state"] == "saved" and chief["agent_id"] == team["chief"]
              and chief["source_sha256"] == source["content_sha256"]
              and chief["content_sha256"] == text_digest(chief["content"])
              and _nonempty(chief["admission_id"]) and _nonempty(chief["result_entry_id"])
              and chief["accepted_draft_receipt_ids"] == {
                  role: row["acceptance_receipt_id"] for role, row in drafts.items() if role != "chief"})
        records = evidence["records"]
        check("all_receipt_stages", set(records) == set(STAGES))
        payloads = {}
        for stage in STAGES:
            envelope = records[stage]
            check(stage + "_export_hash", set(envelope) == {"payload", "sha256"}
                  and envelope["sha256"] == digest(envelope["payload"]))
            payloads[stage] = envelope["payload"]
        for stage in ("approval", "plugin", "reopen"):
            row = payloads[stage]
            check(stage + "_joins", row["scope"] == scope and row["action"] == action
                  and row["source_sha256"] == source["content_sha256"]
                  and _nonempty(row["id"]) and bool(row["raw"]))
        approval, plugin, publisher, receiver, reopened, ack = (payloads[key] for key in STAGES)
        check("human_exact_administrative_permission", approval["actor_id"] == scope["owner_id"]
              and approval["administrative_delivery_confirmed"] is True
              and approval["follow_up_bot_id"] == team["follow_up"]
              and approval["state"] == "approved")
        consent = evidence["consent"]
        check("reviewed_contact_consent", consent["state"] == "confirmed"
              and consent["source_sha256"] == approval["consent_source_sha256"]
              and consent["receipt_id"] == approval["id"] and consent["before_dispatch"] is True
              and _nonempty(consent["reviewed_content"])
              and consent["source_sha256"] == text_digest(consent["reviewed_content"]))
        check("follow_up_real_plugin_receipt", plugin["actor_id"] == team["follow_up"]
              and plugin["tool"] == "execute_reviewed_delivery"
              and plugin["state"] == "saved" and plugin["provider"] == "spruce")
        expected = scenario["approved_action"]
        content_sha = text_digest(expected["body"])
        check("publisher_exact_message", publisher["operation_id"] == action["operation_id"]
              and publisher["state"] == "accepted" and _nonempty(publisher["request_id"])
              and publisher["content_sha256"] == content_sha
              and publisher["recipient"] == expected["recipient"])
        native = publisher["raw"]
        revision, observation = native["command_revision"], native["submit_observation"]
        command, observed = revision["private_command"], observation["public_observation"]
        check("publisher_native_command", revision["action_revision_id"] == action["revision_id"]
              and revision["intended_operation_id"] == action["operation_id"]
              and revision["payload_hash"] == action["payload_hash"]
              and all(revision[key] == scope[key] for key in SCOPE_KEYS)
              and command["operation_id"] == action["operation_id"]
              and command["revision_id"] == action["revision_id"]
              and command["selection"]["vendor"] == "spruce"
              and command["intent"]["kind"] == "message.submit"
              and command["intent"]["text"] == expected["body"]
              and command["intent"]["destination"] == {"channel": "secure", "contact_id": expected["recipient"]}
              and command["intent"].get("attachment") is None)
        check("publisher_native_observation", observation["source"] == "submit"
              and observation["kind"] == "submission" and observation["operation_id"] == action["operation_id"]
              and observed["operation_id"] == action["operation_id"] and observed["acceptance"] == "accepted"
              and observation["private_reference"]["value"] == publisher["request_id"]
              and observed["sha256"] == digest({"domain": "cosmas-vendor-public-observation.v1",
                  "value": {key: value for key, value in observed.items() if key != "sha256"}}))
        check("independent_receiver_receipt", receiver["contract"] == "cosmabot.virtual-receiver-receipt.v1"
              and receiver["synthetic_only"] is True and receiver["state"] == "received"
              and receiver["sha256"] == digest({key: value for key, value in receiver.items() if key != "sha256"})
              and _nonempty(receiver["id"]) and _nonempty(receiver["item_id"]))
        check("receiver_exact_message", receiver["operation_id"] == action["operation_id"]
              and receiver["request_id"] == publisher["request_id"]
              and receiver["recipient"] == expected["recipient"]
              and receiver["content"] == expected["body"] and receiver["content_sha256"] == content_sha
              and receiver["wire_sha256"] == publisher["wire_sha256"])
        check("receipt_chronology", _time(approval["observed_at"]) <= _time(plugin["admitted_at"])
              <= _time(receiver["observed_at"]) <= _time(plugin["observed_at"])
              <= _time(ack["observed_at"]))
        transport_evidence = reopened["raw"].get("status_observations", [])
        transport_supported = reopened["transport"] == "not_observed" or (
            reopened["transport"] == "pending" and any(
                row.get("operation_id") == action["operation_id"] and row.get("transport") == "pending"
                and row.get("sha256") == digest({"domain": "cosmas-vendor-public-observation.v1",
                    "value": {key: value for key, value in row.items() if key != "sha256"}})
                for row in transport_evidence))
        check("reopen_exact_saved_reference", reopened["request_id"] == publisher["request_id"]
              and reopened["item_id"] == receiver["item_id"]
              and reopened["receiver_receipt_id"] == receiver["id"]
              and reopened["dispatch"] == "response_observed" and reopened["conflicting_evidence"] is False
              and reopened["acceptance"] == "accepted" and transport_supported
              and reopened["state"] not in {"pending", "unconfirmed", "unknown", "superseded"})
        check("patient_ack_after_receiver", ack["actor"] == "virtual_patient"
              and ack["author_agent_id"] in {"/root", "/root/fax_ui", "/root/fax_backend", "/root/google_calendar"}
              and ack["state"] == "acknowledged" and ack["operation_id"] == action["operation_id"]
              and ack["receiver_receipt_id"] == receiver["id"]
              and ack["receiver_sha256"] == receiver["sha256"] and _nonempty(ack["id"])
              and _nonempty(ack["content"]) and ack["content_sha256"] == text_digest(ack["content"])
              and ack["scenario_id"] == scenario["scenario_id"]
              and ack["administrative_intent"] == scenario["administrative_intent"]["purpose"])
        counters = evidence["counters"]
        check("single_dispatch_no_replay", all(type(counters[key]) is int for key in (
            "pre_consent_submissions", "submission_requests", "receiver_items", "replay_new_submissions"))
              and counters["pre_consent_submissions"] == 0 and counters["submission_requests"] == 1
              and counters["receiver_items"] == 1 and counters["replay_new_submissions"] == 0)
        check("administrative_only", expected["clinical_content_allowed"] is False
              and publisher["document_attached"] is False)
        if scenario["scenario_id"] == "mobile-ankle-referral-packet":
            pdf = source["referral_packet"]
            data = b64decode(pdf["pdf_base64"], validate=True)
            check("referral_pdf_bytes", 5 <= len(data) <= 1_048_576
                  and hashlib.sha256(data).hexdigest() == pdf["pdf_sha256"]
                  and len(data) == pdf["byte_length"])
            reader = PdfReader(BytesIO(data), strict=True)
            extracted = "\n".join(page.extract_text() for page in reader.pages)
            check("referral_pdf_source_text", len(reader.pages) == pdf["pages"] and 1 <= pdf["pages"] <= 3
                  and extracted == pdf["extracted_text"] and text_digest(extracted) == pdf["extracted_text_sha256"]
                  and pdf["source_sha256"] == source["content_sha256"]
                  and pdf["accepted_scribe_sha256"] == drafts["scribe"]["content_sha256"]
                  and pdf["visit_prep_sha256"] == drafts["visit_prep"]["content_sha256"])
            for name in ("intent", "ingest"):
                custody = pdf["custody"]["intent" if name == "intent" else "content"]
                check("referral_pdf_" + name, custody["outcome"] == "recorded"
                      and custody["scope"] == {"kind": "workspace", "id": scope["workspace_id"]}
                      and custody["artifact"]["artifact_id"] == pdf["artifact_id"]
                      and custody["artifact"]["document"] == {"artifact_id": pdf["artifact_id"],
                          "sha256": pdf["pdf_sha256"], "byte_length": pdf["byte_length"], "media_type": "application/pdf"}
                      and custody["artifact"]["source"] == revision["public_review"]["source"]
                      and custody["effect"]["receipt_sha256"] == digest({"domain": "cosmas-vendor-public-receipt.v1",
                          "value": {key: custody[key] for key in ("scope", "command_kind", "idempotency_key", "request_sha256")}
                          | {"effect": {key: value for key, value in custody["effect"].items() if key != "receipt_sha256"}}}))
            preview, reviewed = pdf["custody"]["preview"], pdf["human_review"]
            check("referral_pdf_preview_reviewed", pdf["custody"]["content"]["artifact"]["state"] == "ready"
                  and preview["status"] == 200 and preview["sha256"] == pdf["pdf_sha256"]
                  and preview["byte_length"] == pdf["byte_length"]
                  and reviewed["actor_id"] == scope["owner_id"] and reviewed["reviewed"] is True
                  and reviewed["artifact_id"] == pdf["artifact_id"] and reviewed["pdf_sha256"] == pdf["pdf_sha256"]
                  and reviewed["source_sha256"] == source["content_sha256"]
                  and _nonempty(reviewed["context_sha256"]) and _nonempty(reviewed["content"])
                  and reviewed["sha256"] == digest({key: value for key, value in reviewed.items() if key != "sha256"})
                  and _time(reviewed["observed_at"]) <= _time(approval["observed_at"]))
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeError):
        check("well_formed_evidence", False)
    passed = bool(checks) and all(checks.values())
    return {"contract": "cosmabot.completed-action-verdict.v1", "passed": passed,
        "completion": "receiver_received_and_virtual_patient_acknowledged" if passed else "not_established",
        "checks": checks, "failures": [key for key, value in checks.items() if not value],
        "limits": ["Exported receipt cross-check, not independent origin attestation.",
            "Owned Spruce HTTP receiver substitute; no live account or clinical/referral delivery qualification."]}


def evaluate_cycles(items):
    """Three fresh teams/workspaces with separately bounded receiver outcomes."""
    results = [evaluate_completed_action(evidence, scenario) for evidence, scenario in items]
    checks = {"three_cases": len(items) == 3,
        "distinct_scenarios": len({scenario["scenario_id"] for _, scenario in items}) == 3,
        "desktop_and_mobile": {scenario["platform"] for _, scenario in items} == {"desktop", "mobile"},
        "distinct_workspaces": len({evidence.get("scope", {}).get("workspace_id") for evidence, _ in items}) == 3}
    identities = [agent for evidence, _ in items for agent in evidence.get("team", {}).values()]
    checks["three_distinct_bot_teams"] = len(identities) == 15 and len(set(identities)) == 15
    return {"contract": "cosmabot.completed-action-cycles-verdict.v1",
        "passed": all(checks.values()) and all(result["passed"] for result in results),
        "checks": checks, "results": results}
