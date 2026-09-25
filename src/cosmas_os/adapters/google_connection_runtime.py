"""Optional personal Google connection in the normal workspace lifecycle."""

from contextlib import contextmanager

from cosmas_os.adapters.google_connection import GooglePersonalConnection


@contextmanager
def google_connection_lifespan(app, settings, sessions):
    service = None
    try:
        if settings.workspace_google_connection_enabled:
            service = GooglePersonalConnection(settings, sessions)
        app.state.google_connection = service
        yield
    finally:
        app.state.google_connection = None
        if service is not None:
            service.close()
