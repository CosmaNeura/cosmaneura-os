"""Exact, per-request consent for already-saved public Research evidence."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

CanonicalUUID = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")]


class ResearchEvidenceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entry_id: CanonicalUUID
    entry_revision: int = Field(ge=1, le=500)
    run_id: CanonicalUUID
    save_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResearchAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    consented: Literal[True]
    entries: list[ResearchEvidenceAnchor] = Field(min_length=1, max_length=3)

    @model_validator(mode="before")
    @classmethod
    def exact_consent(cls, value):
        if not isinstance(value, dict) or type(value.get("version")) is not int or value.get("consented") is not True:
            raise ValueError("explicit analysis consent required")
        return value

    @model_validator(mode="after")
    def distinct_entries(self):
        if len({entry.entry_id for entry in self.entries}) != len(self.entries):
            raise ValueError("distinct saved evidence entries required")
        return self


class ResearchAnalysisFields(BaseModel):
    research_analysis: ResearchAnalysis | None = None

    @model_validator(mode="before")
    @classmethod
    def no_null_selection(cls, value):
        if isinstance(value, dict) and "research_analysis" in value and value["research_analysis"] is None:
            raise ValueError("analysis selection must be absent or explicit")
        return value

    @model_serializer(mode="wrap")
    def preserve_legacy_request(self, handler):
        value = handler(self)
        if self.research_analysis is None:
            value.pop("research_analysis", None)
        return value
