"""Explicit consent to draft from one already-reviewed private Inbox source."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from cosmas_os.api.research_analysis_schemas import CanonicalUUID, ResearchAnalysisFields


class InboxAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    consented: Literal[True]
    item_id: CanonicalUUID
    item_version: int = Field(ge=1, le=2147483647)
    source_id: CanonicalUUID
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_receipt_id: CanonicalUUID
    review_receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    triage_receipt_id: CanonicalUUID
    triage_receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if (
            not isinstance(value, dict)
            or type(value.get("version")) is not int
            or value.get("consented") is not True
        ):
            raise ValueError("Explicit Inbox draft consent is required")
        return value


class ConversationAnalysisFields(ResearchAnalysisFields):
    inbox_analysis: InboxAnalysis | None = None

    @model_validator(mode="before")
    @classmethod
    def one_explicit_source_selection(cls, value):
        if isinstance(value, dict) and "inbox_analysis" in value:
            if value["inbox_analysis"] is None or "research_analysis" in value:
                raise ValueError("Select exactly one explicit analysis source")
        return value

    @model_serializer(mode="wrap")
    def preserve_absent_selections(self, handler):
        value = handler(self)
        for field in ("inbox_analysis", "research_analysis"):
            if getattr(self, field) is None:
                value.pop(field, None)
        return value
