"""Optional personal Microsoft connection in the normal workspace lifecycle."""

from contextlib import contextmanager

from cosmas_os.adapters.microsoft_connection import MicrosoftPersonalConnection
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.application.microsoft_message import install_binding_reader
from cosmas_os.application.workspace import WorkspaceError


@contextmanager
def microsoft_connection_lifespan(app, settings, sessions):
    service = None
    try:
        if settings.workspace_microsoft_connection_enabled:
            service = MicrosoftPersonalConnection(settings, sessions)
        app.state.microsoft_connection = service
        def binding_reader(session, account, require_full):
            if service is None or not settings.workspace_microsoft_message_available:
                raise WorkspaceError("microsoft_message_unavailable", 404)
            identity = RequestIdentity(account.box_id, account.principal_id, "clerk_jwt",
                                       account.organization_id, account.id)
            return service.message_binding(identity, require_full=require_full, session=session)

        with install_binding_reader(binding_reader):
            yield
    finally:
        app.state.microsoft_connection = None
        if service is not None:
            service.close()
