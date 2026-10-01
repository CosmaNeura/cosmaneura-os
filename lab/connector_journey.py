"""Five bots actively use typed connector tools, then exchange exact drafts.

Upstream source selection happens before a separate scripted provider reviews
the synthetic fax source. Only then can Follow-up prepare a private proposal.
This scenario never approves or sends that proposal.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.application import workspace
from cosmas_os.models import Decision, Operation
from lab.cases import Case
from lab.connector_tools import ConnectorWorld
from lab.fax_sandbox import bound
from lab.review_process import INPUTS
from lab.store import LabError

CASE = Case("connector_tools", "Bots use connector tools and verify a shared encounter",
    "Prepare the invented Shawn encounter from selected Google observations and cardiac-trial evidence. "
    "Exchange exact drafts, then prepare a Documo administrative proposal after a separate synthetic provider source review. "
    "DOB and heart diagnosis remain unknown; trial eligibility is undetermined; no fax is approved or sent.",
    "SYNTHETIC ONLY — connector handoff workflow", (), inputs=INPUTS)


class JourneyWorld(ConnectorWorld):
    def validate_saved_artifact(self, role):
        if role in {"visit_prep", "research"}:
            sources = [s for s in self.app.sources() if s["id"] in self.source_reads[role]]
            if role == "visit_prep":
                selected = set()
                for source in sources:
                    try:
                        content = json.loads(source["content"])
                    except ValueError:
                        continue
                    if isinstance(content, dict) and content.get("schema") == "synthetic_account_observation_evidence_v1":
                        selected.add(content.get("kind"))
                if not {"mail", "calendar"} <= selected:
                    raise LabError("save_and_read_one_selected_google_mail_and_calendar_source_before_finishing")
            elif not any(s["label"] == "Research · public source excerpts" for s in sources):
                raise LabError("save_and_read_the_selected_trial_evidence_before_finishing")
        if role in {"chief", "follow_up"}:
            rows = [json.loads(line) for line in self.store.events.read_text().splitlines()]
            if not any(r["episode"] == self.episode and r["role"] == role and r.get("tool") == "fax_receipt"
                       and r.get("ok") for r in rows):
                raise LabError("inspect_the_existing_documo_proposal_with_fax_receipt_before_finishing")

    def _execute(self, role, name, args):
        if name == "save_artifact":
            self.validate_saved_artifact(role)
        if name == "delegate_team" and "follow_up" in args.roles:
            # The model cannot create a human review; it can only see the
            # scripted scenario's already-established admission.
            if self.fax is None:
                raise LabError("fax_fixture_provider_review_required")
        return super()._execute(role, name, args)

    def replay(self, role):
        """Deterministic qualification of the same individual tool boundaries."""
        def call(name, arguments):
            result = self.execute(role, name, arguments)
            if isinstance(result, dict) and "error" in result:
                raise LabError(result["error"])
            return result

        for source in call("list_sources", {}):
            call("read_source", {"source_id": source["id"]})
        if role == "visit_prep":
            for kind in ("mail_headers", "calendar"):
                observed = call("account_read_" + kind, {"provider": "google", "idempotency_key": "prep-read-" + kind})
                selected = call("account_select_observed_items", {
                    "read_key": "prep-read-" + kind,
                    "item_ids": [observed["observation"]["items"][0]["id"]],
                    "expected_workspace_revision": call("application_status", {})["workspace_revision"],
                    "idempotency_key": "prep-select-" + kind})
                call("read_source", {"source_id": selected["entry_id"]})
        elif role == "research":
            result = call("research_lookup_trials", {"idempotency_key": "research-trial-lookup",
                "expected_workspace_revision": call("application_status", {})["workspace_revision"]})["result"]
            saved = call("research_save_selection", {"run_id": result["run_id"],
                "source_hashes": [result["results"][0]["sha256"]], "idempotency_key": "research-selected-trial",
                "expected_workspace_revision": call("application_status", {})["workspace_revision"]})["result"]
            call("read_source", {"source_id": saved["entry_id"]})
        if role == "follow_up":
            readiness = call("fax_readiness", {"provider": "documo"})
            options = readiness["options"]
            prepared = call("fax_prepare", {"provider": "documo", "expected_workspace_revision": options["entry_revision"],
                "idempotency_key": "followup-private-documo", "proposed_operation_id": readiness["proposal_ids"]["fax"],
                "source": options["source"], "document": readiness["document"], "action": "fax",
                "connection": {k: options["connections"][0][k] for k in ("id", "revision", "public_sha256")},
                "correspondence": {k: options["correspondences"][0][k] for k in ("id", "revision", "public_sha256")}})
            call("fax_receipt", {"provider": "documo", "ticket_id": prepared["detail"]["summary"]["ticket_id"],
                **bound(prepared["detail"], "followup-read-documo"), "refresh": False})
        elif role == "chief":
            summary = call("fax_list_proposals", {"provider": "documo"})["catalog"]["items"][0]
            call("fax_receipt", {"provider": "documo", "ticket_id": summary["ticket_id"],
                "expected_version": summary["version"], "operation_id": summary["operation_id"],
                "revision_id": summary["revision_id"], "payload_hash": summary["payload_hash"],
                "idempotency_key": "chief-read-documo", "refresh": False})
        dependencies = []
        if role in {"chief", "follow_up"}:
            for artifact in call("list_artifacts", {}):
                if artifact["role"] != role:
                    dependency = {"artifact_id": artifact["id"], "sha256": artifact["sha256"]}
                    call("read_artifact", dependency)
                    dependencies.append(dependency)
        for source in call("list_sources", {}):
            call("read_source", {"source_id": source["id"]})
        call("save_artifact", {"body": "SYNTHETIC private draft: heart history and DOB remain unknown. "
            "Review selected account metadata and the saved cardiac-trial source; eligibility is undetermined. "
            "Staff completion is not documented. The administrative fax proposal awaits human review; dispatch has not started. "
            "No treatment recommendation, patient contact or delivery is recorded.",
            "source_ids": sorted(self.source_reads[role]), "dependencies": dependencies, "share_with": ["chief", "follow_up"]})


def run_connectors(app, store, episode, model, *, concurrency=3):
    started = time.monotonic()
    world = JourneyWorld(store, episode, CASE, app, model, concurrency=concurrency, prepare_fax=False)
    phases, artifacts, checks, details = {}, [], {}, []
    try:
        phase = time.monotonic()
        # Account/research writes share one workspace revision, so their
        # explicit selections run serially; independent Scribe work overlaps.
        with ThreadPoolExecutor(max_workers=2) as pool:
            scribe = pool.submit(world.run_agent, "scribe")
            world.run_agent("visit_prep")
            world.run_agent("research")
            scribe.result()
        phases["upstream_tools_and_drafts"] = round((time.monotonic() - phase) * 1000)
        for role in ("scribe", "visit_prep", "research"):
            store.read(episode, role, "follow_up")
            world.started_roles.add(role)
        world.prepare_fax_fixture()
        phase = time.monotonic()
        world.run_agent("follow_up")
        world.started_roles.add("follow_up")
        phases["private_fax_proposal_and_followup"] = round((time.monotonic() - phase) * 1000)
        phase = time.monotonic()
        world.run_agent("chief")
        phases["chief_verification"] = round((time.monotonic() - phase) * 1000)
        artifacts = [store.read(episode, role, role) for role in ("chief", "scribe", "visit_prep", "research", "follow_up")]
        rows = [json.loads(line) for line in store.events.read_text().splitlines() if json.loads(line)["episode"] == episode]
        calls = [row for row in rows if row["kind"] == "tool" and row.get("ok")]
        saved = [row["result"] for row in calls if row.get("tool") in {"account_save_selected_observations", "account_select_observed_items"}
                 and row["result"].get("status") == "saved"]
        trial = [row["result"]["result"] for row in calls if row.get("tool") == "research_save_selection"]
        details = [row["result"]["detail"]["summary"] for row in calls if row.get("tool") == "fax_receipt"]
        by_role = {a["role"]: a for a in artifacts}
        account_ids, trial_ids = {r["entry_id"] for r in saved}, {r["entry_id"] for r in trial}
        with Session(app.engine) as session:
            snapshot = workspace.read(session, app.box, app.owner, app.workspace)
            decisions = session.scalar(select(func.count()).select_from(Decision).where(Decision.box_id == app.box))
            operations = session.scalar(select(func.count()).select_from(Operation).where(Operation.box_id == app.box))
        checks = {
            "five_agents_saved_exact_drafts": len(artifacts) == 5 and not world.failures,
            "prep_used_and_saved_mail_and_calendar": len(account_ids) == 2 and account_ids <= set(by_role["visit_prep"]["source_ids"]),
            "research_used_and_saved_selected_trial": len(trial_ids) == 1 and trial_ids <= set(by_role["research"]["source_ids"]),
            "chief_read_all_selected_connector_evidence": account_ids | trial_ids <= set(by_role["chief"]["source_ids"]),
            "followup_consumed_three_exact_artifacts": {d["artifact_id"] for d in by_role["follow_up"]["dependencies"]} == {"visit_prep", "scribe", "research"},
            "chief_consumed_exact_followup": any(d["artifact_id"] == "follow_up" and d["sha256"] == by_role["follow_up"]["sha256"] for d in by_role["chief"]["dependencies"]),
            "followup_inspected_unsubmitted_private_fax": bool(details) and all(d["state"] == "pending_approval" and d["acceptance"] == "not_observed" and not d["submit_claimed"] for d in details),
            "source_selections_persist_in_real_workspace": account_ids | trial_ids <= {e["id"] for e in snapshot["entries"]},
            "no_human_decision_or_external_submission": decisions == 0 and operations == 0 and world.fax is not None and world.fax.calls == [],
        }
    except Exception as error:
        world.failures.append({"error": str(error) if isinstance(error, LabError) else type(error).__name__})
        checks["connector_workflow_finished"] = False
    finally:
        world.close()
    return {"id": episode, "case": "connector_tools", "title": CASE.title, "passed": bool(checks) and all(checks.values()),
        "checks": checks, "failures": world.failures, "artifacts": artifacts, "tool_calls": world.tool_count,
        "duration_ms": round((time.monotonic() - started) * 1000), "timing": {"phase_ms": phases},
        "connector_scenarios": [{"provider": "google+research+documo", "scenario": "active_tool_handoffs", "passed": bool(checks) and all(checks.values()),
            "checks": checks, "duration_ms": round((time.monotonic() - started) * 1000),
            "evidence_level": "actual model-selected tools" if model else "deterministic individual tool replay"}],
        "application": {"status": "private_proposal_awaits_human_review", "external_effects": 0, "fax_receipts": details,
            "source_review": "separate scripted synthetic provider", "installed_app_engine": "not_exercised"}}
