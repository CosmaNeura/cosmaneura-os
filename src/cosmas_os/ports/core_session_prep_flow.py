"""Provider UI-action lifecycle surrounding a Core Session Prep brief read."""

from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from cosmas_os.ports.core_capture import (
    CoreCaptureSelection,
    CoreInteractionCredential,
    CoreMountToken,
)
from cosmas_os.ports.core_session_prep import (
    CoreSessionPrepPort,
    CoreSessionPrepRead,
    CoreSessionPrepReceipt,
    Reference,
)
from cosmas_os.ports.scribe_capture import ProtectedModel


class CoreSessionPrepContext(ProtectedModel):
    credential: CoreInteractionCredential
    context_snapshot_ref: Reference


class CoreSessionPrepFlowPort(CoreSessionPrepPort, Protocol):
    def exchange_context(
        self, selection: CoreCaptureSelection, bearer: SecretStr
    ) -> CoreMountToken: ...
    def resolve_context(
        self, selection: CoreCaptureSelection, token: CoreMountToken, client_turn_id: UUID
    ) -> CoreSessionPrepContext: ...
    def accept_action(self, context: CoreSessionPrepContext) -> CoreSessionPrepRead: ...
    def complete_action(
        self, selection: CoreSessionPrepRead, result: CoreSessionPrepReceipt
    ) -> None: ...
