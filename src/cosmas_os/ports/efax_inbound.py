"""Closed private eFax inbound contracts; metadata is not clinical-note custody."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from cosmas_os.ports.scribe_capture import ProtectedModel
from cosmas_os.ports.vendor_connectors import ConnectionSelection, Timestamp, digest

MAX_LIST_BYTES = 65536
MAX_PDF_BYTES = 1048576
MAX_IMAGE_BYTES = ((MAX_PDF_BYTES + 2) // 3) * 4 + 2048
MAX_PAGES = 50
Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
FaxNumber = Annotated[
    str, Field(strict=True, min_length=1, max_length=32, pattern=r"^\+?[0-9]{1,31}$")
]


class Failure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ListRequest(ProtectedModel):
    selection: ConnectionSelection
    request_id: UUID
    starts_at: Timestamp
    ends_at: Timestamp
    limit: int = Field(strict=True, ge=1, le=25)
    offset: int = Field(strict=True, ge=0, le=5000)

    @model_validator(mode="after")
    def bounded(self):
        if (
            self.selection.vendor != "efax"
            or self.selection.environment != "production"
            or not timedelta(0) < self.ends_at - self.starts_at <= timedelta(days=7)
        ):
            raise ValueError("invalid inbound scope")
        return self


class FaxMetadata(ProtectedModel):
    fax_id: UUID
    size: int = Field(strict=True, ge=0, le=16777216)
    duration: int = Field(strict=True, ge=0, le=86400)
    pages: int = Field(strict=True, ge=0, le=10000)
    image_downloaded: StrictBool
    completed_timestamp: Timestamp
    destination_fax_number: FaxNumber
    originating_fax_number: FaxNumber
    originating_fax_tsid: str = Field(strict=True, max_length=128)
    fax_status: Literal["STORED", "NOT_STORED"] | None = None

    @model_validator(mode="after")
    def safe_tsid(self):
        if any(ord(c) < 32 or ord(c) == 127 for c in self.originating_fax_tsid):
            raise ValueError("invalid fax tsid")
        return self


class ListSnapshot(ProtectedModel):
    request: ListRequest
    first_record: int = Field(strict=True, ge=0, le=2147483647)
    last_record: int = Field(strict=True, ge=0, le=2147483647)
    items: tuple[FaxMetadata, ...] = Field(max_length=25)
    observed_at: Timestamp
    raw_sha256: Digest
    source_sha256: Digest
    scope: Literal["one_received_metadata_page"] = "one_received_metadata_page"
    inbox_complete: Literal[False] = False
    continuation: Literal["unknown"] = "unknown"

    @model_validator(mode="after")
    def exact(self):
        if (
            len(self.items) > self.request.limit
            or len({item.fax_id for item in self.items}) != len(self.items)
            or any(
                not self.request.starts_at <= item.completed_timestamp <= self.request.ends_at
                for item in self.items
            )
            or [item.completed_timestamp for item in self.items]
            != sorted((item.completed_timestamp for item in self.items), reverse=True)
            or self.source_sha256 != self.commitment()
        ):
            raise ValueError("invalid inbound list")
        return self

    def commitment(self):
        return digest(
            "cosmas-efax-inbound-list.v1",
            self.model_dump(mode="json", exclude={"source_sha256"}),
        )


class ImageCommand(ProtectedModel):
    selection: ConnectionSelection
    operation_id: UUID
    source_sha256: Digest
    fax_id: UUID
    format: Literal["PDF"] = "PDF"
    expires_at: Timestamp
    side_effect: Literal["marks_fax_downloaded_or_read"] = "marks_fax_downloaded_or_read"

    def commitment(self):
        return digest("cosmas-efax-image-command.v1", self.model_dump(mode="json"))


class ImageApproval(ProtectedModel):
    operation_id: UUID
    command_sha256: Digest
    selection_sha256: Digest
    operator_id: UUID
    approved_at: Timestamp
    expires_at: Timestamp
    reviewed_exact_fax: Literal[True]
    approved_mark_downloaded_or_read: Literal[True]

    @model_validator(mode="before")
    @classmethod
    def explicit_true(cls, value):
        if (
            value.get("reviewed_exact_fax") is not True
            or value.get("approved_mark_downloaded_or_read") is not True
        ):
            raise ValueError("explicit operator authorization required")
        return value


class ImageReceipt(ProtectedModel):
    operation_id: UUID
    command_sha256: Digest
    selection_sha256: Digest
    fax_id: UUID
    state: Literal["not_attempted", "outcome_unconfirmed", "acquired", "needs_human"]
    attempted: StrictBool
    provider_read_state: Literal[
        "unchanged_by_this_attempt", "may_have_changed", "endpoint_reported_download"
    ]
    content_available: StrictBool
    observed_at: Timestamp
    response_sha256: Digest | None = None
    document_sha256: Digest | None = None
    source_sha256: Digest | None = None
    byte_length: int | None = Field(default=None, strict=True, ge=1, le=MAX_PDF_BYTES)
    pages: int | None = Field(default=None, strict=True, ge=1, le=MAX_PAGES)
    retry_allowed: Literal[False] = False
    trust: Literal["untrusted_external_document"] = "untrusted_external_document"

    @model_validator(mode="after")
    def coherent_outcome(self):
        document_fields = (
            self.document_sha256,
            self.source_sha256,
            self.byte_length,
            self.pages,
        )
        if self.state == "not_attempted":
            if (
                self.attempted
                or self.provider_read_state != "unchanged_by_this_attempt"
                or self.content_available
            ):
                raise ValueError("invalid undispatched receipt")
        elif not self.attempted or self.provider_read_state == "unchanged_by_this_attempt":
            raise ValueError("dispatched receipt must preserve read mutation")
        if self.state == "acquired":
            if (
                not self.content_available
                or self.response_sha256 is None
                or any(v is None for v in document_fields)
            ):
                raise ValueError("acquired receipt needs exact document custody")
        elif self.content_available or any(v is not None for v in document_fields):
            raise ValueError("unavailable receipt cannot publish document custody")
        return self


@dataclass(frozen=True, repr=False)
class Acquired:
    receipt: ImageReceipt
    document: bytes | None = field(repr=False)
