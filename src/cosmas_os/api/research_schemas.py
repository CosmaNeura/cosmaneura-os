"""Closed v1 public-query, provenance and recovery contracts."""

from typing import Annotated, Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator

from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.ports.research import SOURCES, research_digest

SourceId = Literal["pubmed", "clinical_trials", "dailymed", "rxnorm", "openfda",
                   "cms_coverage", "cms_open_data", "medicare_care_compare", "npi_registry"]
Topic = Literal["literature", "drug_safety", "trials", "coverage", "provider_data"]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MAX_REQUEST_BYTES = 8192
MAX_RESPONSE_BYTES = 131072
MAX_HISTORY_BYTES = 1048576
DEADLINE_SECONDS = 30


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def no_literal_coercion(cls, value):
        if isinstance(value, dict):
            if "contract_version" in value and type(value["contract_version"]) is not int:
                raise ValueError("integer contract version required")
            if "public_query_confirmed" in value and value["public_query_confirmed"] is not True:
                raise ValueError("explicit boolean public query review required")
        return value


class Search(Closed):
    contract_version: Literal[1]
    idempotency_key: IdempotencyKey
    expected_revision: int = Field(ge=1)
    team_revision: int = Field(ge=1)
    bot: UUID4
    topic: Topic
    sources: list[SourceId] = Field(min_length=1, max_length=3)
    query: str = Field(min_length=1, max_length=500)
    public_query_confirmed: Literal[True]

    @model_validator(mode="after")
    def public_query(self):
        if type(self.contract_version) is not int or self.public_query_confirmed is not True:
            raise ValueError("explicit public query review required")
        if self.query.strip() != self.query or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in self.query):
            raise ValueError("plain, trimmed public query required")
        if len(set(self.sources)) != len(self.sources) or any(self.topic not in SOURCES[s][1] for s in self.sources):
            raise ValueError("distinct sources for the selected topic required")
        return self


class Resolve(Closed):
    contract_version: Literal[1]
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def strict_version(self):
        if type(self.contract_version) is not int:
            raise ValueError("invalid version")
        return self


class Save(Resolve):
    expected_revision: int = Field(ge=1)
    source_hashes: list[Hash] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.source_hashes)) != len(self.source_hashes):
            raise ValueError("distinct sources required")
        return self


class SourceField(Closed):
    label: str = Field(min_length=1, max_length=80)
    text: str = Field(max_length=1500)


class SourceRecord(Closed):
    source: SourceId
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2048)
    source_updated_at: str | None = Field(max_length=80)
    version: str | None = Field(max_length=128)
    retrieved_at: str = Field(min_length=1, max_length=80)
    excerpt: str = Field(max_length=2500)
    fields: list[SourceField] = Field(max_length=12)
    truncated: bool
    raw_response_sha256: Hash
    query_sha256: Hash
    result_scope: Literal["limited", "complete", "unknown"]
    attribution: str = Field(min_length=1, max_length=200)
    sha256: Hash

    @model_validator(mode="after")
    def bound_source(self):
        import re
        from datetime import datetime
        from urllib.parse import urlsplit
        hosts = {
            "pubmed": "pubmed.ncbi.nlm.nih.gov", "clinical_trials": "clinicaltrials.gov",
            "dailymed": "dailymed.nlm.nih.gov", "rxnorm": "mor.nlm.nih.gov",
            "openfda": "api.fda.gov", "cms_coverage": "www.cms.gov",
            "cms_open_data": "data.cms.gov", "medicare_care_compare": "data.cms.gov",
            "npi_registry": "npiregistry.cms.hhs.gov",
        }
        url = urlsplit(self.url)
        if (url.scheme != "https" or url.netloc != hosts[self.source] or url.username or url.password
                or not url.path.startswith("/") or "#" in self.url
                or any(char.isspace() or char == "\\" for char in self.url)):
            raise ValueError("source citation host mismatch")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", self.retrieved_at):
            raise ValueError("explicit ISO source retrieval time required")
        # Python normalizes an offset such as +00:60; the public contract does not.
        if not self.retrieved_at.endswith("Z"):
            offset = self.retrieved_at[-6:]
            if int(offset[1:3]) > 23 or int(offset[4:6]) > 59:
                raise ValueError("source retrieval timezone out of range")
        stamp = datetime.fromisoformat(self.retrieved_at)
        if stamp.tzinfo is None:
            raise ValueError("source retrieval timezone required")
        if any(value is not None and not value.strip() for value in (self.version, self.source_updated_at)):
            raise ValueError("empty source metadata must be null")
        strings = [self.id, self.title, self.url, self.excerpt, self.attribution,
                   self.version or "", self.source_updated_at or "", self.retrieved_at]
        strings.extend(value for field in self.fields for value in (field.label, field.text))
        if any(any((ord(char) < 32 and char not in "\t\n") or ord(char) == 127
                   or 0xD800 <= ord(char) <= 0xDFFF for char in value) for value in strings):
            raise ValueError("invalid source text")
        if research_digest(self.model_dump(mode="json", exclude={"sha256"})) != self.sha256:
            raise ValueError("source content hash mismatch")
        return self
