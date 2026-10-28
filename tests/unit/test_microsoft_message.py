"""Actual synthetic HTTP for selected Outlook text; no account or vendor I/O."""
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from cosmas_os.adapters.microsoft_connection import SCOPES, MicrosoftPersonalConnection
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.microsoft_message import MicrosoftMessageBinding, MicrosoftMessageSelection

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
ID = "AAMk+/invented=="


def binding():
    return MicrosoftMessageBinding(account_id="12345678-1234-4234-8234-123456789abc",
        binding_digest="a" * 64, connected_at=NOW, grant_sha256="b" * 64)


def message(**changes):
    return {"id": ID, "conversationId": "AAQk+/conversation==", "changeKey": "CQAA/test==",
        "subject": "Invented request", "from": {"emailAddress": {"address": "sender@example.invalid"}},
        "receivedDateTime": NOW.isoformat(), "isRead": False, "hasAttachments": False,
        "body": {"contentType": "text", "content": "Invented administrative question.\r\nPlease check the visit."},
        "attachments": [], **changes}


def service(value=None, *, status=200, raw=None, extra_headers=None):
    conn: Any = object.__new__(MicrosoftPersonalConnection)
    conn.now = lambda: NOW
    conn.settings = SimpleNamespace(workspace_microsoft_message_available=True)
    conn._enabled = lambda: None
    conn.credential = lambda identity: ({"token": "invented-token"}, "a" * 64, binding().account_id)
    conn.message_binding = lambda *a, **k: binding()
    conn._message_authentication_failed = lambda *a: None
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, headers={"content-type": "application/json", **(extra_headers or {})},
            stream=httpx.ByteStream(raw if raw is not None else json.dumps(value or message()).encode()))

    conn._client = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False)
    return conn, requests


def test_one_exact_encoded_message_text_no_writes_or_attachment_downloads():
    conn, requests = service()
    result = conn.read_message(object(), MicrosoftMessageSelection(message_id=ID))
    assert result.status == "complete" and result.content is not None
    assert result.content.startswith("Subject: Invented request\nFrom: sender@example.invalid\nReceived: ")
    assert "\r" not in result.content and result.content_sha256 == hashlib.sha256(result.content.encode()).hexdigest()
    assert result.change_key == "CQAA/test==" and result.custody == binding()
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.raw_path.split(b"?")[0] == b"/v1.0/me/messages/AAMk%2B%2Finvented%3D%3D"
    assert requests[0].headers["prefer"] == 'outlook.body-content-type="text"'
    assert requests[0].url.params["$expand"] == "attachments($select=id,isInline)"
    assert SCOPES == "offline_access User.Read Mail.Read Calendars.Read"


@pytest.mark.parametrize("changes,reason", [
    ({"hasAttachments": True}, "attachment"),
    ({"attachments": [{"id": "inline-image", "isInline": True}]}, "attachment"),
    ({"attachments": None}, "ambiguous"),
    ({"attachments@odata.nextLink": "https://example.invalid/next"}, "ambiguous"),
    ({"body": {"contentType": "html", "content": '<img src="https://example.invalid/image">'}}, "html_only"),
    ({"body": {"contentType": "text", "content": "x" * 5000}}, "oversize"),
    ({"body": {"contentType": "text", "content": "bad\0text"}}, "invalid_encoding"),
    ({"body": {"contentType": "text", "content": "  "}}, "ambiguous"),
    ({"body": {"contentType": "other", "content": "invented"}}, "unsupported_mime"),
])
def test_unreadable_or_partial_message_is_withheld_and_never_followed(changes, reason):
    conn, requests = service(message(**changes))
    result = conn.read_message(object(), MicrosoftMessageSelection(message_id=ID))
    assert result.status == "needs_human" and result.reason == reason
    assert result.content is None and result.content_sha256 is None and len(requests) == 1


@pytest.mark.parametrize("changes", [
    {"id": "another"}, {"conversationId": "https://outside.invalid"}, {"conversationId": None},
    {"changeKey": "too long"}, {"isRead": "false"}, {"hasAttachments": None},
    {"receivedDateTime": "2026-10-25T12:00:00"}, {"subject": "x" * 999},
])
def test_invalid_or_different_message_never_becomes_a_source(changes):
    conn, _ = service(message(**changes))
    with pytest.raises(WorkspaceError, match="microsoft_message_response_invalid"):
        conn.read_message(object(), MicrosoftMessageSelection(message_id=ID))


@pytest.mark.parametrize("raw,headers", [(b'{}' * 70000, {}), (b'{"id":1,"id":2}', {}),
    (b'{}', {"content-encoding": "gzip"}), (b'{}', {"content-type": "text/html"})])
def test_bounded_transport_rejects_oversize_duplicate_and_encoded_bodies(raw, headers):
    conn, _ = service(raw=raw, extra_headers=headers)
    with pytest.raises(WorkspaceError):
        conn.read_message(object(), MicrosoftMessageSelection(message_id=ID))


@pytest.mark.parametrize("status,code", [(401, "authentication_required"), (403, "permission_denied"),
    (404, "record_unavailable"), (429, "rate_limited"), (302, "read_unconfirmed")])
def test_fixed_refusals_do_not_disclose_provider_body(status, code):
    conn, requests = service(status=status, raw=b'invented provider detail must remain private')
    with pytest.raises(WorkspaceError) as error:
        conn.read_message(object(), MicrosoftMessageSelection(message_id=ID))
    assert error.value.code == "microsoft_message_" + code and len(requests) == 1


def test_changed_grant_during_transport_withholds_entire_result():
    conn, requests = service()
    count = 0

    def current(*a, **k):
        nonlocal count
        count += 1
        return binding() if count < 3 else binding().model_copy(update={"grant_sha256": "c" * 64})

    conn.message_binding = current
    with pytest.raises(WorkspaceError, match="microsoft_message_grant_changed"):
        conn.read_message(object(), MicrosoftMessageSelection(message_id=ID))
    assert len(requests) == 1


def test_disabled_feature_or_invalid_selection_performs_no_transport():
    conn, requests = service()
    conn.settings.workspace_microsoft_message_available = False
    with pytest.raises(WorkspaceError, match="microsoft_message_unavailable"):
        conn.read_message(object(), MicrosoftMessageSelection(message_id=ID))
    assert requests == []
