"""Bounded document custody beneath the durable vendor ingestion ledger.

Only the application may construct a scope from its authorized, saved artifact
record. This port supplies neither an upload token nor permission to disclose a
document. It deliberately accepts no renderer-provided storage path or URL.
"""

from typing import Literal, Protocol, get_args
from uuid import UUID

from cosmas_os.ports.scribe_capture import ProtectedModel
from cosmas_os.ports.vendor_connectors import DocumentBinding, VendorError

ArtifactErrorCode = Literal[
    "artifact_not_found", "artifact_changed", "storage_unavailable", "storage_unconfirmed"
]


class ArtifactStoreError(Exception):
    def __init__(self, code: ArtifactErrorCode):
        self.code: ArtifactErrorCode = code if code in get_args(ArtifactErrorCode) else "storage_unavailable"
        super().__init__(self.code)


class VendorArtifactScope(ProtectedModel):
    box_id: UUID
    workspace_id: UUID
    owner_id: UUID
    document: DocumentBinding

    def storage_segments(self) -> tuple[str, ...]:
        return (str(self.box_id), "vendor-documents", str(self.workspace_id),
                str(self.owner_id), f"{self.document.artifact_id}.pdf")

    def require_bytes(self, data: bytes) -> None:
        try:
            self.document.require_bytes(data)
        except VendorError:
            raise ArtifactStoreError("artifact_changed") from None


class VendorArtifactStore(Protocol):
    def put_verified(self, scope: VendorArtifactScope, data: bytes, *, deadline: float | None = None) -> None:
        """Create exclusively, or verify an existing byte-identical object.

        An unknown result is resolved by read_verified against the same durable
        record. No conflicting object is overwritten or removed.
        An API caller passes its existing absolute monotonic deadline. No new
        ordinary storage I/O starts after observed expiry. Cleanup may finish;
        a blocking OS call cannot be preempted and late success is unconfirmed.
        """
        ...

    def read_verified(self, scope: VendorArtifactScope, *, deadline: float | None = None) -> bytes:
        """Read expected size plus one, verify, and never return success after deadline."""
        ...
