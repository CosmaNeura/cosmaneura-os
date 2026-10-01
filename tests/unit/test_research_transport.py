"""Actual asynchronous client with inert upstream streams; no service acceptance."""

import asyncio
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters import public_research as adapter
from cosmas_os.application.capture_deadline import CaptureBudget, CaptureDeadlineExceeded
from cosmas_os.config import Settings
from cosmas_os.ports.research import ResearchUnavailable, research_digest

ORIGIN = "https://rxnav.nlm.nih.gov"
SETID = "11111111-1111-4111-8111-111111111111"
NPI = "1234567890"


@pytest.fixture(autouse=True)
def reset_pacing():
    with adapter._RATE_LOCK:
        adapter._NEXT_READ.clear()
    yield
    with adapter._RATE_LOCK:
        adapter._NEXT_READ.clear()


def settings(source="rxnorm", **kwargs):
    values: dict[str, Any] = {"_env_file": None, "research_sources": source, **kwargs}
    return Settings(**values)


class ObservedStream(httpx.AsyncByteStream):
    def __init__(self, *, chunks=(), delay: float = 0, started=None):
        self.chunks, self.delay, self.started = chunks, delay, started
        self.closed = 0
        self.thread_ids = []

    async def __aiter__(self):
        self.thread_ids.append(threading.get_ident())
        if self.started is not None:
            self.started.set()
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.thread_ids.append(threading.get_ident())
        self.closed += 1


class ObservedTransport(httpx.AsyncBaseTransport):
    def __init__(self, response, *, header_delay=0, started=None):
        self.response, self.header_delay, self.started = response, header_delay, started
        self.closed = 0
        self.requests = []
        self.thread_ids = []

    async def handle_async_request(self, request):
        self.thread_ids.append(threading.get_ident())
        self.requests.append(request)
        if self.started is not None:
            self.started.set()
        if self.header_delay:
            await asyncio.sleep(self.header_delay)
        return self.response

    async def aclose(self):
        self.thread_ids.append(threading.get_ident())
        self.closed += 1


def read(port, origin=ORIGIN):
    return port._read(origin, "/REST/drugs.json", {}, lambda: 30)


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_real_eight_second_absolute_header_and_body_deadline(phase):
    # Both scenarios use the actual eight-second constant and AsyncClient.
    # The body stream stays active, so a per-chunk timeout would not pass.
    assert adapter.REQUEST_SECONDS == 8
    stream = ObservedStream(chunks=[b"x" * 1024] * 40, delay=0.3)
    transport = ObservedTransport(httpx.Response(200, stream=stream),
                                  header_delay=60 if phase == "headers" else 4)
    port = adapter.PublicResearch(settings(), transport=transport, budget=CaptureBudget(30))
    started = time.monotonic()
    with pytest.raises(ResearchUnavailable, match="^source_timeout$"):
        read(port)
    elapsed = time.monotonic() - started
    assert 7.6 <= elapsed < 10.5
    assert len(transport.requests) == 1 and transport.closed == 1
    assert stream.closed == (0 if phase == "headers" else 1)
    assert len(set(transport.thread_ids + stream.thread_ids)) == 1
    assert not port.budget._callbacks


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_outer_capture_cancellation_closes_owned_client_before_worker_returns(phase):
    started = threading.Event()
    stream = ObservedStream(chunks=[b"pending"], delay=60,
                            started=started if phase == "body" else None)
    transport = ObservedTransport(httpx.Response(200, stream=stream),
        header_delay=60 if phase == "headers" else 0,
        started=started if phase == "headers" else None)
    budget = CaptureBudget(30)
    port = adapter.PublicResearch(settings(), transport=transport, budget=budget)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(read, port)
        assert started.wait(2)
        cancelled_at = time.monotonic()
        budget.cancel()
        with pytest.raises(CaptureDeadlineExceeded):
            future.result(timeout=2)
        assert time.monotonic() - cancelled_at < 2
    assert transport.closed == 1 and len(transport.requests) == 1
    assert stream.closed == (0 if phase == "headers" else 1)
    assert len(set(transport.thread_ids + stream.thread_ids)) == 1
    assert not budget._callbacks


def test_shorter_outer_budget_expiration_does_not_become_a_successful_source():
    transport = ObservedTransport(httpx.Response(200, content=b"late"), header_delay=60)
    budget = CaptureBudget(0.15)
    started = time.monotonic()
    with pytest.raises(CaptureDeadlineExceeded):
        read(adapter.PublicResearch(settings(), transport=transport, budget=budget))
    assert time.monotonic() - started < 2
    assert transport.closed == 1 and not budget._callbacks


def test_complete_body_hash_and_aggregate_two_mebibyte_budget_across_sources():
    body = b"x" * (adapter.MAX_BODY // 2)
    responses = [httpx.Response(200, content=body),
                 httpx.Response(200, stream=ObservedStream(chunks=[body, b"!"]))]
    calls = []

    def respond(request):
        calls.append(request)
        return responses[len(calls) - 1]

    port = adapter.PublicResearch(settings(), transport=httpx.MockTransport(respond))
    raw, digest = read(port)
    assert raw == body and digest == hashlib.sha256(body).hexdigest()
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        read(port, "https://clinicaltrials.gov")
    assert len(calls) == 2
    # An exhausted aggregate budget must reject before another upstream request.
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        read(port, "https://api.fda.gov")
    assert len(calls) == 2


def test_exact_aggregate_body_ceiling_is_accepted_then_fences_further_gets():
    body = b"x" * adapter.MAX_BODY
    transport = ObservedTransport(httpx.Response(200, content=body))
    port = adapter.PublicResearch(settings(), transport=transport)
    assert read(port) == (body, hashlib.sha256(body).hexdigest())
    assert port.remaining_bytes == 0
    with pytest.raises(ResearchUnavailable):
        read(port)
    assert len(transport.requests) == 1 and transport.closed == 1


@pytest.mark.parametrize("length", ["8", "2", "-1", "1.5", "\u0663", "9" * 100])
def test_incomplete_or_malformed_content_length_never_yields_hashed_success(length):
    stream = ObservedStream(chunks=[b"abc"])
    transport = ObservedTransport(httpx.Response(200, stream=stream,
        headers=[(b"content-length", length.encode("utf-8"))]))
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        read(adapter.PublicResearch(settings(), transport=transport))
    assert transport.closed == 1 and stream.closed == 1


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be"])
def test_utf16_json_and_xml_fail_closed_before_interpretation(encoding):
    raw = '{"drugGroup":{}}'.encode(encoding)
    port = adapter.PublicResearch(settings(), transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=raw)))
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        port.lookup("rxnorm", "Invented", check=lambda: 30)
    xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY e "expanded">]><x>&e;</x>'
    with pytest.raises((ValueError, UnicodeError)):
        adapter.xml_document(xml.encode(encoding), pubmed=True)


def test_markup_plaintext_has_bounded_work_and_output_for_unmatched_openings():
    # The former regex scanned the two-megabyte suffix once for each '<'.
    hostile = "<" * adapter.MAX_BODY
    started = time.monotonic()
    assert adapter.plain(hostile) == "<" * 3001
    assert time.monotonic() - started < 2
    assert adapter.plain("Dose <b>five</b> &amp; six; a < b") == "Dose five & six; a < b"
    assert adapter.plain("&#" + "9" * 10000).startswith("\ufffd")
    with pytest.raises(ValueError, match="size limit"):
        adapter.plain("x" * (adapter.MAX_BODY + 1))
    nested = ["x"]
    for _ in range(64):
        nested = [nested]
    with pytest.raises(ValueError, match="nesting limit"):
        adapter.plain(nested)


def test_record_truncation_remains_truthful_after_plaintext_bounding():
    value = adapter.record("pubmed", "Invented", "a" * 64, identity="1",
        title="<b>" + "T" * 501 + "</b>", url="https://pubmed.ncbi.nlm.nih.gov/1/",
        excerpt="E" * 2501, fields=[("Field", "F" * 751)])
    assert value["truncated"] is True
    assert len(value["title"]) == 500 and len(value["excerpt"]) == 2500
    assert len(value["fields"][0]["text"]) == 750


def test_deep_json_and_xml_are_closed_failures_with_small_bodies():
    raw = b"[" * 2000 + b"0" + b"]" * 2000
    port = adapter.PublicResearch(settings(), transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=raw)))
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        port.lookup("rxnorm", "Invented", check=lambda: 30)
    with pytest.raises(ValueError, match="nesting limit"):
        adapter.xml_document(b"<x>" * 65 + b"</x>" * 65)
    with pytest.raises(ValueError, match="declaration"):
        adapter.xml_document(b"<?xml " * 200000)


def lookup(source, value, query="Invented", **kwargs):
    return adapter.PublicResearch(settings(source, **kwargs), transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=value))).lookup(source, query, check=lambda: 30)


def trial():
    return {"studies": [{"protocolSection": {
        "identificationModule": {"nctId": "NCT12345678", "briefTitle": "Invented trial"},
        "statusModule": {}}}], "totalCount": 1}


@pytest.mark.parametrize("criteria,expected", [
    ("Inclusion criteria:\n* LVEF <40%\n* Age >75 by time of infusion",
     "Inclusion criteria: * LVEF <40% * Age >75 by time of infusion"),
    (r"LVEF \< 40%; screening \< 2 weeks; age \>75; Hgb A1c \> 8.5%",
     "LVEF < 40%; screening < 2 weeks; age >75; Hgb A1c > 8.5%"),
    (r"LVEF \<=40%; age \>=75", "LVEF <=40%; age >=75"),
    ("LVEF &lt;40%; age &gt;75; measurement ≤40 or ≥75",
     "LVEF <40%; age >75; measurement ≤40 or ≥75"),
    (r"Invented marker <reference> and age >75; literal \* symbol",
     r"Invented marker <reference> and age >75; literal \* symbol"),
])
def test_trial_markdown_comparisons_preserve_complete_eligibility(criteria, expected):
    value = trial()
    value["studies"][0]["protocolSection"]["eligibilityModule"] = {"eligibilityCriteria": criteria}
    row = lookup("clinical_trials", value)[0]
    assert row["excerpt"] == expected and row["truncated"] is False
    assert row["raw_response_sha256"] == hashlib.sha256(httpx.Response(200, json=value).content).hexdigest()
    assert row["sha256"] == research_digest({key: item for key, item in row.items() if key != "sha256"})


def test_trial_plaintext_comparisons_also_survive_titles_and_summary_fields():
    value = trial()
    protocol = value["studies"][0]["protocolSection"]
    protocol["identificationModule"]["briefTitle"] = r"Invented LVEF \<40% and age \>75 study"
    protocol["descriptionModule"] = {"briefSummary": r"Compare LVEF \<40% with LVEF \>50%."}
    row = lookup("clinical_trials", value)[0]
    assert row["title"] == "Invented LVEF <40% and age >75 study"
    assert row["fields"] == [{"label": "Study summary", "text": "Compare LVEF <40% with LVEF >50%."}]


def test_trial_comparison_normalization_keeps_existing_excerpt_and_field_limits():
    value = trial()
    criteria = r"LVEF \<40%; age \>75. " * 200
    plain = " ".join(("LVEF <40%; age >75. " * 200).split())
    value["studies"][0]["protocolSection"].update({
        "eligibilityModule": {"eligibilityCriteria": criteria},
        "descriptionModule": {"briefSummary": criteria},
    })
    row = lookup("clinical_trials", value)[0]
    assert row["excerpt"] == plain[:2500]
    assert row["fields"] == [{"label": "Study summary", "text": plain[:750]}]
    assert row["truncated"] is True
    assert row["sha256"] == research_digest({key: item for key, item in row.items() if key != "sha256"})


@pytest.mark.parametrize("total", [True, False, 1.0, 1.5, "1", -1, 0])
@pytest.mark.parametrize("source", ["clinical_trials", "openfda"])
def test_boolean_fractional_or_inconsistent_counts_cannot_claim_completeness(source, total):
    kwargs: dict[str, Any]
    if source == "clinical_trials":
        value, kwargs = trial(), {}
        value["totalCount"] = total
    else:
        value = {"results": [{"id": "invented", "openfda": {"generic_name": ["Invented"]}}],
                 "meta": {"results": {"total": total}}}
        kwargs = {"research_openfda_api_key": SecretStr("invented")}
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        lookup(source, value, **kwargs)


def test_missing_count_remains_unknown_and_valid_integral_count_can_be_complete():
    value = trial()
    assert lookup("clinical_trials", value)[0]["result_scope"] == "complete"
    adapter._NEXT_READ.clear()
    value.pop("totalCount")
    assert lookup("clinical_trials", value)[0]["result_scope"] == "unknown"


def test_duplicate_returned_identity_cannot_claim_two_complete_studies():
    value = trial()
    value["studies"] *= 2
    value["totalCount"] = 2
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        lookup("clinical_trials", value)


def test_trial_details_keep_registry_phase_intervention_and_individual_site_status():
    value = trial()
    protocol = value["studies"][0]["protocolSection"]
    protocol.update({
        "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-09-20"}},
        "conditionsModule": {"conditions": ["Myocardial Infarction", "Heart Failure"]},
        "designModule": {"phases": ["PHASE1", "PHASE2"]},
        "armsInterventionsModule": {"interventions": [{"type": "BIOLOGICAL", "name": "Invented cell therapy"}]},
        "contactsLocationsModule": {"locations": [
            {"facility": "Invented Trial Center", "city": "Example City", "state": "Example State",
             "country": "United States", "status": "ACTIVE_NOT_RECRUITING"},
            {"facility": "Invented Second Center", "country": "Canada"},
        ]},
        "eligibilityModule": {"minimumAge": "18 Years", "maximumAge": "75 Years", "sex": "ALL",
                              "eligibilityCriteria": "Invented inclusion and exclusion criteria."},
        "descriptionModule": {"briefSummary": "Invented study summary."},
    })
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=value)

    with adapter.PublicResearch(settings("clinical_trials"), transport=httpx.MockTransport(respond)) as port:
        row = port.lookup("clinical_trials", "Invented cell therapy", check=lambda: 30)[0]
    assert len(requests) == 1 and requests[0].method == "GET"
    assert str(requests[0].url).startswith("https://clinicaltrials.gov/api/v2/studies?")
    assert dict(requests[0].url.params) == {
        "query.term": "Invented cell therapy", "pageSize": "5", "format": "json", "countTotal": "true"}
    assert {field["label"]: field["text"] for field in row["fields"]} == {
        "Recruitment status": "RECRUITING", "Conditions": "Myocardial Infarction; Heart Failure",
        "Phase": "PHASE1; PHASE2",
        "Interventions": "Type: BIOLOGICAL; Name: Invented cell therapy",
        "Locations": "Facility: Invented Trial Center; City: Example City; State: Example State; "
                     "Country: United States; Site status: ACTIVE_NOT_RECRUITING | "
                     "Facility: Invented Second Center; Country: Canada",
        "Minimum age": "18 Years", "Maximum age": "75 Years", "Sex": "ALL",
        "Study summary": "Invented study summary.",
    }
    assert row["excerpt"] == "Invented inclusion and exclusion criteria."
    assert row["source_updated_at"] == "2026-09-20"
    assert row["url"] == "https://clinicaltrials.gov/study/NCT12345678"
    assert row["result_scope"] == "complete" and row["truncated"] is False
    assert row["sha256"] == research_digest({key: item for key, item in row.items() if key != "sha256"})


def test_trial_missing_optional_details_do_not_invent_site_recruitment_or_phase():
    value = trial()
    value["studies"][0]["protocolSection"]["contactsLocationsModule"] = {
        "locations": [{"facility": "Invented Trial Center", "country": "United States"}]}
    row = lookup("clinical_trials", value)[0]
    assert row["fields"] == [{"label": "Locations", "text": "Facility: Invented Trial Center; Country: United States"}]
    assert row["source_updated_at"] is None and row["truncated"] is False


@pytest.mark.parametrize("module,details", [
    ("conditionsModule", {"conditions": "Myocardial Infarction"}),
    ("conditionsModule", {"conditions": {"name": "Myocardial Infarction"}}),
    ("conditionsModule", {"conditions": [1]}),
    ("conditionsModule", {"conditions": [True]}),
    ("conditionsModule", {"conditions": [None]}),
    ("conditionsModule", None),
    ("designModule", {"phases": "PHASE1"}), ("designModule", {"phases": [1]}),
    ("armsInterventionsModule", {"interventions": {"name": "Invented"}}),
    ("armsInterventionsModule", {"interventions": [None]}),
    ("armsInterventionsModule", {"interventions": [{"name": 17}]}),
    ("contactsLocationsModule", {"locations": {"facility": "Invented"}}),
    ("contactsLocationsModule", {"locations": [True]}),
    ("contactsLocationsModule", {"locations": [{"status": []}]}),
])
def test_trial_malformed_optional_details_fail_without_claiming_complete_results(module, details):
    value = trial()
    value["studies"][0]["protocolSection"][module] = details
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        lookup("clinical_trials", value)


def test_trial_long_site_and_intervention_lists_are_marked_shortened_within_existing_limits():
    value = trial()
    value["studies"][0]["protocolSection"].update({
        "statusModule": {"overallStatus": "RECRUITING"},
        "designModule": {"phases": ["PHASE2"]},
        "armsInterventionsModule": {"interventions": [{"type": "BIOLOGICAL", "name": "Invented " * 200}]},
        "contactsLocationsModule": {"locations": [
            {"facility": "Invented Center " + str(index), "city": "Example City", "country": "United States"}
            for index in range(60)]},
        "eligibilityModule": {"minimumAge": "18 Years", "maximumAge": "75 Years", "sex": "ALL",
                              "eligibilityCriteria": "Invented criteria " * 200},
        "descriptionModule": {"briefSummary": "Invented summary " * 200},
    })
    row = lookup("clinical_trials", value)[0]
    fields = {field["label"]: field["text"] for field in row["fields"]}
    assert len(fields["Locations"]) == len(fields["Interventions"]) == 750
    assert len(row["fields"]) <= 8 and sum(len(field["text"]) for field in row["fields"]) <= 3000
    assert len(row["excerpt"]) == 2500 and row["truncated"] is True
    assert row["sha256"] == research_digest({key: item for key, item in row.items() if key != "sha256"})


def test_trial_conditions_keep_source_terms_and_limits_without_inference_from_query():
    value = trial()
    value["studies"][0]["protocolSection"]["conditionsModule"] = {
        "conditions": [r"Invented LVEF \<40% cohort", "Invented registry condition"]}
    row = lookup("clinical_trials", value, "heart attack stem cell treatment")[0]
    assert row["fields"] == [{"label": "Conditions",
        "text": "Invented LVEF <40% cohort; Invented registry condition"}]
    assert "heart attack" not in row["fields"][0]["text"]
    assert row["truncated"] is False
    adapter._NEXT_READ.clear()
    value["studies"][0]["protocolSection"]["conditionsModule"]["conditions"] *= 100
    row = lookup("clinical_trials", value)[0]
    assert len(row["fields"][0]["text"]) == 750 and row["truncated"] is True
    assert sum(len(field["text"]) for field in row["fields"]) <= 3000


def npi():
    return {"result_count": 1, "results": [{"number": NPI,
        "basic": {"first_name": "Invented", "last_name": "Provider"},
        "taxonomies": [{"desc": "Invented specialty"}]}]}


@pytest.mark.parametrize("changes", [
    {"result_count": True}, {"result_count": 1.0}, {"result_count": "1"},
    {"result_count": -1}, {"result_count": 0}, {"result_count": 2},
    {"results": {}}, {"results": ""}, {"results": [None]},
])
def test_npi_requires_integral_consistent_count_and_result_collection(changes):
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        lookup("npi_registry", {**npi(), **changes}, NPI)


@pytest.mark.parametrize("field,value", [("number", {"value": NPI}), ("number", 1234567890.0),
    ("basic", []), ("basic", {"organization_name": 123}), ("taxonomies", {}),
    ("taxonomies", [{"desc": 123}])])
def test_npi_requires_documented_field_types(field, value):
    result = npi()
    result["results"][0][field] = value
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        lookup("npi_registry", result, NPI)


def test_npi_zero_and_one_results_are_explicit_and_hash_bound():
    assert lookup("npi_registry", {"result_count": 0}, NPI) == []
    adapter._NEXT_READ.clear()
    assert lookup("npi_registry", npi(), NPI)[0]["result_scope"] == "complete"
    adapter._NEXT_READ.clear()
    with pytest.raises(ResearchUnavailable):
        lookup("npi_registry", {"results": []}, NPI)


def test_pubmed_search_metadata_cannot_supply_unhashed_completeness():
    xml = b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345</PMID><Article><ArticleTitle>Invented evidence</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
    for total in ("1", "100"):
        adapter._NEXT_READ.clear()
        def respond(request, total=total):
            if request.url.path.endswith("esearch.fcgi"):
                return httpx.Response(200, json={"esearchresult": {"idlist": ["12345"], "count": total}})
            return httpx.Response(200, content=xml)
        rows = adapter.PublicResearch(settings("pubmed"), transport=httpx.MockTransport(respond)).lookup(
            "pubmed", "Invented", check=lambda: 30)
        assert rows[0]["result_scope"] == "unknown"
        assert rows[0]["raw_response_sha256"] == hashlib.sha256(xml).hexdigest()


@pytest.mark.parametrize("total", [True, 1, 1.0, "1.0", "-1", "0"])
def test_pubmed_count_must_be_a_consistent_publisher_decimal_string(total):
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        lookup("pubmed", {"esearchresult": {"idlist": ["12345"], "count": total}})


@pytest.mark.parametrize("returned", [[], ["12345", "12345"], ["99999"]])
def test_pubmed_requires_exact_selected_identity_coverage(returned):
    articles = "".join('<PubmedArticle><MedlineCitation><PMID>' + identity + '</PMID><Article><ArticleTitle>Invented</ArticleTitle></Article></MedlineCitation></PubmedArticle>' for identity in returned)
    xml = ("<PubmedArticleSet>" + articles + "</PubmedArticleSet>").encode()
    def respond(request):
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["12345"], "count": "1"}})
        return httpx.Response(200, content=xml)
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        adapter.PublicResearch(settings("pubmed"), transport=httpx.MockTransport(respond)).lookup(
            "pubmed", "Invented", check=lambda: 30)


def test_same_local_identity_from_two_publishers_keeps_distinct_source_hashes():
    first = adapter.record("pubmed", "Invented", "a" * 64, identity="12345", title="Invented",
                           url="https://pubmed.ncbi.nlm.nih.gov/12345/")
    second = adapter.record("rxnorm", "Invented", "a" * 64, identity="12345", title="Invented",
                            url="https://mor.nlm.nih.gov/RxNav/search?searchTerm=12345")
    assert first["id"] == second["id"] and first["source"] != second["source"]
    assert first["sha256"] != second["sha256"] and first["query_sha256"] != second["query_sha256"]


def test_dailymed_provenance_comes_from_the_hashed_spl_not_the_search_result():
    xml = f'<document xmlns="urn:hl7-org:v3"><setId root="{SETID}"/><versionNumber value="2"/><title>Hashed label title</title><effectiveTime value="20260920"/></document>'.encode()
    def respond(request):
        if request.url.path.endswith(".xml"):
            return httpx.Response(200, content=xml)
        return httpx.Response(200, json={"data": [{"setid": SETID, "spl_version": 2,
            "title": "Unhashed search title", "published_date": "1900-01-01"}],
            "metadata": {"next_page_url": "unhashed-page"}})
    row = adapter.PublicResearch(settings("dailymed"), transport=httpx.MockTransport(respond)).lookup(
        "dailymed", "Invented", check=lambda: 30)[0]
    assert row["title"] == "Hashed label title" and row["source_updated_at"] == "20260920"
    assert row["version"] == "2" and row["result_scope"] == "unknown"
    assert row["raw_response_sha256"] == hashlib.sha256(xml).hexdigest()


def test_duplicate_dailymed_identity_is_refused_before_a_repeated_label_get():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"setid": SETID}, {"setid": SETID}]})
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        adapter.PublicResearch(settings("dailymed"), transport=httpx.MockTransport(respond)).lookup(
            "dailymed", "Invented", check=lambda: 30)
    assert len(calls) == 1


def dataset_mapping():
    return {"dataset_id": "22222222-2222-4222-8222-222222222222", "query_field": "name",
        "id_field": "id", "title_field": "name", "text_fields": ["summary"],
        "expected_columns": ["id", "name", "summary"], "version": "operator-version",
        "released_at": "1900-01-01"}


def test_operator_dataset_mapping_is_not_presented_as_upstream_release_evidence():
    row = lookup("cms_open_data", [{"id": "1", "name": "Invented", "summary": "Hashed data"}],
        research_dataset_mappings=json.dumps({"cms_open_data": dataset_mapping()}))[0]
    assert row["version"] is None and row["source_updated_at"] is None
    assert "operator-version" not in json.dumps(row) and "1900-01-01" not in json.dumps(row)


@pytest.mark.parametrize("total,offset", [(True, 0), (1.0, 0), ("1", 0), (0, 0), (1, False)])
def test_care_compare_integral_count_and_query_echo_are_required(total, offset):
    metadata = b"invented metadata"
    schema = {"fields": ["id", "name", "summary"]}
    mapping = {**dataset_mapping(), "dataset_id": "abcd-ef12", "distribution_index": 0,
        "metadata_sha256": hashlib.sha256(metadata).hexdigest(),
        "response_schema_sha256": research_digest(schema)}
    response = {"schema": schema, "count": total,
        "query": {"conditions": [{"property": "name", "value": "Invented", "operator": "="}],
                  "limit": 5, "offset": offset},
        "results": [{"id": "1", "name": "Invented", "summary": "Hashed data"}]}
    def respond(request):
        return httpx.Response(200, content=metadata) if "/metastore/" in request.url.path else httpx.Response(200, json=response)
    with pytest.raises(ResearchUnavailable, match="^invalid_source_response$"):
        adapter.PublicResearch(settings("medicare_care_compare",
            research_dataset_mappings=json.dumps({"medicare_care_compare": mapping})),
            transport=httpx.MockTransport(respond)).lookup("medicare_care_compare", "Invented", check=lambda: 30)


def test_deep_copied_selection_survives_caller_settings_mutation():
    supplied = settings()
    port = adapter.PublicResearch(supplied)
    before = deepcopy(adapter.PublicResearch.selection(port.settings))
    supplied.research_sources = "pubmed"
    assert adapter.PublicResearch.selection(port.settings) == before
    assert adapter.PublicResearch.selection(supplied) != before
