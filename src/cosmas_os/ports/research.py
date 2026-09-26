"""Read-only public research. Public queries never inherit encounter context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, Protocol

TOPICS = {
    "literature": "Medical literature",
    "drug_safety": "Drug information",
    "trials": "Clinical trials",
    "coverage": "Coverage policies",
    "provider_data": "Providers and facilities",
}

SOURCES = {
    "pubmed": ("PubMed", ("literature",), "Published medical literature and abstracts.", "https://www.ncbi.nlm.nih.gov/books/NBK25501/"),
    "clinical_trials": ("ClinicalTrials.gov", ("trials",), "Registered trials, eligibility criteria and study updates.", "https://clinicaltrials.gov/data-api/api"),
    "dailymed": ("DailyMed", ("drug_safety",), "Current submitted drug labeling; label version and update dates matter.", "https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_api.cfm"),
    "rxnorm": ("RxNorm", ("drug_safety",), "Normalized medication names and identifiers; not a drug safety database.", "https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html"),
    "openfda": ("openFDA", ("drug_safety",), "FDA drug labeling and warnings. Missing fields do not establish safety.", "https://open.fda.gov/apis/drug/label/"),
    "cms_coverage": ("CMS Coverage", ("coverage",), "Look up an exact NCD ID, optionally ID:version. Full LCD content requires separate license access.", "https://api.coverage.cms.gov/"),
    "cms_open_data": ("CMS Open Data", ("coverage", "provider_data"), "CMS public datasets; dataset identity and release date must be retained.", "https://data.cms.gov/api-docs"),
    "medicare_care_compare": ("Medicare Care Compare", ("provider_data",), "Provider and facility public comparison datasets; not patient records.", "https://data.cms.gov/provider-data/"),
    "npi_registry": ("NPI Registry", ("provider_data",), "Look up a public provider by their 10-digit NPI; registration is not proof of current licensure.", "https://npiregistry.cms.hhs.gov/api-page"),
}


def research_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


class ResearchUnavailable(Exception):
    """A closed code, never an upstream response or a credential."""
    def __init__(self, code: str = "source_unavailable"):
        super().__init__(code)
        self.code = code


class ResearchPort(Protocol):
    def lookup(self, source: str, query: str, *, check: Callable[[], float]) -> list[dict]: ...


def catalog(*, enabled: bool, configured: frozenset[str]) -> dict:
    return {
        "contract": "research.catalog.v1",
        "enabled": enabled,
        "topics": [{"id": key, "label": label} for key, label in TOPICS.items()],
        "sources": [{"id": key, "label": value[0], "topics": list(value[1]),
                     "description": value[2], "documentation_url": value[3],
                     "state": "enabled" if enabled and key in configured else "not_configured"}
                    for key, value in SOURCES.items()],
    }
