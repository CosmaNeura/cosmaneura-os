"""Personal mailbox consent must finish in the browser that started it.

The provider HTTP stand-in only answers the token, profile, mail and calendar
requests the connection service already makes. Custody, callback routing and
the session reads are the product code.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker
from tests.unit.test_google_callback_broker import journey as journey
from tests.unit.test_google_callback_broker import start as broker_start

from cosmas_os.adapters.google_connection import (
    CALENDAR_URL,
    FULL_MAIL_SCOPE,
    GMAIL_ORIGIN,
    MESSAGES_PATH,
    USERINFO_URL,
    GooglePersonalConnection,
)
from cosmas_os.adapters.microsoft_connection import (
    GRAPH_ORIGIN,
    MicrosoftPersonalConnection,
)
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.api.google_connection_routes import (
    PATH as GOOGLE_PATH,
)
from cosmas_os.api.google_connection_routes import (
    GoogleConnectionBoundary,
)
from cosmas_os.api.google_connection_routes import (
    router as google_router,
)
from cosmas_os.api.microsoft_connection_routes import (
    PATH as MICROSOFT_PATH,
)
from cosmas_os.api.microsoft_connection_routes import (
    MicrosoftConnectionBoundary,
)
from cosmas_os.api.microsoft_connection_routes import (
    router as microsoft_router,
)
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.models import BoxContext, ExternalIdentity, Principal
from cosmas_os.ports.google_message import GoogleMessageSelection

SESSION = "Bearer placeholder-session"
BASE = "https://api.example.invalid"
OWNER = {
    "email": "owner@example.invalid",
    "subject": "invented_owner_google",
    "microsoft_id": "11111111-1111-4111-8111-111111111111",
    "note": "Owner inbox note",
    "shift": "Owner shift",
    "body": "Owner administrative note",
    "code": "placeholder-owner-code",
    "token": "placeholder-owner-access",
    "refresh": "placeholder-owner-refresh",
}
VICTIM = {
    "email": "physician@example.invalid",
    "subject": "invented_physician_google",
    "microsoft_id": "22222222-2222-4222-8222-222222222222",
    "note": "Physician inbox note",
    "shift": "Physician shift",
    "body": "Physician administrative note",
    "code": "placeholder-victim-code",
    "token": "placeholder-victim-access",
    "refresh": "placeholder-victim-refresh",
}
PEOPLE = (OWNER, VICTIM)


def _person_from_token(request):
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ")
    return next(person for person in PEOPLE if person["token"] == token)


def _google_scope(full):
    scopes = (
        "openid email https://www.googleapis.com/auth/gmail.metadata "
        "https://www.googleapis.com/auth/calendar.events.readonly"
    )
    if full:
        scopes += " " + FULL_MAIL_SCOPE
    return scopes


def _stamp():
    return str(int((datetime.now(UTC) - timedelta(days=1)).timestamp() * 1000))


def _gmail(person, *, full):
    message = {
        "id": "inventedmsg",
        "threadId": "inventedthread",
        "historyId": "101",
        "internalDate": _stamp(),
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "filename": "",
            "headers": [
                {"name": "Subject", "value": person["note"]},
                {"name": "From", "value": "Invented Sender <sender@example.invalid>"},
            ],
        },
    }
    if full:
        raw = person["body"].encode()
        message["payload"]["body"] = {
            "size": len(raw),
            "data": base64.urlsafe_b64encode(raw).decode().rstrip("="),
        }
    return message


def _google_events(person):
    start = datetime.now(UTC) + timedelta(days=1)
    end = start + timedelta(hours=1)
    return {"items": [{
        "id": "inventedevent",
        "summary": person["shift"],
        "status": "confirmed",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }]}


def _microsoft_events(person):
    start = datetime.now(UTC) + timedelta(days=1)
    end = start + timedelta(hours=1)
    clock = "%Y-%m-%dT%H:%M:%S"
    return {"value": [{
        "id": "inventedevent",
        "subject": person["shift"],
        "start": {"dateTime": start.strftime(clock), "timeZone": "UTC"},
        "end": {"dateTime": end.strftime(clock), "timeZone": "UTC"},
        "isCancelled": False,
        "isAllDay": False,
    }]}


def _json(payload):
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        stream=httpx.ByteStream(json.dumps(payload).encode()),
    )


@pytest.fixture(params=[
    ("google", "start"),
    ("google", "start_full_mail"),
    ("microsoft", "start"),
])
def desk(request, engine):
    provider, action = request.param
    factory = sessionmaker(engine, expire_on_commit=False)
    box, owner, account = (str(uuid4()) for _ in range(3))
    with factory.begin() as session:
        session.add(BoxContext(id=box, display_name="Invented practice"))
        session.flush()
        session.add(Principal(
            id=owner, box_id=box, principal_type="human", display_name="Invented owner",
        ))
        session.flush()
        session.add(ExternalIdentity(
            id=account, box_id=box, principal_id=owner,
            issuer="https://identity.example.invalid", subject="invented_" + account,
            organization_id="invented_org", active=True, reviewed_by="invented",
            evidence_ref="invented:oauth-binding",
        ))
    settings = SimpleNamespace(
        workspace_available=True, workspace_authenticated_enabled=True, auth_mode="clerk_jwt",
        workspace_microsoft_connection_enabled=True, workspace_google_connection_enabled=True,
        workspace_google_message_available=True,
        microsoft_connection_tenant_id=str(uuid4()), microsoft_connection_client_id=str(uuid4()),
        google_connection_client_id="invented.apps.googleusercontent.com",
        google_connection_broker_enabled=False,
    )
    for name in ("microsoft", "google"):
        setattr(settings, name + "_connection_return_origin", "https://os.example.invalid")
        setattr(settings, name + "_connection_callback_uri",
                "https://api.example.invalid/connections/" + name + "/callback")
        setattr(settings, name + "_connection_client_secret", SecretStr("placeholder-client-secret"))
        setattr(settings, name + "_connection_encryption_key",
                SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode()))
    case = SimpleNamespace(
        factory=factory, requests=[], provider=provider, action=action,
        full=action == "start_full_mail", account=account, box=box, owner=owner,
        identity=RequestIdentity(box, owner, "clerk_jwt", "invented_org", account),
    )

    def respond(incoming):
        case.requests.append(incoming)
        microsoft = provider == "microsoft"
        if incoming.method == "POST":
            form = parse_qs(incoming.content.decode())
            code = (form.get("code") or form.get("refresh_token") or [None])[0]
            person = next(item for item in PEOPLE if code in {item["code"], item["refresh"]})
            scope = ("User.Read Mail.Read Calendars.Read" if microsoft else _google_scope(case.full))
            return _json({
                "access_token": person["token"], "refresh_token": person["refresh"],
                "expires_in": 3600, "token_type": "Bearer", "scope": scope,
            })
        person = _person_from_token(incoming)
        url = str(incoming.url).split("?", 1)[0]
        if url == USERINFO_URL:
            return _json({"sub": person["subject"], "email": person["email"], "email_verified": True})
        if url == GRAPH_ORIGIN + "/v1.0/me":
            return _json({
                "id": person["microsoft_id"], "displayName": "Invented member", "mail": person["email"],
            })
        if url == CALENDAR_URL:
            return _json(_google_events(person))
        if url == GRAPH_ORIGIN + "/v1.0/me/calendarView":
            return _json(_microsoft_events(person))
        if url == GRAPH_ORIGIN + "/v1.0/me/mailFolders/inbox/messages":
            return _json({"value": [{
                "id": "inventedmessage", "subject": person["note"], "isRead": False,
                "from": {"emailAddress": {"address": "sender@example.invalid"}},
                "receivedDateTime": "2026-11-01T15:00:00Z",
            }]})
        if url == GMAIL_ORIGIN + MESSAGES_PATH:
            return _json({"messages": [{"id": "inventedmsg"}]})
        if url == GMAIL_ORIGIN + MESSAGES_PATH + "/inventedmsg":
            return _json(_gmail(person, full=incoming.url.params.get("format") == "full"))
        raise AssertionError("unexpected provider request")

    connection = (GooglePersonalConnection if provider == "google" else MicrosoftPersonalConnection)
    case.service = connection(settings, factory, transport=httpx.MockTransport(respond))
    case.path = GOOGLE_PATH if provider == "google" else MICROSOFT_PATH
    case.callback_path = "/connections/" + provider + "/callback"
    case.header = ("X-Cosmas-Google-Connection" if provider == "google"
                   else "X-Cosmas-Microsoft-Connection")
    app = FastAPI()

    def identity(request: Request):
        # The product session route requires one bearer. The provider redirect
        # does not carry that header; this dependency must not run for it.
        if request.headers.get("authorization") != SESSION:
            raise HTTPException(status_code=401, detail="bearer token required")
        return case.identity

    def gate():
        return None

    routes = google_router if provider == "google" else microsoft_router
    boundary = GoogleConnectionBoundary if provider == "google" else MicrosoftConnectionBoundary
    app.include_router(routes(runtime=lambda: case.service, identity_dependency=identity, workspace_gate=gate))

    def problem(_, error: WorkspaceError):
        return JSONResponse({"detail": error.code}, status_code=error.status)

    app.add_exception_handler(WorkspaceError, problem)
    app.add_middleware(boundary)
    case.app = app
    try:
        yield case
    finally:
        case.service.close()


def _client(case):
    return TestClient(case.app, base_url=BASE)


def _headers(case, *, authenticated):
    headers = {case.header: "1"}
    if authenticated:
        headers["Authorization"] = SESSION
    return headers


def _start(case, client):
    response = client.post(case.path, json={"action": case.action}, headers=_headers(case, authenticated=True))
    assert response.status_code == 200, response.text
    parts = urlsplit(response.json()["authorization_url"])
    if case.provider == "google":
        assert parts.scheme == "https" and parts.netloc == "accounts.google.com"
    else:
        assert parts.scheme == "https" and parts.netloc == "login.microsoftonline.com"
    return parse_qs(parts.query)["state"][0]


def _finish(client, case, state, code):
    # A provider redirect is a top-level GET. It has the copied state and code,
    # and no CosmaBot bearer.
    return client.get(
        case.callback_path, params={"state": state, "code": code}, follow_redirects=False,
    )


def _custody(case):
    with case.factory() as session:
        attempts = session.scalars(select(case.service.Attempt).where(
            case.service.Attempt.account_id == case.account,
        )).all()
        credential = session.get(case.service.Credential, case.account)
        return (
            len(case.requests),
            tuple(sorted(
                (row.id, row.status, bytes(row.sealed) if row.sealed else None, row.state_digest)
                for row in attempts
            )),
            None if credential is None else (
                credential.status, bytes(credential.sealed) if credential.sealed else None,
            ),
        )


def _views(case, client):
    headers = _headers(case, authenticated=True)
    text = ""
    for action in ("mail", "calendar", "status"):
        response = client.post(case.path, json={"action": action}, headers=headers)
        text += response.text
    if case.action == "start_full_mail":
        try:
            reading = case.service.read_message(
                case.identity, GoogleMessageSelection(message_id="inventedmsg"),
            )
        except WorkspaceError:
            reading = None
        if reading is not None and reading.content:
            text += reading.content
    return text


def _assert_victim_not_attached(case, client, before):
    disclosed = _views(case, client)
    assert VICTIM["email"] not in disclosed
    assert VICTIM["note"] not in disclosed
    assert VICTIM["shift"] not in disclosed
    assert VICTIM["body"] not in disclosed
    assert VICTIM["subject"] not in disclosed
    assert VICTIM["microsoft_id"] not in disclosed
    # Exchanging the code, or marking the attempt exchanged, is a side effect
    # even when the response text no longer shows the mailbox.
    assert _custody(case) == before


def test_initiating_client_can_connect_and_read_its_own_mailbox(desk):
    case = desk
    with _client(case) as browser:
        state = _start(case, browser)
        finished = _finish(browser, case, state, OWNER["code"])
        assert finished.status_code == 303
        assert finished.headers["location"].endswith("#" + case.provider + "-connected")
        disclosed = _views(case, browser)
    assert OWNER["email"] in disclosed and OWNER["note"] in disclosed and OWNER["shift"] in disclosed
    assert VICTIM["email"] not in disclosed and VICTIM["note"] not in disclosed
    with case.factory() as session:
        credential = session.get(case.service.Credential, case.account)
        assert credential is not None and credential.status == "ready"
        private = case.service._open(
            credential.sealed, "credential", case.account, credential.binding_digest,
        )
    if case.provider == "google":
        assert private["subject"] == OWNER["subject"] and private["email"] == OWNER["email"]
        assert private["mail_full_read"] is (case.action == "start_full_mail")
        if case.action == "start_full_mail":
            assert OWNER["body"] in disclosed
    else:
        assert private["subject"] == OWNER["microsoft_id"] and private["email"] == OWNER["email"]


def test_forwarded_provider_consent_does_not_attach_the_other_mailbox(desk):
    case = desk
    with _client(case) as attacker:
        state = _start(case, attacker)
        refused = attacker.post(case.path, json={"action": "start"})
        assert refused.status_code == 401
    before = _custody(case)
    with _client(case) as victim:
        assert list(victim.cookies) == []
        _finish(victim, case, state, VICTIM["code"])
        _assert_victim_not_attached(case, victim, before)


def test_forwarded_provider_consent_does_not_replace_the_connected_mailbox(desk):
    case = desk
    with _client(case) as browser:
        _finish(browser, case, _start(case, browser), OWNER["code"])
        state = _start(case, browser)
        owned = _custody(case)
    with _client(case) as victim:
        assert list(victim.cookies) == []
        _finish(victim, case, state, VICTIM["code"])
    with _client(case) as browser:
        disclosed = _views(case, browser)
    assert OWNER["email"] in disclosed and OWNER["note"] in disclosed and OWNER["shift"] in disclosed
    assert VICTIM["email"] not in disclosed and VICTIM["note"] not in disclosed
    assert VICTIM["shift"] not in disclosed and VICTIM["body"] not in disclosed
    _, attempts, credential = _custody(case)
    assert (attempts, credential) == owned[1:]
    assert not any(request.method == "POST" for request in case.requests[owned[0]:])


@pytest.fixture
def mailbox_broker(journey):
    """Drop this journey's box identity so the next case can reuse the fixture subject."""
    try:
        yield journey
    finally:
        with journey.box_factory.begin() as session:
            session.execute(delete(journey.service.Attempt).where(
                journey.service.Attempt.account_id == journey.account,
            ))
            session.execute(delete(journey.service.Credential).where(
                journey.service.Credential.account_id == journey.account,
            ))
            session.execute(delete(ExternalIdentity).where(ExternalIdentity.id == journey.account))


@pytest.mark.parametrize("full", [False, True])
def test_forwarded_broker_callback_does_not_exchange_or_store(mailbox_broker, full):
    case = mailbox_broker
    state = broker_start(case, full=full)
    assert case.calls == []
    with case.box_factory() as session:
        attempt = session.scalar(select(case.service.Attempt).where(
            case.service.Attempt.account_id == case.account,
        ))
        before = (attempt.id, attempt.status, bytes(attempt.sealed), attempt.state_digest)
        assert session.get(case.service.Credential, case.account) is None
    # Registration may have used this client. The colleague's browser only has
    # the state copied out of the authorization URL.
    case.central.cookies.clear()
    response = case.central.get(
        "/connections/google/callback",
        params={"state": state, "code": VICTIM["code"]},
    )
    assert case.calls == []
    assert "connection complete" not in response.text
    with case.box_factory() as session:
        attempt = session.get(case.service.Attempt, before[0])
        account = session.get(ExternalIdentity, case.account)
        assert (attempt.id, attempt.status, bytes(attempt.sealed), attempt.state_digest) == before
        assert session.get(case.service.Credential, case.account) is None
        identity = RequestIdentity(
            case.box, account.principal_id, "clerk_jwt", case.org, case.account,
        )
    status = case.service.status(identity)
    assert status["state"] != "connected"
    assert status["account"] is None
