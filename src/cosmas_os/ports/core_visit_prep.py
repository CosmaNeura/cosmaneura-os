"""Visit Prep v1.0.1 wire types; no Core server import or clinical persistence."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from cosmas_os.ports.core_encounters import ActorRef, Closed, Digest, TenantRef, TypeSuffix

PrepRef = Annotated[str, Field(pattern=r"^visit_prep" + TypeSuffix, strict=True)]
Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$", strict=True)]
Words = Annotated[str, Field(min_length=1, max_length=2000, strict=True)]
ResponseKind = Literal["answered", "skipped"] | None
SourceRef = Annotated[
    str, Field(pattern=r"^visit_prep_(response|contribution)" + TypeSuffix, strict=True)
]
ReviewRef = Annotated[str, Field(pattern=r"^visit_prep_contribution" + TypeSuffix, strict=True)]
Positive = Annotated[int, Field(ge=1, strict=True)]


class CoreVisitPrepRead(Closed):
    contract_version: Literal["1"] = "1"
    action: Literal["visit-prep.open"] = "visit-prep.open"
    purpose: Literal["provider_previsit_review"] = "provider_previsit_review"
    preparation_ref: PrepRef
    expected_actor_ref: ActorRef
    expected_tenant_ref: TenantRef
    connection_sha256: Digest
    workspace_id: UUID
    request_nonce: UUID


class CoreVisitPrepList(Closed):
    contract_version: Literal["1"] = "1"
    action: Literal["visit-prep.list"] = "visit-prep.list"
    purpose: Literal["provider_previsit_review"] = "provider_previsit_review"
    expected_actor_ref: ActorRef
    expected_tenant_ref: TenantRef
    connection_sha256: Digest
    workspace_id: UUID
    request_nonce: UUID
    before_ref: PrepRef | None
    limit: Annotated[int, Field(ge=1, le=20, strict=True)]


class PreparationSelection(Closed):
    preparation_ref: PrepRef
    recipient_first_name: Annotated[str, Field(min_length=1, max_length=120, strict=True)] = Field(
        repr=False
    )
    recipient_role: Literal["patient", "caregiver"]
    scheduled_at: AwareDatetime
    timezone_name: Annotated[str, Field(min_length=1, max_length=64, strict=True)]
    lifecycle_state: Literal["invited", "confirmed", "in_progress", "completed", "misdirected"]
    chart_linked: Annotated[bool, Field(strict=True)]
    available_to_open: Annotated[bool, Field(strict=True)]
    created_at: AwareDatetime | None


class CoreVisitPrepSelections(Closed):
    contract_version: Literal["1"]
    connection_sha256: Digest
    workspace_id: UUID
    request_nonce: UUID
    checked_at: AwareDatetime
    preparations: Annotated[tuple[PreparationSelection, ...], Field(max_length=20)] = Field(
        repr=False
    )
    next_before_ref: PrepRef | None

    @model_validator(mode="after")
    def unique_selections(self):
        refs = [p.preparation_ref for p in self.preparations]
        if (
            len(set(refs)) != len(refs)
            or self.next_before_ref is not None
            and (not refs or self.next_before_ref != refs[-1])
        ):
            raise ValueError("invalid_visit_prep_selections")
        return self


class Choice(Closed):
    value: Key
    label: Annotated[str, Field(min_length=1, max_length=120, strict=True)]


class Topic(Closed):
    question_key: Key
    position: Annotated[int, Field(ge=1, le=5, strict=True)]
    prompt: Annotated[str, Field(min_length=1, max_length=1000, strict=True)]
    kind: Literal["story", "list", "choice"]
    choices: Annotated[tuple[Choice, ...], Field(max_length=8)]
    response_kind: ResponseKind
    answer: Words | None
    initial_response_kind: ResponseKind
    initial_answer: Words | None
    changed: Annotated[bool, Field(strict=True)]
    original_response_id: Annotated[str, Field(pattern=r"^visit_prep_response" + TypeSuffix)] | None
    additional_answer_source_id: ReviewRef | None
    current_revision_id: ReviewRef | None
    recorded_at: AwareDatetime | None
    initial_recorded_at: AwareDatetime | None
    explanation_words: Words | None
    explanation_source_id: ReviewRef | None
    explanation_recorded_at: AwareDatetime | None


class Preparation(Closed):
    id: PrepRef
    question_set_version_id: Annotated[
        str, Field(pattern=r"^visit_prep_question_set_version" + TypeSuffix)
    ]
    patient_id: Annotated[str, Field(pattern=r"^patient" + TypeSuffix)] | None
    appointment_id: Annotated[str, Field(pattern=r"^appointment" + TypeSuffix)] | None
    lifecycle_state: Literal["confirmed", "in_progress", "completed"]
    has_email_contact: Annotated[bool, Field(strict=True)]
    has_sms_contact: Annotated[bool, Field(strict=True)]
    physician_display_name: Annotated[str, Field(min_length=1, max_length=160, strict=True)]
    practice_display_name: Annotated[str, Field(min_length=1, max_length=200, strict=True)]
    scheduled_at: AwareDatetime
    timezone_name: Annotated[str, Field(min_length=1, max_length=64, strict=True)]
    schedule_generation: Positive
    credential_generation: Positive
    credential_expires_at: AwareDatetime
    credential_active: Annotated[bool, Field(strict=True)]
    revoked_at: AwareDatetime | None
    created_at: AwareDatetime | None
    updated_at: AwareDatetime | None


class Basis(Closed):
    original_response_count: Annotated[int, Field(ge=0, le=5, strict=True)]
    event_sequence: Annotated[int, Field(ge=0, strict=True)]


class Sources(Closed):
    contract: Literal["visit_prep.patient_sources.v1"]
    package_id: PrepRef
    source_version: Digest
    preparation: Preparation
    basis: Basis
    actor_role: Literal["patient", "caregiver"]
    original_interview_completed: Annotated[bool, Field(strict=True)]
    current_answers_complete: Annotated[bool, Field(strict=True)]
    current_answers_reviewed: Annotated[bool, Field(strict=True)]
    current_review_id: ReviewRef | None
    reviewed_at: AwareDatetime | None
    missing_question_keys: Annotated[tuple[Key, ...], Field(max_length=5)]
    skipped_question_keys: Annotated[tuple[Key, ...], Field(max_length=5)]
    topics: Annotated[tuple[Topic, ...], Field(min_length=1, max_length=5)]


class Evidence(Closed):
    source_ref: SourceRef
    quote: Annotated[str, Field(min_length=1, max_length=300, strict=True)]


class BriefItem(Closed):
    text: Annotated[str, Field(min_length=1, max_length=700, strict=True)]
    evidence: Annotated[tuple[Evidence, ...], Field(min_length=1, max_length=5)]


class Brief(Closed):
    headline: BriefItem | None
    summary: Annotated[tuple[BriefItem, ...], Field(max_length=5)]
    visit_priorities: Annotated[tuple[BriefItem, ...], Field(max_length=3)]
    medication_and_adherence: Annotated[tuple[BriefItem, ...], Field(max_length=3)]
    barriers: Annotated[tuple[BriefItem, ...], Field(max_length=2)]
    uncertainties: Annotated[tuple[BriefItem, ...], Field(max_length=3)]


class Package(Closed):
    contract: Literal["visit_prep.patient_synthesis.v1"]
    sources: Sources = Field(repr=False)
    status: Literal["missing", "stale", "ready"]
    build_status: Literal["not_requested", "pending", "running", "failed", "ready"]
    retry_at: AwareDatetime | None
    artifact_id: Annotated[str, Field(pattern=r"^visit_prep_brief" + TypeSuffix)] | None
    version: Positive | None
    recorded_at: AwareDatetime | None
    generator_version: Key
    prompt_version: Key
    model_profile: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
    brief: Brief | None = Field(repr=False)

    @model_validator(mode="after")
    def current_lineage(self):
        ready = self.status == "ready"
        if (
            ready != (self.build_status == "ready")
            or any(
                ready != (value is not None)
                for value in (self.artifact_id, self.version, self.recorded_at, self.brief)
            )
            or ready
            and self.retry_at is not None
        ):
            raise ValueError("invalid_visit_prep_lineage")
        sources = self.sources
        if sources.package_id != sources.preparation.id:
            raise ValueError("invalid_visit_prep_scope")
        keys = [topic.question_key for topic in sources.topics]
        positions = [topic.position for topic in sources.topics]
        missing = [topic.question_key for topic in sources.topics if topic.response_kind is None]
        skipped = [
            topic.question_key for topic in sources.topics if topic.response_kind == "skipped"
        ]
        if (
            len(set(keys)) != len(keys)
            or positions != sorted(set(positions))
            or (
                tuple(missing) != sources.missing_question_keys
                or tuple(skipped) != sources.skipped_question_keys
            )
        ):
            raise ValueError("invalid_visit_prep_topics")
        evidence = {}
        for topic in sources.topics:
            if (topic.response_kind == "answered") != (topic.answer is not None):
                raise ValueError("invalid_visit_prep_answer")
            if topic.response_kind == "answered":
                ref = (
                    topic.current_revision_id
                    or topic.additional_answer_source_id
                    or topic.original_response_id
                )
                words = topic.answer
                if topic.kind == "choice":
                    labels = [
                        choice.label for choice in topic.choices if choice.value == topic.answer
                    ]
                    if len(labels) != 1:
                        raise ValueError("invalid_visit_prep_choice")
                    words = labels[0]
                if ref is None or words is None:
                    raise ValueError("invalid_visit_prep_source")
                evidence[ref] = words
            if topic.explanation_source_id and topic.explanation_words:
                evidence[topic.explanation_source_id] = topic.explanation_words
            if topic.explanation_words is not None and (
                topic.kind != "choice"
                or topic.response_kind != "answered"
                or topic.explanation_source_id is None
                or topic.explanation_recorded_at is None
            ):
                raise ValueError("invalid_visit_prep_explanation")
        if self.brief:
            for item in (
                *([self.brief.headline] if self.brief.headline else []),
                *self.brief.summary,
                *self.brief.visit_priorities,
                *self.brief.medication_and_adherence,
                *self.brief.barriers,
                *self.brief.uncertainties,
            ):
                if any(
                    e.source_ref not in evidence or e.quote not in evidence[e.source_ref]
                    for e in item.evidence
                ):
                    raise ValueError("invalid_visit_prep_citation")
        return self


class CoreVisitPrepReceipt(Closed):
    contract_version: Literal["1"]
    preparation_ref: PrepRef
    connection_sha256: Digest
    workspace_id: UUID
    request_nonce: UUID
    checked_at: AwareDatetime
    package: Package = Field(repr=False)

    @model_validator(mode="after")
    def matching_package(self):
        if self.preparation_ref != self.package.sources.package_id:
            raise ValueError("invalid_visit_prep_scope")
        return self
