"""Explicit model consent for one selected membership or payment work record."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from cosmas_os.api.inbox_analysis_schemas import ConversationAnalysisFields as PriorAnalysisFields
from cosmas_os.api.research_analysis_schemas import CanonicalUUID


class MembershipAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    consented: Literal[True]
    kind: Literal["membership", "payment"]
    ticket_id: CanonicalUUID
    ticket_version: int = Field(ge=1, le=500)
    revision_id: CanonicalUUID
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if (
            not isinstance(value, dict)
            or type(value.get("version")) is not int
            or value.get("consented") is not True
        ):
            raise ValueError("Explicit membership or payment review consent is required")
        return value


class ConversationAnalysisFields(PriorAnalysisFields):
    membership_analysis: MembershipAnalysis | None = None

    @model_validator(mode="before")
    @classmethod
    def single_selection(cls, value):
        if isinstance(value, dict) and "membership_analysis" in value:
            if value["membership_analysis"] is None or any(
                k in value for k in ("research_analysis", "inbox_analysis")
            ):
                raise ValueError("Select exactly one explicit analysis source")
        return value

    @model_serializer(mode="wrap")
    def preserve_absent_selections(self, handler):
        value = handler(self)
        for field in ("membership_analysis", "inbox_analysis", "research_analysis"):
            if getattr(self, field) is None:
                value.pop(field, None)
        return value
