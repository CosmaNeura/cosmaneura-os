"""Read-only evidence from the exact latest saved membership result."""

from pydantic import Field

from cosmas_os.api.finance_work_schemas import FinanceDetail, FinanceResponse, FinanceVerify
from cosmas_os.api.membership_work_schemas import Scope
from cosmas_os.api.vendor_work_schemas import ID, ContractVersion, Digest, Output, Positive


class SavedMembershipBinding(Output):
    ticket_id: ID
    version: Positive = Field(le=100)
    revision_id: ID
    payload_hash: Digest
    result_receipt_id: ID
    result_receipt_sha256: Digest


class MembershipSavedFinance(Output):
    contract_version: ContractVersion
    scope: Scope
    membership: SavedMembershipBinding
    request: FinanceVerify
    receipt: FinanceResponse
    detail: FinanceDetail
