from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AuthSubject:
    principal_id: str
    principal_type: str
    display_name: str
    is_owner: bool


class AuthPort(Protocol):
    def get_subject(self, subject_id: str) -> AuthSubject: ...


@dataclass(frozen=True)
class ScheduleAppointment:
    external_id: str
    start_at: datetime
    patient_label: str
    source: str = "csv"


class SchedulePort(Protocol):
    def import_appointments(self, csv_text: str) -> list[ScheduleAppointment]: ...


@dataclass(frozen=True)
class NotifyRequest:
    operation_id: str
    channel: str
    body: str
    target_ref: str


@dataclass(frozen=True)
class NotifyReceipt:
    external_reference: str
    status: str  # succeeded | failed | unknown


class NotifyPort(Protocol):
    def send(self, request: NotifyRequest) -> NotifyReceipt: ...


class BlobPort(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str) -> str: ...
    def get_bytes(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def issue_upload_token(self, artifact_id: str) -> str: ...
    def consume_upload_token(self, token: str) -> str: ...


class ClockPort(Protocol):
    def now(self) -> datetime: ...
