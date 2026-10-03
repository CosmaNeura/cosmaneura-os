"""Closed owner-only inbound commands; callers cannot provide credentials or URLs."""

import re
from typing import Annotated, Literal

from pydantic import AwareDatetime, BeforeValidator, Field, StrictBool

from cosmas_os.ports.scribe_capture import ProtectedModel

Key = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9:_-]{8,100}$")]


class SourceResolve(ProtectedModel):
    idempotency_key: Key


Identifier = Annotated[
    str,
    Field(strict=True, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


def canonical_timestamp(value):
    # A retained browser command and its public receipt hash must commit to
    # identical wire text, without offset conversion or fractional rounding.
    if type(value) is not str or re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value
    ) is None:
        raise ValueError("Canonical UTC seconds required")
    return value


Timestamp = Annotated[AwareDatetime, BeforeValidator(canonical_timestamp)]


class Grant(ProtectedModel):
    idempotency_key: Key
    installation_id: Identifier
    reviewed_account: StrictBool
    reviewed_mark_read: StrictBool
    image_enabled: StrictBool
    expires_at: Timestamp


class Revoke(ProtectedModel):
    idempotency_key: Key
    grant_id: Identifier


class Observe(ProtectedModel):
    idempotency_key: Key
    grant_id: Identifier
    starts_at: Timestamp
    ends_at: Timestamp
    limit: int = Field(strict=True, ge=1, le=25)
    offset: int = Field(strict=True, ge=0, le=5000)


class Propose(ProtectedModel):
    idempotency_key: Key
    grant_id: Identifier
    observation_id: Identifier
    observation_sha256: Digest
    fax_id: Identifier
    fax_sha256: Digest


class Decide(ProtectedModel):
    idempotency_key: Key
    ticket_id: Identifier
    revision_id: Identifier
    expected_version: int = Field(strict=True, ge=1, le=100)
    choice: Literal["approve", "reject"]
    reviewed_mark_read: StrictBool


class Acquire(ProtectedModel):
    idempotency_key: Key
    ticket_id: Identifier
    revision_id: Identifier
    expected_version: int = Field(strict=True, ge=1, le=100)
    approval_sha256: Digest


class Resolve(ProtectedModel):
    idempotency_key: Key
    kind: Literal["command", "observation", "image"]
