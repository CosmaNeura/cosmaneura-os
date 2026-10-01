"""Real research lookup/save/analysis services with an offline invented registry.

The transport is synthetic. PostgreSQL records, source hashes, save selection and
the downstream analysis context use the actual application. No model is called.
"""

import hashlib
import json
from copy import deepcopy
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.adapters.gpt41 import GPT41Connector
from cosmas_os.adapters.public_research import PublicResearch
from cosmas_os.api.research_schemas import Save, Search
from cosmas_os.application import model_work, research, research_analysis, workspace
from cosmas_os.application.capture_deadline import CaptureBudget
from cosmas_os.config import Settings
from cosmas_os.models import EncounterWorkspace, WorkspaceEntry
from cosmas_os.research_models import ResearchRun, ResearchSave
from lab.store import LabError

SCENARIOS = ("condition_handoff", "limited_search", "missing_conditions", "malformed_conditions",
             "source_unavailable", "empty_search", "altered_selection")
QUERY = "myocardial infarction cell therapy"
PRIVATE_MARKER = "SYNTHETIC_PRIVATE_WORKSPACE_MUST_NOT_ENTER_PUBLIC_RESEARCH"


def registry_response():
    """Two wholly invented trial records; the second is deliberately unselected."""
    protocol = {
        "identificationModule": {"nctId": "NCT90000001", "briefTitle": "SYNTHETIC ONLY — cardiac cell study"},
        "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-09-20"}},
        "conditionsModule": {"conditions": ["Myocardial Infarction", "Heart Failure"]},
        "designModule": {"phases": ["PHASE1"]},
        "armsInterventionsModule": {"interventions": [{"type": "BIOLOGICAL", "name": "Invented cell intervention"}]},
        "contactsLocationsModule": {"locations": [{"facility": "Invented Cardiac Research Center",
            "city": "Example City", "country": "United States", "status": "ACTIVE_NOT_RECRUITING"}]},
        "eligibilityModule": {"minimumAge": "18 Years", "maximumAge": "75 Years", "sex": "ALL",
            "eligibilityCriteria": "SYNTHETIC ONLY. LVEF <40%; trial staff must assess all criteria. Individual eligibility is undetermined."},
        "descriptionModule": {"briefSummary": "Invented early-phase investigation; no established benefit or treatment recommendation."},
    }
    other = deepcopy(protocol)
    other["identificationModule"] = {"nctId": "NCT90000002", "briefTitle": "SYNTHETIC ONLY — unselected cohort"}
    other["conditionsModule"] = {"conditions": ["UNSELECTED Nonischemic Cardiomyopathy"]}
    return {"studies": [{"protocolSection": protocol}, {"protocolSection": other}], "totalCount": 2}


def exercise(app, store, episode, scenario):
    if scenario not in SCENARIOS:
        raise LabError("unknown_research_capability_scenario")
    body = registry_response()
    if scenario == "limited_search":
        body.update(totalCount=25, nextPageToken="synthetic-next-page")
    elif scenario == "missing_conditions":
        body["studies"][0]["protocolSection"].pop("conditionsModule")
    elif scenario == "malformed_conditions":
        body["studies"][0]["protocolSection"]["conditionsModule"] = {"conditions": {"label": "invented malformed field"}}
    elif scenario == "empty_search":
        body = {"studies": [], "totalCount": 0}
    raw = json.dumps(body).encode()
    calls, checks, stages = [], {}, []
    budget = CaptureBudget(30)
    scope = (app.box, app.owner, app.workspace)

    def respond(request):
        if (request.method != "GET" or request.url.host != "clinicaltrials.gov"
                or request.url.path != "/api/v2/studies" or dict(request.url.params) != {
                    "query.term": QUERY, "pageSize": "5", "format": "json", "countTotal": "true"}):
            raise LabError("unexpected_research_request")
        calls.append({"method": request.method, "path": request.url.path, "query": QUERY})
        with Session(app.engine) as s:
            intent = s.scalar(select(ResearchRun).where(ResearchRun.workspace_id == app.workspace,
                ResearchRun.idempotency_key == "research-capability-" + scenario))
            checks["lookup_intent_saved_before_source_read"] = intent is not None and intent.state == "running"
        return httpx.Response(503, json={"error": "synthetic source failure"}) if scenario == "source_unavailable" else httpx.Response(200, content=raw)

    configuration_values: dict[str, Any] = {"_env_file": None, "research_sources": "clinical_trials"}
    configuration = Settings(**configuration_values)
    with Session(app.engine) as s, PublicResearch(configuration,
            transport=httpx.MockTransport(respond), budget=budget) as port:
        before = workspace.read(s, *scope)
        before = workspace.append(s, *scope, expected=before["revision"], key="research-private-" + scenario,
            kind="evidence", content=PRIVATE_MARKER + ": invented heart-attack encounter; no DOB supplied.",
            source_label="Synthetic private encounter control")["workspace"]
        request = Search.model_validate_json(json.dumps({"contract_version": 1,
            "idempotency_key": "research-capability-" + scenario, "expected_revision": before["revision"],
            "team_revision": app.team_revision, "bot": app.addresses["research"], "topic": "trials",
            "sources": ["clinical_trials"], "query": QUERY, "public_query_confirmed": True}))
        run = research.search(s, *scope, request=request, configured=PublicResearch.configured(configuration),
            port=port, check=budget.check, reauthenticate=lambda: app.check_agent("research"))
        replay = research.search(s, *scope, request=request, configured=PublicResearch.configured(configuration),
            port=port, check=budget.check, reauthenticate=lambda: app.check_agent("research"))
        checks["same_lookup_does_not_repeat_source_read"] = run == replay and len(calls) == 1
        checks["source_read_uses_only_explicit_public_query"] = len(calls) == 1 and calls[0]["query"] == QUERY
        stages.append({"stage": "lookup", "run_id": run["run_id"], "request_sha256": run["request_sha256"],
            "state": run["state"], "result_count": len(run["results"]), "workspace_revision": before["revision"]})
        failed = scenario in {"malformed_conditions", "source_unavailable"}
        if failed or scenario == "empty_search":
            code = "invalid_source_response" if scenario == "malformed_conditions" else "source_unavailable"
            checks["honest_source_outcome"] = (run["state"] == "unavailable" and run["errors"] == [
                {"source": "clinical_trials", "code": code}]) if failed else run["state"] == "completed" and not run["errors"]
            checks["no_invented_trial_or_saved_packet"] = not run["results"] and s.scalar(
                select(func.count()).select_from(ResearchSave).where(ResearchSave.run_id == run["run_id"])) == 0
            checks["workspace_unchanged_without_selected_source"] = workspace.read(s, *scope)["revision"] == before["revision"]
            saved = None
            context_hash = None
            review_material = "Synthetic source lookup unavailable; no trial was selected." if failed else "Synthetic lookup returned no studies. No eligibility or treatment conclusion was produced."
        else:
            selected = run["results"][0]
            fields = {value["label"]: value["text"] for value in selected["fields"]}
            checks["source_conditions_are_retained_or_explicitly_absent"] = ("Conditions" not in fields if scenario == "missing_conditions"
                else fields.get("Conditions") == "Myocardial Infarction; Heart Failure")
            checks["exact_response_hash_is_retained"] = selected["raw_response_sha256"] == hashlib.sha256(raw).hexdigest()
            save_request = Save.model_validate({"contract_version": 1, "idempotency_key": "research-save-" + scenario,
                "expected_revision": before["revision"], "source_hashes": [selected["sha256"]]})
            if scenario == "altered_selection":
                forged = save_request.model_copy(update={"source_hashes": ["0" * 64]})
                try:
                    research.save(s, *scope, run["run_id"], request=forged,
                        check=budget.check, reauthenticate=lambda: app.check_agent("research"))
                except workspace.WorkspaceError as error:
                    checks["unretrieved_source_cannot_be_saved"] = error.code == "research_selection_unavailable"
                    s.rollback()
                else:
                    raise LabError("unretrieved_source_saved")
            saved = research.save(s, *scope, run["run_id"], request=save_request,
                check=budget.check, reauthenticate=lambda: app.check_agent("research"))
            duplicate = research.save(s, *scope, run["run_id"], request=save_request,
                check=budget.check, reauthenticate=lambda: app.check_agent("research"))
            checks["same_save_reuses_exact_entry"] = saved == duplicate
            anchor = {"entry_id": saved["entry_id"], "entry_revision": saved["entry_revision"],
                "run_id": saved["run_id"], "save_request_sha256": saved["request_sha256"]}
            command = {"content": "Compare only the selected public trial. Do not determine eligibility or recommend treatment.",
                "research_analysis": {"version": 1, "consented": True, "entries": [anchor]}}
            w = s.get(EncounterWorkspace, app.workspace)
            context = research_analysis.build_context(s, w, {"role": "research", "response_style": "brief"}, command)
            prepared = GPT41Connector(lambda: (_ for _ in ()).throw(LabError("unexpected_model_access"))).prepare(context)
            passage = prepared["sources"][0]
            context_hash = model_work.source_digest(context)
            review_material = passage["text"]
            checks["all_selected_fields_reach_analysis"] = all(field["label"] + ": " + field["text"] in review_material
                for field in selected["fields"]) and selected["excerpt"] in review_material
            checks["selection_excludes_other_trial_and_private_workspace"] = (
                "UNSELECTED" not in review_material and PRIVATE_MARKER not in review_material and len(prepared["sources"]) == 1)
            checks["citation_status_uncertainty_survives_handoff"] = all(value in review_material for value in (
                selected["url"], selected["sha256"], "RECRUITING", "ACTIVE_NOT_RECRUITING",
                "Individual eligibility is undetermined.", "no established benefit", "LVEF <40%"))
            checks["result_scope_survives_handoff"] = "Reported result scope: " + ("limited" if scenario == "limited_search" else "complete") in review_material
            checks["exact_retained_passage_not_silently_shortened"] = passage["truncated"] is False
            checks["preparing_analysis_performs_no_additional_source_read"] = len(calls) == 1
            if scenario == "altered_selection":
                changed = deepcopy(command)
                changed["research_analysis"]["entries"][0]["save_request_sha256"] = "0" * 64
                try:
                    research_analysis.build_context(s, w, {"role": "research", "response_style": "brief"}, changed)
                except workspace.WorkspaceError as error:
                    checks["changed_analysis_anchor_refused"] = error.code == "source_changed"
                else:
                    raise LabError("changed_analysis_anchor_admitted")
            stages.append({"stage": "selected_source_saved", **anchor, "context_sha256": context_hash,
                "source_sha256": selected["sha256"], "source_id": selected["id"], "source_url": selected["url"]})

    app.engine.dispose()
    with Session(app.engine) as s:
        reopened = research.resolve(s, *scope, key=request.idempotency_key)
        checks["lookup_survives_database_reopen"] = reopened == run
        if saved:
            recovered = research.resolve_save(s, *scope, run["run_id"], key=save_request.idempotency_key)
            checks["selected_source_save_survives_database_reopen"] = recovered == saved
            w = s.get(EncounterWorkspace, app.workspace)
            reopened_context = research_analysis.build_context(s, w, {"role": "research", "response_style": "brief"}, command)
            checks["exact_analysis_context_survives_database_reopen"] = model_work.source_digest(reopened_context) == context_hash
            entry = s.get(WorkspaceEntry, saved["entry_id"])
            if entry is None:
                raise LabError("saved_research_entry_missing")
            entry_content_hash = hashlib.sha256(entry.content.encode()).hexdigest()
        else:
            entry_content_hash = None
    artifact = store.save(episode, "research-" + scenario, {"body": review_material,
        "share_with": ["chief", "provider", "nurse", "pa"], "run_id": run["run_id"],
        "run_request_sha256": run["request_sha256"], "saved": saved,
        "entry_content_sha256": entry_content_hash, "context_sha256": context_hash,
        "evidence_level": "actual research services and PostgreSQL; invented offline registry; no model or public API calls"})
    store.event(episode, "research", "research_capability_verified", scenario=scenario,
        passed=all(checks.values()), run_id=run["run_id"], artifact_sha256=artifact["sha256"])
    return {"role": "research", "scenario": scenario, "passed": all(checks.values()), "checks": checks,
        "artifacts": [artifact], "receipt_stages": stages, "source_requests": calls,
        "external_effects": 0, "model_calls": 0, "evidence_level": artifact["evidence_level"]}
