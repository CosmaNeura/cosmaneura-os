"""Core's Session Prep 1.0.0 brief receipt, distinct from raw prior-note context.

The caller must already hold a current provider interaction and its accepted
``session-prep.open`` UI-action turn. These types confer no source authority.
"""

from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import AwareDatetime, Field, model_validator

from cosmas_os.ports.core_capture import CoreInteractionCredential
from cosmas_os.ports.scribe_capture import ProtectedModel

Reference = Annotated[str, Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9._~-]+$")]
Version = Annotated[int, Field(ge=1, le=2_147_483_647, strict=True)]
Lineage = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
]
SourceClass = Literal["clinician_finalized_note", "patient_reported_visit_prep"]


class CoreSessionPrepRead(ProtectedModel):
    credential: CoreInteractionCredential
    source_turn_ref: Reference
    context_snapshot_ref: Reference
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._~-]+$")


class CitedText(ProtectedModel):
    text: str = Field(min_length=1, max_length=1000)
    source_refs: tuple[Reference, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_citations(self):
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("duplicate_session_prep_citation")
        return self


class Recap(CitedText):
    text: str = Field(min_length=1, max_length=4000)


class PatientReported(ProtectedModel):
    label: Literal["Patient-reported Visit Prep"]
    summary: str = Field(min_length=1, max_length=2000)
    source_refs: tuple[Reference, ...] = Field(min_length=1, max_length=6)


class PreparedBrief(ProtectedModel):
    recap: Recap
    trajectory_and_material_changes: tuple[CitedText, ...] = Field(max_length=8)
    talking_points: tuple[CitedText, ...] = Field(min_length=1, max_length=8)
    open_threads: tuple[CitedText, ...] = Field(max_length=8)
    cautions: tuple[CitedText, ...] = Field(max_length=8)
    suggested_outline: tuple[CitedText, ...] = Field(min_length=1, max_length=8)
    patient_reported: PatientReported | None


class PrepProvenance(ProtectedModel):
    source_class: SourceClass
    included: bool = Field(strict=True)
    source_ref: Reference | None
    source_version: Version | None = None
    source_at: AwareDatetime | None
    author_class: Literal["clinician", "patient"] | None
    reason_code: Literal[
        "eligible_finalized_note",
        "eligible_patient_visit_prep",
        "no_eligible_source",
        "source_not_enabled",
        "selection_limit",
        "source_temporarily_unavailable",
    ]

    @model_validator(mode="after")
    def lineage(self):
        complete = all(
            value is not None
            for value in (self.source_ref, self.source_version, self.source_at, self.author_class)
        )
        if self.included != complete:
            raise ValueError("invalid_session_prep_provenance")
        expected = (
            ("clinician", "eligible_finalized_note")
            if self.source_class == "clinician_finalized_note"
            else ("patient", "eligible_patient_visit_prep")
        )
        if self.included and (self.author_class, self.reason_code) != expected:
            raise ValueError("invalid_session_prep_source_class")
        if not self.included and self.reason_code.startswith("eligible_"):
            raise ValueError("invalid_session_prep_exclusion")
        if (
            self.source_class == "clinician_finalized_note"
            and self.reason_code == "source_not_enabled"
        ):
            raise ValueError("invalid_session_prep_exclusion")
        return self


class CoreSessionPrepBrief(ProtectedModel):
    schema_version: Literal["1.0.0"]
    state: Literal["ready", "refreshing", "pending", "unavailable"]
    detail: Literal["brief"]
    freshness: Literal["current", "stale", "none"]
    completeness: Literal["complete", "partial", "none"]
    current_through: AwareDatetime | None
    snapshot_ref: Reference | None
    snapshot_version: Version | None = None
    snapshot_generated_at: AwareDatetime | None
    snapshot_supersedes_ref: Reference | None
    source_version_digest: Annotated[str, Field(pattern=r"^sha256_[a-f0-9]{64}$")] | None = None
    brief_ref: Reference | None
    brief_version: Version | None = None
    brief_generated_at: AwareDatetime | None
    brief_supersedes_ref: Reference | None
    brief_generator_version: Lineage | None
    brief_prompt_version: Lineage | None
    brief_model_profile: Lineage | None
    source_count: int = Field(ge=0, le=6, strict=True)
    provenance: tuple[PrepProvenance, ...] = Field(max_length=8)
    prepared_brief: PreparedBrief | None
    # The existing provider API accepts brief reads only. A larger/raw source
    # response must never silently expand what this caller requested.
    supporting_context: None = None
    retry_after_seconds: Annotated[int, Field(ge=1, le=300, strict=True)] | None = None
    reason_code: (
        Literal[
            "refresh_in_progress",
            "generation_pending",
            "no_eligible_sources",
            "context_not_available",
        ]
        | None
    )

    @model_validator(mode="after")
    def consistent_brief(self):
        lineage = (
            self.current_through,
            self.snapshot_ref,
            self.snapshot_version,
            self.snapshot_generated_at,
            self.source_version_digest,
            self.brief_ref,
            self.brief_version,
            self.brief_generated_at,
            self.brief_generator_version,
            self.brief_prompt_version,
            self.prepared_brief,
        )
        if self.state in {"pending", "unavailable"}:
            if (
                any(
                    value is not None
                    for value in (
                        *lineage,
                        self.snapshot_supersedes_ref,
                        self.brief_supersedes_ref,
                        self.brief_model_profile,
                    )
                )
                or self.source_count
                or self.provenance
                or self.freshness != "none"
                or self.completeness != "none"
            ):
                raise ValueError("content_in_empty_session_prep")
            valid = (
                (self.reason_code == "generation_pending" and self.retry_after_seconds is not None)
                if self.state == "pending"
                else (
                    self.reason_code in {"no_eligible_sources", "context_not_available"}
                    and self.retry_after_seconds is None
                )
            )
            if not valid:
                raise ValueError("invalid_session_prep_retry")
            return self

        if any(value is None for value in lineage) or self.completeness == "none":
            raise ValueError("missing_session_prep_lineage")
        expected = ("current", None) if self.state == "ready" else ("stale", "refresh_in_progress")
        if (self.freshness, self.reason_code) != expected or (self.retry_after_seconds is None) != (
            self.state == "ready"
        ):
            raise ValueError("invalid_session_prep_freshness")
        included = {source.source_ref: source for source in self.provenance if source.included}
        if (
            not included
            or len(included) != self.source_count
            or len(included) != sum(source.included for source in self.provenance)
        ):
            raise ValueError("invalid_session_prep_source_count")
        omitted = any(
            source.reason_code in {"selection_limit", "source_temporarily_unavailable"}
            for source in self.provenance
        )
        if omitted != (self.completeness == "partial"):
            raise ValueError("invalid_session_prep_completeness")
        assert self.prepared_brief is not None
        brief = self.prepared_brief
        for text in (
            brief.recap,
            *brief.trajectory_and_material_changes,
            *brief.talking_points,
            *brief.open_threads,
            *brief.cautions,
            *brief.suggested_outline,
        ):
            if not set(text.source_refs) <= included.keys():
                raise ValueError("unresolved_session_prep_citation")
        if brief.patient_reported is not None:
            refs = brief.patient_reported.source_refs
            patient_sources = {
                key
                for key, source in included.items()
                if source.source_class == "patient_reported_visit_prep"
            }
            if len(refs) != len(set(refs)) or not set(refs) <= patient_sources:
                raise ValueError("invalid_session_prep_patient_citation")
        assert (
            isinstance(self.current_through, datetime)
            and isinstance(self.snapshot_generated_at, datetime)
            and isinstance(self.brief_generated_at, datetime)
        )
        if not self.current_through <= self.snapshot_generated_at <= self.brief_generated_at or any(
            source.source_at is None or source.source_at > self.current_through
            for source in included.values()
        ):
            raise ValueError("invalid_session_prep_time_order")
        if (self.snapshot_version == 1) != (self.snapshot_supersedes_ref is None) or (
            self.brief_version == 1
        ) != (self.brief_supersedes_ref is None):
            raise ValueError("invalid_session_prep_predecessor")
        return self


class CoreSessionPrepReceipt(ProtectedModel):
    tool_call_ref: Reference
    tool_name: Literal["session-prep.context.read"]
    tool_version: Literal["1.0.0"]
    status: Literal["completed"]
    approval_ref: None
    access_intent_ref: None
    access_outcome_ref: None
    result_classification: Literal["phi_possible"]
    result: CoreSessionPrepBrief
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def artifact_precedes_receipt(self):
        if (
            self.result.brief_generated_at is not None
            and self.result.brief_generated_at > self.recorded_at
        ):
            raise ValueError("invalid_session_prep_receipt_time")
        return self


class CoreSessionPrepPort(Protocol):
    def read_brief(self, selection: CoreSessionPrepRead) -> CoreSessionPrepReceipt: ...
