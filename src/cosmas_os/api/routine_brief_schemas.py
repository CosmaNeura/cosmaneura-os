"""Closed incoming-brief projections; no source content or command capability."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from cosmas_os.api.vendor_work_schemas import ID, Day, Digest, Output, Positive

Count = Annotated[int, Field(strict=True, ge=0, le=100)]


class Person(Output):
    id: ID
    name: Annotated[str, Field(strict=True, min_length=1, max_length=80)]
    available: bool


class IncomingItem(Output):
    ticket_id: ID
    revision_id: ID
    payload_hash: Digest
    version: Positive
    state: Literal["pending_approval", "approved", "closed", "rejected", "source_unavailable", "work_changed"]
    body: Annotated[str, Field(strict=True, min_length=1, max_length=180)] | None
    due_date: Day | None
    responsible: Person
    originator_id: ID
    requires_owner_attention: bool
    pending_offer: bool
    ready_for_review: bool
    verified_current: bool
    publication_receipt_id: ID | None
    result_receipt_id: ID | None
    verification_receipt_id: ID | None
    changed_since_report: bool

    @model_validator(mode="after")
    def semantics(self):
        if self.verified_current and (self.state != "closed" or not all((self.publication_receipt_id,
                self.result_receipt_id, self.verification_receipt_id))):
            raise ValueError("Exact verified local receipt required")
        if (self.pending_offer or self.ready_for_review) and self.state != "approved":
            raise ValueError("Only active work can await responsibility or review")
        if self.state in {"source_unavailable", "work_changed"} and any((self.body, self.due_date, self.pending_offer,
                self.ready_for_review, self.verified_current, self.publication_receipt_id,
                self.result_receipt_id, self.verification_receipt_id)):
            raise ValueError("Unavailable context and receipt claims must be withheld")
        return self


class IncomingCounts(Output):
    pending_approval: Count
    open: Count
    overdue: Count
    awaiting_acceptance: Count
    responsible_unavailable: Count
    awaiting_review: Count
    verified_complete: Count
    source_unavailable: Count
    work_changed: Count


class IncomingSection(Output):
    coverage: Literal["complete", "partial", "unavailable", "not_included"]
    reason: Literal["source_unavailable", "work_changed", "collection_limit", "legacy_report"] | None
    items: list[IncomingItem] = Field(max_length=100)
    matching_items: Count
    counts: IncomingCounts | None
    withheld_sources: bool

    @model_validator(mode="after")
    def semantics(self):
        if len({v.ticket_id for v in self.items}) != len(self.items) or len(self.items) > self.matching_items:
            raise ValueError("Distinct bounded work identities required")
        if self.coverage in {"unavailable", "not_included"}:
            if self.items or self.matching_items or self.counts is not None or self.reason is None:
                raise ValueError("Unknown coverage cannot claim zero work")
            if self.coverage == "not_included" and (self.reason != "legacy_report" or self.withheld_sources):
                raise ValueError("Legacy coverage has no incoming observation")
            if self.coverage == "unavailable" and (self.reason not in {"source_unavailable", "collection_limit"} or not self.withheld_sources):
                raise ValueError("Unavailable coverage has no confirmed counts")
        elif self.counts is None:
            raise ValueError("Observed section counts required")
        if self.coverage == "complete" and (self.reason is not None or self.withheld_sources
                or any(v.state in {"source_unavailable", "work_changed"} for v in self.items)):
            raise ValueError("Complete coverage cannot hide unavailable sources")
        return self
