"""Closed public delivery commands; private vendor commands never cross this API."""

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BeforeValidator, ConfigDict, Field, model_validator

from cosmas_os.ports.scribe_capture import ProtectedModel

VERSION = "1"
MAX_JSON = 32768
MAX_DOCUMENT = 8388608
WHITESPACE = frozenset("\t\n\v\f\r \x85\xa0\u1680\u2028\u2029\u202f\u205f\u3000") | frozenset(
    chr(i) for i in range(0x2000, 0x200B)
)


def _uuid(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError("canonical UUID required")
    return value


def _true(value):
    if value is not True:
        raise ValueError("explicit true required")
    return value


def _version(value):
    if type(value) is not int or value != 1:
        raise ValueError("exact contract version required")
    return value


def _text(value):
    if type(value) is not str:
        raise ValueError("text required")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value.encode("utf-8")
    if (
        any(ord(c) < 32 and c not in "\t\n" or ord(c) == 127 for c in value)
        or not value
        or all(c in WHITESPACE for c in value)
    ):
        raise ValueError("invalid text")
    return value


def _day(value):
    if type(value) is not str or date.fromisoformat(value).isoformat() != value:
        raise ValueError("exact date required")
    return value


ID = Annotated[str, BeforeValidator(_uuid)]
Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
Key = Annotated[str, Field(strict=True, min_length=8, max_length=100, pattern=r"^[A-Za-z0-9:_-]+$")]
Positive = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Counter = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
Confirmed = Annotated[Literal[True], BeforeValidator(_true)]
ContractVersion = Annotated[Literal[1], BeforeValidator(_version)]
Message = Annotated[str, BeforeValidator(_text), Field(max_length=4000)]
Goal = Annotated[str, BeforeValidator(_text), Field(max_length=500)]
Evidence = Annotated[str, BeforeValidator(_text), Field(max_length=2000)]
Day = Annotated[str, BeforeValidator(_day)]
Action = Literal[
    "spruce_secure_message", "spruce_fax", "spruce_media_upload", "srfax_fax", "documo_fax", "efax_fax"
]
CommandKind = Literal[
    "propose",
    "decide",
    "withdraw",
    "publish",
    "submit",
    "reconcile",
    "result",
    "verify",
    "handoff",
    "artifact_intent",
    "artifact_content",
]


class Closed(ProtectedModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def absent_not_null(cls, value):
        if type(value) is dict:
            if any(type(k) is not str or v is None for k, v in value.items()):
                raise ValueError("unknown/null field")
        return value

    def public(self):
        return self.model_dump(mode="json", exclude_none=True, by_alias=True)


class Selection(Closed):
    id: ID
    revision: Positive
    public_sha256: Digest


class ReviewedSource(Closed):
    kind: Literal["reviewed_note"]
    note_id: ID
    content_sha256: Digest
    source_fingerprint: Digest


class Document(Closed):
    artifact_id: ID
    sha256: Digest
    byte_length: Annotated[int, Field(strict=True, ge=5, le=MAX_DOCUMENT)]
    media_type: Literal["application/pdf"]


class Revision(Closed):
    ticket_id: ID
    expected_version: Positive
    revision_id: ID
    payload_hash: Digest


class VendorProposal(Closed):
    expected_workspace_revision: Positive
    idempotency_key: Key
    proposed_operation_id: ID
    action: Action
    connection: Selection
    source: ReviewedSource
    due_date: Day
    expected_outcome: Goal
    share_to_practice: bool
    correspondence: Selection | None = None
    document: Document | None = None
    message: Message | None = None
    uploaded_media_operation_id: ID | None = None
    supersedes_operation_id: ID | None = None
    acknowledge_prior_uncertainty: Confirmed | None = None
    revises: Revision | None = None

    @model_validator(mode="after")
    def action_union(self):
        fields = {
            "correspondence": self.correspondence,
            "document": self.document,
            "message": self.message,
            "uploaded_media_operation_id": self.uploaded_media_operation_id,
        }
        required, optional = {
            "spruce_secure_message": (
                {"correspondence", "message"},
                {"uploaded_media_operation_id"},
            ),
            "spruce_fax": ({"correspondence", "uploaded_media_operation_id"}, set()),
            "spruce_media_upload": ({"document"}, set()),
            "srfax_fax": ({"correspondence", "document"}, set()),
            "documo_fax": ({"correspondence", "document"}, set()),
            "efax_fax": ({"correspondence", "document"}, set()),
        }[self.action]
        present = {k for k, v in fields.items() if v is not None}
        if not required <= present or present - required - optional:
            raise ValueError("invalid delivery action fields")
        if (
            (self.supersedes_operation_id is not None)
            != (self.acknowledge_prior_uncertainty is True)
            or self.supersedes_operation_id is not None
            and self.revises is not None
        ):
            raise ValueError("invalid replacement")
        return self


class BoundCommand(Closed):
    expected_version: Positive
    operation_id: ID
    revision_id: ID
    payload_hash: Digest
    idempotency_key: Key


class VendorDecision(BoundCommand):
    review_sha256: Digest
    choice: Literal["approve", "reject"]
    administrative_delivery_confirmed: Confirmed | None = None
    follow_up_bot_id: ID | None = None

    @model_validator(mode="after")
    def exact_delegation(self):
        if (self.administrative_delivery_confirmed is True) != (self.follow_up_bot_id is not None):
            raise ValueError("administrative confirmation and exact Follow up bot required together")
        if self.follow_up_bot_id is not None and self.choice != "approve":
            raise ValueError("only an exact approval can authorize Follow up")
        return self


class VendorPublication(BoundCommand):
    review_sha256: Digest
    share_to_practice: Confirmed


class ObservationHead(Closed):
    sequence: Counter
    sha256: Digest


class VendorResult(BoundCommand):
    observation_head: ObservationHead
    evidence_sha256: Digest
    disposition: Literal[
        "reported_success", "reported_exception", "verified_in_vendor", "unable_to_establish"
    ]
    evidence: Evidence


class VendorStaffResult(VendorResult):
    disposition: Literal["reported_success", "reported_exception"]


class VendorVerify(BoundCommand):
    result_receipt_id: ID
    result_receipt_sha256: Digest
    observation_head: ObservationHead
    evidence_sha256: Digest
    reviewed_result: Confirmed
    reviewed_observations: Confirmed
    outcome_confirmed: Confirmed
    reviewed_conflicting_evidence: bool


class VendorResolve(Closed):
    command_kind: CommandKind
    idempotency_key: Key
    request_sha256: Digest


class VendorStaffResolve(VendorResolve):
    command_kind: Literal["handoff", "result"]


class VendorHandoff(Closed):
    expected_version: Positive
    revision_id: ID
    payload_hash: Digest
    idempotency_key: Key
    kind: Literal["offer", "accept", "decline", "recall", "reclaim"]
    recipient_id: ID | None = None
    offer_id: ID | None = None

    @model_validator(mode="after")
    def exact_shape(self):
        if (self.kind == "offer") != (self.recipient_id is not None) or (
            self.kind in {"accept", "decline", "recall"}
        ) != (self.offer_id is not None):
            raise ValueError("invalid handoff fields")
        return self


class VendorArtifactIntent(Closed):
    artifact_id: ID
    idempotency_key: Key
    source: ReviewedSource
    sha256: Digest
    byte_length: Annotated[int, Field(strict=True, ge=5, le=MAX_DOCUMENT)]
    media_type: Literal["application/pdf"]


class VendorArtifactResolve(VendorResolve):
    artifact_id: ID
    command_kind: Literal["artifact_intent", "artifact_content"]


class VendorArtifactContent(Closed):
    artifact_id: ID
    intent_sha256: Digest
    idempotency_key: Key
    sha256: Digest
    byte_length: Annotated[int, Field(strict=True, ge=5, le=MAX_DOCUMENT)]
    media_type: Literal["application/pdf"]


def json_value(value: Any, depth=0):
    """Reject non-JSON objects, subclasses, surrogates and ambiguous numbers."""
    if depth > 30:
        raise ValueError("JSON depth exceeded")
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str or not key.isascii():
                raise ValueError("invalid JSON key")
            json_value(child, depth + 1)
    elif type(value) is list:
        for child in value:
            json_value(child, depth + 1)
    elif type(value) is str:
        value.encode("utf-8")
    elif type(value) is int:
        if abs(value) > 2147483647:
            raise ValueError("integer bound exceeded")
    elif value is not None and type(value) is not bool:
        raise ValueError("invalid JSON scalar")
    return value


def canonical(value):
    json_value(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def public_digest(domain, value):
    return hashlib.sha256(canonical({"domain": domain, "value": value})).hexdigest()


def request_digest(kind, scope, model):
    return public_digest(
        "cosmas-vendor-public-request.v1",
        {"command_kind": kind, "scope": scope, "request": model.public()},
    )


def read_json(raw, model, maximum=MAX_JSON):
    if type(raw) is not bytes or len(raw) > maximum:
        raise ValueError("invalid request size")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    if type(value) is not dict:
        raise ValueError("object required")
    json_value(value)
    return model.model_validate(value)


def timestamp(value: datetime):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("UTC timestamp required")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def bounded(value, maximum):
    if len(canonical(value)) > maximum:
        raise ValueError("response bound exceeded")
    return value


def safe_label(value, limit=80):
    if type(value) is not str:
        raise ValueError("label required")
    return _text(value)[:limit]


def _timestamp(value):
    if type(value) is not str or len(value) != 27:
        raise ValueError("exact UTC timestamp required")
    if timestamp(datetime.fromisoformat(value.replace("Z", "+00:00"))) != value:
        raise ValueError("exact UTC timestamp required")
    return value


Timestamp = Annotated[str, BeforeValidator(_timestamp)]
Label = Annotated[str, BeforeValidator(_text), Field(max_length=80)]
DestinationLabel = Annotated[str, BeforeValidator(_text), Field(max_length=255)]
WorkState = Literal["pending_approval", "approved", "rejected", "withdrawn", "superseded", "closed"]
Dispatch = Literal[
    "not_started", "invocation_started", "proved_not_dispatched", "unconfirmed", "response_observed"
]
Acceptance = Literal["not_observed", "accepted", "rejected", "unconfirmed"]
Transport = Literal["not_observed", "pending", "delivered", "failed", "unknown"]
ResultState = Literal["none", "recorded_success", "recorded_exception"]
Verification = Literal["pending", "verified", "exception_unresolved"]
ProviderError = Literal[
    "connector_disabled",
    "capability_unavailable",
    "connection_changed",
    "authority_required",
    "approval_changed",
    "request_invalid",
    "artifact_changed",
    "response_invalid",
    "response_too_large",
    "transport_unconfirmed",
    "provider_rejected",
    "provider_throttled",
    "duplicate_unresolved",
    "signature_invalid",
    "event_untrusted",
    "reference_unavailable",
]
Reason = Literal[
    "available",
    "feature_disabled",
    "owner_only",
    "not_current",
    "not_approved",
    "expired",
    "source_changed",
    "selection_changed",
    "permission_unavailable",
    "artifact_unavailable",
    "submit_already_claimed",
    "reference_unavailable",
    "original_account_unavailable",
    "read_in_progress",
    "history_limit",
    "result_required",
    "manual_verification_required",
    "exception_unresolved",
    "already_published",
    "closed",
]
ErrorCode = Literal[
    "invalid_vendor_request",
    "vendor_contract_required",
    "vendor_work_unavailable",
    "vendor_feature_disabled",
    "vendor_idempotency_conflict",
    "vendor_revision_changed",
    "vendor_source_changed",
    "vendor_selection_changed",
    "vendor_permission_unavailable",
    "vendor_approval_expired",
    "vendor_submit_already_claimed",
    "vendor_reference_unavailable",
    "vendor_original_account_unavailable",
    "vendor_read_in_progress",
    "vendor_result_changed",
    "vendor_evidence_changed",
    "vendor_exception_unresolved",
    "vendor_history_limit",
    "vendor_credential_text_forbidden",
    "artifact_unavailable",
    "artifact_changed",
    "artifact_write_in_progress",
    "artifact_write_unconfirmed",
    "vendor_unavailable",
]


class Output(ProtectedModel):
    """Closed response validator; explicit nullable fields remain on the wire."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True, strict=True)

    def public(self):
        # Omitted optional fields stay absent; explicit null fields stay present.
        return self.model_dump(mode="json", exclude_unset=True, by_alias=True)


class ConnectionView(Closed):
    id: ID
    revision: Positive
    vendor: Literal["spruce", "srfax", "documo", "efax"]
    environment: Literal["production", "sandbox"]
    label: Label
    actions: Annotated[list[Action], Field(min_length=1, max_length=3)]
    availability: Literal["enabled", "disabled", "read_only", "revoked"]
    public_sha256: Digest

    @model_validator(mode="after")
    def capability_union(self):
        allowed = {
            "spruce": {"spruce_secure_message", "spruce_fax", "spruce_media_upload"},
            "srfax": {"srfax_fax"},
            "documo": {"documo_fax"},
            "efax": {"efax_fax"},
        }[self.vendor]
        if (
            len(set(self.actions)) != len(self.actions)
            or set(self.actions) - allowed
            or self.vendor != "documo"
            and self.environment != "production"
        ):
            raise ValueError("invalid capability union")
        bounded(self.public(), 2048)
        return self


class CorrespondenceView(Closed):
    id: ID
    revision: Positive
    connection_id: ID
    channel: Literal["secure", "fax"]
    recipient_label: Label
    destination_display: DestinationLabel
    permission: Literal["reviewed", "expired", "revoked"]
    expires_at: Timestamp
    public_sha256: Digest

    @model_validator(mode="after")
    def wire_bound(self):
        bounded(self.public(), 2048)
        return self


class Summary(Closed):
    ticket_id: ID
    version: Positive
    revision_id: ID
    operation_id: ID
    payload_hash: Digest
    action: Action
    state: WorkState
    published: bool
    submit_claimed: bool
    dispatch: Dispatch
    acceptance: Acceptance
    transport: Transport
    conflicting_evidence: bool
    result: ResultState
    verification: Verification
    due_date: Day
    outcome_excerpt: Annotated[str, BeforeValidator(_text), Field(max_length=160)]
    responsible_id: ID
    observation_head: ObservationHead
    evidence_sha256: Digest

    @model_validator(mode="after")
    def wire_bound(self):
        bounded(self.public(), 1536)
        return self


class Availability(Closed):
    allowed: bool
    reason: Reason

    @model_validator(mode="after")
    def agrees(self):
        if self.allowed != (self.reason == "available"):
            raise ValueError("invalid action availability")
        return self


class ActionAvailability(Closed):
    approve: Availability
    reject: Availability
    withdraw: Availability
    publish: Availability
    submit: Availability
    reconcile: Availability
    result: Availability
    verify: Availability


class UploadedMedia(Closed):
    operation_id: ID
    document: Document


class SupersedesView(Closed):
    ticket_id: ID
    operation_id: ID
    action: Action
    prior_dispatch: Dispatch
    prior_acceptance: Acceptance
    prior_transport: Transport
    uncertainty_acknowledged: Confirmed


class Review(Closed):
    ticket_id: ID
    revision_id: ID
    operation_id: ID
    action: Action
    connection: ConnectionView
    source: ReviewedSource
    correspondence: CorrespondenceView | None = None
    document: Document | None = None
    uploaded_media: UploadedMedia | None = None
    message: Message | None = None
    due_date: Day
    expected_outcome: Goal
    share_to_practice: bool
    expires_at: Timestamp
    supersedes: SupersedesView | None = None

    @model_validator(mode="after")
    def action_union(self):
        fields = {
            "correspondence": self.correspondence,
            "document": self.document,
            "message": self.message,
            "uploaded_media": self.uploaded_media,
        }
        required, optional = {
            "spruce_secure_message": ({"correspondence", "message"}, {"uploaded_media"}),
            "spruce_fax": ({"correspondence", "uploaded_media"}, set()),
            "spruce_media_upload": ({"document"}, set()),
            "srfax_fax": ({"correspondence", "document"}, set()),
            "documo_fax": ({"correspondence", "document"}, set()),
            "efax_fax": ({"correspondence", "document"}, set()),
        }[self.action]
        present = {k for k, v in fields.items() if v is not None}
        if (
            not required <= present
            or present - required - optional
            or self.action not in self.connection.actions
        ):
            raise ValueError("invalid review action")
        if self.correspondence and (
            self.correspondence.connection_id != self.connection.id
            or self.correspondence.channel
            != ("secure" if self.action == "spruce_secure_message" else "fax")
        ):
            raise ValueError("invalid review correspondence")
        return self


class Person(Closed):
    id: ID
    name: Label
    available: bool


class HumanResult(Closed):
    receipt_id: ID
    receipt_sha256: Digest
    actor: Person
    disposition: Literal[
        "reported_success", "reported_exception", "verified_in_vendor", "unable_to_establish"
    ]
    evidence: Evidence
    recorded_at: Timestamp
    observation_head: ObservationHead


class Detail(Output):
    contract_version: ContractVersion
    workspace_id: ID
    view_version: Positive
    observed_at: Timestamp
    summary: Summary
    review: Review
    review_sha256: Digest
    latest_result: HumanResult | None
    availability: ActionAvailability


class Options(Output):
    contract_version: ContractVersion
    workspace_id: ID
    entry_revision: Positive
    enabled: bool
    connections: Annotated[list[ConnectionView], Field(max_length=10)]
    correspondences: Annotated[list[CorrespondenceView], Field(max_length=10)]
    source: ReviewedSource | None
    observed_at: Timestamp


Cursor = Annotated[str, Field(strict=True, min_length=1, max_length=512, pattern=r"^[\x21-\x7e]+$")]


class Catalog(Output):
    contract_version: ContractVersion
    workspace_id: ID
    items: Annotated[list[Summary], Field(max_length=25)]
    next_cursor: Cursor | None
    observed_at: Timestamp


class Observation(Closed):
    id: ID
    sequence: Positive
    operation_id: ID
    kind: Literal["submission", "transport", "dispatch"]
    observed_at: Timestamp
    recorded_at: Timestamp
    sha256: Digest
    acceptance: Literal["accepted", "rejected", "unconfirmed"] | None = None
    transport: Literal["pending", "delivered", "failed", "unknown"] | None = None
    dispatch: Dispatch | None = None
    pages_total: Annotated[int, Field(strict=True, ge=0, le=1000000)] | None = None
    pages_delivered: Annotated[int, Field(strict=True, ge=0, le=1000000)] | None = None
    safe_error: ProviderError | None = None

    @model_validator(mode="after")
    def exact_kind(self):
        statuses = {
            "submission": self.acceptance,
            "transport": self.transport,
            "dispatch": self.dispatch,
        }
        if statuses[self.kind] is None or sum(v is not None for v in statuses.values()) != 1:
            raise ValueError("invalid observation kind")
        if (
            (self.pages_total is None) != (self.pages_delivered is None)
            or self.pages_total is not None
                and (self.kind != "transport" or self.pages_delivered is None or self.pages_delivered > self.pages_total)
        ):
            raise ValueError("invalid page observation")
        bounded(self.public(), 2048)
        return self


class ObservationPage(Output):
    contract_version: ContractVersion
    ticket_id: ID
    operation_id: ID
    observations: Annotated[list[Observation], Field(max_length=20)]
    head: ObservationHead
    next_cursor: Cursor | None
    observed_at: Timestamp


class Scope(Closed):
    kind: Literal["workspace", "practice_work"]
    id: ID


class Effect(Closed):
    ticket_id: ID
    operation_id: ID
    revision_id: ID
    payload_hash: Digest
    receipt_id: ID
    effect_version: Positive
    recorded_at: Timestamp
    receipt_sha256: Digest


class EffectSummary(Closed):
    effect: Literal[
        "proposed",
        "revised",
        "approved",
        "rejected",
        "withdrawn",
        "published",
        "submit_claimed",
        "read_claimed",
        "result_recorded",
        "verified",
        "handoff_recorded",
    ]
    publication_recorded: bool


class CommandResponse(Output):
    contract_version: ContractVersion
    scope: Scope
    command_kind: CommandKind
    idempotency_key: Key
    request_sha256: Digest
    outcome: Literal["recorded", "unconfirmed", "not_found"]
    effect: Effect | None
    summary: EffectSummary | None
    observed_at: Timestamp

    @model_validator(mode="after")
    def outcome_union(self):
        if (self.effect is not None) != (self.outcome == "recorded") or (
            self.summary is not None
        ) != (self.outcome == "recorded"):
            raise ValueError("invalid command outcome")
        return self


class ArtifactMetadata(Output):
    artifact_id: ID
    version: Positive
    source: ReviewedSource
    document: Document
    intent_sha256: Digest
    state: Literal["empty", "receiving", "ready", "quarantined"]
    generation: Counter
    lease_until: Timestamp | None


class ArtifactEffect(Closed):
    artifact_id: ID
    receipt_id: ID
    effect_version: Positive
    recorded_at: Timestamp
    receipt_sha256: Digest


class ArtifactResponse(Output):
    contract_version: ContractVersion
    scope: Scope
    command_kind: Literal["artifact_intent", "artifact_content"]
    idempotency_key: Key
    request_sha256: Digest
    outcome: Literal["recorded", "unconfirmed", "not_found"]
    effect: ArtifactEffect | None
    artifact: ArtifactMetadata | None
    observed_at: Timestamp

    @model_validator(mode="after")
    def outcome_union(self):
        if self.scope.kind != "workspace" or (self.effect is not None) != (
            self.outcome == "recorded"
        ):
            raise ValueError("invalid artifact outcome")
        if self.outcome == "recorded" and self.artifact is None:
            raise ValueError("artifact metadata required")
        return self


class SharedVendorStatus(Closed):
    action: Action
    operation_id: ID
    submit_claimed: bool
    acceptance: Acceptance
    transport: Transport
    conflicting_evidence: bool
    result: ResultState
    verification: Verification
    observation_head: ObservationHead
    evidence_sha256: Digest


class SharedVendorWork(Closed):
    work_kind: Literal["vendor_delivery"]
    ticket_id: ID
    version: Positive
    revision_id: ID
    payload_hash: Digest
    state: WorkState
    ready_for_review: bool
    historical: bool
    publication_receipt_id: ID
    body: Goal
    due_date: Day
    expected_outcome: Goal
    viewer_id: ID
    originator: Person
    responsible: Person
    vendor_work: SharedVendorStatus


class SharedOffer(Closed):
    id: ID
    from_person: Person = Field(alias="from")
    to: Person


class SharedHandoff(Output):
    id: ID
    kind: Literal["offer", "accept", "decline", "recall", "reclaim"]
    actor: Person
    from_person: Person = Field(alias="from")
    to: Person
    offer_id: ID | None
    created_at: Timestamp


class SharedVendorDetail(Output):
    work_kind: Literal["vendor_delivery"]
    ticket_id: ID
    version: Positive
    revision_id: ID
    payload_hash: Digest
    state: WorkState
    ready_for_review: bool
    historical: bool
    publication_receipt_id: ID
    body: Goal
    due_date: Day
    expected_outcome: Goal
    viewer_id: ID
    originator: Person
    responsible: Person
    vendor_work: SharedVendorStatus
    pending_offer: SharedOffer | None
    handoffs: Annotated[list[SharedHandoff], Field(max_length=201)]
    latest_result: HumanResult | None
