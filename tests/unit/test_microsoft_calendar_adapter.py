"""Exact existing Graph calendar GET; all account labels/events are invented."""

import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from cosmas_os.adapters.microsoft_connection import SCOPES, MicrosoftPersonalConnection
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.microsoft_calendar import MicrosoftCalendarBinding, MicrosoftCalendarWindow

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
ACCOUNT = "12345678-1234-4234-8234-123456789abc"


def binding():
    return MicrosoftCalendarBinding(account_id=ACCOUNT, binding_digest="a" * 64, connected_at=NOW,
        grant_sha256="b" * 64)


def event(**changes):
    return {"id": "AAMk+/selected==", "subject": "Invented clinic planning", "isCancelled": False, "isAllDay": True,
        "start": {"dateTime": "2026-11-05T00:00:00", "timeZone": "UTC"},
        "end": {"dateTime": "2026-11-06T00:00:00", "timeZone": "UTC"}, **changes}


def service(rows=None, *, status=200, on_request=None):
    conn: Any = object.__new__(MicrosoftPersonalConnection)
    conn.now = lambda: NOW
    conn._enabled = lambda: None
    conn.calendar_binding = lambda *_args, **_kwargs: binding()
    private = {"token": "invented-fixture-token", "label": "Invented Outlook", "email": "owner@example.invalid"}
    conn.credential = lambda _identity: (private, "a" * 64, ACCOUNT)
    credential = SimpleNamespace(status="ready", binding_digest="a" * 64, sealed=b"invented-seal")
    current = SimpleNamespace(get=lambda *_args: credential, commit=lambda: None)
    conn._session = lambda: nullcontext(current)
    conn._account = lambda *_args, **_kwargs: (SimpleNamespace(id=ACCOUNT), object(), "a" * 64)
    conn._open = lambda *_args: private
    conn._audit = lambda *_args: None
    requests = []

    def respond(request):
        requests.append(request)
        if on_request:
            on_request(conn)
        return httpx.Response(status, headers={"content-type": "application/json"},
            stream=httpx.ByteStream(json.dumps({"value": rows if rows is not None else [event()],
                "@odata.nextLink": "https://outside.invalid/do-not-follow"}).encode()))

    conn._client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    return conn, requests


def window():
    return MicrosoftCalendarWindow(starts_at=NOW, ends_at=NOW + timedelta(days=7))


def test_one_existing_calendars_read_get_uses_reserved_window_and_never_follows_pages_or_writes():
    conn, requests = service()
    try:
        observed = conn.calendar_observation(object(), window=window())
        assert observed.custody == binding() and observed.observation.window == window()
        assert observed.observation.items[0].id == "AAMk+/selected==" and observed.observation.items[0].all_day
        assert observed.observation.items[0].starts_at == "2026-11-05T00:00:00+00:00"
        assert len(requests) == 1 and requests[0].method == "GET"
        assert str(requests[0].url).split("?", 1)[0] == "https://graph.microsoft.com/v1.0/me/calendarView"
        assert dict(requests[0].url.params) == {"$top": "25", "$select": "id,subject,start,end,isCancelled,isAllDay",
            "$orderby": "start/dateTime", "startDateTime": NOW.isoformat(),
            "endDateTime": (NOW + timedelta(days=7)).isoformat()}
        assert requests[0].headers["prefer"] == 'outlook.timezone="UTC"'
        assert SCOPES == "offline_access User.Read Mail.Read Calendars.Read"
        assert "token" not in observed.observation.model_dump_json()
    finally:
        conn.close()


@pytest.mark.parametrize("rows", [[event(), event()], [event(id="https://outside.invalid")],
    [event(isAllDay="true")], [event(start={"dateTime": "2026-11-05T00:00:00", "timeZone": "Pacific Standard Time"})],
    [event(end={"dateTime": "2026-11-03T00:00:00", "timeZone": "UTC"})], [event()] * 26])
def test_malformed_unbounded_or_noncurrent_calendar_result_is_never_an_observation(rows):
    conn, requests = service(rows)
    try:
        with pytest.raises(ValueError):
            conn.calendar_observation(object(), window=window())
        assert len(requests) == 1
    finally:
        conn.close()


def test_changed_account_grant_after_read_is_withheld():
    def changed(conn):
        conn.calendar_binding = lambda *_args, **_kwargs: binding().model_copy(update={"grant_sha256": "d" * 64})

    conn, requests = service(on_request=changed)
    try:
        with pytest.raises(WorkspaceError, match="microsoft_calendar_grant_changed"):
            conn.calendar_observation(object(), window=window())
        assert len(requests) == 1
    finally:
        conn.close()
