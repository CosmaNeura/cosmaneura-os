from pydantic import Field

from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.ports.routines import BriefSchedule
from cosmas_os.ports.scribe_capture import ProtectedModel


class RoutineSave(ProtectedModel):
    expected_revision: int = Field(strict=True, ge=0)
    team_revision: int = Field(strict=True, ge=1)
    idempotency_key: IdempotencyKey
    configuration: BriefSchedule
