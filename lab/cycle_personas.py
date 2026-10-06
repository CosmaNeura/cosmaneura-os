"""Invented provider/patient conversations and receipt-bound cycle expectations.

These authored turns are inputs and acceptance criteria, never completed-action
evidence. A runner must record/recognize the speech or disclose typed input.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

CONTRACT = "cosmabot.virtual-clinic-personas.v1"
AUTHOR = "/root/fax_ui"
ROLES = ("scribe", "visit_prep", "research", "follow_up", "chief")


def turn(role, text, *, phase="visit"):
    return {"speaker": role, "phase": phase, "content": text, "synthetic_only": True}


COMMON = {
    "scribe": ["Use only recognized or explicitly reviewed source details.",
        "Separate patient reports from provider decisions; preserve missing facts.",
        "Save a private draft; exact human review is required before using it downstream."],
    "visit_prep": ["Prepare an administrative checklist from the accepted Scribe draft.",
        "Read only currently granted records and preserve unavailable information."],
    "research": ["Propose a general query without patient identifiers.",
        "Wait for exact human query approval before publisher I/O.",
        "Report actual returned evidence and limits; an empty result is not a citation."],
    "follow_up": ["Prepare a private action draft with named owner, exact recipient and consent scope.",
        "Human approval is distinct from plugin submission and receiver completion.",
        "Do not claim patient acknowledgment before its exact receiver receipt."],
    "chief": ["Read each exact accepted specialist result and preserve source/agent hashes.",
        "Distinguish drafted, approved, submitted, received and acknowledged work.",
        "Do not close pending or unknown work; reopening must not dispatch it again."],
}

_SCENARIOS = (
    {
        "scenario_id": "desktop-postvisit-confirmation", "platform": "desktop", "viewport": {"width": 1280, "height": 900},
        "provider": {"name": "Dr. Mira Solis", "role": "physician", "context": "An interrupted post-visit review; wants one clear administrative next step."},
        "patient": {"name": "Avery Cedar", "context": "Checks a private test inbox after work; agrees to one administrative confirmation."},
        "recording_consent": "Both virtual participants agree to record this invented conversation for the local test.",
        "turns": [
            turn("provider", "Avery, this is an invented follow-up discussion. We are not deciding treatment today. May I record it for the local visit note?"),
            turn("patient", "Yes. I understand this is a test recording. I want help confirming the next visit, not a change to my medicines."),
            turn("provider", "Please tell me what the office still needs to clarify."),
            turn("patient", "The reminder says Thursday, but it does not show the calendar date or start time. I can check the private test inbox after four in the afternoon."),
            turn("provider", "I will ask the coordinator to confirm the exact Thursday date, time, and location. The current chart and medicines have not been verified in this conversation."),
            turn("patient", "You may send one administrative confirmation request to my selected private test inbox. Please do not include symptoms or medicines."),
            turn("provider", "The coordinator owns the confirmation request. I will review its recipient and wording before it is submitted. Until the receiver confirms it, the task stays pending."),
        ],
        "reviewed_contact_resolution": None,
        "approved_action": {"kind": "administrative_confirmation", "recipient": "virtual_patient_private_inbox",
            "body": "Please confirm the calendar date, start time, and location of your next Thursday visit with the coordinator.",
            "owner": "virtual practice coordinator", "clinical_content_allowed": False},
        "patient_acknowledgment": "I received the administrative request in the selected test inbox. I will ask the coordinator to confirm the exact date, time, and location.",
        "specific_criteria": {"scribe": ["Do not invent a Thursday date, medication review, examination or diagnosis."],
            "visit_prep": ["Flag date/time/location as unconfirmed; preserve after-four preference."],
            "research": ["Use a general appointment-reminder communication question; do not send visit identifiers."],
            "follow_up": ["One private administrative request; no clinical content and no booking."],
            "chief": ["Close only the receiver-confirmed administrative transmission and recorded acknowledgment, not the appointment itself."]},
    },
    {
        "scenario_id": "mobile-ankle-referral-packet", "platform": "mobile", "viewport": {"width": 390, "height": 844},
        "provider": {"name": "Casey Fern, FNP", "role": "nurse_practitioner", "context": "Uses a virtual phone view between visits; checks the complete referral packet before approval."},
        "patient": {"name": "Rowan Lark", "context": "Reports an ankle twist and asks where the reviewed referral packet goes."},
        "recording_consent": "Both virtual participants agree to record the invented ankle discussion for this test.",
        "turns": [
            turn("provider", "Rowan, may I record this invented visit discussion? The test team will prepare drafts for review."),
            turn("patient", "Yes. I twisted my left ankle stepping off a curb on Saturday. It still aches, and I brought my purple brace. I have not given you an examination result."),
            turn("provider", "We have no examination, imaging result, diagnosis, or medication dose confirmed here. Your allergy history also needs confirmation."),
            turn("patient", "I do not remember the name of the medicine I reacted to. Please leave that uncertain rather than guessing."),
            turn("provider", "For this synthetic workflow I will prepare a referral packet for review. It will describe your report and the facts still needing verification. Preparing this packet does not send it to a rehabilitation desk."),
            turn("patient", "You may send me one administrative confirmation in the selected private test inbox that the referral packet is ready for coordinator review. Do not send the packet or my clinical details in that message."),
            turn("provider", "The referral coordinator owns that review. I will review the PDF separately and approve only the exact administrative message. No referral transfer or consultation booking is authorized here."),
        ],
        "reviewed_contact_resolution": None,
        "approved_action": {"kind": "referral_packet_ready_confirmation", "recipient": "virtual_patient_private_inbox",
            "body": "Your referral packet is ready for practice coordinator review. Please contact the coordinator through this private test inbox for the next administrative step.",
            "owner": "virtual referral coordinator", "clinical_content_allowed": False},
        "patient_acknowledgment": "I received the administrative confirmation in the selected private test inbox. I understand that the packet still needs coordinator review, has not been delivered to another practice, and no consultation has been booked.",
        "specific_criteria": {"scribe": ["Preserve left ankle, Saturday curb injury, purple brace and unknown allergy."],
            "visit_prep": ["Request examination/imaging/allergy verification; do not invent results."],
            "research": ["General evidence question on evaluating reported ankle injury; preserve applicability limits."],
            "follow_up": ["Prepare/review the exact referral PDF separately; transmit only the administrative confirmation without the PDF or clinical details."],
            "chief": ["Require administrative message receiver receipt and later patient acknowledgment; referral delivery and booking remain incomplete."]},
    },
    {
        "scenario_id": "desktop-cough-contact-resolution", "platform": "desktop", "viewport": {"width": 1280, "height": 900},
        "provider": {"name": "Alex Reed, PA", "role": "physician_assistant", "context": "Stops a callback when the patient contact instruction is ambiguous."},
        "patient": {"name": "Jamie Moss", "context": "Shares a household phone and initially gives unclear callback/voicemail permission."},
        "recording_consent": "Both virtual participants consent to record this invented cough conversation.",
        "turns": [
            turn("provider", "Jamie, may we record this invented discussion? We will keep any action as a draft until its recipient and consent are reviewed."),
            turn("patient", "Yes. I started coughing after cleaning a dusty storage room. I have a green-pack inhaler, but I do not know its name or how often I use it. I have not supplied my date of birth."),
            turn("provider", "The inhaler label, dose, frequency, date of birth and examination are unverified. This conversation does not establish the cause of the cough."),
            turn("patient", "Call the number in the file, or perhaps leave a message with my partner. I am not sure which phone is listed."),
            turn("provider", "That instruction is ambiguous. We will not call, leave voicemail, or share clinical details until you clarify the exact contact and permission."),
        ],
        "reviewed_contact_resolution": [
            turn("patient", "Use only the selected private test inbox for one administrative callback request. Do not use the household phone, do not leave voicemail, and do not contact my partner.", phase="contact_resolution"),
            turn("provider", "I reviewed that clarification. The coordinator may send one administrative request to the selected private test inbox. No symptoms, inhaler details or date of birth will be included.", phase="contact_resolution"),
        ],
        "approved_action": {"kind": "administrative_callback", "recipient": "virtual_patient_private_inbox",
            "body": "Please contact the practice coordinator through this private test inbox to confirm your preferred callback time.",
            "owner": "virtual practice coordinator", "clinical_content_allowed": False},
        "patient_acknowledgment": "I received the administrative request in my selected private test inbox. No message went to the household phone or my partner. I will confirm a callback time with the coordinator.",
        "specific_criteria": {"scribe": ["Preserve cough after dust, green-pack ambiguity, unknown DOB/dose/frequency, and unresolved initial contact consent."],
            "visit_prep": ["Request exact inhaler label and missing identifiers; do not fill them from another case."],
            "research": ["General cough/dust-exposure verification query; no invented citations or treatment advice."],
            "follow_up": ["Blocked before reviewed contact clarification; no household phone, voicemail or partner disclosure."],
            "chief": ["Bind approved action to the later reviewed clarification hash; require zero pre-consent dispatches."]},
    },
)


def scenarios():
    result = deepcopy(_SCENARIOS)
    for case in result:
        case["contract"] = "cosmabot.virtual-clinic-scenario.v1"
        for actor in ("provider", "patient"):
            case[actor]["author_agent_id"] = AUTHOR
        case["approved_action"]["action"] = "spruce_secure_message"
        case["administrative_intent"] = {
            "purpose": case["approved_action"]["kind"],
            "destination_name": case["approved_action"]["recipient"],
            "consent_question": "May the reviewed Follow-up bot send this exact administrative message once to the selected private test inbox?",
        }
        case["final_patient_ack"] = {"actor": "virtual_patient", "author_agent_id": AUTHOR,
            "content_template": case.pop("patient_acknowledgment"),
            "requires_receiver_receipt": True, "state": "not_generated"}
        case["completion_criteria"] = {role: COMMON[role] + case["specific_criteria"][role] for role in ROLES}
        case["team_tasks"] = {role: {"expected_output": case["completion_criteria"][role],
            "completion_state": "not_executed"} for role in ROLES}
        case["synthetic_only"] = True
        case["author_agent_id"] = AUTHOR
        case["acknowledgment_gate"] = "Generate only after exact durable receiver receipt; source script alone cannot establish receipt."
    return result


def speech_script(case, *, include_contact_resolution=False):
    turns = case["turns"]
    if include_contact_resolution:
        turns = turns + (case["reviewed_contact_resolution"] or [])
    return "\n".join(f"{item['speaker'].title()}: {item['content']}" for item in turns)


def export_personas(root: Path):
    root.mkdir(parents=True, exist_ok=False)
    cases = scenarios()
    rows = []
    for case in cases:
        text = speech_script(case)
        case["speech_script"] = text
        case["speech_script_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        reviewed = speech_script(case, include_contact_resolution=True)
        case["script_with_contact_resolution"] = reviewed
        case["script_with_contact_resolution_sha256"] = hashlib.sha256(reviewed.encode()).hexdigest()
        path = root / f"{case['scenario_id']}.json"
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n")
        rows.append({"scenario_id": case["scenario_id"], "path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"contract": CONTRACT, "author_agent_id": AUTHOR, "synthetic_only": True,
        "role_simulation": "Provider and patient authored by the same Codex subagent; no independent patient cohort or clinical authority.",
        "completion_evidence": "not_executed", "scenarios": rows}
    (root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
