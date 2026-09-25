from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from cosmas_os.api.capture_schemas import CaptureBotSelection
from cosmas_os.api.note_schemas import Digest
from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.ports.scheduling import AvailabilitySlot, AvailabilityWindow
from cosmas_os.ports.scribe_capture import ProtectedModel


class WorkspaceAvailabilityRequest(ProtectedModel):
    bot: CaptureBotSelection
    window: AvailabilityWindow


class AppointmentDecision(ProtectedModel):
    revision_id: UUID
    payload_hash: Digest
    choice: Literal["approve", "reject"]


class AppointmentExecutionRequest(ProtectedModel):
    operation_id: UUID
    revision_id: UUID
    payload_hash: Digest
    mode: Literal["submit", "reconcile", "retry"]


class CurrentAppointmentRequest(ProtectedModel):
    bot: CaptureBotSelection


class AppointmentPrepare(CurrentAppointmentRequest):
    action: Literal["book", "reschedule", "cancel"]
    slot: AvailabilitySlot | None = None
    share: bool = Field(strict=True)
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def selected_action(self):
        if not self.share or (self.action == "cancel") != (self.slot is None):
            raise ValueError("Select an exact action and explicitly share its proposal")
        return self
