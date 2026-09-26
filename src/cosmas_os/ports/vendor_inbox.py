"""Trusted internal, read-only inbox source contracts; never a browser admission.

A hash is a commitment, not authority. The application must construct the binding
from a current human-reviewed mapping and independently authorize every read.
External text carries no approval, reply, triage or completion authority.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from cosmas_os.ports.scribe_capture import ProtectedModel
from cosmas_os.ports.vendor_connectors import (
    ConnectionSelection,
    Digest,
    OpaqueID,
    Timestamp,
    digest,
)

MAX_INBOX_TEXT_BYTES = 16_384
MAX_INBOX_PARTICIPANTS = 16


class SpruceInboxParticipant(ProtectedModel):
    contact_id: OpaqueID
    # A delegate's contact is never silently relabeled as the patient's contact.
    relationship: Literal["patient", "delegate"]


class SpruceInboxReadBinding(ProtectedModel):
    selection: ConnectionSelection
    patient_link_id: UUID
    correspondence_version_id: UUID
    correspondence_sha256: Digest
    contact_id: OpaqueID
    conversation_id: OpaqueID
    item_id: OpaqueID
    secure_endpoint_raw_value: Annotated[str, Field(strict=True, min_length=1, max_length=2048)]
    permitted_participants: Annotated[
        tuple[SpruceInboxParticipant, ...], Field(min_length=1, max_length=MAX_INBOX_PARTICIPANTS)
    ]

    @model_validator(mode="after")
    def exact_secure_mapping(self):
        if self.selection.vendor != "spruce" or self.selection.environment != "production":
            raise ValueError("unsupported inbox selection")
        contacts = tuple(p.contact_id for p in self.permitted_participants)
        if (
            len(set(contacts)) != len(contacts)
            or contacts != tuple(sorted(contacts))
            or self.contact_id not in contacts
            or sum(p.relationship == "patient" for p in self.permitted_participants) > 1
        ):
            raise ValueError("invalid reviewed participant set")
        # This value is compared as opaque reviewed evidence, never fetched or
        # normalized into an endpoint. Spruce's derived endpoint ID may differ.
        value = self.secure_endpoint_raw_value
        if value != value.strip() or any(ord(c) < 33 for c in value):
            raise ValueError("invalid reviewed secure endpoint")
        if len(value.encode("utf-8")) > 2048:
            raise ValueError("invalid reviewed secure endpoint")
        return self

    def commitment(self) -> str:
        return digest("cosmas-spruce-inbox-binding.v1", self.model_dump(mode="json"))


AttachmentKind = Literal[
    "audio", "carePlan", "document", "entityProfile", "genericUrl", "image",
    "paymentRequest", "video", "visit", "unknown",
]


class SpruceInboxUnsupported(ProtectedModel):
    attachments: StrictBool
    pages: StrictBool
    buttons: StrictBool
    event: StrictBool
    attachment_types: Annotated[tuple[AttachmentKind, ...], Field(max_length=10)] = ()

    @model_validator(mode="after")
    def coherent_types(self):
        if self.attachment_types != tuple(sorted(set(self.attachment_types))):
            raise ValueError("invalid attachment classification")
        if self.attachments != bool(self.attachment_types):
            raise ValueError("invalid attachment classification")
        return self


class SpruceInboxSnapshot(ProtectedModel):
    binding: SpruceInboxReadBinding
    created_at: Timestamp
    modified_at: Timestamp
    observed_at: Timestamp
    text: Annotated[str, Field(strict=True, max_length=MAX_INBOX_TEXT_BYTES)]
    item_response_sha256: Digest
    conversation_response_sha256: Digest
    # Canonical JSON digests ignore object-key serialization order; raw hashes
    # above retain exact wire evidence. Neither original response is published.
    item_content_sha256: Digest
    conversation_content_sha256: Digest
    source_sha256: Digest
    unsupported: SpruceInboxUnsupported
    conversation_archived: StrictBool
    conversation_read_only: StrictBool
    trust: Literal["untrusted_external_text"] = "untrusted_external_text"

    @model_validator(mode="after")
    def bounded_source(self):
        if self.modified_at < self.created_at:
            raise ValueError("invalid source timestamps")
        if len(self.text.encode("utf-8")) > MAX_INBOX_TEXT_BYTES:
            raise ValueError("source text too large")
        if any(ord(c) < 32 and c not in "\n\r\t" for c in self.text):
            raise ValueError("invalid source text")
        if self.source_sha256 != self.snapshot_digest():
            raise ValueError("source commitment mismatch")
        return self

    def snapshot_digest(self) -> str:
        return digest(
            "cosmas-spruce-inbox-source.v1",
            self.model_dump(mode="json", exclude={
                "source_sha256", "observed_at", "item_response_sha256",
                "conversation_response_sha256",
            }),
        )

    @property
    def needs_human_review(self) -> bool:
        # Every source needs human review; unsupported content additionally
        # prevents claiming that the complete message has been reviewed.
        return True

    @property
    def incomplete_content(self) -> bool:
        return any((self.unsupported.attachments, self.unsupported.pages,
                    self.unsupported.buttons, self.unsupported.event, not self.text.strip()))


def compare_inbox_snapshots(
    previous: SpruceInboxSnapshot, incoming: SpruceInboxSnapshot,
) -> Literal["same", "newer", "older", "conflict", "scope_changed"]:
    """Classify evidence only; callers must retain history and block conflicts.

    There is no trustworthy vendor sequence in these GET responses. Arrival
    order cannot replace modifiedAt. A changed parent at an older item timestamp
    is a conflict, not evidence that the previous parent remains current.
    """
    previous = SpruceInboxSnapshot.model_validate(previous.model_dump(mode="python"))
    incoming = SpruceInboxSnapshot.model_validate(incoming.model_dump(mode="python"))
    if previous.binding != incoming.binding:
        return "scope_changed"
    if previous.created_at != incoming.created_at:
        return "conflict"
    if previous.source_sha256 == incoming.source_sha256:
        return "same"
    if incoming.modified_at < previous.modified_at:
        return (
            "older" if previous.conversation_content_sha256 == incoming.conversation_content_sha256
            else "conflict"
        )
    if incoming.modified_at == previous.modified_at:
        return "conflict"
    return "newer"
