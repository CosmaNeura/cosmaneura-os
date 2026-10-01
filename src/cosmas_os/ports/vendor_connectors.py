"""Private vendor ports. Values bind intent; they do not prove human approval.

Default-off adapters require an application authorization callback. Durable F8
claims, event deduplication and public disclosure checks remain application work.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Literal, get_args
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BeforeValidator,
    Field,
    SecretBytes,
    field_validator,
    model_validator,
)

from cosmas_os.ports.scribe_capture import ProtectedModel

Vendor = Literal["spruce", "srfax", "documo", "efax", "stripe", "portal"]
Environment = Literal["sandbox", "production"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OpaqueID = Annotated[str, Field(strict=True, min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")]
EndpointID = Annotated[str, Field(strict=True, min_length=1, max_length=255, pattern=r"^[A-Za-z0-9+/=_-]+$")]
Capability = Literal["message.submit", "media.upload", "fax.submit", "delivery.read",
    "payment_intent.create", "payment_intent.read", "webhook.verify", "referral.submit",
    "referral.read", "document.upload"]
SafeError = Literal["connector_disabled", "capability_unavailable", "connection_changed",
    "authority_required", "approval_changed", "request_invalid", "artifact_changed",
    "response_invalid", "response_too_large", "transport_unconfirmed", "provider_rejected",
    "provider_throttled", "duplicate_unresolved", "signature_invalid", "event_untrusted",
    "reference_unavailable"]
PaymentState = Literal["requires_payment_method", "requires_confirmation", "requires_action",
    "processing", "requires_capture", "canceled", "succeeded"]
MAX_DOCUMENT_BYTES = 8_388_608


def explicit_timestamp(value):
    if isinstance(value, datetime):
        return value
    if type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", value):
        return value
    raise ValueError("An explicit timezone-aware timestamp is required")


Timestamp = Annotated[AwareDatetime, BeforeValidator(explicit_timestamp)]


def digest(domain: str, value) -> str:
    raw = json.dumps({"domain": domain, "value": value}, sort_keys=True,
        ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class VendorError(Exception):
    """Closed errors never contain provider exceptions, response data or secrets."""

    def __init__(self, code: SafeError, *, attempted: bool = False):
        if type(code) is not str or code not in get_args(SafeError):
            code = "request_invalid"
        attempted = attempted is True
        super().__init__(code)
        self.code: SafeError = code
        self.attempted = attempted


class ConnectionSelection(ProtectedModel):
    vendor: Vendor
    connection_id: UUID
    box_id: UUID
    owner_id: UUID
    environment: Environment
    remote_account_id: OpaqueID
    credential_ref: UUID
    configuration_sha256: Digest

    @model_validator(mode="after")
    def account(self):
        value = self.remote_account_id
        if self.vendor == "documo" and str(UUID(value)) != value:
            raise ValueError("Invalid Documo account identifier")
        if self.vendor == "stripe" and re.fullmatch(r"acct_[A-Za-z0-9]+", value) is None:
            raise ValueError("Invalid Stripe account identifier")
        if self.vendor == "srfax" and (not value.isascii() or not value.isdigit() or int(value) <= 0):
            raise ValueError("Invalid SRFax account identifier")
        return self

    def commitment(self) -> str:
        return digest("cosmas-vendor-selection.v1", self.model_dump(mode="json"))


class DocumentBinding(ProtectedModel):
    artifact_id: UUID
    sha256: Digest
    byte_length: int = Field(strict=True, ge=1, le=MAX_DOCUMENT_BYTES)
    media_type: Literal["application/pdf"] = "application/pdf"
    display_name: Literal["document.pdf"] = "document.pdf"

    def require_bytes(self, content: bytes) -> None:
        if (type(content) is not bytes or len(content) != self.byte_length
                or hashlib.sha256(content).hexdigest() != self.sha256
                or not content.startswith(b"%PDF-")):
            raise VendorError("artifact_changed")


class ProviderReference(ProtectedModel):
    vendor: Vendor
    connection_id: UUID
    environment: Environment
    selection_sha256: Digest
    operation_id: UUID
    request_sha256: Digest
    kind: Literal["media", "async_request", "conversation_item", "fax", "payment_intent", "portal_document", "portal_referral"]
    value: OpaqueID
    observed_at: Timestamp
    artifact_sha256: Digest | None = None
    request_id: OpaqueID | None = None
    portal_id: str | None = Field(default=None, strict=True, pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    portal_profile_sha256: Digest | None = None
    correspondence_sha256: Digest | None = None

    @model_validator(mode="after")
    def reference_kind(self):
        portal_fields = (self.portal_id, self.portal_profile_sha256, self.correspondence_sha256)
        if self.vendor == "portal":
            if self.kind not in {"portal_document", "portal_referral"} or any(value is None for value in portal_fields):
                raise ValueError("Portal reference requires its exact profile and correspondence")
        elif any(value is not None for value in portal_fields):
            raise ValueError("Portal metadata is unavailable on another vendor reference")
        if self.kind == "media":
            if self.vendor != "spruce" or self.artifact_sha256 is None:
                raise ValueError("Media reference requires its artifact commitment")
            if str(UUID(self.value)) != self.value:
                raise ValueError("Invalid media identifier")
        elif self.kind == "portal_document":
            if self.vendor != "portal" or self.artifact_sha256 is None:
                raise ValueError("Portal document requires its artifact commitment")
        elif self.artifact_sha256 is not None:
            raise ValueError("Only media references bind an uploaded artifact")
        if self.kind == "portal_referral" and self.vendor != "portal":
            raise ValueError("Unsupported portal reference")
        if self.kind in {"async_request", "conversation_item"} and self.vendor != "spruce":
            raise ValueError("Unsupported reference kind")
        if self.kind == "fax":
            if self.vendor == "srfax":
                if not self.value.isascii() or not self.value.isdigit() or int(self.value) <= 0:
                    raise ValueError("Invalid fax reference")
            elif self.vendor in {"documo", "efax"}:
                if str(UUID(self.value)) != self.value:
                    raise ValueError("Invalid fax identifier")
            else:
                raise ValueError("Unsupported fax reference")
        if self.kind == "payment_intent" and (self.vendor != "stripe" or re.fullmatch(r"pi_[A-Za-z0-9]+", self.value) is None):
            raise ValueError("Invalid payment reference")
        return self


class UploadedMedia(ProtectedModel):
    document: DocumentBinding
    reference: ProviderReference

    @model_validator(mode="after")
    def exact_upload(self):
        if self.reference.kind != "media" or self.reference.artifact_sha256 != self.document.sha256:
            raise ValueError("Media reference does not bind this document")
        return self


class MediaUploadIntent(ProtectedModel):
    kind: Literal["media.upload"] = "media.upload"
    document: DocumentBinding


class SecureDestination(ProtectedModel):
    channel: Literal["secure"] = "secure"
    contact_id: OpaqueID


class PhoneDestination(ProtectedModel):
    channel: Literal["sms", "fax"]
    number: str = Field(strict=True, pattern=r"^\+[1-9][0-9]{7,14}$")


class EmailDestination(ProtectedModel):
    channel: Literal["email"] = "email"
    address: str = Field(strict=True, min_length=3, max_length=254,
        pattern=r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$")


class SpruceMessageIntent(ProtectedModel):
    kind: Literal["message.submit"] = "message.submit"
    internal_endpoint_id: EndpointID
    destination: Annotated[SecureDestination | PhoneDestination | EmailDestination, Field(discriminator="channel")]
    text: str = Field(strict=True, max_length=4000)
    attachment: UploadedMedia | None = None

    @field_validator("text")
    @classmethod
    def unicode_text(cls, value):
        value.encode("utf-8")
        if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
            raise ValueError("Invalid message text")
        return value

    @model_validator(mode="after")
    def channel_content(self):
        if self.destination.channel == "fax":
            if self.attachment is None:
                raise ValueError("Fax requires an approved uploaded PDF")
        elif not self.text.strip():
            raise ValueError("Message requires text")
        return self


class FaxIntent(ProtectedModel):
    kind: Literal["fax.submit"] = "fax.submit"
    caller_id: str = Field(strict=True, pattern=r"^[2-9][0-9]{9}$")
    destination: str = Field(strict=True, pattern=r"^1[2-9][0-9]{9}$")
    sender_email: str | None = Field(default=None, strict=True, max_length=254)
    document: DocumentBinding

    @field_validator("sender_email")
    @classmethod
    def email(cls, value):
        if value is not None:
            EmailDestination(address=value)
        return value


class StripePaymentIntentIntent(ProtectedModel):
    kind: Literal["payment_intent.create"] = "payment_intent.create"
    customer_id: str = Field(strict=True, pattern=r"^cus_[A-Za-z0-9]+$", max_length=255)
    amount: int = Field(strict=True, ge=50, le=99_999_999)
    currency: Literal["usd"] = "usd"


class PortalCorrespondence(ProtectedModel):
    """Private references to reviewed mappings, never arbitrary remote URLs/IDs.

    The concrete adapter/application must resolve these exact saved patient,
    practice and recipient mappings under current authority before an effect.
    Possessing this value does not prove that the mappings remain authorized.
    """

    patient_mapping_id: UUID
    practice_mapping_id: UUID
    recipient_mapping_id: UUID
    mappings_sha256: Digest

    def commitment(self):
        return digest("cosmas-portal-correspondence.v1", self.model_dump(mode="json"))


class PortalIntent(ProtectedModel):
    portal_id: str = Field(strict=True, pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    profile_sha256: Digest
    correspondence: PortalCorrespondence


class PortalDocumentIntent(PortalIntent):
    kind: Literal["document.upload"] = "document.upload"
    document: DocumentBinding


class PortalAttachment(ProtectedModel):
    document: DocumentBinding
    reference: ProviderReference

    @model_validator(mode="after")
    def exact_upload(self):
        if self.reference.kind != "portal_document" or self.reference.artifact_sha256 != self.document.sha256:
            raise ValueError("Portal upload does not bind this document")
        return self


class PortalReferralIntent(PortalIntent):
    kind: Literal["referral.submit"] = "referral.submit"
    summary: str = Field(strict=True, min_length=1, max_length=4000)
    attachment: PortalAttachment | None = None

    @field_validator("summary")
    @classmethod
    def explicit_summary(cls, value):
        if not value.strip():
            raise ValueError("Referral requires an explicit summary")
        return SpruceMessageIntent.unicode_text(value)


class VendorCommand(ProtectedModel):
    selection: ConnectionSelection
    operation_id: UUID
    revision_id: UUID
    expires_at: Timestamp
    intent: Annotated[MediaUploadIntent | SpruceMessageIntent | FaxIntent | StripePaymentIntentIntent | PortalDocumentIntent | PortalReferralIntent,
        Field(discriminator="kind")]

    @field_validator("expires_at")
    @classmethod
    def utc_expiry(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def adapter_scope(self):
        vendor = self.selection.vendor
        if (isinstance(self.intent, (MediaUploadIntent, SpruceMessageIntent)) and vendor != "spruce"
                or isinstance(self.intent, FaxIntent) and vendor not in {"srfax", "documo", "efax"}
                or isinstance(self.intent, StripePaymentIntentIntent) and vendor != "stripe"
                or isinstance(self.intent, PortalIntent) and vendor != "portal"):
            raise ValueError("Intent vendor differs")
        if isinstance(self.intent, FaxIntent) and ((vendor == "srfax") != (self.intent.sender_email is not None)):
            raise ValueError("Sender email applies to SRFax only")
        if isinstance(self.intent, (SpruceMessageIntent, PortalReferralIntent)) and self.intent.attachment:
            ref = self.intent.attachment.reference
            if ref.selection_sha256 != self.selection.commitment():
                raise ValueError("Uploaded media account differs")
            if isinstance(self.intent, PortalReferralIntent) and (ref.portal_id != self.intent.portal_id
                    or ref.portal_profile_sha256 != self.intent.profile_sha256
                    or ref.correspondence_sha256 != self.intent.correspondence.commitment()):
                raise ValueError("Portal upload profile or correspondence differs")
        return self

    def commitment(self) -> str:
        return digest("cosmas-vendor-command.v1", self.model_dump(mode="json"))


class ApprovalBinding(ProtectedModel):
    operation_id: UUID
    revision_id: UUID
    action: Literal["media.upload", "message.submit", "fax.submit", "payment_intent.create", "document.upload", "referral.submit"]
    approved_payload_sha256: Digest
    selection_sha256: Digest
    expires_at: Timestamp

    def require_command(self, command: VendorCommand, now: datetime):
        if (self.operation_id != command.operation_id or self.revision_id != command.revision_id
                or self.action != command.intent.kind or self.approved_payload_sha256 != command.commitment()
                or self.selection_sha256 != command.selection.commitment() or self.expires_at != command.expires_at):
            raise VendorError("approval_changed")
        if now >= self.expires_at:
            raise VendorError("authority_required")


class SubmissionObservation(ProtectedModel):
    vendor: Vendor
    connection_id: UUID
    operation_id: UUID
    request_sha256: Digest
    observed_at: Timestamp
    state: Literal["accepted", "rejected", "unconfirmed"]
    reference: ProviderReference | None
    safe_error: SafeError | None
    response_sha256: Digest | None

    @model_validator(mode="after")
    def evidence(self):
        if self.state == "accepted" and (self.reference is None or self.safe_error is not None):
            raise ValueError("Acceptance requires exact provider reference")
        if self.reference and (self.reference.vendor != self.vendor or self.reference.connection_id != self.connection_id
                or self.reference.operation_id != self.operation_id or self.reference.request_sha256 != self.request_sha256):
            raise ValueError("Reference scope differs")
        return self


class DeliveryObservation(ProtectedModel):
    reference: ProviderReference
    observed_at: Timestamp
    state: Literal["pending", "transport_delivered", "transport_failed", "unknown"]
    pages_total: int | None = Field(strict=True, default=None, ge=0, le=1_000_000)
    pages_delivered: int | None = Field(strict=True, default=None, ge=0, le=1_000_000)
    response_sha256: Digest

    @model_validator(mode="after")
    def pages(self):
        if self.pages_delivered is not None and (self.pages_total is None or self.pages_delivered > self.pages_total):
            raise ValueError("Inconsistent page count")
        return self


class PaymentObservation(ProtectedModel):
    reference: ProviderReference
    observed_at: Timestamp
    state: PaymentState
    amount: int = Field(strict=True, ge=50, le=99_999_999)
    currency: Literal["usd"]
    amount_received: int = Field(strict=True, ge=0, le=99_999_999)
    livemode: bool = Field(strict=True)
    response_sha256: Digest


class PreparedPortalRequest(ProtectedModel):
    """A private semantic command, never an arbitrary HTTP body or URL.

    Pure preparation binds the exact reviewed profile and optional PDF bytes.
    Each concrete implementation owns its fixed encoding and receipt parser.
    """

    command: VendorCommand
    profile_sha256: Digest
    document: SecretBytes | None = None

    @field_validator("document", mode="before")
    @classmethod
    def only_private_bytes(cls, value):
        if value is not None and type(value) is not bytes and not isinstance(value, SecretBytes):
            raise ValueError("Portal document must be exact private bytes")
        return value

    @model_validator(mode="after")
    def bound_profile_and_bytes(self):
        intent = self.command.intent
        if not isinstance(intent, PortalIntent) or intent.profile_sha256 != self.profile_sha256:
            raise ValueError("Portal preparation profile differs")
        if isinstance(intent, PortalDocumentIntent):
            if self.document is None:
                raise VendorError("artifact_changed")
            intent.document.require_bytes(self.document.get_secret_value())
        elif self.document is not None:
            raise ValueError("Referral cannot implicitly upload a document")
        return self


class PortalObservation(ProtectedModel):
    reference: ProviderReference
    observed_at: Timestamp
    state: Literal["pending", "received", "declined", "unknown"]
    response_sha256: Digest

    @model_validator(mode="after")
    def referral_only(self):
        if self.reference.kind != "portal_referral":
            raise ValueError("Portal status requires its exact referral reference")
        return self


class EventCandidate(ProtectedModel):
    vendor: Vendor
    connection_id: UUID
    observed_at: Timestamp
    authenticity: Literal["signature_verified", "untrusted_hint"]
    body_sha256: Digest
    event_type: str = Field(strict=True, min_length=1, max_length=100)
    event_id: OpaqueID | None = None
    object_id: OpaqueID | None = None
    request_id: OpaqueID | None = None


class CapabilityDescription(ProtectedModel):
    capability: Capability
    evidence: Literal["documented", "contract_gap", "unsupported"]
    external_acceptance: Literal[False] = False

    @field_validator("external_acceptance", mode="before")
    @classmethod
    def not_qualified(cls, value):
        if value is not False:
            raise ValueError("External acceptance has not been qualified")
        return value
