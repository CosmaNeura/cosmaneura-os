"""Grant-aware status uses synthetic custody only, without any provider reads."""

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from tests.unit.test_personal_connection_failure import connection as connection
from tests.unit.test_personal_connection_failure import start

from cosmas_os.adapters.google_connection import CALENDAR_SCOPE, GooglePersonalConnection
from cosmas_os.api.google_connection_routes import HEADERS, PATH, router
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.models import ExternalIdentity


def client(case):
    app = FastAPI()
    app.include_router(router(runtime=lambda: case.service,
        identity_dependency=lambda: case.identity, workspace_gate=lambda: None))
    def problem(_, error: Exception):
        assert isinstance(error, WorkspaceError)
        return JSONResponse({"detail": error.code}, status_code=error.status, headers=HEADERS)
    app.add_exception_handler(WorkspaceError, problem)
    return TestClient(app, headers={"Authorization": "Bearer synthetic"})


def test_legacy_google_and_microsoft_status_keep_the_exact_public_contract(connection):
    case = connection
    assert case.service.callback(start(case), "synthetic_PRIVATE_code")
    with case.factory() as session:
        connected_at = session.get(case.service.Credential, case.account).connected_at.isoformat()
    before = len(case.requests)
    assert case.service.status(case.identity) == {
        "state": "connected", "account": {"label": "Gmail" if case.service.provider == "google" else "Invented member",
            "email": "member@example.invalid"}, "connected_at": connected_at,
    }
    assert len(case.requests) == before
    assert "PRIVATE" not in json.dumps(case.service.status(case.identity))


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
@pytest.mark.parametrize("calendar", [None, False, True])
def test_capabilities_come_from_the_sealed_grant_without_refresh_or_content_reads(connection, calendar):
    case = connection
    if calendar:
        case.scopes = "openid email https://www.googleapis.com/auth/gmail.metadata " + CALENDAR_SCOPE
    assert case.service.callback(start(case), "synthetic_PRIVATE_code")
    with case.factory() as session:
        credential = session.get(case.service.Credential, case.account)
        if calendar is None:  # A real legacy sealed credential predates the capability flag.
            private = case.service._open(credential.sealed, "credential", case.account, credential.binding_digest)
            private.pop("calendar_read")
            credential.sealed = case.service._seal(private, "credential", case.account, credential.binding_digest)
            session.commit()
        sealed = credential.sealed
    before = len(case.requests)
    with client(case) as http:
        old = http.post(PATH, json={"action": "status"}, headers={"X-Cosmas-Google-Connection": "1"})
        new = http.post(PATH, json={"action": "status", "include_capabilities": True},
            headers={"X-Cosmas-Google-Connection": "1"})
    assert old.status_code == new.status_code == 200
    assert new.json() == {**old.json(), "capabilities": {"mail": True, "calendar": calendar is True}}
    assert new.headers["cache-control"] == "no-store"
    assert "PRIVATE" not in new.text and "refresh" not in new.text and "token" not in new.text
    assert len(case.requests) == before
    with case.factory() as session:
        assert session.get(case.service.Credential, case.account).sealed == sealed


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
def test_pending_and_disconnected_states_never_claim_access(connection):
    case = connection
    def expect_state(expected):
        value = case.service.status(case.identity, include_capabilities=True)
        assert value["state"] == expected
        assert value["capabilities"] == {"mail": expected == "connected", "calendar": False}
    expect_state("sign_in_required")
    state = start(case)
    expect_state("sign_in_pending")
    assert case.service.callback(state, "synthetic_PRIVATE_code")
    expect_state("connected")
    start(case)
    expect_state("sign_in_pending")
    case.service.disconnect(case.identity)
    assert case.service.status(case.identity, include_capabilities=True)["capabilities"] == {"mail": False, "calendar": False}


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
def test_revoked_account_cannot_observe_capabilities(connection):
    case = connection
    assert case.service.callback(start(case), "synthetic_PRIVATE_code")
    with case.factory() as session:
        session.get(ExternalIdentity, case.account).active = False
        session.commit()
    with pytest.raises(WorkspaceError):
        case.service.status(case.identity, include_capabilities=True)


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
def test_capability_opt_in_is_status_only_and_private_failures_are_redacted(connection, monkeypatch):
    case = connection
    assert case.service.callback(start(case), "synthetic_PRIVATE_code")
    before = len(case.requests)
    with client(case) as http:
        for action in ("start", "disconnect", "mail", "calendar"):
            response = http.post(PATH, json={"action": action, "include_capabilities": True},
                headers={"X-Cosmas-Google-Connection": "1"})
            assert response.status_code == 422
        monkeypatch.setattr(case.service, "_open", lambda *args: (_ for _ in ()).throw(RuntimeError("synthetic_PRIVATE_token")))
        response = http.post(PATH, json={"action": "status", "include_capabilities": True},
            headers={"X-Cosmas-Google-Connection": "1"})
    assert response.status_code == 503 and response.json() == {"detail": "google_connection_unavailable"}
    assert len(case.requests) == before
