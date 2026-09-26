"""Fresh private encounter choices for an already bound incoming source."""

from pydantic import Field

from cosmas_os.api.inbox_work_schemas import Scope
from cosmas_os.api.vendor_work_schemas import (
    ID,
    ContractVersion,
    Digest,
    Output,
    Positive,
    Timestamp,
)


class ReviewTarget(Output):
    workspace_id: ID
    expected_workspace_revision: Positive
    appointment_id: ID
    label: str = Field(min_length=1, max_length=200)
    start_at: Timestamp


class ReviewOptions(Output):
    contract_version: ContractVersion
    scope: Scope
    item_id: ID
    item_version: Positive
    source_id: ID
    source_sha256: Digest
    patient_link_id: ID
    choices: list[ReviewTarget] = Field(max_length=100)
    options_sha256: Digest
