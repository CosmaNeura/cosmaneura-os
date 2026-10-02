"""Exact calendar summaries through real adapters; all resources are invented."""

import base64
import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from cosmas_os.adapters.google_connection import (
    CALENDAR_SCOPE,
    CALENDAR_URL,
    FULL_MAIL_SCOPE,
    SCOPES,
    GooglePersonalConnection,
)
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.application import workspace as ws
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.google_calendar import (
    GoogleCalendarAccount,
    GoogleCalendarBinding,
    GoogleCalendarEvent,
    GoogleCalendarObservation,
    GoogleCalendarRead,
    GoogleCalendarWindow,
)

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
ACCOUNT = "12345678-1234-4234-8234-123456789abc"
OWNER = "22345678-1234-4234-8234-123456789abc"
BOX = "32345678-1234-4234-8234-123456789abc"


def event(**changes):
    return {"id": "invented_event", "summary": "Invented visit", "status": "tentative",
            "start": {"dateTime": "2026-10-31T13:00:00-04:00"},
            "end": {"dateTime": "2026-10-31T14:00:00-04:00"}, **changes}


def summary(**changes):
    return {"id": "invented_event", "subject": "Invented visit", "starts_at": "2026-10-31T17:00:00Z",
            "ends_at": "2026-10-31T18:00:00Z", "all_day": False, "cancelled": False, **changes}


def window(**changes):
    return GoogleCalendarWindow(**{"starts_at": NOW, "ends_at": NOW + timedelta(days=7), **changes})


def observation(**changes):
    value = {"kind": "calendar", "account": GoogleCalendarAccount(label="Invented", email="invented@example.invalid"),
             "items": (GoogleCalendarEvent(**summary()),), "more": False, "observed_at": NOW,
             "window": window(), **changes}
    return GoogleCalendarObservation(**value)


@pytest.fixture
def connection(monkeypatch):
    settings = SimpleNamespace(workspace_available=True, workspace_authenticated_enabled=True,
        workspace_google_connection_enabled=True, workspace_google_message_available=False,
        auth_mode="clerk_jwt", google_connection_client_id="invented.apps.googleusercontent.com",
        google_connection_return_origin="https://os.example.invalid",
        google_connection_callback_uri="https://api.example.invalid/connections/google/callback",
        google_connection_client_secret=SecretStr("invented-secret"),
        google_connection_encryption_key=SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode()))
    account = SimpleNamespace(id=ACCOUNT, box_id=BOX, principal_id=OWNER, active=True,
                              issuer="https://identity.example.invalid", subject="invented-subject",
                              organization_id="invented-organization")
    identity = RequestIdentity(BOX, OWNER, "clerk_jwt", account.organization_id, ACCOUNT)
    statements, requests, guards = [], [], []
    credential = SimpleNamespace(status="ready", sealed=None, expires_at=NOW + timedelta(hours=1),
                                 connected_at=NOW, binding_digest="")
    state = SimpleNamespace(response={"items": [event()]}, fault=None, scope_checks=[])

    class Session:
        def scalar(self, statement):
            statements.append(statement)
            if "google_connection_credentials" in str(statement):
                return credential
            parameters = statement.compile().params
            matched = (parameters.get("id_1"), parameters.get("box_id_1"), parameters.get("principal_id_1"))
            return account if account.active and matched == (ACCOUNT, BOX, OWNER) else None

        def commit(self):
            pytest.fail("binding must not commit")

        def close(self):
            pytest.fail("caller-owned binding must not close its session")

    session = Session()

    def respond(request):
        requests.append(request)
        if state.fault:
            state.fault()
        return httpx.Response(200, headers={"content-type": "application/json"},
                              stream=httpx.ByteStream(json.dumps(state.response).encode()))

    conn: Any = GooglePersonalConnection(settings, lambda: pytest.fail("nested session"),
                                         transport=httpx.MockTransport(respond), now=lambda: NOW)
    monkeypatch.setattr(ws, "_human", lambda s, box, actor: state.scope_checks.append((s, box, actor)))
    _, binding = conn._message_account(session, identity)
    credential.binding_digest = binding
    private = {"token": "invented-token", "subject": "invented-google-subject", "calendar_read": True,
               "mail_full_read": False, "granted_scopes": sorted(set(SCOPES.split()) | {CALENDAR_SCOPE}),
               "label": "Invented", "email": "invented@example.invalid"}

    def reseal():
        credential.sealed = conn._seal(private, "credential", ACCOUNT, binding)

    reseal()

    @contextmanager
    def own_session():
        yield session

    monkeypatch.setattr(conn, "_session", own_session)
    monkeypatch.setattr(conn, "credential", lambda selected: (deepcopy(private), binding, ACCOUNT))

    def current(*args, **kwargs):
        guards.append(kwargs.get("audit", False))
        conn.calendar_binding(identity, session=session)

    monkeypatch.setattr(conn, "_read_current", current)
    return SimpleNamespace(conn=conn, settings=settings, account=account, identity=identity, credential=credential,
                           session=session, statements=statements, requests=requests, guards=guards,
                           private=private, state=state, reseal=reseal)


def test_calendar_only_binding_is_db_only_shared_locked_and_refresh_stable(connection):
    f = connection
    first = f.conn.calendar_binding(f.identity, session=f.session)
    assert isinstance(first, GoogleCalendarBinding) and first.account_id == ACCOUNT
    assert f.requests == [] and f.state.scope_checks[-1] == (f.session, BOX, OWNER)
    assert all(stmt._for_update_arg.read is True for stmt in f.statements)
    f.private["token"] = "different-invented-refreshed-token"
    f.credential.expires_at += timedelta(hours=1)
    f.reseal()
    assert f.conn.calendar_binding(f.identity, session=f.session) == first
    f.credential.connected_at += timedelta(seconds=1)
    assert f.conn.calendar_binding(f.identity, session=f.session).grant_sha256 != first.grant_sha256
    assert f.requests == []


def test_calendar_grant_domain_and_exact_scope_changes_cannot_reuse_message_custody(connection):
    f = connection
    calendar = f.conn.calendar_binding(f.identity, session=f.session)
    mail = f.conn.message_binding(f.identity, session=f.session)
    assert calendar.grant_sha256 != mail.grant_sha256
    f.private["mail_full_read"] = True
    f.private["granted_scopes"] = sorted(set(f.private["granted_scopes"]) | {FULL_MAIL_SCOPE})
    f.reseal()
    assert f.conn.calendar_binding(f.identity, session=f.session).grant_sha256 != calendar.grant_sha256
    assert f.requests == []


@pytest.mark.parametrize("changes", [{"calendar_read": False}, {"calendar_read": 1},
    {"calendar_read": False, "mail_full_read": True}, {"calendar_read": True, "granted_scopes": sorted(SCOPES.split())},
    {"calendar_read": True, "granted_scopes": sorted(set(SCOPES.split()) | {CALENDAR_SCOPE, "https://www.googleapis.com/auth/calendar.events"})}])
def test_missing_or_inconsistent_sealed_calendar_scope_never_grants_authority(connection, changes):
    f = connection
    f.private.update(changes)
    if f.private["calendar_read"] is not True and "granted_scopes" not in changes:
        f.private["granted_scopes"] = sorted(set(SCOPES.split()) | ({FULL_MAIL_SCOPE} if f.private["mail_full_read"] else set()))
    f.reseal()
    with pytest.raises((ws.WorkspaceError, ValueError)):
        f.conn.calendar_binding(f.identity, session=f.session)
    assert f.requests == []


@pytest.mark.parametrize("change", ["disabled", "configuration", "inactive", "expired", "wrong_binding", "disconnected", "missing_seal", "bad_seal"])
def test_current_calendar_authority_refuses_changed_or_expired_credentials_without_io(connection, change):
    f = connection
    if change == "disabled":
        f.settings.workspace_google_connection_enabled = False
    elif change == "configuration":
        f.settings.google_connection_return_origin = "https://changed.example.invalid"
    elif change == "inactive":
        f.account.active = False
    elif change == "expired":
        f.credential.expires_at = NOW
    elif change == "wrong_binding":
        f.credential.binding_digest = "f" * 64
    elif change == "disconnected":
        f.credential.status = "disconnected"
    elif change == "missing_seal":
        f.credential.sealed = None
    else:
        f.credential.sealed = b"invented-bad-sealed-value"
    with pytest.raises((ws.WorkspaceError, ValueError, ConnectorUnavailable)):
        f.conn.calendar_binding(f.identity, session=f.session)
    assert f.requests == []


@pytest.mark.parametrize("identity", [RequestIdentity(BOX, OWNER, "dev_headers"),
    RequestIdentity(BOX, OWNER, "clerk_jwt", external_identity_id=None)])
def test_noncurrent_identity_has_no_calendar_binding(connection, identity):
    with pytest.raises(ws.WorkspaceError):
        connection.conn.calendar_binding(identity, session=connection.session)
    assert connection.requests == []


@pytest.mark.parametrize("identity", [RequestIdentity(BOX, OWNER, "clerk_jwt", external_identity_id=BOX),
    RequestIdentity(ACCOUNT, OWNER, "clerk_jwt", external_identity_id=ACCOUNT),
    RequestIdentity(BOX, ACCOUNT, "clerk_jwt", external_identity_id=ACCOUNT)])
def test_other_account_practice_or_human_cannot_reuse_calendar_binding(connection, identity):
    with pytest.raises(ws.WorkspaceError):
        connection.conn.calendar_binding(identity, session=connection.session)
    assert connection.requests == []


def test_optional_observation_uses_exact_frozen_window_one_get_and_no_full_mail_gate(connection):
    f = connection
    # The provider response arrives three seconds after the frozen query start.
    f.conn.now = lambda: NOW + timedelta(seconds=3) if f.requests else NOW
    f.state.response = {"items": [event(), event(id="all_day", start={"date": "2026-11-01"},
        end={"date": "2026-11-03"})], "nextPageToken": "opaque-never-followed"}
    result = f.conn.calendar_observation(f.identity)
    assert isinstance(result, GoogleCalendarRead)
    assert result.observation.window == window()
    assert result.observation.observed_at == NOW + timedelta(seconds=3)
    assert result.observation.items[0].starts_at == "2026-10-31T17:00:00+00:00"
    assert result.observation.items[0].cancelled is False
    assert result.observation.items[1].ends_at == "2026-11-03" and result.observation.items[1].all_day
    assert result.observation.more and len(f.requests) == 1 and f.guards[-1] == "calendar"
    request = f.requests[0]
    assert request.method == "GET" and str(request.url).split("?", 1)[0] == CALENDAR_URL
    assert dict(request.url.params) == {"timeMin": NOW.isoformat(), "timeMax": (NOW + timedelta(days=7)).isoformat(),
        "maxResults": "25", "singleEvents": "true", "orderBy": "startTime", "showDeleted": "false",
        "timeZone": "UTC", "fields": "items(id,summary,status,start(date,dateTime),end(date,dateTime)),nextPageToken"}
    public = result.observation.model_dump(mode="json")
    assert "custody" not in public and "token" not in json.dumps(public)
    assert f.settings.workspace_google_message_available is False


def test_legacy_calendar_wire_keeps_its_exact_keys_without_private_custody(connection):
    f = connection
    value = f.conn.calendar(f.identity)
    assert set(value) == {"kind", "account", "items", "more", "observed_at"}
    assert set(value["items"][0]) == {"id", "subject", "starts_at", "ends_at", "all_day", "cancelled"}
    assert "window" not in value and "custody" not in value and len(f.requests) == 1


@pytest.mark.parametrize("response", [{"items": [event(id=f"invented_{index}") for index in range(26)]},
    {"items": [event(), event()]}, {"items": [event(attendees=[{"email": "unrequested@example.invalid"}])]},
    {"items": [event(description="Unrequested private details")]}, {"items": [], "timeZone": "America/New_York"},
    {"items": [], "nextPageToken": ""}])
def test_exact_provider_response_refuses_unrequested_or_unbounded_content_before_success_audit(connection, response):
    f = connection
    f.state.response = response
    with pytest.raises(ValueError):
        f.conn.calendar_observation(f.identity)
    assert len(f.requests) == 1 and "calendar" not in f.guards


def test_twenty_five_summaries_are_bounded_and_cancelled_is_not_treated_as_confirmed(connection):
    f = connection
    f.state.response = {"items": [event(id=f"invented_{index}", status="cancelled" if index == 0 else "tentative")
        for index in range(25)], "nextPageToken": "never-fetch-next-page"}
    value = f.conn.calendar_observation(f.identity)
    assert len(value.observation.items) == 25 and value.observation.more
    assert value.observation.items[0].cancelled is True
    assert value.observation.items[1].cancelled is False
    assert len(f.requests) == 1


def test_permission_loss_before_get_does_not_start_a_provider_read(connection):
    f = connection
    f.private["calendar_read"] = False
    f.private["granted_scopes"] = sorted(SCOPES.split())
    f.reseal()
    with pytest.raises(ws.WorkspaceError, match="google_calendar_consent_required"):
        f.conn.calendar_observation(f.identity)
    assert f.requests == [] and f.guards == []


def test_permission_loss_after_parsing_before_success_audit_withholds_observation(connection):
    f = connection
    original = f.conn._text
    def text(value, limit):
        result = original(value, limit)
        f.credential.status = "disconnected"
        return result
    f.conn._text = text
    with pytest.raises(ws.WorkspaceError):
        f.conn.calendar_observation(f.identity)
    assert len(f.requests) == 1 and "calendar" not in f.guards


@pytest.mark.parametrize("change", ["revoke", "grant", "config"])
def test_change_during_exact_summary_get_withholds_result_and_success_audit(connection, change):
    f = connection
    def change_authority():
        if change == "revoke":
            f.credential.status = "disconnected"
        elif change == "grant":
            f.private["calendar_read"] = False
            f.private["granted_scopes"] = sorted(SCOPES.split())
            f.reseal()
        else:
            f.settings.workspace_google_connection_enabled = False
    f.state.fault = change_authority
    with pytest.raises((ws.WorkspaceError, ConnectorUnavailable)):
        f.conn.calendar_observation(f.identity)
    assert len(f.requests) == 1 and "calendar" not in f.guards


@pytest.mark.parametrize("starts_at,ends_at", [(NOW.replace(tzinfo=None), NOW + timedelta(days=7)),
    (NOW, NOW + timedelta(days=6)), (NOW, NOW + timedelta(days=7, seconds=1)),
    (NOW, NOW), (NOW, NOW - timedelta(days=7)),
    (NOW.astimezone(ZoneInfo("America/New_York")), (NOW + timedelta(days=7)).astimezone(ZoneInfo("America/New_York")))])
def test_window_rejects_naive_nonutc_or_non168_hour_bounds(starts_at, ends_at):
    with pytest.raises(ValidationError):
        GoogleCalendarWindow(starts_at=starts_at, ends_at=ends_at)


def test_dst_query_window_is_168_hours_after_normalizing_server_clock_to_utc(connection):
    f = connection
    local = NOW.astimezone(ZoneInfo("America/New_York"))
    f.conn.now = lambda: local
    result = f.conn.calendar_observation(f.identity)
    assert result.observation.window == window()
    assert result.observation.window.ends_at - result.observation.window.starts_at == timedelta(hours=168)


@pytest.mark.parametrize("changes", [{"starts_at": "2026-11-01", "ends_at": "2026-11-02"},
    {"starts_at": "2026-10-31T17:00:00", "ends_at": "2026-10-31T18:00:00Z"},
    {"ends_at": "2026-10-31T17:00:00Z"}, {"ends_at": "2026-10-31T16:00:00Z"},
    {"all_day": True, "starts_at": "2026-11-01", "ends_at": "2026-11-02T00:00:00Z"},
    {"all_day": True, "starts_at": "2026-02-30", "ends_at": "2026-03-01"},
    {"all_day": True, "starts_at": "2026-11-02", "ends_at": "2026-11-01"},
    {"subject": "Invented\nconflicting instruction"}, {"id": "../details"}, {"description": "Unrequested"}])
def test_event_closed_contract_rejects_malformed_mixed_bounds_and_unrequested_details(changes):
    with pytest.raises(ValidationError):
        GoogleCalendarEvent(**summary(**changes))


def test_ongoing_event_overlaps_query_but_equal_exclusive_boundaries_do_not():
    ongoing = GoogleCalendarEvent(**summary(starts_at=(NOW - timedelta(hours=1)).isoformat(), ends_at=(NOW + timedelta(hours=1)).isoformat()))
    assert observation(items=(ongoing,)).items == (ongoing,)
    for event in (GoogleCalendarEvent(**summary(ends_at=NOW.isoformat(), starts_at=(NOW - timedelta(hours=1)).isoformat())),
        GoogleCalendarEvent(**summary(starts_at=(NOW + timedelta(days=7)).isoformat(), ends_at=(NOW + timedelta(days=7, hours=1)).isoformat()))):
        with pytest.raises(ValidationError):
            observation(items=(event,))


def test_all_day_bounds_remain_exclusive_calendar_dates_without_claiming_timezone():
    value = GoogleCalendarEvent(**summary(all_day=True, starts_at="2026-11-01", ends_at="2026-11-03"))
    starts_at, ends_at = value.bounds()
    assert not isinstance(starts_at, datetime) and not isinstance(ends_at, datetime)
    assert value.model_dump()["ends_at"] == "2026-11-03" and "timezone" not in value.model_dump()


def test_observation_rejects_duplicates_limits_bad_clock_and_extra_fields():
    row = GoogleCalendarEvent(**summary())
    for changes in ({"items": (row, row)}, {"items": (row,) * 26},
        {"observed_at": NOW.replace(tzinfo=None)}, {"observed_at": NOW - timedelta(seconds=1)},
        {"observed_at": NOW + timedelta(days=7)}, {"nextPageToken": "never-expose"}):
        with pytest.raises(ValidationError):
            observation(**changes)


def test_nested_ports_are_frozen_and_private_binding_rejects_naive_or_extra_fields(connection):
    value = connection.conn.calendar_observation(connection.identity)
    with pytest.raises(ValidationError):
        value.observation.items[0].subject = "Changed"
    with pytest.raises(ValidationError):
        GoogleCalendarBinding(**{**value.custody.model_dump(), "connected_at": NOW.replace(tzinfo=None)})
    with pytest.raises(ValidationError):
        GoogleCalendarRead(**{**value.model_dump(), "details_url": "https://unapproved.invalid"})
