"""Optional personal Google connection in the normal workspace lifecycle."""

from contextlib import contextmanager

from cosmas_os.adapters.google_connection import GooglePersonalConnection
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.application.google_calendar import (
    install_binding_reader as install_calendar_binding_reader,
)
from cosmas_os.application.google_message import install_binding_reader
from cosmas_os.application.workspace import WorkspaceError


@contextmanager
def google_connection_lifespan(app, settings, sessions):
    service = None
    try:
        if settings.workspace_google_connection_enabled:
            service = GooglePersonalConnection(settings, sessions)
        app.state.google_connection = service

        def binding_reader(session, account, require_full):
            if service is None or not settings.workspace_google_message_available:
                raise WorkspaceError("google_message_unavailable", 404)
            identity = RequestIdentity(account.box_id, account.principal_id, "clerk_jwt",
                                       account.organization_id, account.id)
            return service.message_binding(identity, require_full=require_full, session=session)

        def calendar_binding_reader(session, account):
            if service is None or not settings.workspace_google_calendar_available:
                raise WorkspaceError("google_calendar_unavailable", 404)
            identity = RequestIdentity(account.box_id, account.principal_id, "clerk_jwt",
                                       account.organization_id, account.id)
            return service.calendar_binding(identity, session=session)

        with install_binding_reader(binding_reader), install_calendar_binding_reader(calendar_binding_reader):
            yield
    finally:
        app.state.google_connection = None
        if service is not None:
            service.close()
