"""Pinned build-time research contract, copied from the selected OS service.

Source: W63r2 os-source/src/cosmas_os; SOURCES from ports/research.py and
DatasetMapping from adapters/public_research.py. Keep both definitions identical
to that runtime; upgrade them together when selecting a new runtime contract.
No transport, credentials, data lookup or application startup is imported.
"""

from dataclasses import dataclass
import re

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
