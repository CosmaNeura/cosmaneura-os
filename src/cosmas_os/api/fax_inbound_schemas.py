"""Strict public commands select installed accounts, never provider URLs/secrets."""

from typing import Literal

from pydantic import Field, StrictBool

from cosmas_os.api.efax_inbound_schemas import Digest, Identifier, Key, Timestamp
from cosmas_os.ports.scribe_capture import ProtectedModel


class Grant(ProtectedModel):
    idempotency_key: Key
    connection_id: Identifier
    reviewed_account: StrictBool
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
    limit: int = Field(default=25, strict=True, ge=1, le=25)


class Propose(ProtectedModel):
    idempotency_key: Key
    grant_id: Identifier
    observation_id: Identifier
    observation_sha256: Digest
    source_sha256: Digest


class Decide(ProtectedModel):
    idempotency_key: Key
    ticket_id: Identifier
    revision_id: Identifier
    expected_version: int = Field(strict=True, ge=1, le=100)
    choice: Literal["approve", "reject"]
    reviewed_exact_fax: StrictBool


class Acquire(ProtectedModel):
    idempotency_key: Key
    ticket_id: Identifier
    revision_id: Identifier
    expected_version: int = Field(strict=True, ge=1, le=100)
    approval_sha256: Digest


class Resolve(ProtectedModel):
    idempotency_key: Key
