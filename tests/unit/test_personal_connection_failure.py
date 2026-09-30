"""Real durable OAuth claims with invented identities and bounded provider HTTP."""

import base64
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from cosmas_os.adapters.google_connection import (
    CALENDAR_SCOPE,
    CALENDAR_URL,
    GooglePersonalConnection,
)
from cosmas_os.adapters.microsoft_connection import (
    MicrosoftConnectionFailure,
    MicrosoftPersonalConnection,
)
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, Principal


@pytest.fixture(params=[MicrosoftPersonalConnection, GooglePersonalConnection])
def connection(request, engine):
    factory = sessionmaker(engine, expire_on_commit=False)
    box, owner, account = (str(uuid4()) for _ in range(3))
    with factory() as session:
        session.add(BoxContext(id=box, display_name="Invented practice"))
        session.flush()
        session.add(Principal(id=owner, box_id=box, principal_type="human", display_name="Invented owner"))
        session.flush()
        session.add(ExternalIdentity(id=account, box_id=box, principal_id=owner,
            issuer="https://identity.example.invalid", subject="invented_" + account,
            organization_id="invented_org", active=True, reviewed_by="invented",
            evidence_ref="invented:oauth-test"))
        session.commit()
    settings = SimpleNamespace(workspace_available=True, workspace_authenticated_enabled=True,
        auth_mode="clerk_jwt", workspace_microsoft_connection_enabled=True,
        workspace_google_connection_enabled=True,
        microsoft_connection_tenant_id=str(uuid4()), microsoft_connection_client_id=str(uuid4()),
        google_connection_client_id="invented.apps.googleusercontent.com")
    for provider in ("microsoft", "google"):
        setattr(settings, provider + "_connection_return_origin", "https://os.example.invalid")
        setattr(settings, provider + "_connection_callback_uri", "https://api.example.invalid/connections/" + provider + "/callback")
        setattr(settings, provider + "_connection_client_secret", SecretStr("synthetic_PRIVATE_secret"))
        setattr(settings, provider + "_connection_encryption_key", SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode()))
    case = SimpleNamespace(factory=factory, fault=None, scopes=None, calls=[], requests=[], account=account, calendar_response={"items": []})

    def respond(incoming):
        case.calls.append(incoming.method)
        case.requests.append(incoming)
        microsoft = request.param is MicrosoftPersonalConnection
        if not microsoft and str(incoming.url).split("?", 1)[0] == CALENDAR_URL:
            if case.fault == "calendar_revoke":
                with factory() as session:
                    session.get(ExternalIdentity, account).active = False
                    session.commit()
            return httpx.Response(200, headers={"content-type": "application/json"},
                stream=httpx.ByteStream(json.dumps(case.calendar_response).encode()))
        if incoming.method == "POST":
            if case.fault == "exception":
                raise RuntimeError("synthetic_PRIVATE_exception")
            if case.fault == "revoke":
                with factory() as session:
                    identity = session.get(ExternalIdentity, account)
                    assert identity is not None
                    identity.active = False
                    session.commit()
            scopes = "User.Read Mail.Read Calendars.Read" if microsoft else "openid email https://www.googleapis.com/auth/gmail.metadata"
            if case.scopes is not None:
                scopes = case.scopes
            if case.fault == "scope":
                scopes += " Mail.Send"
            payload = dict(access_token="synthetic_PRIVATE_token", refresh_token="synthetic_PRIVATE_refresh",
                expires_in=3600, token_type="Bearer", scope=scopes)
        else:
            payload = dict(id=str(uuid4()), displayName="Invented member", mail="member@example.invalid") if microsoft else dict(sub="invented_member", email="member@example.invalid", email_verified=True)
        status = 400 if case.fault == "http" else 200
        return httpx.Response(status, headers={"content-type": "application/json"},
            stream=httpx.ByteStream(json.dumps(payload).encode()))

    case.service = request.param(settings, factory, transport=httpx.MockTransport(respond))
    case.identity = RequestIdentity(box, owner, "clerk_jwt", "invented_org", account)
    try:
        yield case
    finally:
        case.service.close()


def start(case):
    return parse_qs(urlsplit(case.service.start(case.identity)["authorization_url"]).query)["state"][0]


def outcomes(case):
    with case.factory() as session:
        return [(row.outcome, row.detail) for row in session.scalars(select(AuditEvent).where(
            AuditEvent.aggregate_id == case.account,
            AuditEvent.event_type.endswith("sign_in_finished"),
        ))]


@pytest.mark.parametrize("fault", ["http", "scope", "exception"])
def test_failure_is_private_durable_single_use_and_explicitly_recoverable(connection, fault, caplog):
    case = connection
    case.fault = fault
    state = start(case)
    assert case.service.callback(state, "synthetic_PRIVATE_code") is False
    reason = ({"http": "token_http", "scope": "permissions_unexpected", "exception": "token_exchange"}
        if case.service.provider == "microsoft" else
        {"http": "token_exchange", "scope": "account_verification", "exception": "token_exchange"})[fault]
    assert outcomes(case) == [("failed_" + reason, {})]
    assert case.service.status(case.identity)["state"] == "sign_in_required"
    with case.factory() as session:
        attempt = session.scalar(select(case.service.Attempt).where(case.service.Attempt.account_id == case.account))
        assert attempt.status == "failed" and attempt.sealed is None
        assert session.get(case.service.Credential, case.account) is None
    assert case.calls == ["POST"]
    assert case.service.callback(state, "synthetic_PRIVATE_code") is False
    assert case.calls == ["POST"] and len(outcomes(case)) == 1
    assert "PRIVATE" not in caplog.text and state not in caplog.text
    case.fault = None
    renewed = start(case)
    assert renewed != state
    assert case.service.callback(renewed, "synthetic_PRIVATE_new_code") is True
    assert case.service.status(case.identity)["state"] == "connected"
    assert case.calls == ["POST", "POST", "GET"]
    assert sorted(outcomes(case)) == sorted([("failed_" + reason, {}), ("connected", {})])


def test_revocation_after_exchange_prevents_profile_read_and_credentials(connection):
    case = connection
    case.fault = "revoke"
    assert case.service.callback(start(case), "synthetic_PRIVATE_code") is False
    assert case.calls == ["POST"]
    assert outcomes(case) == [("failed_authority_check", {})]
    with case.factory() as session:
        assert session.get(case.service.Credential, case.account) is None


def test_declining_consent_remains_distinct_from_failure(connection):
    case = connection
    assert case.service.callback(start(case), denied=True) is False
    assert case.calls == []
    assert outcomes(case) == [("declined", {})]


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
def test_google_calendar_requires_its_explicit_grant_and_keeps_existing_gmail(connection):
    case = connection
    assert case.service.callback(start(case), "synthetic_PRIVATE_code")
    before = len(case.requests)
    with pytest.raises(WorkspaceError, match="google_calendar_consent_required"):
        case.service.calendar(case.identity)
    assert len(case.requests) == before
    assert case.service.status(case.identity)["state"] == "connected"


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
@pytest.mark.parametrize("revoke", [False, True])
def test_google_calendar_uses_bounded_primary_read_and_rechecks_authority(connection, revoke, caplog):
    from datetime import datetime, timedelta
    case = connection
    case.scopes = "openid email https://www.googleapis.com/auth/gmail.metadata " + CALENDAR_SCOPE
    fields = parse_qs(urlsplit(case.service.start(case.identity)["authorization_url"]).query)
    assert fields["scope"] == [case.scopes]
    assert case.service.callback(fields["state"][0], "synthetic_PRIVATE_code")
    case.fault = "calendar_revoke" if revoke else None
    if revoke:
        with pytest.raises(WorkspaceError):
            case.service.calendar(case.identity)
    else:
        result = case.service.calendar(case.identity)
        assert result["kind"] == "calendar" and result["items"] == [] and not result["more"]
    request = case.requests[-1]
    assert request.method == "GET" and str(request.url).split("?", 1)[0] == CALENDAR_URL
    params = request.url.params
    assert params["maxResults"] == "25" and params["singleEvents"] == "true"
    assert params["showDeleted"] == "false" and params["orderBy"] == "startTime"
    assert datetime.fromisoformat(params["timeMax"]) - datetime.fromisoformat(params["timeMin"]) == timedelta(days=7)
    assert params["fields"] == "items(id,summary,status,start(date,dateTime),end(date,dateTime)),nextPageToken"
    assert "PRIVATE" not in caplog.text
    with case.factory() as session:
        audits = session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == case.account,
            AuditEvent.event_type.endswith("calendar_read"))).all()
        assert len(audits) == (0 if revoke else 1)


@pytest.mark.parametrize("connection", [MicrosoftPersonalConnection], indirect=True)
@pytest.mark.parametrize("scopes", [
    "user.read mail.read calendars.read",
    "https://graph.microsoft.com/User.Read https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Calendars.Read",
    "https%3A%2F%2Fgraph.microsoft.com%2Fuser.read https%3A%2F%2Fgraph.microsoft.com%2Fmail.read https%3A%2F%2Fgraph.microsoft.com%2Fcalendars.read",
    "offline_access%20User.Read%20Mail.Read%20Calendars.Read",
    "User.Read Mail.Read Calendars.Read openid profile email",
    "user.read mail.read calendars.read https://graph.microsoft.com/openid profile email",
])
def test_microsoft_documented_scope_spellings_save_the_same_read_only_connection(connection, scopes):
    case = connection
    case.scopes = scopes
    started = case.service.start(case.identity)
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    assert query["scope"] == ["offline_access User.Read Mail.Read Calendars.Read"]
    assert case.service.callback(query["state"][0], "synthetic_PRIVATE_code") is True
    assert case.service.status(case.identity)["state"] == "connected"
    assert case.calls == ["POST", "GET"]
    assert outcomes(case) == [("connected", {})]


@pytest.mark.parametrize("scopes,reason", [
    (None, "format"), ({"scope": "Mail.Read"}, "format"), ("", "format"),
    ("x" * 2049, "format"), ("User.Read Mail.Read Calendars.Read%0A", "format"),
    ("User.Read Mail.Read Calendars.Read%FF", "format"),
    ("User.Read Mail.Read", "missing"),
    ("user.read mail.read calendars.readwrite", "missing"),
    ("https://other.example.invalid/User.Read Mail.Read Calendars.Read", "missing"),
    ("https://graph.microsoft.com.evil.example/User.Read Mail.Read Calendars.Read", "missing"),
    ("https%253A%252F%252Fgraph.microsoft.com%252FUser.Read Mail.Read Calendars.Read", "missing"),
    ("openid profile email", "missing"),
    ("User.Read Mail.Read openid profile email", "missing"),
    ("User.Read Mail.Read Calendars.Read openid profile email Mail.Send", "unexpected"),
    ("User.Read Mail.Read Calendars.Read https://other.example.invalid/openid", "unexpected"),
    ("User.Read Mail.Read Calendars.Read Mail.Send", "unexpected"),
    ("User.Read Mail.Read Calendars.Read Calendars.ReadWrite", "unexpected"),
    ("User.Read Mail.Read Calendars.Read .default", "unexpected"),
    ("User.Read Mail.Read Calendars.Read https://other.example.invalid/User.Read", "unexpected"),
    ("User.Read Mail.Read Calendars.Read synthetic_PRIVATE_token", "unexpected"),
])
def test_scope_compatibility_never_accepts_missing_or_broader_access(scopes, reason):
    with pytest.raises(MicrosoftConnectionFailure) as error:
        MicrosoftPersonalConnection._verify_scopes(scopes)
    assert error.value.reason == "permissions_" + reason
    assert str(error.value) == "Microsoft connection unavailable"
