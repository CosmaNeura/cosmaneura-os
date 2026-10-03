"""Provider-neutral inbound planning; no account discovery, I/O or patient inference."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from cosmas_os.ports.vendor_connectors import ConnectionSelection

MAX_METADATA_BYTES = 131072
MAX_PDF_BYTES = 1048576


class InboundFailure(Exception):
    """Diagnostics expose a bounded reason only, never provider content."""


def commitment(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, repr=False)
class ReadScope:
    selection: ConnectionSelection
    starts_at: datetime
    ends_at: datetime
    request_id: UUID
    limit: int = 25
    account_timezone: str | None = None
    account_date_format: str | None = None
    received_status: str | None = None
    conversation_id: str | None = None
    internal_endpoint_id: str | None = None

    def __post_init__(self):
        if (
            type(self.selection) is not ConnectionSelection
            or self.selection.vendor not in {"spruce", "srfax", "documo"}
            or type(self.limit) is not int
            or not 1 <= self.limit <= 25
            or type(self.starts_at) is not datetime
            or type(self.ends_at) is not datetime
            or self.starts_at.tzinfo is None
            or self.ends_at.tzinfo is None
            or not timedelta(0) < self.ends_at - self.starts_at <= timedelta(days=7)
            or type(self.request_id) is not UUID
        ):
            raise InboundFailure("scope_invalid")
        ConnectionSelection.model_validate(self.selection.model_dump())

    def key(self):
        return commitment(
            {
                "selection": self.selection.commitment(),
                "request": str(self.request_id),
                "start": self.starts_at.isoformat(),
                "end": self.ends_at.isoformat(),
                "limit": self.limit,
                "timezone": self.account_timezone,
                "date_format": self.account_date_format,
                "received_status": self.received_status,
                "conversation": self.conversation_id,
                "endpoint": self.internal_endpoint_id,
            }
        )


@dataclass(frozen=True, repr=False)
class WirePlan:
    method: str
    path: str
    fields: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, repr=False)
class ReceivedFax:
    scope_sha256: str
    locator: tuple[str, ...]
    received_at: datetime
    pages: int
    size: int | None
    viewed: bool | None
    image_available: bool
    image_block_reason: str | None = None
    private_image_url: str | None = field(default=None, repr=False)

    def __post_init__(self):
        import re

        if (
            type(self.scope_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.scope_sha256) is None
            or type(self.locator) is not tuple
            or not 1 <= len(self.locator) <= 3
            or any(
                type(v) is not str
                or not 1 <= len(v) <= 160
                or any(ord(c) < 33 or ord(c) > 126 for c in v)
                for v in self.locator
            )
            or type(self.received_at) is not datetime
            or self.received_at.tzinfo is None
            or type(self.pages) is not int
            or not 0 <= self.pages <= 10000
            or self.size is not None
            and (type(self.size) is not int or not 0 <= self.size <= 16777216)
            or self.viewed is not None
            and type(self.viewed) is not bool
            or type(self.image_available) is not bool
            or self.image_available
            and self.pages < 1
        ):
            raise InboundFailure("locator_invalid")

    def key(self):
        return commitment(
            {
                "scope": self.scope_sha256,
                "locator": self.locator,
                "at": self.received_at.isoformat(),
                "pages": self.pages,
                "size": self.size,
                "viewed": self.viewed,
                "image_available": self.image_available,
                "block": self.image_block_reason,
                "url_commitment": hashlib.sha256(self.private_image_url.encode()).hexdigest()
                if self.private_image_url
                else None,
            }
        )


@dataclass(frozen=True, repr=False)
class MetadataPage:
    scope: ReadScope
    items: tuple[ReceivedFax, ...]
    continuation: str
    raw_sha256: str
    inbox_complete: bool = False


@dataclass(frozen=True, repr=False)
class ImageApproval:
    scope_sha256: str
    source_sha256: str
    approved_by: UUID
    expires_at: datetime

    def check(self, scope: ReadScope, source: ReceivedFax, now: datetime):
        if (
            type(source) is not ReceivedFax
            or self.scope_sha256 != scope.key()
            or source.scope_sha256 != scope.key()
            or self.source_sha256 != source.key()
            or self.approved_by != scope.selection.owner_id
            or type(self.expires_at) is not datetime
            or type(now) is not datetime
            or self.expires_at.tzinfo is None
            or now.tzinfo is None
            or not now < self.expires_at <= now + timedelta(minutes=10)
        ):
            raise InboundFailure("approval_changed")
        if not source.image_available:
            raise InboundFailure(source.image_block_reason or "image_unavailable")


def bounded_json(raw: bytes, maximum=MAX_METADATA_BYTES):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
            raise ValueError
        result = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        if type(result) is not dict:
            raise ValueError
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise InboundFailure("metadata_invalid") from None


def timestamp(value):
    try:
        if type(value) is not str:
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result
    except ValueError:
        raise InboundFailure("metadata_invalid") from None


def count(value, maximum=10000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise InboundFailure("metadata_invalid")
    return value


def checked_page(scope, raw, items, continuation="unknown"):
    if len(items) > scope.limit or len({x.locator for x in items}) != len(items):
        raise InboundFailure("metadata_invalid")
    if any(not scope.starts_at <= x.received_at <= scope.ends_at for x in items):
        raise InboundFailure("metadata_invalid")
    return MetadataPage(
        scope,
        tuple(sorted(items, key=lambda x: x.received_at, reverse=True)),
        continuation,
        hashlib.sha256(raw).hexdigest(),
    )


async def validate_pdf(raw: bytes):
    # Reuse the isolated parser; this does not save, send, log or mark a fax viewed.
    from cosmas_os.adapters.efax_pdf_validation import validate_received_pdf

    try:
        return await validate_received_pdf(raw)
    except Exception:
        raise InboundFailure("document_needs_human") from None
