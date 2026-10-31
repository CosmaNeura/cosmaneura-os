"""Root-owned provisioning qualification port; no caller-provided destinations."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WorkspaceConfirmationRequest:
    practice_id: str
    box_id: str
    organization_id: str
    workspace_api_origin: str
    workspace_url: str
    source_commit: str
    image_sha256: str
    issuer: str
    subject: str
    email: str
    display_name: str
    role: str


@dataclass(frozen=True)
class WorkspaceConfirmationResult:
    # None means membership prepared, never admitted to a clinical workspace.
    proof_sha256: str | None


class WorkspaceConfirmer(Protocol):
    def confirm(self, request: WorkspaceConfirmationRequest, workspace_token: str) -> WorkspaceConfirmationResult: ...


class ProductionWorkspaceConfirmer(ABC):
    """Only a real root provisioner may be installed in the production entrypoint."""

    @abstractmethod
    def confirm(self, request: WorkspaceConfirmationRequest, workspace_token: str) -> WorkspaceConfirmationResult:
        raise NotImplementedError
