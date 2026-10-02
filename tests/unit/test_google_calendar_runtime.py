"""Calendar review is an explicit gate, separate from whole-email consent."""

from types import SimpleNamespace

import pytest

from cosmas_os.adapters import google_connection_runtime as runtime
from cosmas_os.application import google_calendar, google_message
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.config import Settings


def configuration(**overrides):
    values = dict(workspace_enabled=True, workspace_authenticated_enabled=True,
                  database_url="postgresql+psycopg://invented@127.0.0.1:54329/w1a_calendar_runtime",
                  auth_mode="clerk_jwt", synth_seed=False,
                  clerk_issuer="https://clerk.example.invalid",
                  clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
                  clerk_audience="synthetic-test", clerk_organization_id="org_invented",
                  clerk_authorized_parties="http://localhost:5173",
                  beta_box_id="00000000-0000-4000-8000-000000000001",
                  workspace_google_connection_enabled=True)
    return Settings(_env_file=None, **(values | overrides))  # pyright: ignore[reportCallIssue] -- BaseSettings runtime option.


def test_calendar_gate_default_off_and_independent_from_whole_message_consent():
    assert not configuration().workspace_google_calendar_available
    assert configuration(workspace_google_message_enabled=True).workspace_google_message_available
    assert not configuration(workspace_google_message_enabled=True).workspace_google_calendar_available
    calendar = configuration(workspace_google_calendar_enabled=True)
    assert calendar.workspace_google_calendar_available
    assert not calendar.workspace_google_message_available
    for change in (dict(workspace_google_connection_enabled=False), dict(workspace_enabled=False),
                   dict(workspace_authenticated_enabled=False), dict(auth_mode="synth_headers")):
        assert not configuration(workspace_google_calendar_enabled=True, **change).workspace_google_calendar_available


def test_lifecycle_calendar_custody_uses_caller_session_and_restores_reader_after_failure(monkeypatch):
    calls = []

    class Connection:
        def __init__(self, settings, sessions):
            self.closed = False
        def calendar_binding(self, identity, *, session):
            calls.append((identity, session))
            return "invented-current-binding"
        def close(self):
            self.closed = True

    monkeypatch.setattr(runtime, "GooglePersonalConnection", Connection)
    app = SimpleNamespace(state=SimpleNamespace())
    prior_calendar = google_calendar._binding_reader
    prior_message = google_message._binding_reader
    configured = configuration(workspace_google_calendar_enabled=True)
    account = SimpleNamespace(box_id=configured.beta_box_id, principal_id="invented-owner",
                              organization_id="org_invented", id="invented-account")
    session = object()
    with pytest.raises(RuntimeError, match="invented interrupt"):
        with runtime.google_connection_lifespan(app, configured, object()):
            connection = app.state.google_connection
            assert google_calendar._binding_reader is not None
            assert google_message._binding_reader is not None
            assert google_calendar._binding_reader(session, account) == "invented-current-binding"
            assert calls[0][1] is session
            assert calls[0][0].external_identity_id == account.id
            with pytest.raises(WorkspaceError, match="google_message_unavailable"):
                google_message._binding_reader(session, account, True)
            configured.workspace_google_calendar_enabled = False
            with pytest.raises(WorkspaceError, match="google_calendar_unavailable"):
                google_calendar._binding_reader(session, account)
            raise RuntimeError("invented interrupt")
    assert app.state.google_connection is None
    assert connection.closed
    assert google_calendar._binding_reader is prior_calendar
    assert google_message._binding_reader is prior_message
