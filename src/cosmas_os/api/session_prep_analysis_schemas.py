"""An explicit displayed-brief selection, never client-supplied clinical text."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from cosmas_os.api.membership_analysis_schemas import ConversationAnalysisFields as PriorFields


class SessionPrepAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    consented: Literal[True]
    brief_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    brief_version: int = Field(ge=1, le=2_147_483_647)
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="before")
    @classmethod
    def explicit_selection(cls, value):
        if (not isinstance(value, dict) or type(value.get("version")) is not int
                or value.get("consented") is not True):
            raise ValueError("Explicit Session Prep selection is required")
        return value


class ConversationAnalysisFields(PriorFields):
    session_prep_analysis: SessionPrepAnalysis | None = None

    @model_validator(mode="before")
    @classmethod
    def one_selected_analysis(cls, value):
        if isinstance(value, dict) and "session_prep_analysis" in value:
            if value["session_prep_analysis"] is None or any(
                field in value for field in ("research_analysis", "inbox_analysis", "membership_analysis")
            ):
                raise ValueError("Select exactly one analysis source")
        return value

    @model_serializer(mode="wrap")
    def preserve_absent_selection(self, handler):
        value = handler(self)
        for field in ("session_prep_analysis", "membership_analysis", "inbox_analysis", "research_analysis"):
            if getattr(self, field) is None:
                value.pop(field, None)
        return value
