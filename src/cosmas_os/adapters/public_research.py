"""Publisher-specific HTTPS GET readers. No model, arbitrary URL, or license acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode
from xml.etree import ElementTree

import httpx

from cosmas_os.api.research_schemas import SourceRecord
from cosmas_os.application.capture_deadline import CaptureBudget, current_budget
from cosmas_os.ports.research import SOURCES, ResearchUnavailable, research_digest

MAX_BODY = 2 * 1024 * 1024
REQUEST_SECONDS = 8
_RATE_LOCK = threading.Lock()
_NEXT_READ: dict[str, float] = {}
_ENTITY = re.compile(r"&(?:#[0-9]{1,8}|#[xX][0-9a-fA-F]{1,8}|[A-Za-z][A-Za-z0-9]{0,31});?")


def text(value):
    """Flatten source text once, with bounded depth, work and allocation."""
    output, size, items = [], 0, 0
    stack = [iter((value,))]
    while stack:
        try:
            item = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        items += 1
        if items > MAX_BODY:
            raise ValueError("source text item limit")
        if isinstance(item, list):
            if len(stack) >= 64:
                raise ValueError("source text nesting limit")
            stack.append(iter(item))
        elif isinstance(item, (str, int, float)) and not isinstance(item, bool):
            part = str(item)
            size += len(part) + bool(output)
            if size > MAX_BODY:
                raise ValueError("source text size limit")
            output.append(part)
    return "\n".join(output)


def plain(value, *, limit=3001):
    """Linear markup removal, bounded entities, and bounded quoted output."""
    value = text(value)
    pieces, start = [], 0
    # Once no closing bracket remains, copy the remainder without rescanning
    # each '<'. A regex search from every unmatched '<' is quadratic.
    last_close = value.rfind(">")
    while start <= last_close:
        opening = value.find("<", start, last_close)
        if opening < 0:
            break
        closing = value.find(">", opening + 1)
        pieces.extend((value[start:opening], " "))
        start = closing + 1
    pieces.append(value[start:])
    cleaned = _ENTITY.sub(lambda match: html.unescape(match[0]), "".join(pieces))
    return " ".join(cleaned.split())[:limit]


def count(value, *, decimal_string=False):
    """Publisher counts must not coerce booleans, fractions or missing values."""
    if decimal_string:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,12}", value):
            raise ValueError("invalid source count")
        return int(value)
    if type(value) is not int or value < 0:
        raise ValueError("invalid source count")
    return value


def result_scope(total, rows, *, more=False):
    if total is None:
        return "limited" if more else "unknown"
    total = count(total)
    if total < len(rows):
        raise ValueError("inconsistent source count")
    return "limited" if more or total > len(rows) else "complete"


def record(source, query, response_hash, *, identity, title, url, excerpt="", version=None,
           updated=None, fields=(), scope="unknown", attribution=None):
    raw_title, raw_excerpt = plain(title, limit=501), plain(excerpt, limit=2501)
    if not raw_title or not str(identity):
        raise ResearchUnavailable("invalid_source_response")
    selected, remaining, shortened = [], 3000, len(raw_title) > 500 or len(raw_excerpt) > 2500
    for label, value in fields:
        cleaned = plain(value, limit=751)
        if not cleaned:
            continue
        cap = min(750, remaining)
        if cap <= 0 or len(selected) >= 8:
            shortened = True
            break
        selected.append({"label": plain(label, limit=80), "text": cleaned[:cap]})
        remaining -= len(cleaned[:cap])
        shortened = shortened or len(cleaned) > cap
    result = {
        "source": source, "id": str(identity), "title": raw_title[:500], "url": url,
        "source_updated_at": text(updated)[:80] or None, "version": text(version)[:128] or None,
        "retrieved_at": datetime.now(UTC).isoformat(), "excerpt": raw_excerpt[:2500],
        "fields": selected, "truncated": shortened, "raw_response_sha256": response_hash,
        "query_sha256": research_digest({"source": source, "query": query}),
        "result_scope": scope, "attribution": (attribution or SOURCES[source][0])[:200],
    }
    result["sha256"] = research_digest(result)
    return SourceRecord.model_validate(result).model_dump(mode="json")


def trial_items(rows, fields):
    """Keep registry-supplied item boundaries; missing details make no availability claim."""
    if type(rows) is not list:
        raise ValueError("invalid trial detail list")
    output = []
    for row in rows:
        if type(row) is not dict:
            raise ValueError("invalid trial detail")
        parts = []
        for key, label in fields:
            value = row.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError("invalid trial detail text")
            if value.strip():
                parts.append(label + ": " + value)
        if parts:
            output.append("; ".join(parts))
    return " | ".join(output)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate source key")
        result[key] = value
    return result


def xml_document(raw, *, pubmed=False):
    """Only UTF-8 source XML; no entity or internal-DTD expansion in any encoding."""
    value = raw.decode("utf-8-sig")
    declaration = ""
    if value.startswith("<?xml"):
        end = value.find("?>", 0, 512)
        if end < 0:
            raise ValueError("invalid XML declaration")
        declaration = value[:end]
    encoding = re.search(r'encoding\s*=\s*[\'"]([^\'"]+)', declaration, re.I)
    if "\x00" in value or encoding and encoding[1].lower() not in {"utf-8", "utf8", "us-ascii"}:
        raise ValueError("unsupported XML encoding")
    if "<!ENTITY" in value.upper():
        raise ValueError("XML entity declaration refused")
    if "<!DOCTYPE" in value.upper():
        if not pubmed:
            raise ValueError("XML DTD refused")
        # NCBI's external public DTD is descriptive only and is removed before parsing.
        value, count = re.subn(r'<!DOCTYPE\s+PubmedArticleSet\s+(?:SYSTEM\s+[\'"][^\'"\[<>]+[\'"]|PUBLIC\s+[\'"][^\'"\[<>]+[\'"]\s+[\'"][^\'"\[<>]+[\'"])\s*>', "", value)
        if count != 1 or "<!DOCTYPE" in value.upper():
            raise ValueError("XML internal DTD refused")
    tree = ElementTree.fromstring(value)
    # Fixed nesting also bounds repeated itertext() traversal of nested SPL
    # sections; a small body must not hide an arbitrarily deep parse tree.
    stack = [iter((tree,))]
    while stack:
        try:
            node = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        if len(node):
            if len(stack) >= 64:
                raise ValueError("source XML nesting limit")
            stack.append(iter(node))
    return tree


@dataclass(frozen=True)
class DatasetMapping:
    dataset_id: str
    query_field: str
    id_field: str
    title_field: str
    text_fields: tuple[str, ...]
    expected_columns: tuple[str, ...]
    version: str
    released_at: str
    distribution_index: int = 0
    metadata_sha256: str = ""
    response_schema_sha256: str = ""

    @classmethod
    def parse(cls, source, raw):
        required = {"dataset_id", "query_field", "id_field", "title_field", "text_fields", "expected_columns", "version", "released_at"}
        if type(raw) is not dict or not required <= raw.keys() or raw.keys() - required - {"distribution_index", "metadata_sha256", "response_schema_sha256"}:
            raise ValueError("closed dataset mapping required")
        for key in ("query_field", "id_field", "title_field"):
            if not isinstance(raw[key], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_ ]{0,100}", raw[key]):
                raise ValueError("invalid dataset field")
        for key in ("text_fields", "expected_columns"):
            if type(raw[key]) is not list or not 1 <= len(raw[key]) <= 100 or any(not isinstance(v, str) or len(v) > 100 for v in raw[key]):
                raise ValueError("invalid dataset columns")
        if len(raw["text_fields"]) > 8 or not {raw["query_field"], raw["id_field"], raw["title_field"], *raw["text_fields"]} <= set(raw["expected_columns"]):
            raise ValueError("mapping columns absent")
        if any(not isinstance(raw[key], str) or not 1 <= len(raw[key]) <= 100 for key in ("version", "released_at")):
            raise ValueError("dataset version required")
        if source == "cms_open_data":
            if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", raw["dataset_id"]):
                raise ValueError("CMS dataset UUID required")
        elif (not re.fullmatch(r"[a-z0-9]{4}-[a-z0-9]{4}", raw["dataset_id"])
              or type(raw.get("distribution_index")) is not int or not 0 <= raw["distribution_index"] <= 100
              or not re.fullmatch(r"[0-9a-f]{64}", raw.get("metadata_sha256", ""))
              or not re.fullmatch(r"[0-9a-f]{64}", raw.get("response_schema_sha256", ""))):
            raise ValueError("Care Compare dataset and pinned distribution required")
        return cls(**{**raw, "text_fields": tuple(raw["text_fields"]), "expected_columns": tuple(raw["expected_columns"])})


class PublicResearch:
    """Owned synchronous client; the API worker retains capacity through close."""
    def __init__(self, settings, *, transport=None, budget=None):
        self.settings = settings.model_copy(deep=True)
        self.transport = transport
        self.budget = budget or current_budget() or CaptureBudget(30)
        self.remaining_bytes = MAX_BODY
        self.mappings = self._mappings(self.settings)

    @staticmethod
    def selection(settings):
        # In-memory equality only: never persist or emit this credential-bearing
        # selection. Any mapping, configured source or credential change fences I/O.
        return (settings.research_sources, settings.research_dataset_mappings,
                settings.research_openfda_api_key)

    @staticmethod
    def _mappings(settings):
        raw = json.loads(settings.research_dataset_mappings, object_pairs_hook=_unique)
        if type(raw) is not dict or not raw.keys() <= {"cms_open_data", "medicare_care_compare"}:
            raise ValueError("invalid research dataset mappings")
        return {source: DatasetMapping.parse(source, value) for source, value in raw.items()}

    @classmethod
    def configured(cls, settings):
        values = set(settings.research_configured_sources)
        if not settings.research_openfda_api_key or not settings.research_openfda_api_key.get_secret_value():
            values.discard("openfda")
        mappings = cls._mappings(settings)
        for source in ("cms_open_data", "medicare_care_compare"):
            if source not in mappings:
                values.discard(source)
        return frozenset(values)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        # Each request owns and closes its AsyncClient inside the same worker loop.
        pass

    def _read(self, origin, path, params, check, *, headers=None):
        allowed = {
            "https://eutils.ncbi.nlm.nih.gov", "https://clinicaltrials.gov", "https://dailymed.nlm.nih.gov",
            "https://rxnav.nlm.nih.gov", "https://api.fda.gov", "https://api.coverage.cms.gov",
            "https://data.cms.gov", "https://npiregistry.cms.hhs.gov",
        }
        if origin not in allowed or not path.startswith("/") or ".." in path or "?" in path or "#" in path:
            raise ResearchUnavailable("invalid_source_response")
        if self.remaining_bytes <= 0:
            raise ResearchUnavailable("invalid_source_response")
        remaining = min(check(), self.budget.check())
        expires = time.monotonic() + min(REQUEST_SECONDS, remaining)
        # Conservative process-wide pacing. Fleet/IP-wide quotas remain a service acceptance item.
        with _RATE_LOCK:
            now = time.monotonic()
            slot = max(now, _NEXT_READ.get(origin, now))
            if slot + 0.1 >= expires:
                raise ResearchUnavailable("source_rate_limited")
            _NEXT_READ[origin] = slot + 0.5
        async def read():
            raw = bytearray()
            try:
                async with asyncio.timeout(max(0.001, expires - time.monotonic())):
                    if slot > time.monotonic():
                        await asyncio.sleep(slot - time.monotonic())
                    self.budget.check()
                    async with httpx.AsyncClient(transport=self.transport, follow_redirects=False, trust_env=False,
                        timeout=max(0.001, expires - time.monotonic()),
                        limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
                        headers={"User-Agent": "CosmasOS-Research/1.0", "Accept-Encoding": "identity"}) as client:
                        async with client.stream("GET", origin + path, params=params, headers=headers) as response:
                            if response.status_code == 429:
                                raise ResearchUnavailable("source_rate_limited")
                            if response.status_code == 404:
                                raise ResearchUnavailable("no_matching_record")
                            if response.status_code != 200 or response.headers.get("content-encoding", "identity") not in {"", "identity"}:
                                raise ResearchUnavailable()
                            length = response.headers.get("content-length")
                            if length is not None and (not re.fullmatch(r"[0-9]{1,7}", length) or int(length) > self.remaining_bytes):
                                raise ResearchUnavailable("invalid_source_response")
                            async for chunk in response.aiter_bytes(65536):
                                self.budget.check()
                                self.remaining_bytes -= len(chunk)
                                if self.remaining_bytes < 0:
                                    raise ResearchUnavailable("invalid_source_response")
                                raw.extend(chunk)
                            if length is not None and len(raw) != int(length):
                                raise ResearchUnavailable("invalid_source_response")
                    self.budget.check()
            except (httpx.TimeoutException, TimeoutError):
                raise ResearchUnavailable("source_timeout") from None
            except httpx.HTTPError:
                raise ResearchUnavailable() from None
            return bytes(raw), hashlib.sha256(raw).hexdigest()

        result = self.budget.run(read)
        check()
        return result

    def _json(self, origin, path, params, check, *, headers=None):
        raw, digest = self._read(origin, path, params, check, headers=headers)
        try:
            return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError())), digest
        except (ValueError, UnicodeError):
            raise ResearchUnavailable("invalid_source_response") from None

    def lookup(self, source, query, *, check):
        if source not in self.configured(self.settings):
            raise ResearchUnavailable("source_not_configured")
        try:
            rows = getattr(self, "_" + source)(query, check)
            if len({row["id"] for row in rows}) != len(rows):
                raise ValueError("duplicate source identity")
            return rows
        except ResearchUnavailable:
            raise
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError, ElementTree.ParseError):
            raise ResearchUnavailable("invalid_source_response") from None

    def _pubmed(self, query, check):
        value, _ = self._json("https://eutils.ncbi.nlm.nih.gov", "/entrez/eutils/esearch.fcgi",
                             {"db": "pubmed", "term": query, "retmode": "json", "retmax": 5}, check)
        search = value["esearchresult"]
        ids = search["idlist"]
        total = count(search["count"], decimal_string=True)
        if not isinstance(ids, list) or len(ids) > 5 or any(not isinstance(v, str) or not re.fullmatch(r"[0-9]{1,12}", v) for v in ids):
            raise ValueError()
        if total < len(ids) or len(set(ids)) != len(ids) or total and not ids:
            raise ValueError("inconsistent PubMed search")
        if not ids:
            return []
        raw, digest = self._read("https://eutils.ncbi.nlm.nih.gov", "/entrez/eutils/efetch.fcgi",
                                {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}, check)
        tree = xml_document(raw, pubmed=True)
        rows = tree.findall("PubmedArticle")
        if tree.tag != "PubmedArticleSet" or len(rows) > 5:
            raise ValueError()
        output, seen = [], set()
        for row in rows:
            citation = row.find("MedlineCitation")
            if citation is None:
                raise ValueError()
            identity = citation.findtext("PMID")
            if identity is None or identity not in ids or identity in seen:
                raise ValueError()
            seen.add(identity)
            article = citation.find("Article")
            if article is None:
                raise ValueError()
            title_node = article.find("ArticleTitle")
            if title_node is None:
                raise ValueError()
            title = "".join(title_node.itertext())
            abstract = "\n".join("".join(n.itertext()) for n in article.findall("Abstract/AbstractText"))
            date = article.find("Journal/JournalIssue/PubDate")
            published = " ".join(date.itertext()) if date is not None else ""
            output.append(record("pubmed", query, digest, identity=identity, title=title,
                url="https://pubmed.ncbi.nlm.nih.gov/" + identity + "/", excerpt=abstract,
                fields=[("Journal", article.findtext("Journal/Title")), ("Published", published)],
                # The retained response hash covers this XML, not the search
                # response; it cannot prove search-result completeness.
                scope="unknown",
                attribution="PubMed / U.S. National Library of Medicine; abstract rights may belong to the publisher."))
        if seen != set(ids):
            raise ValueError("PubMed returned identity coverage mismatch")
        return output

    def _clinical_trials(self, query, check):
        value, digest = self._json("https://clinicaltrials.gov", "/api/v2/studies",
                                   {"query.term": query, "pageSize": 5, "format": "json", "countTotal": "true"}, check)
        rows = value["studies"]
        if type(rows) is not list or len(rows) > 5:
            raise ValueError()
        scope = result_scope(value.get("totalCount"), rows, more=bool(value.get("nextPageToken")))
        output = []
        for row in rows:
            protocol = row["protocolSection"]
            identity = protocol["identificationModule"]["nctId"]
            if not re.fullmatch(r"NCT\d{8}", identity):
                raise ValueError()
            status = protocol["statusModule"]
            eligibility = protocol.get("eligibilityModule", {})
            phases = protocol.get("designModule", {}).get("phases", [])
            if type(phases) is not list or any(not isinstance(phase, str) for phase in phases):
                raise ValueError("invalid trial phases")
            interventions = trial_items(protocol.get("armsInterventionsModule", {}).get("interventions", []),
                                        (("type", "Type"), ("name", "Name")))
            locations = trial_items(protocol.get("contactsLocationsModule", {}).get("locations", []),
                                    (("facility", "Facility"), ("city", "City"), ("state", "State"),
                                     ("country", "Country"), ("status", "Site status")))
            output.append(record("clinical_trials", query, digest, identity=identity,
                title=protocol["identificationModule"]["briefTitle"], url="https://clinicaltrials.gov/study/" + identity,
                excerpt=eligibility.get("eligibilityCriteria", ""),
                updated=status.get("lastUpdatePostDateStruct", {}).get("date"),
                fields=[("Recruitment status", status.get("overallStatus")), ("Phase", "; ".join(phases)),
                        ("Interventions", interventions), ("Locations", locations),
                        ("Minimum age", eligibility.get("minimumAge")),
                        ("Maximum age", eligibility.get("maximumAge")), ("Sex", eligibility.get("sex")),
                        ("Study summary", protocol.get("descriptionModule", {}).get("briefSummary"))],
                scope=scope))
        return output

    def _dailymed(self, query, check):
        value, _ = self._json("https://dailymed.nlm.nih.gov", "/dailymed/services/v2/spls.json",
                              {"drug_name": query, "pagesize": 2, "page": 1}, check)
        if type(value["data"]) is not list or len(value["data"]) > 2:
            raise ValueError()
        if len({row["setid"] for row in value["data"]}) != len(value["data"]):
            raise ValueError("duplicate label identity")
        output = []
        for row in value["data"]:
            identity = row["setid"]
            if not re.fullmatch(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", identity):
                raise ValueError()
            raw, digest = self._read("https://dailymed.nlm.nih.gov", "/dailymed/services/v2/spls/" + identity + ".xml", {}, check)
            tree = xml_document(raw)
            ns = {"s": "urn:hl7-org:v3"}
            set_id, version_node = tree.find("s:setId", ns), tree.find("s:versionNumber", ns)
            label_title, effective = tree.find("s:title", ns), tree.find("s:effectiveTime", ns)
            if tree.tag != "{urn:hl7-org:v3}document" or set_id is None or set_id.get("root", "").lower() != identity.lower():
                raise ValueError()
            if version_node is None or not re.fullmatch(r"\d{1,12}", version_node.get("value", "")):
                raise ValueError()
            if label_title is None:
                raise ValueError("label title missing")
            version = version_node.get("value")
            if row.get("spl_version") is not None and str(row["spl_version"]) != version:
                raise ValueError("label changed between search and retrieval")
            sections = []
            for section in tree.findall(".//s:section", ns):
                title_node, body_node = section.find("s:title", ns), section.find("s:text", ns)
                if title_node is None or body_node is None:
                    continue
                heading = plain("".join(title_node.itertext()))
                if any(word in heading.upper() for word in ("WARNING", "CONTRAINDICATION", "DRUG INTERACTION")):
                    sections.append((heading, " ".join(body_node.itertext())))
            sections.sort(key=lambda item: "BOXED" not in item[0].upper())
            excerpt = "\n\n".join(heading + ": " + body for heading, body in sections)
            output.append(record("dailymed", query, digest, identity=identity, title="".join(label_title.itertext()),
                url="https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?" + urlencode({"setid": identity}),
                excerpt=excerpt or "No warning section was identified in this response. Open the full label; this is not evidence of safety.",
                version=version, updated=effective.get("value") if effective is not None else None,
                fields=sections,
                scope="unknown",
                attribution="DailyMed / U.S. National Library of Medicine; labeling is submitted to FDA."))
        return output

    def _rxnorm(self, query, check):
        value, digest = self._json("https://rxnav.nlm.nih.gov", "/REST/drugs.json", {"name": query}, check)
        concepts = [item for group in value["drugGroup"].get("conceptGroup", []) for item in group.get("conceptProperties", [])]
        result = []
        for row in concepts[:5]:
            identity = row["rxcui"]
            if not re.fullmatch(r"\d{1,12}", identity):
                raise ValueError()
            result.append(record("rxnorm", query, digest, identity=identity, title=row["name"],
                url="https://mor.nlm.nih.gov/RxNav/search?" + urlencode({"searchBy": "RXCUI", "searchTerm": identity}),
                excerpt=row["name"], fields=[("RxCUI", identity), ("Term type", row.get("tty")), ("Synonym", row.get("synonym"))],
                scope="limited" if len(concepts) > 5 else "complete", attribution="RxNorm / U.S. National Library of Medicine. No drug-interaction service."))
        return result

    def _openfda(self, query, check):
        # A literal phrase only; the public input cannot add arbitrary query fields.
        phrase = query.replace("\\", "\\\\").replace('"', '\\"')
        params = {"search": 'openfda.generic_name:"' + phrase + '"', "limit": 5}
        key = self.settings.research_openfda_api_key.get_secret_value()
        value, digest = self._json("https://api.fda.gov", "/drug/label.json", params, check,
                                   headers={"Authorization": "Basic " + __import__("base64").b64encode((key + ":").encode()).decode()})
        rows = value["results"]
        if type(rows) is not list or len(rows) > 5:
            raise ValueError()
        scope = result_scope(value.get("meta", {}).get("results", {}).get("total"), rows)
        result = []
        for row in rows:
            identity = row["id"]
            if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", identity):
                raise ValueError()
            warnings = row.get("boxed_warning") or row.get("warnings_and_cautions") or row.get("warnings")
            title = text(row.get("openfda", {}).get("brand_name") or row.get("openfda", {}).get("generic_name")) or "FDA drug label " + identity
            result.append(record("openfda", query, digest, identity=identity, title=title,
                url="https://api.fda.gov/drug/label.json?" + urlencode({"search": 'id:"' + identity + '"'}),
                excerpt=warnings or "No warning text was supplied in this result. This is not evidence of safety.",
                version=row.get("version"), updated=row.get("effective_time"),
                fields=[("Contraindications", row.get("contraindications")), ("Drug interactions", row.get("drug_interactions")),
                        ("Indications", row.get("indications_and_usage"))],
                scope=scope,
                attribution="openFDA / U.S. Food and Drug Administration. Confirm against the current product label."))
        return result

    def _cms_coverage(self, query, check):
        match = re.fullmatch(r"(?:NCD\s*)?(\d{1,8})(?::(\d{1,8}))?", query, re.I)
        if not match:
            raise ResearchUnavailable("invalid_source_response")
        params = {"ncdid": match[1]}
        if match[2]:
            params["ncdver"] = match[2]
        value, digest = self._json("https://api.coverage.cms.gov", "/v1/data/ncd/", params, check)
        rows = value["data"]
        # Do not acquire a license token or silently enter a licensed endpoint.
        if value.get("meta", {}).get("status", {}).get("id") != 200 or not isinstance(rows, list) or not rows or len(rows) > 5:
            raise ValueError()
        result = []
        for row in rows:
            identity, version = str(row["document_id"]), row["document_version"]
            if identity != match[1] or type(version) is not int or version < 1 or match[2] and str(version) != match[2]:
                raise ValueError()
            result.append(record("cms_coverage", query, digest, identity=identity, title=row["title"],
                url="https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?" + urlencode({"ncdid": identity, "ncdver": version}),
                excerpt=row.get("indications_limitations") or row.get("item_service_description", ""), version=version,
                fields=[("Effective date", row.get("effective_date")), ("Effective end date", row.get("effective_end_date")),
                        ("Implementation date", row.get("implementation_date")), ("Revision history", row.get("revision_history"))],
                scope="limited" if value.get("meta", {}).get("next_token") or value.get("meta", {}).get("children") else "unknown",
                attribution=plain(row.get("ama_statement")) or "CMS Medicare Coverage Database. Medicare policy does not establish individual benefits."))
        return result

    def _dataset(self, source, query, check):
        mapping = self.mappings[source]
        if source == "cms_open_data":
            path = "/data-api/v1/dataset/" + mapping.dataset_id + "/data"
            params = {"filter[" + mapping.query_field + "]": query, "size": 5, "offset": 0}
            value, digest = self._json("https://data.cms.gov", path, params, check)
            rows, scope = value, "unknown"
        else:
            _, metadata_hash = self._read("https://data.cms.gov", "/provider-data/api/1/metastore/schemas/dataset/items/" + mapping.dataset_id, {}, check)
            if metadata_hash != mapping.metadata_sha256:
                raise ResearchUnavailable("invalid_source_response")
            path = "/provider-data/api/1/datastore/query/" + mapping.dataset_id + "/" + str(mapping.distribution_index)
            params = {"conditions[0][property]": mapping.query_field, "conditions[0][value]": query,
                      "conditions[0][operator]": "=", "limit": 5, "offset": 0, "count": "true",
                      "results": "true", "schema": "true", "keys": "true", "format": "json"}
            value, digest = self._json("https://data.cms.gov", path, params, check)
            if research_digest(value.get("schema")) != mapping.response_schema_sha256:
                raise ValueError("dataset response schema changed")
            echoed = value.get("query", {})
            if (echoed.get("conditions") != [{"property": mapping.query_field, "value": query, "operator": "="}]
                    or type(echoed.get("offset")) is not int or echoed["offset"] != 0
                    or type(echoed.get("limit")) is not int or echoed["limit"] != 5):
                raise ValueError("dataset query echo mismatch")
            rows = value["results"]
            scope = result_scope(value.get("count"), rows)
        if type(rows) is not list or len(rows) > 5:
            raise ValueError()
        result = []
        for row in rows:
            if type(row) is not dict or set(row) != set(mapping.expected_columns) or text(row[mapping.query_field]) != query:
                raise ValueError()
            result.append(record(source, query, digest, identity=text(row[mapping.id_field]), title=row[mapping.title_field],
                url="https://data.cms.gov" + path + "?" + urlencode(params),
                excerpt="\n".join(field + ": " + text(row[field]) for field in mapping.text_fields),
                # Operator mapping values are not publisher metadata in the
                # hashed data response, so source version/date remain unknown.
                fields=[("Dataset", mapping.dataset_id)],
                scope=scope, attribution=SOURCES[source][0] + " / Centers for Medicare & Medicaid Services"))
        return result

    def _cms_open_data(self, query, check):
        return self._dataset("cms_open_data", query, check)

    def _medicare_care_compare(self, query, check):
        return self._dataset("medicare_care_compare", query, check)

    def _npi_registry(self, query, check):
        if not re.fullmatch(r"[0-9]{10}", query):
            raise ResearchUnavailable("invalid_source_response")
        value, digest = self._json("https://npiregistry.cms.hhs.gov", "/api/", {"version": "2.1", "number": query, "limit": 5}, check)
        total = count(value["result_count"])
        rows = value.get("results", [])
        if value.get("Errors") or type(rows) is not list or total != len(rows) or total > 1:
            raise ValueError()
        result = []
        for row in rows:
            # NPPES v2.1 returns this identifier as a decimal string. Retain
            # compatibility with numeric responses without coercing other types.
            if type(row["number"]) not in (str, int) or str(row["number"]) != query:
                raise ValueError()
            basic = row["basic"]
            if type(basic) is not dict or any(not isinstance(basic[key], str) for key in
                    ("organization_name", "first_name", "middle_name", "last_name", "status", "last_updated", "enumeration_date") if key in basic):
                raise ValueError()
            taxonomies = row.get("taxonomies", [])
            if type(taxonomies) is not list or any(type(item) is not dict or not isinstance(item.get("desc", ""), str) for item in taxonomies):
                raise ValueError()
            title = basic.get("organization_name") or " ".join(basic.get(k, "") for k in ("first_name", "middle_name", "last_name"))
            result.append(record("npi_registry", query, digest, identity=query, title=title,
                url="https://npiregistry.cms.hhs.gov/provider-view/" + query, excerpt=title,
                updated=basic.get("last_updated"), fields=[("NPI", query), ("Status", basic.get("status")),
                    ("Taxonomies", [t.get("desc", "") for t in taxonomies]), ("Enumeration date", basic.get("enumeration_date"))],
                scope="complete", attribution="NPPES / CMS. An NPI does not establish licensure or credentialing."))
        return result
