"""Optional personal Microsoft connection in the normal workspace lifecycle."""

from contextlib import contextmanager

from cosmas_os.adapters.microsoft_connection import MicrosoftPersonalConnection


@contextmanager
def microsoft_connection_lifespan(app, settings, sessions):
    service = None
    try:
        if settings.workspace_microsoft_connection_enabled:
            service = MicrosoftPersonalConnection(settings, sessions)
        app.state.microsoft_connection = service
        yield
    finally:
        app.state.microsoft_connection = None
        if service is not None:
            service.close()
