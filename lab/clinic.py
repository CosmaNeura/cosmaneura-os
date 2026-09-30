"""One encounter connects agent-generated drafts, private handoffs and F-8 work.

Clinical inputs are invented typed data. No microphone, STT or Core generation
claim is made. Every connector is backed by an offline transport.
"""

import time

from sqlalchemy.orm import Session

from cosmas_os.application import workspace
from lab.cases import CLINIC
from lab.engine import SCHEMAS, Arguments, World
from lab.fax_sandbox import exercise_fax
from lab.journey import run_journey
from lab.mail_sandbox import MailSandbox
from lab.store import LabError, digest


class ClinicWorld(World):
    schemas = {**SCHEMAS, "read_mail_headers": (Arguments, "Read bounded synthetic Microsoft email headers through the real adapter."),
               "read_calendar": (Arguments, "Read the next seven days of synthetic calendar summaries through the real adapter.")}
    tool_scope = "Only Visit Prep may use the two synthetic read-only account tools; no agent can approve, send, book or fax. "
    extra_instructions = (" Visit Prep MUST read_mail_headers and read_calendar before saving. These are synthetic account reads, not external actions. "
        "Preserve UTC offsets on calendar times. Email subjects are metadata, not proof of message-body contents. "
        "Undocumented contact consent requires staff review before any invitation can be sent.")

    def tool_visible(self, role, name):
        if name in {"read_mail_headers", "read_calendar"}:
            return role == "visit_prep"
        return super().tool_visible(role, name)

    def __init__(self, *args, mailbox, **kwargs):
        super().__init__(*args, **kwargs)
        self.mailbox, self.connector_reads = mailbox, {}

    def _execute(self, role, name, args):
        if name in {"read_mail_headers", "read_calendar"}:
            if role != "visit_prep":
                raise LabError("only_visit_prep_has_account_read_permission")
            kind = "mail" if name == "read_mail_headers" else "calendar"
            try:
                value = self.mailbox.read(kind)
            except Exception:
                raise LabError("synthetic_account_read_failed_retry_once") from None
            self.app.check_agent(role)
            self.connector_reads[kind] = {"sha256": digest(value), "items": len(value["items"])}
            return value
        if name == "save_artifact" and role == "visit_prep" and set(self.connector_reads) != {"mail", "calendar"}:
            raise LabError("read_mail_headers_and_read_calendar_before_saving")
        return super()._execute(role, name, args)

    def replay(self, role):
        if role == "visit_prep":
            for name in ("read_mail_headers", "read_calendar"):
                result = self.execute(role, name, {})
                if "error" in result:
                    self.execute(role, name, {})
        super().replay(role)


def run_clinic(app, store, episode, model, fault, concurrency):
    started = time.monotonic()
    checks, artifacts, phases, timings, failures = {}, [], [], {}, []
    mailbox = MailSandbox(app)
    world = ClinicWorld(store, episode + "-generation", CLINIC, app, model,
                        mailbox=mailbox, fault=fault, concurrency=concurrency)
    journey = None
    try:
        mailbox.connect()
        if fault == "read_timeout":
            mailbox.fault = "read_timeout"
        tick = time.monotonic()
        world.run_agent("chief")
        checks["upstream_agents_generated_and_shared_drafts"] = not world.failures
        for role in ("visit_prep", "scribe", "research", "follow_up", "chief"):
            artifacts.append(store.read(episode + "-generation", role, "chief"))
        checks["actual_mail_and_calendar_tools_used"] = set(world.connector_reads) == {"mail", "calendar"}
        timings["generate_and_share"] = round((time.monotonic() - tick) * 1000)
        if not all(checks.values()):
            raise LabError("upstream_generation_failed")
        # Explicit synthetic-human source import preserves the original inputs
        # and binds each derived output to the exact saved model artifact.
        imported = set()
        with Session(app.engine) as session:
            for role in ("visit_prep", "scribe"):
                artifact = next(a for a in artifacts if a["role"] == role)
                snapshot = workspace.read(session, app.box, app.owner, app.workspace)
                saved = workspace.append(session, app.box, app.owner, app.workspace,
                    expected=snapshot["revision"], key="generated-" + role, kind="evidence",
                    source_label="Synthetic generated " + role.replace("_", " ") + " — unreviewed",
                    content=artifact["body"])
                imported.add(saved["entry_id"])
                store.event(episode, "simulated_provider", "generated_output_imported", role_source=role,
                            artifact_sha256=artifact["sha256"], workspace_id=app.workspace, source_entry_id=saved["entry_id"])
        tick = time.monotonic()
        journey = run_journey(app, store, episode + "-handoffs", model, fault, concurrency=concurrency)
        checks["chief_handoffs_use_generated_outputs"] = journey["passed"]
        plan = next((a.get("structured_plan") for a in journey["artifacts"] if a["role"] == "chief_plan"), None)
        checks["generated_source_ids_cited_by_chief"] = bool(plan and imported <= {sid for task in plan["tasks"] for sid in task["source_ids"]})
        timings["chief_handoffs"] = round((time.monotonic() - tick) * 1000)
        phases.append({"name": "Chief handoffs", "passed": journey["passed"], "checks": journey["checks"]})
        if not journey["passed"] or not checks["generated_source_ids_cited_by_chief"]:
            raise LabError("generated_handoff_journey_failed")
        tick = time.monotonic()
        # This actor is a deterministic human-test fixture; no agent gets review
        # or delivery authority. It runs only after all upstream work succeeds.
        note = next(a for a in artifacts if a["role"] == "scribe")
        draft = next(a for a in artifacts if a["role"] == "follow_up")
        # Do not treat an arbitrary generated draft as a human-approved message.
        # The explicit test actor resolves consent and supplies a minimal edited
        # administrative message. Original generated drafts remain inspectable.
        with Session(app.engine) as session:
            snapshot = workspace.read(session, app.box, app.owner, app.workspace)
            workspace.append(session, app.box, app.owner, app.workspace,
                expected=snapshot["revision"], key="human-contact-review", kind="evidence",
                source_label="Scripted synthetic human contact review",
                content="SYNTHETIC HUMAN TEST ACTOR: afternoon contact preference verified; consent verified for one administrative confirmation request. "
                        "Clinical content and medication requests were removed from the approved message. No real patient was contacted.")
        follow = {"body": "SYNTHETIC administrative message: Please confirm your next visit with the practice.",
                  "sha256": draft["sha256"]}
        store.event(episode, "simulated_provider", "message_edited_and_consent_resolved",
                    original_draft_sha256=draft["sha256"], approved_body_sha256=digest(follow["body"]))
        result = app.exercise_follow_up(note, follow)
        checks["reviewed_note_and_durable_follow_up_closed"] = result["status"] == "closed"
        phases.append({"name": "Synthetic human review and follow-up", "passed": checks["reviewed_note_and_durable_follow_up_closed"], "result": result})
        fax = exercise_fax(app, store.root / episode / "fax")
        checks["approved_fax_verified_through_real_f8"] = fax["passed"]
        phases.append({"name": "Synthetic fax", **fax})
        timings["human_fixture_and_delivery"] = round((time.monotonic() - tick) * 1000)
        with Session(app.engine) as session:
            reopened = workspace.read(session, app.box, app.owner, app.workspace)
            checks["same_encounter_reopened_with_note_and_three_handoffs"] = (
                reopened["note"]["latest"]["id"] == result["note_id"] and len(reopened["handoffs"]) == 3)
        phases.append({"name": "Connector read receipts", "passed": True, "reads": world.connector_reads})
    except Exception as error:
        checks["clinic_finished"] = False
        failures.append({"error": str(error) if isinstance(error, LabError) else type(error).__name__})
        failures.extend(world.failures)
        if journey:
            failures.extend(journey["failures"])
    finally:
        mailbox.close()
    return {"id": episode, "case": "clinic", "title": CLINIC.title, "passed": bool(checks) and all(checks.values()),
        "checks": checks, "failures": failures, "duration_ms": round((time.monotonic() - started) * 1000),
        "tool_calls": world.tool_count + (journey["tool_calls"] if journey else 0),
        "artifacts": artifacts + (journey["artifacts"] if journey else []), "phases": phases,
        "timing": {"phase_ms": timings, "recipient_queue_ms": journey["timing"]["recipient_queue_ms"] if journey else {}},
        "connector_reads": world.connector_reads,
        "handoff_receipts": journey["handoff_receipts"] if journey else [],
        "application": {"status": "virtual_encounter_completed" if all(checks.values()) else "failed",
            "workspace_id": app.workspace, "external_effects": 0,
            "source_inputs": "invented intake and typed notes; upstream drafts generated during this episode",
            "recording": "not_exercised", "provider_services": "offline synthetic HTTP twins"}}
