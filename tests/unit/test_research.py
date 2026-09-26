"""Offline publisher-contract and privacy failures; no service acceptance implied."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from cosmas_os.adapters import public_research as adapter
from cosmas_os.api.research_schemas import Search, SourceRecord
from cosmas_os.api.team_schemas import TeamConfiguration
from cosmas_os.application import provider_team, research, team_setup
from cosmas_os.config import Settings
from cosmas_os.ports.bot_capabilities import ROLE_TEMPLATES
from cosmas_os.ports.research import SOURCES, ResearchUnavailable, research_digest

SETID = "11111111-1111-4111-8111-111111111111"
DATASET = "22222222-2222-4222-8222-222222222222"
XML = f'''<?xml version="1.0"?><document xmlns="urn:hl7-org:v3"><setId root="{SETID}"/>
<versionNumber value="2"/><title>Invented drug label</title><effectiveTime value="20260920"/><component><section><title>BOXED WARNING</title>
<text>Invented warning for a synthetic drug.</text></section></component></document>'''
PUBMED = '''<?xml version="1.0"?><!DOCTYPE PubmedArticleSet SYSTEM "https://unrequested.invalid/schema.dtd">
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345</PMID><Article>
<ArticleTitle>Invented evidence</ArticleTitle><Abstract><AbstractText>Invented abstract.</AbstractText></Abstract>
<Journal><Title>Invented Journal</Title><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'''


def command(**changes):
    return {"contract_version": 1, "idempotency_key": str(uuid4()), "expected_revision": 1,
            "team_revision": 1, "bot": str(uuid4()), "topic": "literature", "sources": ["pubmed"],
            "query": "Invented evidence", "public_query_confirmed": True, **changes}


def configured():
    metadata = b'{"identifier":"abcd-ef12","distribution":[{"title":"Invented"}]}'
    schema = {"fields": ["id", "name", "summary"]}
    common = {"query_field": "name", "id_field": "id", "title_field": "name",
              "text_fields": ["summary"], "expected_columns": ["id", "name", "summary"],
              "version": "invented-v1", "released_at": "2026-09-22"}
    mappings = {"cms_open_data": {**common, "dataset_id": DATASET},
                "medicare_care_compare": {**common, "dataset_id": "abcd-ef12", "distribution_index": 0,
                    "metadata_sha256": hashlib.sha256(metadata).hexdigest(), "response_schema_sha256": research_digest(schema)}}
    return Settings(research_sources=",".join(SOURCES), research_dataset_mappings=json.dumps(mappings),
                    research_openfda_api_key=SecretStr("invented-api-key")), metadata, schema


@pytest.fixture(autouse=True)
def no_rate_wait(monkeypatch):
    adapter._NEXT_READ.clear()
    monkeypatch.setattr(adapter.time, "sleep", lambda _: None)


def test_fifth_standard_template_preserves_exact_four_baseline_and_preset():
    assert list(ROLE_TEMPLATES) == ["scribe", "visit_prep", "follow_up", "chief", "research"]
    original = provider_team.default_configuration()
    assert [bot["role"] for bot in original["bots"]] == ["scribe", "visit_prep", "follow_up", "chief"]
    assert [slot["role"] for slot in team_setup.catalog()["presets"][0]["slots"]] == ["scribe", "visit_prep", "follow_up", "chief"]
    selected = deepcopy(original)
    selected["bots"].append({"role": "research", "instance_id": str(uuid4()), "name": "Research",
                             "enabled": True, "include_notebook": False, "include_evidence": False})
    assert TeamConfiguration.model_validate(selected).bots[-1].role == "research"
    selected["bots"][-1].pop("instance_id")
    with pytest.raises(ValidationError):
        TeamConfiguration.model_validate(selected)


@pytest.mark.parametrize("change", [
    {"public_query_confirmed": False}, {"public_query_confirmed": 1}, {"contract_version": True},
    {"sources": ["pubmed", "pubmed"]}, {"sources": ["openfda"]}, {"query": "  unreviewed "},
    {"query": "x" * 501}, {"query": "bad\x00query"}, {"encounter_text": "must never forward"},
    {"sources": ["https://attacker.invalid"]}, {"expected_revision": True},
])
def test_query_rejects_unreviewed_coerced_private_or_unbounded_input(change):
    with pytest.raises(ValidationError):
        Search.model_validate_json(json.dumps(command(**change)))


def test_query_hash_is_utf8_and_exact():
    value = command(query="étude 漢字")
    parsed = Search.model_validate_json(json.dumps(value)).model_dump(mode="json")
    assert parsed == value
    assert research_digest(parsed) == hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@pytest.mark.parametrize("source,query", [
    ("pubmed", "Invented evidence"), ("clinical_trials", "Invented study"),
    ("dailymed", "Invented drug"), ("rxnorm", "Invented drug"), ("openfda", "Invented drug"),
    ("cms_coverage", "NCD 123:2"), ("cms_open_data", "Invented provider"),
    ("medicare_care_compare", "Invented provider"), ("npi_registry", "1234567890"),
])
def test_all_nine_source_contracts_keep_provenance_and_only_closed_gets(source, query):
    settings, metadata, schema = configured()
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "GET" and request.url.scheme == "https"
        assert "license-agreement" not in str(request.url)
        assert "invented-api-key" not in str(request.url)
        if request.url.path.endswith("esearch.fcgi"):
            value = {"esearchresult": {"idlist": ["12345"], "count": "1"}}
        elif request.url.path.endswith("efetch.fcgi"):
            return httpx.Response(200, content=PUBMED.encode())
        elif source == "clinical_trials":
            value = {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT12345678", "briefTitle": "Invented study"},
                "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-09-20"}},
                "eligibilityModule": {"eligibilityCriteria": "Invented inclusion and exclusion criteria", "minimumAge": "18 Years"}}}], "totalCount": 1}
        elif source == "dailymed":
            if request.url.path.endswith(".xml"):
                return httpx.Response(200, content=XML.encode())
            value = {"data": [{"setid": SETID, "title": "Invented drug", "spl_version": 2, "published_date": "2026-09-20"}], "metadata": {}}
        elif source == "rxnorm":
            value = {"drugGroup": {"conceptGroup": [{"conceptProperties": [{"rxcui": "12345", "name": "Invented drug", "tty": "SCD"}]}]}}
        elif source == "openfda":
            assert request.headers["authorization"].startswith("Basic ")
            value = {"results": [{"id": "invented-label", "version": "2", "effective_time": "20260920",
                "boxed_warning": ["Invented warning"], "openfda": {"generic_name": ["Invented drug"]}}], "meta": {"results": {"total": 1}}}
        elif source == "cms_coverage":
            assert dict(request.url.params) == {"ncdid": "123", "ncdver": "2"}
            value = {"meta": {"status": {"id": 200}}, "data": [{"document_id": 123, "document_version": 2,
                "title": "Invented policy", "effective_date": "09/20/2026", "indications_limitations": "Invented criteria"}]}
        elif source == "cms_open_data":
            assert request.url.params["filter[name]"] == query
            value = [{"id": "invented-1", "name": query, "summary": "Invented public data"}]
        elif source == "medicare_care_compare":
            if "/metastore/" in request.url.path:
                return httpx.Response(200, content=metadata)
            assert request.url.path.endswith("/abcd-ef12/0")
            assert request.url.params["conditions[0][operator]"] == "="
            value = {"results": [{"id": "invented-1", "name": query, "summary": "Invented comparison"}],
                "count": 1, "schema": schema, "query": {"conditions": [{"property": "name", "value": query, "operator": "="}], "limit": 5, "offset": 0}}
        else:
            assert request.url.params["version"] == "2.1"
            value = {"result_count": 1, "results": [{"number": 1234567890, "basic": {"first_name": "Invented", "last_name": "Provider", "last_updated": "2026-09-20"}}]}
        return httpx.Response(200, json=value)

    with adapter.PublicResearch(settings, transport=httpx.MockTransport(respond)) as port:
        rows = port.lookup(source, query, check=lambda: 30)
    assert len(rows) == 1 and 1 <= len(calls) <= 3
    row = rows[0]
    assert row["source"] == source and row["query_sha256"] == research_digest({"source": source, "query": query})
    assert SourceRecord.model_validate(row).sha256 == research_digest({key: value for key, value in row.items() if key != "sha256"})
    if source == "dailymed":
        assert "Invented warning" in row["excerpt"] and row["version"] == "2"
    assert "invented-api-key" not in json.dumps(rows)


@pytest.mark.parametrize("response", [
    lambda: httpx.Response(302, headers={"location": "http://127.0.0.1/private"}),
    lambda: httpx.Response(200, content=b'{"drugGroup":{},"drugGroup":{}}'),
    lambda: httpx.Response(200, content=b"x" * (adapter.MAX_BODY + 1)),
    lambda: httpx.Response(200, content=b"{}", headers={"content-encoding": "made-up"}),
    lambda: httpx.Response(429),
])
def test_upstream_redirect_malformed_oversize_encoding_and_rate_fail_closed(response):
    settings, _, _ = configured()
    calls = []
    transport = httpx.MockTransport(lambda request: (calls.append(request), response())[1])
    with pytest.raises(ResearchUnavailable):
        adapter.PublicResearch(settings, transport=transport).lookup("rxnorm", "Invented", check=lambda: 30)
    assert len(calls) == 1


def test_xml_entities_and_changed_label_identity_are_rejected():
    settings, _, _ = configured()
    for body in (XML.replace(SETID, DATASET), '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///private">]><document/>'):
        adapter._NEXT_READ.clear()
        def respond(request, body=body):
            if request.url.path.endswith(".xml"):
                return httpx.Response(200, content=body.encode())
            return httpx.Response(200, json={"data": [{"setid": SETID, "title": "Invented", "spl_version": 2}]})
        with pytest.raises(ResearchUnavailable):
            adapter.PublicResearch(settings, transport=httpx.MockTransport(respond)).lookup("dailymed", "Invented", check=lambda: 30)


def sample_record(query="Invented evidence"):
    return adapter.record("pubmed", query, "a" * 64, identity="12345", title="Invented study",
                          url="https://pubmed.ncbi.nlm.nih.gov/12345/", excerpt="Invented evidence", scope="unknown")


@pytest.mark.parametrize("changed", ["sha256", "url", "query_sha256"])
def test_observation_rejects_tampered_or_wrong_query_evidence(changed):
    request = command()
    source = sample_record()
    source[changed] = "https://attacker.invalid/" if changed == "url" else "b" * 64
    if changed == "query_sha256":
        source["sha256"] = research_digest({key: value for key, value in source.items() if key != "sha256"})
    row = SimpleNamespace(request=request, request_sha256=research_digest(request), results=[source], errors=[], state="completed",
                          created_at=datetime.now(UTC), id=str(uuid4()), workspace_id=str(uuid4()), idempotency_key=request["idempotency_key"])
    with pytest.raises((ValidationError, ValueError)):
        research.observation(row)


def test_interrupted_observation_is_read_only_and_retains_exact_command():
    request = command()
    row = SimpleNamespace(request=request, request_sha256=research_digest(request), results=[], errors=[], state="running",
                          created_at=datetime.now(UTC) - timedelta(seconds=40), id=str(uuid4()), workspace_id=str(uuid4()), idempotency_key=request["idempotency_key"])
    value = research.observation(row)
    assert value["state"] == "interrupted" and row.state == "running" and value["request"] == request


def test_saved_excerpt_preserves_evidence_limits_and_source_version():
    row = sample_record()
    content = research.source_excerpt([row])
    assert row["url"] in content and row["sha256"] in content and "Version: Not supplied" in content
    assert "Source updated: Not supplied" in content and "require clinician review" in content


def test_missing_keys_and_dataset_mappings_do_not_masquerade_as_connected():
    settings = Settings(research_sources=",".join(SOURCES))
    configured_sources = adapter.PublicResearch.configured(settings)
    assert not {"openfda", "cms_open_data", "medicare_care_compare"} & configured_sources
    assert not settings.workspace_research_available and not settings.workspace_research_io_enabled


def saved_fixture():
    request = command()
    source = sample_record()
    run = SimpleNamespace(request=request, request_sha256=research_digest(request), results=[source], errors=[], state="completed",
        created_at=datetime.now(UTC), id=str(uuid4()), workspace_id=str(uuid4()), box_id=str(uuid4()), owner_id=str(uuid4()),
        idempotency_key=request["idempotency_key"])
    receipt_id, key = str(uuid4()), str(uuid4())
    saved = {"contract_version": 1, "idempotency_key": key, "expected_revision": 3, "source_hashes": [source["sha256"]]}
    receipt = SimpleNamespace(id=receipt_id, request=saved, request_sha256=research_digest(saved), run_id=run.id,
        workspace_id=run.workspace_id, box_id=run.box_id, idempotency_key=key, entry_id=str(uuid4()))
    entry = SimpleNamespace(id=receipt.entry_id, workspace_id=run.workspace_id, box_id=run.box_id,
        actor_id=run.owner_id, kind="evidence", source_label="Research · public source excerpts",
        idempotency_key="research:" + receipt_id, request_hash=receipt.request_sha256, revision=4,
        content=research.source_excerpt([source]))

    class Store:
        def get(self, model, key):
            value = run if model is research.ResearchRun else entry
            return value if value.id == key else None

    return Store(), run, receipt, entry


def test_saved_receipt_recovery_requires_the_exact_existing_entry():
    store, _, receipt, entry = saved_fixture()
    result = research._saved(store, receipt)
    assert result["entry_id"] == entry.id and result["entry_revision"] == 4
    assert result["request"] == receipt.request


@pytest.mark.parametrize("field,value", [
    ("workspace_id", str(uuid4())), ("actor_id", str(uuid4())), ("kind", "note"),
    ("source_label", "Unrelated evidence"), ("idempotency_key", "unbound"), ("request_hash", "a" * 64),
    ("revision", 5), ("content", "Fabricated instead of the selected source excerpt"),
])
def test_saved_receipt_refuses_unrelated_or_changed_entry(field, value):
    store, _, receipt, entry = saved_fixture()
    setattr(entry, field, value)
    with pytest.raises(ValueError):
        research._saved(store, receipt)


@pytest.mark.parametrize("change", ["extra", "unselected", "running", "key"])
def test_saved_receipt_refuses_closed_request_or_run_proof_mismatch(change):
    store, run, receipt, _ = saved_fixture()
    if change == "extra":
        receipt.request["arbitrary_evidence"] = "invented"
    elif change == "unselected":
        receipt.request["source_hashes"] = ["d" * 64]
    elif change == "running":
        run.state, run.results = "running", []
    else:
        receipt.idempotency_key = str(uuid4())
    receipt.request_sha256 = research_digest(receipt.request)
    with pytest.raises((ValidationError, ValueError)):
        research._saved(store, receipt)


def test_lookup_configuration_snapshot_and_current_selection_are_distinct():
    settings, _, _ = configured()
    port = adapter.PublicResearch(settings)
    original = adapter.PublicResearch.selection(port.settings)
    settings.research_openfda_api_key = SecretStr("changed-invented-key")
    assert adapter.PublicResearch.configured(settings) == adapter.PublicResearch.configured(port.settings)
    assert adapter.PublicResearch.selection(settings) != original
    assert adapter.PublicResearch.selection(port.settings) == original
    settings.research_dataset_mappings = '{"invalid_new_mapping":{}}'
    assert adapter.PublicResearch.selection(settings) != original


@pytest.mark.asyncio
async def test_boundary_capacity_error_preserves_the_exact_configured_origin_policy(monkeypatch):
    from threading import BoundedSemaphore

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from cosmas_os.api import capture_deadline, research_routes

    monkeypatch.setattr(capture_deadline, "_workers", BoundedSemaphore(0))
    app = FastAPI()

    def forbidden(**_):
        raise AssertionError("saturated boundary must not enter dependency or database")

    app.include_router(research_routes.router(settings=forbidden, session_factory=forbidden,
        identity_dependency=forbidden, workspace_gate=forbidden, port_factory=adapter.PublicResearch))
    app.add_middleware(CORSMiddleware, allow_origins=["https://client.invalid"], allow_credentials=True,
        allow_methods=["GET", "POST"], allow_headers=["Authorization", "X-Cosmas-Research-Contract"])
    research_routes.install_research_boundary(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid") as client:
        for origin in ["https://client.invalid", "https://foreign.invalid"]:
            response = await client.get("/research/catalog", headers={"origin": origin})
            assert response.status_code == 503 and response.json() == {"detail": "research_unavailable"}
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert response.headers.get("access-control-allow-origin") == (origin if origin.endswith("client.invalid") else None)


@pytest.mark.parametrize("field,value", [("version", "  \t"), ("source_updated_at", "\u0085"),
    ("retrieved_at", "2026-09-22 10:00:00+00:00"), ("retrieved_at", "2026-W39-2T10:00:00+00:00")])
def test_source_metadata_refuses_blank_values_and_noncontract_dates(field, value):
    row = sample_record()
    row[field] = value
    row["sha256"] = research_digest({key: item for key, item in row.items() if key != "sha256"})
    with pytest.raises(ValidationError):
        SourceRecord.model_validate(row)


def test_observation_refuses_more_than_five_records_from_one_source():
    request = command()
    records = [adapter.record("pubmed", request["query"], "a" * 64, identity=str(index), title="Invented",
        url="https://pubmed.ncbi.nlm.nih.gov/" + str(index) + "/") for index in range(6)]
    row = SimpleNamespace(request=request, request_sha256=research_digest(request), results=records,
        errors=[], state="completed", created_at=datetime.now(UTC), id=str(uuid4()), workspace_id=str(uuid4()),
        idempotency_key=request["idempotency_key"])
    with pytest.raises(ValueError, match="research source integrity"):
        research.observation(row)


@pytest.mark.asyncio
async def test_deeply_nested_post_is_closed_before_any_dependency():
    from fastapi import FastAPI

    from cosmas_os.api import research_routes

    def forbidden(**_):
        raise AssertionError("malformed request must not enter dependency or database")

    app = FastAPI()
    app.include_router(research_routes.router(settings=forbidden, session_factory=forbidden,
        identity_dependency=forbidden, workspace_gate=forbidden, port_factory=adapter.PublicResearch))
    research_routes.install_research_boundary(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid") as client:
        response = await client.post('/workspaces/' + str(uuid4()) + '/research/search',
            content='[' * 1400 + '0' + ']' * 1400,
            headers={'authorization': 'Bearer invented', 'x-cosmas-research-contract': '1', 'content-type': 'application/json'})
    assert response.status_code == 422 and response.json() == {"detail": "invalid_research_request"}
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'


@pytest.mark.parametrize("retrieved", ["2026-09-22T10:00:00+00:60", "2026-09-22T10:00:00+01:99",
    "2026-09-22T10:00:00-00:60", "2026-09-22T10:00:00-01:99"])
def test_source_retrieval_refuses_normalized_out_of_range_offsets(retrieved):
    row = sample_record()
    row["retrieved_at"] = retrieved
    row["sha256"] = research_digest({key: value for key, value in row.items() if key != "sha256"})
    with pytest.raises(ValidationError):
        SourceRecord.model_validate(row)


@pytest.mark.parametrize("retrieved", ["2026-09-22T10:00:00+23:59", "2026-09-22T10:00:00-23:59",
    "2026-09-22T10:00:00.123456789Z"])
def test_source_retrieval_preserves_valid_contract_time(retrieved):
    row = sample_record()
    row["retrieved_at"] = retrieved
    row["sha256"] = research_digest({key: value for key, value in row.items() if key != "sha256"})
    assert SourceRecord.model_validate(row).retrieved_at == retrieved


@pytest.mark.asyncio
async def test_history_cursors_reject_malformed_queries_before_identity_or_database():
    from fastapi import FastAPI

    from cosmas_os.api import research_routes

    def forbidden(**_):
        raise AssertionError("invalid cursor must not enter dependencies")

    app = FastAPI()
    app.include_router(research_routes.router(settings=forbidden, session_factory=forbidden,
        identity_dependency=forbidden, workspace_gate=forbidden, port_factory=forbidden))
    research_routes.install_research_boundary(app)
    wid, bot, before = str(uuid4()), str(uuid4()), str(uuid4())
    queries = [f"bot={bot}&before=bad", f"bot={bot}&before={before}&before={before}",
               f"before={before}&bot={bot}", f"bot={bot}&before=", f"bot={bot}&other={before}"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid") as client:
        for path in (f"/workspaces/{wid}/research", f"/workspaces/{wid}/research/saved"):
            for query in queries:
                response = await client.get(path + "?" + query, headers={
                    "authorization": "Bearer invented", "x-cosmas-research-contract": "1"})
                assert response.status_code == 422 and response.json() == {"detail": "invalid_research_request"}
                assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bot", [None, "research", "", str(uuid4()).upper()])
def test_navigation_requires_canonical_bot_before_any_database_read(bot):
    for read in (research.history, research.saved_history):
        with pytest.raises(research.ws.WorkspaceError) as error:
            read(None, "unused", "unused", "unused", bot=bot)
        assert error.value.status == 422
