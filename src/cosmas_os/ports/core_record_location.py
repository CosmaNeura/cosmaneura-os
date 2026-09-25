"""A checked navigation destination; never a clinical save or review receipt."""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime

from cosmas_os.ports.core_capture import AppointmentRef, CoreCaptureBindingSnapshot
from cosmas_os.ports.scribe_capture import ProtectedModel

_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def valid_core_web_origin(value: str) -> bool:
    """Only one canonical HTTPS origin; no renderer-selected destination."""
    if not isinstance(value, str) or not value.startswith("https://"):
        return False
    host = value.removeprefix("https://")
    if len(value) > 255 or not (_HOST.fullmatch(host) and all(_LABEL.fullmatch(part) for part in host.split("."))):
        return False
    last = host.rsplit(".", 1)[-1]
    return "." in host and bool(re.match(r"[a-z]", last))


class CoreRecordLocation(ProtectedModel):
    contract_version: Literal[1] = 1
    workspace_id: UUID
    appointment_ref: AppointmentRef
    href: str
    checked_at: AwareDatetime


def record_location(origin: str, workspace_id: UUID, binding: CoreCaptureBindingSnapshot) -> CoreRecordLocation:
    if not valid_core_web_origin(origin) or binding.workspace_id != workspace_id:
        raise ValueError("invalid_record_location")
    if not datetime.now(UTC) - timedelta(seconds=30) <= binding.checked_at <= datetime.now(UTC) + timedelta(seconds=5):
        raise ValueError("record_location_expired")
    return CoreRecordLocation(workspace_id=workspace_id, appointment_ref=binding.appointment_ref,
        href=f"{origin}/notes/{binding.appointment_ref}", checked_at=binding.checked_at)
