"""Receipt joins, chronology and uncertain-state regressions; invented fixtures."""
from base64 import b64encode
from copy import deepcopy
from typing import Any

import pytest
from lab.completed_action_evaluator import (
    digest,
    evaluate_completed_action,
    evaluate_cycles,
    seal,
    text_digest,
)
from lab.cycle_personas import scenarios, speech_script
from lab.referral_pdf import build_referral_pdf


def evidence(case):
    content = speech_script(case, include_contact_resolution=True)
    source_sha = text_digest(content)
    scope = {"workspace_id": "workspace", "box_id": "box", "owner_id": "human"}
    action = {"action": "spruce_secure_message", "ticket_id": "ticket", "revision_id": "revision",
              "operation_id": "operation", "payload_hash": "a" * 64}
    team = {role: "bot-" + role for role in ("scribe", "visit_prep", "research", "follow_up", "chief")}
    def draft(role) -> dict[str, Any]:
        return {"state": "accepted", "agent_id": team[role], "source_sha256": source_sha,
            "content": role + " reviewed result", "content_sha256": text_digest(role + " reviewed result"),
            "acceptance_receipt_id": role + "-accept", "revision_id": role + "-revision"}
    joined = {"scope": scope, "action": action, "source_sha256": source_sha,
              "raw": {"native_product_fixture": True}}
    approval = {**deepcopy(joined), "id": "approval", "state": "approved", "actor_id": "human",
        "administrative_delivery_confirmed": True, "follow_up_bot_id": team["follow_up"],
        "consent_source_sha256": source_sha, "observed_at": "2026-10-06T12:00:00Z"}
    plugin = {**deepcopy(joined), "id": "plugin", "state": "saved", "actor_id": team["follow_up"],
        "tool": "execute_reviewed_delivery", "provider": "spruce",
        "admitted_at": "2026-10-06T12:00:01Z", "observed_at": "2026-10-06T12:00:03Z"}
    publisher = {"operation_id": "operation", "state": "accepted", "request_id": "request",
        "content_sha256": text_digest(case["approved_action"]["body"]),
        "recipient": case["approved_action"]["recipient"], "wire_sha256": "b" * 64,
        "document_attached": False}
    observed = {"id": "observation", "operation_id": "operation", "acceptance": "accepted"}
    observed["sha256"] = digest({"domain": "cosmas-vendor-public-observation.v1", "value": observed})
    publisher["raw"] = {"command_revision": {**scope, "action_revision_id": "revision",
        "intended_operation_id": "operation", "payload_hash": action["payload_hash"],
        "private_command": {"operation_id": "operation", "revision_id": "revision",
            "selection": {"vendor": "spruce"}, "intent": {"kind": "message.submit",
                "text": case["approved_action"]["body"], "destination": {"channel": "secure",
                    "contact_id": case["approved_action"]["recipient"]}}}},
        "submit_observation": {"source": "submit", "kind": "submission", "operation_id": "operation",
            "private_reference": {"value": "request"}, "public_observation": observed}}
    receiver = {"contract": "cosmabot.virtual-receiver-receipt.v1", "id": "receiver", "item_id": "item",
        "operation_id": "operation", "request_id": "request", "state": "received", "synthetic_only": True,
        "content": case["approved_action"]["body"], "content_sha256": publisher["content_sha256"],
        "recipient": publisher["recipient"], "wire_sha256": publisher["wire_sha256"],
        "observed_at": "2026-10-06T12:00:02Z"}
    receiver["sha256"] = digest(receiver)
    reopened = {**deepcopy(joined), "id": "reopen", "state": "approved", "dispatch": "response_observed",
        "request_id": "request", "item_id": "item", "receiver_receipt_id": "receiver",
        "conflicting_evidence": False, "acceptance": "accepted", "transport": "not_observed"}
    ack = {"actor": "virtual_patient", "author_agent_id": case["patient"]["author_agent_id"],
        "state": "acknowledged", "operation_id": "operation", "receiver_receipt_id": "receiver",
        "receiver_sha256": receiver["sha256"], "id": "patient-ack", "content": "I received the administrative request.",
        "content_sha256": text_digest("I received the administrative request."), "scenario_id": case["scenario_id"],
        "administrative_intent": case["administrative_intent"]["purpose"], "observed_at": "2026-10-06T12:00:04Z"}
    drafts = {role: draft(role) for role in team}
    drafts["chief"].update(state="saved", admission_id="chief-admission", result_entry_id="chief-result",
        accepted_draft_receipt_ids={role: drafts[role]["acceptance_receipt_id"] for role in team if role != "chief"})
    drafts["chief"].pop("acceptance_receipt_id")
    referral = None
    if case['platform'] == 'mobile':
        pdf = build_referral_pdf(accepted_scribe=drafts['scribe']['content'], visit_prep=drafts['visit_prep']['content'],
            owner_label='Synthetic owner', source_sha256=source_sha, synthetic_only=True)
        document = {'artifact_id': 'artifact', 'sha256': pdf.pdf_sha256, 'byte_length': len(pdf.data),
                    'media_type': 'application/pdf'}
        proof = {'kind': 'reviewed_note', 'note_id': 'note', 'content_sha256': source_sha, 'source_fingerprint': 'c' * 64}
        publisher['raw']['command_revision']['public_review'] = {'source': proof}
        def custody(kind, state):
            row = {'scope': {'kind': 'workspace', 'id': scope['workspace_id']}, 'command_kind': kind,
                'idempotency_key': 'key-' + kind, 'request_sha256': 'd' * 64, 'outcome': 'recorded',
                'effect': {'artifact_id': 'artifact', 'receipt_id': kind + '-receipt'},
                'artifact': {'artifact_id': 'artifact', 'document': document, 'source': proof, 'state': state}}
            row['effect']['receipt_sha256'] = digest({'domain': 'cosmas-vendor-public-receipt.v1', 'value': {
                key: row[key] for key in ('scope', 'command_kind', 'idempotency_key', 'request_sha256', 'effect')}})
            return row
        human_review = {'actor_id': scope['owner_id'], 'artifact_id': 'artifact', 'pdf_sha256': pdf.pdf_sha256,
            'source_sha256': source_sha, 'context_sha256': 'e' * 64, 'reviewed': True, 'content': 'Reviewed actual PDF.',
            'observed_at': '2026-10-06T11:59:59Z'}
        human_review['sha256'] = digest(human_review)
        referral = {'artifact_id': 'artifact', 'pdf_base64': b64encode(pdf.data).decode(), 'pdf_sha256': pdf.pdf_sha256,
            'byte_length': len(pdf.data), 'pages': pdf.pages, 'extracted_text': pdf.extracted_text,
            'extracted_text_sha256': pdf.extracted_text_sha256, 'source_sha256': source_sha,
            'accepted_scribe_sha256': pdf.accepted_scribe_sha256, 'visit_prep_sha256': pdf.visit_prep_sha256,
            'custody': {'intent': custody('artifact_intent', 'empty'), 'content': custody('artifact_content', 'ready'),
                'preview': {'status': 200, 'sha256': pdf.pdf_sha256, 'byte_length': len(pdf.data)}},
            'human_review': human_review}
    return {"contract": "cosmabot.completed-action-evidence.v1", "scenario_id": case["scenario_id"],
        "platform": case["platform"], "scope": scope, "action": action,
        "source": {"reviewed": True, "entry_ids": ["source-entry"], "content": content,
                   "content_sha256": source_sha, "input_mode": "simulated_asr", 'referral_packet': referral},
        "team": team, "drafts": drafts,
        "records": {stage: seal(value) for stage, value in zip(
            ("approval", "plugin", "publisher", "receiver", "reopen", "patient_ack"),
            (approval, plugin, publisher, receiver, reopened, ack), strict=True)},
        "consent": {"state": "confirmed", "source_sha256": source_sha, "receipt_id": "approval",
                    "before_dispatch": True, "reviewed_content": content},
        "counters": {"pre_consent_submissions": 0, "submission_requests": 1, "receiver_items": 1,
                     "replay_new_submissions": 0}}


@pytest.mark.parametrize("case", scenarios(), ids=lambda case: case["scenario_id"])
def test_all_three_complete_only_with_bound_later_receiver_and_ack(case):
    result = evaluate_completed_action(evidence(case), case)
    assert result["passed"], result["failures"]
    assert "not independent origin attestation" in result["limits"][0]


@pytest.mark.parametrize("stage,field,value,failure", [
    ("approval", "administrative_delivery_confirmed", False, "human_exact_administrative_permission"),
    ("plugin", "actor_id", "different-bot", "follow_up_real_plugin_receipt"),
    ("plugin", "state", "pending", "follow_up_real_plugin_receipt"),
    ("publisher", "request_id", "different-request", "receiver_exact_message"),
    ("publisher", "document_attached", True, "administrative_only"),
    ("receiver", "state", "pending", "independent_receiver_receipt"),
    ("receiver", "recipient", "different-recipient", "receiver_exact_message"),
    ("reopen", "dispatch", "unconfirmed", "reopen_exact_saved_reference"),
    ("reopen", "conflicting_evidence", True, "reopen_exact_saved_reference"),
    ("patient_ack", "observed_at", "2026-10-06T11:59:59Z", "receipt_chronology"),
    ("patient_ack", "receiver_receipt_id", "wrong-receipt", "patient_ack_after_receiver"),
])
def test_hashed_but_wrong_or_uncertain_evidence_does_not_complete(stage, field, value, failure):
    case = scenarios()[0]
    packet = evidence(case)
    packet["records"][stage]["payload"][field] = value
    packet["records"][stage] = seal(packet["records"][stage]["payload"])
    result = evaluate_completed_action(packet, case)
    assert not result["passed"] and failure in result["failures"]


@pytest.mark.parametrize("mutation,failure", [
    (lambda p: p["records"].pop("publisher"), "all_receipt_stages"),
    (lambda p: p["records"]["approval"].update(sha256="0" * 64), "approval_export_hash"),
    (lambda p: p["source"].update(content="changed source"), "source_reviewed"),
    (lambda p: p["drafts"]["research"].update(state="draft"), "accepted_team_outputs"),
    (lambda p: p["drafts"]["chief"].update(state="pending"), "chief_saved_result"),
    (lambda p: p["counters"].update(replay_new_submissions=1), "single_dispatch_no_replay"),
    (lambda p: p["counters"].update(pre_consent_submissions=1), "single_dispatch_no_replay"),
    (lambda p: p["consent"].update(state="ambiguous"), "reviewed_contact_consent"),
])
def test_missing_drift_replay_and_ambiguous_consent_remain_open(mutation, failure):
    case = scenarios()[2]
    packet = deepcopy(evidence(case))
    mutation(packet)
    result = evaluate_completed_action(packet, case)
    assert not result["passed"] and failure in result["failures"]


def test_personas_keep_ack_unexecuted_and_referral_delivery_outside_authority(tmp_path):
    from lab.cycle_personas import export_personas
    cases = scenarios()
    assert len({case["scenario_id"] for case in cases}) == 3
    assert all(case["final_patient_ack"]["state"] == "not_generated" for case in cases)
    assert "has not been delivered" in cases[1]["final_patient_ack"]["content_template"]
    assert all(not case["approved_action"]["clinical_content_allowed"] for case in cases)
    assert "Do not use the household phone" not in speech_script(cases[2])
    assert "Do not use the household phone" in speech_script(cases[2], include_contact_resolution=True)
    manifest = export_personas(tmp_path / "personas")
    assert manifest["completion_evidence"] == "not_executed"
    with pytest.raises(FileExistsError):
        export_personas(tmp_path / "personas")


def test_reused_workspace_or_team_cannot_establish_three_independent_journeys():
    items = [(evidence(case), case) for case in scenarios()]
    result = evaluate_cycles(items)
    assert not result["passed"]
    assert result["checks"]["distinct_workspaces"] is False
    assert result["checks"]["three_distinct_bot_teams"] is False


def test_native_not_observed_preserved_but_pending_requires_native_status_evidence():
    case = scenarios()[0]
    packet = evidence(case)
    assert evaluate_completed_action(packet, case)['passed']
    reopened = packet['records']['reopen']['payload']
    reopened['transport'] = 'pending'
    packet['records']['reopen'] = seal(reopened)
    assert 'reopen_exact_saved_reference' in evaluate_completed_action(packet, case)['failures']
    status = {'id': 'status', 'operation_id': 'operation', 'kind': 'transport', 'transport': 'pending'}
    status['sha256'] = digest({'domain': 'cosmas-vendor-public-observation.v1', 'value': status})
    reopened['raw']['status_observations'] = [status]
    packet['records']['reopen'] = seal(reopened)
    assert evaluate_completed_action(packet, case)['passed']


def test_mobile_ready_claim_requires_actual_pdf_preview_and_prior_human_review():
    case = scenarios()[1]
    packet = evidence(case)
    assert evaluate_completed_action(packet, case)['passed']
    packet['source']['referral_packet']['human_review']['reviewed'] = False
    assert 'referral_pdf_preview_reviewed' in evaluate_completed_action(packet, case)['failures']
    packet['source'].pop('referral_packet')
    assert not evaluate_completed_action(packet, case)['passed']
