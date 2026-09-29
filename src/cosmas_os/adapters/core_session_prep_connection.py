"""Bounded Session Prep service identity and transport, with no capture fallback."""

from contextlib import contextmanager
from datetime import UTC, datetime

from azure.identity import ManagedIdentityCredential

from cosmas_os.adapters.core_capture_connection import _CoreClient
from cosmas_os.adapters.core_record_connection import BoundedIdentityTransport
from cosmas_os.adapters.core_session_prep_flow import HttpCoreSessionPrepFlow
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable

SESSION_PREP_PATH_LIMITS = {
    "/embed/v1/context-tokens/exchange": 16384,
    "/service/v1/agent/mount-context/resolve": 16384,
    "/service/v1/agent/conversation-turns/write": 16384,
    "/service/v1/companion/session-prep/brief": 262144,
}


class BoundedSessionPrepConnection(HttpCoreSessionPrepFlow):
    def __init__(
        self,
        origin,
        workload_token,
        budget,
        *,
        transport_factory=None,
        now=lambda: datetime.now(UTC),
    ):
        budget.check()

        def token():
            budget.check()
            value = workload_token()
            budget.check()
            return value

        super().__init__(origin, token, now=now)
        self._client.close()
        self._client = _CoreClient(
            self._origin, budget, transport_factory, path_limits=SESSION_PREP_PATH_LIMITS
        )


@contextmanager
def session_prep_connection(settings, budget):
    budget.check()
    if not settings.workspace_session_prep_available:
        raise ConnectorUnavailable("session_prep_unavailable")
    transport = BoundedIdentityTransport(budget)
    try:
        credential = ManagedIdentityCredential(
            client_id=settings.core_session_prep_managed_identity_client_id,
            transport=transport,
            retry_total=0,
            retry_connect=0,
            retry_read=0,
            retry_status=0,
        )
        try:
            connection = BoundedSessionPrepConnection(
                settings.core_capture_origin,
                lambda: credential.get_token(settings.core_session_prep_scope).token,
                budget,
            )
            try:
                yield connection
            finally:
                connection.close()
        finally:
            credential.close()
    finally:
        transport.close()
