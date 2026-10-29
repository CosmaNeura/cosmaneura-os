"""Explicit file upload metadata and exact source review/recovery commands."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator

from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.ports.calendar_imports import Digest, Protected, ReportedSource, Window


class Status(Protected):
    action: Literal["status"]


class ListImports(Protected):
    action: Literal["list"]


class Upload(Protected):
    action: Literal["upload"]
    idempotency_key: IdempotencyKey
    byte_sha256: Digest
    file_base64: str = Field(strict=True, min_length=4, max_length=1398104)
    window: Window
    reported_source: ReportedSource


class Inspect(Protected):
    action: Literal["inspect"]
    import_id: UUID


class Resolve(Protected):
    action: Literal["resolve"]
    idempotency_key: IdempotencyKey


class Revoke(Protected):
    action: Literal["revoke"]
    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: IdempotencyKey
    import_id: UUID
    source_sha256: Digest


COMMAND = TypeAdapter(Annotated[Status | ListImports | Upload | Inspect | Resolve | Revoke, Field(discriminator="action")])


class Review(Protected):
    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: IdempotencyKey
    import_id: UUID
    source_sha256: Digest
    item_index: int = Field(strict=True, ge=0, lt=500)
    item_sha256: Digest
    reviewed_visit: Literal[True]
    reviewed_exact_summary: Literal[True]
    reviewed_untrusted_source: Literal[True]

    @field_validator("reviewed_visit", "reviewed_exact_summary", "reviewed_untrusted_source", mode="before")
    @classmethod
    def explicit_review(cls, value):
        if value is not True:
            raise ValueError("explicit_calendar_import_review_required")
        return value
