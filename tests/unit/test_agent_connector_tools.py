"""Closed query proposal and exact reviewed-handle contracts; no publisher I/O."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cosmas_os.application import agent_connector_tools as tools
from cosmas_os.ports.agent_connectors import (
    CONNECTOR_REQUEST_ADAPTER,
    ProposeResearchQuery,
    ToolSelectionV2,
)
from cosmas_os.ports.bot_capabilities import BotContext, SourcePassage


def proposal(**changes):
    return {"tool": "propose_research_query", "topic": "literature", "sources": ["pubmed"],
        "query": "acute ankle injury evidence", **changes}


@pytest.mark.parametrize("change", [
    {"public_query_confirmed": True}, {"owner_id": str(uuid4())}, {"url": "https://example.invalid"},
    {"query": "x" * 501}, {"sources": ["pubmed"] * 4}, {"tool": "approve_research_query"},
])
def test_model_cannot_attest_review_add_identity_endpoint_or_approval(change):
    with pytest.raises(ValidationError):
        CONNECTOR_REQUEST_ADAPTER.validate_python(proposal(**change))


@pytest.mark.parametrize("change", [
    {"sources": ["pubmed", "pubmed"]}, {"sources": ["clinical_trials"]}, {"topic": "send"},
    {"query": " hidden "}, {"query": "bad\x00query"}, {"sources": ["https://example.invalid"]},
])
def test_existing_public_query_contract_rejects_invalid_proposal_before_io(change):
    candidate = ProposeResearchQuery.model_validate(proposal(**change))
    with pytest.raises(ValidationError):
        tools._search({**candidate.model_dump(exclude={"tool"}), "bot": str(uuid4()),
            "team_revision": 1}, key="invented-validation", expected=1)


@pytest.mark.parametrize("extra", [{"query": "changed query"}, {"public_query_confirmed": True},
    {"bot": str(uuid4())}, {"account_id": str(uuid4())}, {"endpoint": "https://example.invalid"}])
def test_execution_uses_only_exact_reviewed_handle(extra):
    request = {"tool": "execute_reviewed_research", "ticket_id": str(uuid4()),
        "revision_id": str(uuid4()), "payload_hash": "a" * 64, **extra}
    with pytest.raises(ValidationError):
        CONNECTOR_REQUEST_ADAPTER.validate_python(request)


def test_tool_schemas_expose_proposal_and_reads_without_approval_or_external_sends():
    definitions = tools.tool_definitions()
    assert [value["name"] for value in definitions] == list(tools.TOOL_NAMES)
    for value in definitions:
        schema = value["parameters"]
        assert schema["additionalProperties"] is False
        assert not {"public_query_confirmed", "owner_id", "agent_id", "account_id", "url"} & schema["properties"].keys()


def test_evidence_binding_allows_question_change_but_refuses_source_tail_change():
    source = SourcePassage(str(uuid4()), 1, "Invented evidence", "evidence", "Invented evidence tail")
    context = BotContext(str(uuid4()), 1, "research", "first question", "brief", (source,), ())
    changed = deepcopy(context)
    object.__setattr__(changed, "question", "different reviewed-work question")
    assert tools.evidence_digest(context) == tools.evidence_digest(changed)
    changed_source = deepcopy(context)
    object.__setattr__(changed_source.sources[0], "content", source.content + "!")
    assert tools.evidence_digest(context) != tools.evidence_digest(changed_source)


def test_selection_v2_never_coerces_reviewed_intent_hash():
    value = {"contract": "cosmas-agent-tool-selection.v2", "sources": [],
        "teammate_drafts": [], "operations": [], "connector_capabilities": ["research_propose"],
        "connector_intents": [{"kind": "research", "ticket_id": str(uuid4()),
            "revision_id": str(uuid4()), "payload_hash": "a" * 64}], "sha256": "b" * 64}
    assert ToolSelectionV2.model_validate(value).connector_intents[0].kind == "research"
    value["connector_intents"][0]["payload_hash"] = "invalid"
    with pytest.raises(ValidationError):
        ToolSelectionV2.model_validate(value)


def test_compact_lookup_delivery_preserves_original_hashes_and_explicit_omissions():
    record = {"source": "pubmed", "id": "12345", "title": "Invented source",
        "url": "https://pubmed.ncbi.nlm.nih.gov/12345/", "source_updated_at": None,
        "version": None, "retrieved_at": "2026-10-06T00:00:00Z", "truncated": False,
        "raw_response_sha256": "a" * 64, "query_sha256": "b" * 64, "result_scope": "limited",
        "attribution": "Invented source", "sha256": "c" * 64, "excerpt": "x" * 2500,
        "fields": [{"label": "Invented field", "text": "y" * 1500}] * 12}
    lookup = {"workspace_id": str(uuid4()), "run_id": str(uuid4()), "request_sha256": "d" * 64,
        "state": "completed", "query": "invented evidence", "topic": "literature",
        "sources": ["pubmed"], "results": [record] * 15, "errors": []}
    result = tools.result_projection(lookup)
    assert result["retained_lookup_sha256"] == tools.research_digest(lookup)
    assert len(result["results"]) == 12 and result["delivery_omissions"]["records"] == 3
    row = result["results"][0]
    assert row["sha256"] == record["sha256"] and len(row["excerpt"]) == 500
    assert row["delivery_omissions"] == {"excerpt_characters": 2000, "fields": 9,
        "field_text_characters": 4050}
    assert result["source_save_required"] and not result["clinical_eligibility_established"]


def test_large_utf8_deliveries_stop_at_explicit_record_byte_budget():
    record = {"source": "pubmed", "id": "12345", "title": "漢" * 500,
        "url": "https://pubmed.ncbi.nlm.nih.gov/12345/", "source_updated_at": "漢" * 80,
        "version": "漢" * 128, "retrieved_at": "2026-10-06T00:00:00Z", "truncated": False,
        "raw_response_sha256": "a" * 64, "query_sha256": "b" * 64, "result_scope": "limited",
        "attribution": "漢" * 200, "sha256": "c" * 64, "excerpt": "漢" * 2500,
        "fields": [{"label": "漢" * 80, "text": "漢" * 1500}] * 12}
    lookup = {"workspace_id": str(uuid4()), "run_id": str(uuid4()), "request_sha256": "d" * 64,
        "state": "completed", "query": "漢" * 500, "topic": "literature",
        "sources": ["pubmed"], "results": [record] * 15, "errors": []}
    projected = tools.result_projection(lookup)
    import json
    assert len(json.dumps(projected, ensure_ascii=False).encode()) < tools.MAX_RESPONSE_BYTES
    assert len(projected["results"]) < 12
    assert projected["delivery_omissions"]["records"] == 15 - len(projected["results"])
