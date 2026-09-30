"""Offline selection/admission proofs. Actual database/model acceptance is separate."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from cosmas_os.adapters.gpt41 import GPT41Connector
from cosmas_os.adapters.public_research import record
from cosmas_os.api.model_work_schemas import ENTRY_MODEL_BYTES, ConversationBinding
from cosmas_os.api.research_analysis_schemas import ResearchAnalysis
from cosmas_os.api.team_schemas import ConversationRequest
from cosmas_os.application import conversation, research
from cosmas_os.application import model_work as work
from cosmas_os.application import research_analysis as analysis
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import ModelWorkAdmission, ProviderTeamRevision, WorkspaceEntry
from cosmas_os.ports.research import research_digest
from cosmas_os.research_models import ResearchRun, ResearchSave

STAMP = datetime(2026, 9, 22, 12, tzinfo=UTC)


class MemoryProofs:
    """Selected-row test double; no SQL execution, I/O, or model dispatcher."""

    def __init__(self):
        self.rows = {}
        self.reads = []
        self.added = []
        self.commits = 0

    def get(self, cls, identity):
        self.reads.append((cls, identity))
        return self.rows.get((cls, identity))

    def scalar(self, statement):
        assert statement.column_descriptions[0]["entity"] is ResearchSave
        values = statement.compile().params
        self.reads.append((ResearchSave, values["entry_id_1"]))
        return next((row for (cls, _), row in self.rows.items() if cls is ResearchSave
                     and row.entry_id == values["entry_id_1"]), None)

    def scalars(self, _statement):
        return []

    def add(self, row):
        if row.id is None:
            row.id = str(uuid4())
        self.added.append(row)

    def flush(self):
        pass

    def rollback(self):
        pass

    def commit(self):
        self.commits += 1


def fixture(count=1, *, excerpt="Invented public evidence."):
    s = MemoryProofs()
    w = NS(id=str(uuid4()), box_id=str(uuid4()), owner_id=str(uuid4()), revision=10)
    bot = NS(agent_id=str(uuid4()))
    settings = {"role": "research", "instance_id": str(uuid4()), "name": "Research",
                "enabled": True, "response_style": "brief", "include_notebook": True,
                "include_evidence": True, "job_focus": "PRIVATE JOB", "working_preferences": "PRIVATE PREFS"}
    version = NS(id=str(uuid4()), revision=3, configuration={"bots": [settings],
                                                         "practice_context": "PRIVATE PRACTICE"})
    anchors = []
    for index in range(count):
        run_id, receipt_id, entry_id = (str(uuid4()) for _ in range(3))
        query = "Invented query " + str(index)
        result = record("pubmed", query, "a" * 64, identity=str(10000 + index),
                        title="Invented public title", url=f"https://pubmed.ncbi.nlm.nih.gov/{10000 + index}/",
                        excerpt=excerpt)
        request = {"contract_version": 1, "idempotency_key": "search-" + run_id,
                   "expected_revision": 1, "team_revision": 3, "bot": settings["instance_id"],
                   "topic": "literature", "sources": ["pubmed"], "query": query,
                   "public_query_confirmed": True}
        run = NS(id=run_id, workspace_id=w.id, box_id=w.box_id, owner_id=w.owner_id,
                 agent_id=bot.agent_id, request=request, request_sha256=research_digest(request),
                 idempotency_key=request["idempotency_key"], state="completed", results=[result],
                 errors=[], created_at=STAMP, finished_at=STAMP)
        save = {"contract_version": 1, "idempotency_key": "save-" + receipt_id,
                "expected_revision": index + 1, "source_hashes": [result["sha256"]]}
        receipt = NS(id=receipt_id, run_id=run_id, entry_id=entry_id, workspace_id=w.id,
                     box_id=w.box_id, request=save, request_sha256=research_digest(save),
                     idempotency_key=save["idempotency_key"])
        entry = NS(id=entry_id, workspace_id=w.id, box_id=w.box_id, actor_id=w.owner_id,
                   kind="evidence", source_label="Research · public source excerpts",
                   idempotency_key="research:" + receipt_id, request_hash=receipt.request_sha256,
                   revision=index + 2, content=research.source_excerpt([result]))
        s.rows.update({(ResearchRun, run_id): run, (ResearchSave, receipt_id): receipt,
                       (WorkspaceEntry, entry_id): entry})
        anchors.append({"entry_id": entry_id, "entry_revision": entry.revision,
                        "run_id": run_id, "save_request_sha256": receipt.request_sha256})
    selection = {"version": 1, "consented": True, "entries": anchors}
    command = {"expected_revision": w.revision, "team_revision": version.revision,
               "role": settings["instance_id"], "idempotency_key": "analysis-1",
               "content": "Compare only my selected public sources.", "research_analysis": selection}
    return s, w, version, bot, settings, command


def arguments(command):
    return {"expected": command["expected_revision"], "team_revision": command["team_revision"],
            "key": command["idempotency_key"], "role": command["role"], "content": command["content"],
            "research_analysis": command["research_analysis"]}


def replace_packet(case, index, excerpts):
    s, _, _, _, _, command = case
    anchor = command["research_analysis"]["entries"][index]
    run = s.rows[(ResearchRun, anchor["run_id"])]
    receipt = next(row for (cls, _), row in s.rows.items()
                   if cls is ResearchSave and row.run_id == run.id)
    values = [record("pubmed", run.request["query"], "a" * 64, identity=str(10000 + item),
                     title="Invented public title", url=f"https://pubmed.ncbi.nlm.nih.gov/{10000 + item}/",
                     excerpt=excerpt) for item, excerpt in enumerate(excerpts)]
    run.results = values
    receipt.request["source_hashes"] = [value["sha256"] for value in values]
    receipt.request_sha256 = research_digest(receipt.request)
    entry = s.rows[(WorkspaceEntry, anchor["entry_id"])]
    entry.content, entry.request_hash = research.source_excerpt(values), receipt.request_sha256
    anchor["save_request_sha256"] = receipt.request_sha256
    return entry


def row_and_context(case):
    s, w, version, bot, settings, command = case
    context = analysis.build_context(s, w, settings, command)
    row = NS(box_id=w.box_id, owner_id=w.owner_id, workspace_id=w.id,
             agent_id=bot.agent_id, team_revision_id=version.id, external_identity_id="invented-identity",
             kind="conversation", request_body=deepcopy(command), source_sha256=work.source_digest(context),
             prepared_envelope=GPT41Connector(lambda: pytest.fail("credential access")).prepare(context),
             request_hash=work.conversation_request_hash(**{k: v for k, v in arguments(command).items() if k != "key"}))
    return row, context


def gates(monkeypatch, case):
    s, w, version, bot, settings, _ = case
    monkeypatch.setattr(work, "lock_owner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(work, "_identity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(work.ws, "_workspace", lambda *_args, **_kwargs: w)
    monkeypatch.setattr(work.team, "active_bot", lambda *_args, **_kwargs: (version, bot, settings))
    monkeypatch.setattr(work.team, "runtime_settings", NS(workspace_llm_available=True,
                        workspace_research_available=True, workspace_research_io_enabled=False))
    monkeypatch.setattr(work.ws, "read", lambda *_args, **_kwargs: pytest.fail("whole workspace read"))
    return s, w


def test_absent_selection_preserves_old_wire_hash_and_recovery_binding():
    legacy = {"expected_revision": 1, "team_revision": 2, "idempotency_key": "old-ask-1",
              "role": "scribe", "content": "Invented old question"}
    assert ConversationRequest.model_validate(legacy).model_dump(mode="json") == legacy
    binding = {"kind": "conversation", **{k: v for k, v in legacy.items() if k != "content"}}
    assert ConversationBinding.model_validate(binding).model_dump(mode="json") == binding
    request = {"expected": 1, "team_revision": 2, "role": "scribe", "content": legacy["content"]}
    assert work.conversation_request_hash(**request) == payload_hash(request)


@pytest.mark.parametrize("change", [
    lambda c: c.update(research_analysis=None),
    lambda c: c["research_analysis"].update(consented=False),
    lambda c: c["research_analysis"].update(consented=1),
    lambda c: c["research_analysis"].update(version=True),
    lambda c: c["research_analysis"].update(entries=[]),
    lambda c: c["research_analysis"].update(entries=c["research_analysis"]["entries"] * 2),
    lambda c: c["research_analysis"].update(include_evidence=True),
    lambda c: c["research_analysis"]["entries"][0].update(entry_revision=True),
    lambda c: c["research_analysis"]["entries"][0].update(entry_id="foreign-path"),
    lambda c: c["research_analysis"]["entries"][0].update(content="private injected text"),
])
def test_closed_explicit_selection_rejects_coercion_and_unreviewed_context(change):
    command = fixture()[-1]
    change(command)
    with pytest.raises(ValidationError):
        ConversationRequest.model_validate(command)


def test_selected_context_and_actual_prepared_body_contain_only_exact_selected_evidence():
    s, w, version, bot, settings, command = fixture(3)
    omitted = command["research_analysis"]["entries"].pop(1)
    context = analysis.build_context(s, w, settings, command)
    selected = command["research_analysis"]["entries"]
    envelope = GPT41Connector(lambda: pytest.fail("credentials accessed")).prepare(context)
    body = json.loads(envelope["body"]["messages"][1]["content"])
    assert {source["source_id"] for source in body["sources"]} == {v["entry_id"] for v in selected}
    for value in body["sources"]:
        assert value["text"] == s.rows[(WorkspaceEntry, value["source_id"])].content
        assert value["truncated"] is False
    assert not any(identity == omitted["entry_id"] for _, identity in s.reads)
    assert body["question"] == command["content"]
    assert body["practice_preferences"] == ""
    assert body["bot_preferences"] == {"job_focus": "", "working_preferences": ""}
    assert all(body[key] == [] for key in ("linked_work", "follow_up_status", "conversation_history",
                                          "allowed_handoff_roles", "handoff_targets", "selected_skills"))
    assert "PRIVATE" not in json.dumps(envelope)


def trial_fixture(*, excerpt="Invented eligibility criteria.", fields=(), count=1):
    case = fixture(count)
    s, _, _, _, _, command = case
    for anchor in command["research_analysis"]["entries"]:
        run = s.rows[(ResearchRun, anchor["run_id"])]
        receipt = next(row for (cls, _), row in s.rows.items()
                       if cls is ResearchSave and row.entry_id == anchor["entry_id"])
        run.request.update(topic="trials", sources=["clinical_trials"])
        run.request_sha256 = research_digest(run.request)
        source = record("clinical_trials", run.request["query"], "a" * 64,
            identity="NCT12345678", title="Invented cell therapy study",
            url="https://clinicaltrials.gov/study/NCT12345678", updated="2026-09-20",
            excerpt=excerpt, fields=fields, scope="limited")
        run.results = [source]
        receipt.request["source_hashes"] = [source["sha256"]]
        receipt.request_sha256 = research_digest(receipt.request)
        anchor["save_request_sha256"] = receipt.request_sha256
        entry = s.rows[(WorkspaceEntry, anchor["entry_id"])]
        entry.content, entry.request_hash = research.source_excerpt([source]), receipt.request_sha256
    return case


def test_realistic_trial_hydrates_all_selected_fields_and_full_retained_eligibility():
    excerpt = ("Invented eligibility criterion; " * 90)[:2400]
    fields = (("Recruitment status", "RECRUITING"), ("Phase", "PHASE2"),
              ("Interventions", "Invented biological cell intervention; " * 8),
              ("Locations", "Invented academic center; Site status: RECRUITING; " * 8),
              ("Minimum age", "18 Years"), ("Maximum age", "75 Years"), ("Sex", "ALL"))
    s, w, _, _, settings, command = trial_fixture(excerpt=excerpt, fields=fields)
    anchor = command["research_analysis"]["entries"][0]
    run = s.rows[(ResearchRun, anchor["run_id"])]
    selected = run.results[0]
    run.results.append(record("clinical_trials", run.request["query"], "b" * 64,
        identity="NCT87654321", title="Unselected source", url="https://clinicaltrials.gov/study/NCT87654321",
        fields=(("Locations", "UNSELECTED LOCATION MUST NOT ENTER CONTEXT"),)))
    entry = s.rows[(WorkspaceEntry, anchor["entry_id"])]
    original = entry.content
    context = analysis.build_context(s, w, settings, command)
    prepared = GPT41Connector(lambda: pytest.fail("Model I/O")).prepare(context)
    source = prepared["sources"][0]
    assert len(source["text"]) <= 5000 and source["truncated"] is False
    assert selected["excerpt"] == excerpt.strip()
    assert selected["excerpt"] in source["text"] and selected["sha256"] in source["text"]
    for field in selected["fields"]:
        assert field["label"] + ": " + field["text"] in source["text"]
    assert "2026-09-20" in source["text"] and "Reported result scope: limited" in source["text"]
    assert "UNSELECTED LOCATION" not in source["text"]
    assert source["source_id"] == entry.id and entry.content == original
    assert s.added == [] and s.commits == 0


@pytest.mark.parametrize("corruption", ["metadata", "workspace"])
def test_retained_trial_metadata_cannot_bypass_hash_or_workspace_binding(corruption):
    s, w, _, _, settings, command = trial_fixture(fields=(("Recruitment status", "RECRUITING"),))
    anchor = command["research_analysis"]["entries"][0]
    run = s.rows[(ResearchRun, anchor["run_id"])]
    if corruption == "metadata":
        run.results[0]["fields"][0]["text"] = "CHANGED WITHOUT A NEW SOURCE HASH"
    else:
        run.workspace_id = str(uuid4())
    with pytest.raises(WorkspaceError, match="source_changed"):
        analysis.build_context(s, w, settings, command)
    assert s.added == [] and s.commits == 0


def test_overbudget_trial_refuses_instead_of_shortening_fields_or_eligibility():
    fields = tuple((label, "x" * 750) for label in ("Recruitment status", "Phase", "Interventions", "Locations"))
    s, w, _, _, settings, command = trial_fixture(excerpt="e" * 2500, fields=fields)
    entry = s.rows[(WorkspaceEntry, command["research_analysis"]["entries"][0]["entry_id"])]
    original = entry.content
    assert len(original) < 5000
    with pytest.raises(WorkspaceError, match="research_analysis_too_large") as error:
        analysis.build_context(s, w, settings, command)
    assert error.value.status == 422 and entry.content == original
    assert s.added == [] and s.commits == 0


def test_retained_trial_metadata_counts_toward_aggregate_utf8_limit():
    fields = tuple((label, "漢" * 700) for label in ("Recruitment status", "Phase", "Interventions", "Locations"))
    s, w, _, _, settings, command = trial_fixture(excerpt="漢" * 900, fields=fields, count=3)
    contents = [research.analysis_excerpt(s.rows[(ResearchRun, anchor["run_id"])].results)
                for anchor in command["research_analysis"]["entries"]]
    assert all(len(content) <= 5000 for content in contents)
    assert sum(len(content) for content in contents) <= 15000
    assert sum(len(content.encode()) for content in contents) > 32768
    with pytest.raises(WorkspaceError, match="research_analysis_too_large"):
        analysis.build_context(s, w, settings, command)
    assert s.added == [] and s.commits == 0


@pytest.mark.parametrize("corruption", ["missing_receipt", "foreign_workspace", "foreign_box", "foreign_owner",
    "wrong_run", "wrong_save_hash", "wrong_revision", "ordinary_evidence", "changed_text", "wrong_actor",
    "changed_record", "changed_save", "running_run", "missing_entry", "changed_run_request"])
def test_selected_proof_ownership_and_corruption_fail_closed(corruption):
    s, w, _, _, settings, command = fixture()
    anchor = command["research_analysis"]["entries"][0]
    entry = s.rows[(WorkspaceEntry, anchor["entry_id"])]
    run = s.rows[(ResearchRun, anchor["run_id"])]
    receipt = next(row for (cls, _), row in s.rows.items() if cls is ResearchSave)
    if corruption == "missing_receipt":
        del s.rows[(ResearchSave, receipt.id)]
    elif corruption == "foreign_workspace":
        receipt.workspace_id = str(uuid4())
    elif corruption == "foreign_box":
        run.box_id = str(uuid4())
    elif corruption == "foreign_owner":
        run.owner_id = str(uuid4())
    elif corruption == "wrong_run":
        anchor["run_id"] = str(uuid4())
    elif corruption == "wrong_save_hash":
        anchor["save_request_sha256"] = "b" * 64
    elif corruption == "wrong_revision":
        anchor["entry_revision"] += 1
    elif corruption == "ordinary_evidence":
        entry.source_label = "Provider evidence"
    elif corruption == "changed_text":
        entry.content += " injected encounter text"
    elif corruption == "wrong_actor":
        entry.actor_id = str(uuid4())
    elif corruption == "changed_record":
        run.results[0]["excerpt"] = "changed upstream assertion"
    elif corruption == "changed_save":
        receipt.request["source_hashes"] = ["f" * 64]
    elif corruption == "running_run":
        run.state, run.results = "running", []
    elif corruption == "missing_entry":
        del s.rows[(WorkspaceEntry, entry.id)]
    else:
        run.request["query"] = "changed source query"
    with pytest.raises(WorkspaceError, match="source_changed"):
        analysis.build_context(s, w, settings, command)
    assert s.added == [] and s.commits == 0


def test_direct_selected_path_requires_research_bot():
    s, w, _, _, settings, command = fixture()
    settings["role"] = "scribe"
    with pytest.raises(WorkspaceError, match="research_bot_required"):
        analysis.build_context(s, w, settings, command)
    assert s.reads == []


def test_selection_order_hash_and_exact_anchors_survive_durable_binding():
    command = fixture(3)[-1]
    request = ConversationRequest.model_validate(command).model_dump(mode="json")
    assert request == command
    binding = {"kind": "conversation", **{k: v for k, v in request.items() if k != "content"}}
    restored = ConversationBinding.model_validate_json(json.dumps(binding)).model_dump(mode="json")
    assert restored["research_analysis"] == command["research_analysis"]
    args = {k: v for k, v in arguments(command).items() if k != "key"}
    original = work.conversation_request_hash(**args)
    command["research_analysis"]["entries"].reverse()
    assert work.conversation_request_hash(**args) != original
    args.pop("research_analysis")
    assert work.conversation_request_hash(**args) != original


def test_unchanged_selected_context_revalidates_without_io_or_whole_workspace(monkeypatch):
    case = fixture()
    s, w = gates(monkeypatch, case)
    row, _ = row_and_context(case)
    calls = []
    assert work._current_input(s, row, reauthenticate=lambda: calls.append("identity"))[0] is w
    assert calls == ["identity"]
    w.revision += 1  # A later private notebook/status change cannot enter selected context.
    assert work._current_input(s, row)[0] is w


@pytest.mark.parametrize("revoke", ["identity", "team", "model", "research", "restriction", "source", "agent", "selection"])
def test_existing_claim_and_settlement_input_check_rejects_revocation(monkeypatch, revoke):
    case = fixture()
    s, _ = gates(monkeypatch, case)
    row, _ = row_and_context(case)
    settings = case[4]

    def denied(*_args, **_kwargs):
        raise WorkspaceError("authority_changed")

    reauthenticate = denied if revoke == "identity" else None
    if revoke == "team":
        monkeypatch.setattr(work.team, "active_bot", denied)
    elif revoke == "model":
        monkeypatch.setattr(work.team.runtime_settings, "workspace_llm_available", False)
    elif revoke == "research":
        monkeypatch.setattr(work.team.runtime_settings, "workspace_research_available", False)
    elif revoke == "restriction":
        settings["blocked_capabilities"] = ["model_answer"]
    elif revoke == "source":
        anchor = row.request_body["research_analysis"]["entries"][0]
        s.rows[(WorkspaceEntry, anchor["entry_id"])].content += "corruption"
    elif revoke == "agent":
        case[3].agent_id = str(uuid4())
    elif revoke == "selection":
        row.request_body["research_analysis"]["entries"][0]["entry_revision"] += 1
    with pytest.raises(WorkspaceError):
        work._current_input(s, row, reauthenticate=reauthenticate)


def test_recovery_uses_exact_selected_hash_but_never_reloads_sources_or_current_model(monkeypatch):
    case = fixture()
    s, w, _, _, _, command = case
    expected = work.conversation_request_hash(**{k: v for k, v in arguments(command).items() if k != "key"})
    calls = []
    monkeypatch.setattr(work, "read_workspace", lambda *_a, **_k: w)
    monkeypatch.setattr(work.team, "active_bot", lambda *_a, **_k: pytest.fail("current bot gate in recovery"))
    monkeypatch.setattr(analysis, "build_context", lambda *_a, **_k: pytest.fail("source read in recovery"))

    def observe(_s, _w, *, key, request_hash, as_of):
        calls.append((key, request_hash, as_of))
        if request_hash != expected:
            raise WorkspaceError("idempotency_conflict")
        return {"outcome": "unknown", "request_sha256": request_hash}

    monkeypatch.setattr(work, "conversation_observation", observe)
    assert work.resolve_conversation(s, w.box_id, w.owner_id, w.id, **arguments(command),
                                     clock=lambda: STAMP)["outcome"] == "unknown"
    assert calls == [(command["idempotency_key"], expected, STAMP)]
    changed = arguments(command)
    changed.pop("research_analysis")
    with pytest.raises(WorkspaceError, match="idempotency_conflict"):
        work.resolve_conversation(s, w.box_id, w.owner_id, w.id, **changed, clock=lambda: STAMP)
    assert not s.reads and not s.added and not s.commits


def test_selected_analysis_never_uses_local_fallback_or_missing_model_contract(monkeypatch):
    case = fixture()
    s, w = gates(monkeypatch, case)
    command = case[-1]
    monkeypatch.setattr(conversation, "runtime_settings", NS(workspace_llm_available=False))
    monkeypatch.setattr(work, "now", lambda *_args, **_kwargs: STAMP)
    monkeypatch.setattr(work, "conversation_observation", lambda *_a, **_k: {"outcome": "not_found"})
    monkeypatch.setattr(conversation, "generate_reply", lambda *_a: pytest.fail("local fallback"))
    for negotiated, code in ((False, "model_contract_required"), (True, "model_unavailable")):
        with pytest.raises(WorkspaceError, match=code):
            conversation.ask(cast(Session, s), w.box_id, w.owner_id, w.id, **arguments(command), model_contract=negotiated)
    assert not s.added and not s.commits


def test_actual_admission_keeps_selection_and_only_selected_prepared_body(monkeypatch):
    case = fixture(3)
    s, w = gates(monkeypatch, case)
    command = case[-1]
    monkeypatch.setattr(work, "conversation_observation", lambda *_a, **_k: {"outcome": "not_found"})
    monkeypatch.setattr(work, "workspace_units", lambda *_a: 0)
    monkeypatch.setattr(work, "_allowance", lambda *_a: {"remaining_units": 9})
    aid, prior = work.reserve_conversation(s, w.box_id, w.owner_id, w.id,
                                           **arguments(command), clock=lambda: STAMP)
    admitted = next(row for row in s.added if isinstance(row, ModelWorkAdmission))
    assert aid == admitted.id and prior is None and s.commits == 1
    assert admitted.request_body == command
    assert admitted.reservation_expires_at.timestamp() - STAMP.timestamp() == 10
    assert admitted.external_identity_id is None
    assert admitted.agent_id == case[3].agent_id and admitted.team_revision_id == case[2].id
    assert admitted.request_hash == work.conversation_request_hash(
        **{k: v for k, v in arguments(command).items() if k != "key"})
    assert "PRIVATE" not in json.dumps(admitted.prepared_envelope)
    assert len(admitted.prepared_envelope["sources"]) == 3
    command["research_analysis"]["entries"].clear()
    assert len(admitted.request_body["research_analysis"]["entries"]) == 3


def test_no_fourth_entry_and_bounds_precede_admission(monkeypatch):
    too_many = fixture(4)[-1]["research_analysis"]
    with pytest.raises(ValidationError):
        ResearchAnalysis.model_validate(too_many)
    case = fixture()
    s, w = gates(monkeypatch, case)
    command = case[-1]
    anchor = command["research_analysis"]["entries"][0]
    # Keep the real save/source proof verifier intact while lowering its downstream
    # model limit to exercise exact boundary behavior with a valid source packet.
    content = s.rows[(WorkspaceEntry, anchor["entry_id"])].content
    monkeypatch.setattr(analysis, "MAX_ENTRY_CHARACTERS", len(content))
    analysis.build_context(s, w, case[4], command)
    monkeypatch.setattr(analysis, "MAX_ENTRY_CHARACTERS", len(content) - 1)
    monkeypatch.setattr(work, "conversation_observation", lambda *_a, **_k: {"outcome": "not_found"})
    monkeypatch.setattr(work, "workspace_units", lambda *_a: 0)
    monkeypatch.setattr(work, "_allowance", lambda *_a: {"remaining_units": 9})
    with pytest.raises(WorkspaceError, match="research_analysis_too_large"):
        work.reserve_conversation(s, w.box_id, w.owner_id, w.id, **arguments(command), clock=lambda: STAMP)
    assert s.added == [] and s.commits == 0


def test_aggregate_utf8_bound_counts_bytes_before_admission(monkeypatch):
    s, w, _, _, settings, command = fixture(3, excerpt="Invented é漢😀 evidence")
    contents = [row.content for (cls, _), row in s.rows.items() if cls is WorkspaceEntry]
    count = sum(len(content.encode()) for content in contents)
    monkeypatch.setattr(analysis, "MAX_TOTAL_BYTES", count)
    analysis.build_context(s, w, settings, command)
    monkeypatch.setattr(analysis, "MAX_TOTAL_BYTES", count - 1)
    with pytest.raises(WorkspaceError, match="research_analysis_too_large"):
        analysis.build_context(s, w, settings, command)


def test_real_five_thousand_character_packet_is_exact_and_one_more_is_rejected():
    case = fixture()
    entry = replace_packet(case, 0, ["a" * 2500, "b"])
    tail = "b" * (5000 - len(entry.content) + 1)
    assert len(tail) <= 2500
    entry = replace_packet(case, 0, ["a" * 2500, tail])
    assert len(entry.content) == 5000
    context = analysis.build_context(case[0], case[1], case[4], case[5])
    envelope = GPT41Connector(lambda: pytest.fail("credential access")).prepare(context)
    assert envelope["sources"][0]["text"] == entry.content
    assert envelope["sources"][0]["truncated"] is False
    replace_packet(case, 0, ["a" * 2500, tail + "b"])
    with pytest.raises(WorkspaceError, match="research_analysis_too_large"):
        analysis.build_context(case[0], case[1], case[4], case[5])


def test_real_unicode_packets_hit_aggregate_byte_bound_without_hitting_character_bound():
    case = fixture(3)
    entries = [replace_packet(case, index, ["漢" * 2500, "漢" * 1500]) for index in range(3)]
    assert all(len(entry.content) <= 5000 for entry in entries)
    assert sum(len(entry.content) for entry in entries) < 15000
    assert sum(len(entry.content.encode()) for entry in entries) > 32768
    with pytest.raises(WorkspaceError, match="research_analysis_too_large"):
        analysis.build_context(case[0], case[1], case[4], case[5])


@pytest.mark.parametrize("maximum", [False, True])
def test_model_projection_retains_three_anchors_for_exact_restart_recovery(monkeypatch, maximum):
    case = fixture(3)
    s, w, version, bot, settings, command = case
    if maximum:
        command["idempotency_key"] = "a" * 100
        settings["name"] = "🧪" * 40
    row, _ = row_and_context(case)
    row.id, row.request_entry_id = str(uuid4()), str(uuid4())
    row.state, row.dispatch_id = "running", str(uuid4())
    row.admitted_at, row.lease_ends_at, row.reason = STAMP, STAMP + timedelta(seconds=90), None
    s.rows[(ProviderTeamRevision, version.id)] = version
    monkeypatch.setattr(work, "admission_observation", lambda *_a: {
        "id": row.id, "state": "running", "unit": 1, "admitted_at": STAMP.isoformat(),
        "dispatch": "started", "usage": "unknown", "input_tokens": None, "output_tokens": None})
    monkeypatch.setattr(s, "scalars", lambda _statement: [row])
    value = {"id": w.id, "entries": [{"id": row.request_entry_id}]}
    projected = work.project_workspace(s, value, as_of=STAMP)
    metadata = projected["entries"][0]["model_request"]
    assert metadata["request"]["research_analysis"] == command["research_analysis"]
    assert len(work.canonical(metadata)) <= ENTRY_MODEL_BYTES
    assert "content" not in metadata["request"]
    restored = {**metadata["request"], "content": command["content"]}
    restored.pop("kind")
    assert ConversationRequest.model_validate(restored).model_dump(mode="json") == command


def test_exact_request_replay_returns_retained_unknown_after_model_and_research_disabled(monkeypatch):
    case = fixture()
    s, w = gates(monkeypatch, case)
    command = case[-1]
    retained = {"outcome": "unknown", "request_sha256": work.conversation_request_hash(
        **{k: v for k, v in arguments(command).items() if k != "key"})}
    monkeypatch.setattr(conversation, "runtime_settings", NS(workspace_llm_available=False))
    monkeypatch.setattr(work, "now", lambda *_a: STAMP)
    monkeypatch.setattr(work.team, "active_bot", lambda *_a: pytest.fail("replay checked current model/bot"))

    def observe(_s, _w, **kwargs):
        assert kwargs["request_hash"] == retained["request_sha256"]
        return retained

    monkeypatch.setattr(work, "conversation_observation", observe)
    result = conversation.ask(cast(Session, s), w.box_id, w.owner_id, w.id,
                              **arguments(command), model_contract=True)
    assert result == retained and not s.reads and not s.added and s.commits == 1
