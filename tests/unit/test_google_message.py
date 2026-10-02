"""Bounded plaintext Gmail parsing and exact one-message HTTP; invented content."""

import base64
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from cosmas_os.adapters.google_connection import (
    _EXPECTED_GOOGLE_GRANT,
    CALENDAR_SCOPE,
    FULL_MAIL_SCOPE,
    SCOPES,
    GooglePersonalConnection,
)
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.google_message import (
    GoogleMessageBinding,
    GoogleMessageRead,
    GoogleMessageSelection,
)

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
TEXT = "Invented administrative question. Please confirm how to request a visit."


def part(text=TEXT, mime="text/plain", **changes):
    raw = text.encode()
    return {"mimeType": mime, "filename": "", "body": {"size": len(raw),
        "data": base64.urlsafe_b64encode(raw).decode().rstrip("=")}, **changes}


def message(**changes):
    return {"id": "invented_message", "threadId": "invented_thread", "historyId": "101",
        "internalDate": str(int(NOW.timestamp() * 1000)), "labelIds": ["INBOX", "UNREAD"],
        "payload": {**part(), "headers": [{"name": "Subject", "value": "Invented request"},
            {"name": "From", "value": "Invented Sender <sender@example.invalid>"}]}, **changes}


def binding():
    return GoogleMessageBinding(account_id="12345678-1234-4234-8234-123456789abc",
        binding_digest="a" * 64, connected_at=NOW, grant_sha256="b" * 64)


def service(monkeypatch, response):
    conn: Any = object.__new__(GooglePersonalConnection)
    conn.now = lambda: NOW
    conn.settings = SimpleNamespace(workspace_google_message_available=True)
    conn._enabled = lambda: None
    conn.token_url = "https://oauth2.googleapis.com/token"
    conn.credential = lambda identity: ({"token": "invented-token", "mail_full_read": True},
        "a" * 64, binding().account_id)
    conn.message_binding = lambda *a, **k: binding()
    requests, guards = [], []
    conn._read_current = lambda *a, **k: guards.append(k.get("audit", False))
    def handle(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"},
            stream=httpx.ByteStream(json.dumps(response).encode()))
    conn._transport = httpx.MockTransport(handle)
    return conn, requests, guards


def test_plaintext_and_alternative_html_keep_only_exact_plaintext():
    assert GooglePersonalConnection._plain_body(part()) == (TEXT, None)
    alternate = {"mimeType": "multipart/alternative", "parts": [part(), part("<p>Invented HTML</p>", "text/html")]}
    assert GooglePersonalConnection._plain_body(alternate) == (TEXT, None)


@pytest.mark.parametrize("container", ["multipart/mixed", "multipart/related"])
def test_independent_html_is_not_omitted_from_a_complete_selected_message(monkeypatch, container):
    value = message()
    value["payload"] = {
        "mimeType": container,
        "parts": [part(), part("<p>Invented separate message facts</p>", "text/html")],
        "headers": value["payload"]["headers"],
    }
    conn, requests, _ = service(monkeypatch, value)
    result = conn.read_message(object(), GoogleMessageSelection(message_id="invented_message"))
    assert result.status == "needs_human" and result.reason == "ambiguous"
    assert result.content is None and result.content_sha256 is None
    assert len(requests) == 1 and requests[0].url.params["format"] == "full"


@pytest.mark.parametrize("container", ["multipart/mixed", "multipart/related"])
def test_explicit_alternative_remains_supported_inside_a_container(container):
    alternative = {"mimeType": "multipart/alternative", "parts": [part(), part("<p>Invented HTML</p>", "text/html")]}
    assert GooglePersonalConnection._plain_body({"mimeType": container, "parts": [alternative]}) == (TEXT, None)


@pytest.mark.parametrize("container", ["multipart/mixed", "multipart/related"])
def test_alternative_ancestor_does_not_authorize_omitting_independent_nested_html(container):
    nested = {"mimeType": "multipart/alternative", "parts": [part(), {
        "mimeType": container, "parts": [part("<p>Invented separate message facts</p>", "text/html")],
    }]}
    assert GooglePersonalConnection._plain_body(nested) == (None, "ambiguous")


@pytest.mark.parametrize("container", ["multipart/mixed", "multipart/related"])
def test_html_only_alternative_cannot_borrow_a_plain_representation_from_another_part(container):
    unrelated_alternative = {"mimeType": "multipart/alternative", "parts": [part("<p>Invented separate facts</p>", "text/html")]}
    assert GooglePersonalConnection._plain_body({"mimeType": container, "parts": [part(), unrelated_alternative]}) == (None, "ambiguous")


@pytest.mark.parametrize("payload,reason", [
    (part(mime="text/html"), "html_only"),
    (part(filename="invented.pdf"), "attachment"),
    (part(body={"size": 10, "attachmentId": "must-never-fetch"}), "attachment"),
    (part(mime="application/pdf"), "unsupported_mime"),
    (part(body={"size": 3, "data": "!!!"}), "invalid_encoding"),
    (part(body={"size": 3, "data": "_w"}), "invalid_encoding"),
    (part(body={"size": 1, "data": "YQ_"}), "invalid_encoding"),
    (part(body={"size": True, "data": "YQ"}), "invalid_encoding"),
    ({"mimeType": "multipart/mixed", "parts": [part(), part()]}, "ambiguous"),
    ({"mimeType": "multipart/mixed", "parts": [part()] * 17}, "oversize"),
])
def test_unsupported_or_ambiguous_mime_never_returns_partial_content(payload, reason):
    assert GooglePersonalConnection._plain_body(payload) == (None, reason)


def test_actual_mock_http_reads_exact_selected_message_and_custody(monkeypatch):
    conn, requests, guards = service(monkeypatch, message())
    result = conn.read_message(object(), GoogleMessageSelection(message_id="invented_message", thread_id="invented_thread"))
    assert result.status == "complete" and result.content is not None and TEXT in result.content
    assert result.content.startswith("Subject: Invented request\nFrom: sender@example.invalid\nReceived: ")
    assert result.content_sha256 == hashlib.sha256(result.content.encode()).hexdigest()
    assert result.custody == binding() and result.history_id == "101" and not result.is_read
    assert len(requests) == 1 and requests[0].method == "GET"
    assert str(requests[0].url).split("?", 1)[0] == "https://gmail.googleapis.com/gmail/v1/users/me/messages/invented_message"
    assert requests[0].url.params["format"] == "full" and "q" not in requests[0].url.params
    assert len(guards) >= 5 and guards[-1] == "full_mail"


@pytest.mark.parametrize("payload,reason", [(part(filename="invented.pdf"), "attachment"),
    (part(mime="text/html"), "html_only"), (part("x" * 5000), "oversize")])
def test_needs_human_has_no_body_or_content_hash_and_no_attachment_fetch(monkeypatch, payload, reason):
    value = message()
    value["payload"] = {**payload, "headers": value["payload"]["headers"]}
    conn, requests, _ = service(monkeypatch, value)
    result = conn.read_message(object(), GoogleMessageSelection(message_id="invented_message"))
    assert result.status == "needs_human" and result.reason == reason
    assert result.content is None and result.content_sha256 is None and len(requests) == 1


def test_metadata_grant_cannot_read_full_content_or_trigger_http(monkeypatch):
    conn, requests, _ = service(monkeypatch, message())
    conn.credential = lambda _: ({"token": "invented-token", "calendar_read": True}, "a" * 64, binding().account_id)
    with pytest.raises(WorkspaceError, match="google_mail_consent_required"):
        conn.read_message(object(), GoogleMessageSelection(message_id="invented_message"))
    assert requests == []


@pytest.mark.parametrize("change", [{"id": "wrong_message"}, {"threadId": "wrong_thread"}])
def test_provider_message_identity_must_match_selected_handle(monkeypatch, change):
    conn, requests, guards = service(monkeypatch, message(**change))
    with pytest.raises(ValueError):
        conn.read_message(object(), GoogleMessageSelection(message_id="invented_message", thread_id="invented_thread"))
    assert len(requests) == 1 and "full_mail" not in guards


def test_revoke_during_stream_withholds_content_and_success_audit(monkeypatch):
    conn, requests, guards = service(monkeypatch, message())
    def current(*a, **k):
        guards.append(k.get("audit", False))
        if requests:
            raise WorkspaceError("google_connection_changed", 409)
    conn._read_current = current
    with pytest.raises(WorkspaceError):
        conn.read_message(object(), GoogleMessageSelection(message_id="invented_message"))
    assert len(requests) == 1 and "full_mail" not in guards


def test_message_models_are_closed_and_incomplete_results_cannot_carry_content():
    with pytest.raises(ValidationError):
        GoogleMessageSelection.model_validate({"message_id": "invented_message", "url": "https://unapproved.invalid"})
    with pytest.raises(ValidationError):
        GoogleMessageSelection(message_id="../arbitrary")
    conn = GoogleMessageRead(message_id="invented_message", thread_id="invented_thread", subject="", sender="",
        received_at=NOW, is_read=False, observed_at=NOW, status="needs_human", reason="html_only",
        raw_sha256="a" * 64, custody=binding())
    value = conn.model_dump()
    value["content"] = TEXT
    with pytest.raises(ValidationError):
        GoogleMessageRead.model_validate(value)


def test_caller_session_binding_never_creates_closes_or_commits_a_nested_session():
    conn: Any = object.__new__(GooglePersonalConnection)
    conn.now = lambda: NOW
    conn._enabled = lambda: None
    conn.settings = SimpleNamespace(workspace_google_message_available=True)
    conn._session = lambda: pytest.fail("nested session")
    private = {"subject": "invented_google_subject", "calendar_read": True, "mail_full_read": True,
        "granted_scopes": sorted(set(SCOPES.split()) | {FULL_MAIL_SCOPE,
            "https://www.googleapis.com/auth/calendar.events.readonly"})}
    conn._open = lambda *args: private
    conn._message_account = lambda s, identity: (SimpleNamespace(id=binding().account_id), "a" * 64)
    credential = SimpleNamespace(status="ready", binding_digest="a" * 64,
        expires_at=NOW.replace(hour=13), connected_at=NOW, sealed=b"invented-sealed")
    session = SimpleNamespace(scalar=lambda *a: credential)
    first = conn.message_binding(object(), require_full=True, session=session)
    credential.sealed = b"invented-refresh-sealed"
    assert conn.message_binding(object(), require_full=True, session=session) == first
    credential.connected_at = NOW.replace(minute=1)
    assert conn.message_binding(object(), require_full=True, session=session).grant_sha256 != first.grant_sha256


def test_sealed_capability_does_not_silently_accept_changed_scope_set():
    private = {"calendar_read": True, "mail_full_read": True, "granted_scopes": sorted(SCOPES.split())}
    with pytest.raises(ValueError):
        GooglePersonalConnection._grant_scopes(private)


def test_before_and_after_binding_mismatch_withholds_complete_message(monkeypatch):
    conn, requests, guards = service(monkeypatch, message())
    count = 0
    def current(*a, **k):
        nonlocal count
        count += 1
        return binding() if count == 1 else binding().model_copy(update={"grant_sha256": "c" * 64})
    conn.message_binding = current
    with pytest.raises(WorkspaceError, match="google_connection_changed"):
        conn.read_message(object(), GoogleMessageSelection(message_id="invented_message"))
    assert len(requests) == 1 and "full_mail" not in guards


def test_full_message_gate_off_prevents_sign_in_read_and_private_binding(monkeypatch):
    conn, requests, guards = service(monkeypatch, message())
    conn.settings.workspace_google_message_available = False
    for call in (lambda: conn.start_full_mail(object()),
        lambda: conn.read_message(object(), GoogleMessageSelection(message_id="invented_message")),
        lambda: GooglePersonalConnection.message_binding(conn, object(), require_full=True)):
        with pytest.raises(WorkspaceError, match="google_message_unavailable"):
            call()
    assert requests == [] and guards == []


def test_full_message_gate_disabled_during_transport_withholds_content_and_success(monkeypatch):
    conn, requests, guards = service(monkeypatch, message())
    def respond(request):
        requests.append(request)
        conn.settings.workspace_google_message_available = False
        return httpx.Response(200, headers={"content-type": "application/json"},
            stream=httpx.ByteStream(json.dumps(message()).encode()))
    conn._transport = httpx.MockTransport(respond)
    with pytest.raises(WorkspaceError, match="google_message_unavailable"):
        conn.read_message(object(), GoogleMessageSelection(message_id="invented_message"))
    assert len(requests) == 1 and "full_mail" not in guards


@pytest.mark.parametrize("scopes", [
    SCOPES + " " + CALENDAR_SCOPE,
    SCOPES + " " + FULL_MAIL_SCOPE,
    SCOPES + " " + CALENDAR_SCOPE + " " + FULL_MAIL_SCOPE + " https://www.googleapis.com/auth/gmail.send",
])
def test_full_sealed_grant_rejects_missing_or_broader_permissions_before_profile_read(scopes):
    conn: Any = object.__new__(GooglePersonalConnection)
    conn._request = lambda *a, **k: pytest.fail("must not disclose profile request after bad grant")
    marker = _EXPECTED_GOOGLE_GRANT.set(set(SCOPES.split()) | {CALENDAR_SCOPE, FULL_MAIL_SCOPE})
    try:
        with pytest.raises(ValueError, match="Google permissions unavailable"):
            conn._verified({"scope": scopes}, None)
    finally:
        _EXPECTED_GOOGLE_GRANT.reset(marker)


def test_readonly_grant_without_sealed_full_consent_is_rejected_before_profile_read():
    conn: Any = object.__new__(GooglePersonalConnection)
    conn._request = lambda *a, **k: pytest.fail("full grant cannot be introduced implicitly")
    with pytest.raises(ValueError, match="Google permissions unavailable"):
        conn._verified({"scope": SCOPES + " " + CALENDAR_SCOPE + " " + FULL_MAIL_SCOPE}, None)


@pytest.mark.parametrize("scopes", [SCOPES, SCOPES + " " + CALENDAR_SCOPE,
    SCOPES + " " + CALENDAR_SCOPE + " " + FULL_MAIL_SCOPE])
def test_verified_exact_grant_keeps_legacy_capabilities_and_refresh_binding(scopes):
    conn: Any = object.__new__(GooglePersonalConnection)
    conn.now = lambda: NOW
    requests = []
    def profile(*a, **kw):
        requests.append((a, kw))
        return {"sub": "invented_member", "email": "member@example.invalid", "email_verified": True}
    conn._request = profile
    expected = set(scopes.split()) if FULL_MAIL_SCOPE in scopes else None
    marker = _EXPECTED_GOOGLE_GRANT.set(expected)
    try:
        private, expires = conn._verified({"scope": scopes, "access_token": "synthetic_PRIVATE_token",
            "refresh_token": "synthetic_PRIVATE_refresh", "token_type": "Bearer", "expires_in": 3600}, None)
    finally:
        _EXPECTED_GOOGLE_GRANT.reset(marker)
    assert len(requests) == 1 and requests[0][0][:2] == ("GET", "https://openidconnect.googleapis.com/v1/userinfo")
    assert private["granted_scopes"] == sorted(scopes.split())
    assert private["mail_full_read"] == (FULL_MAIL_SCOPE in scopes)
    assert private["calendar_read"] == (CALENDAR_SCOPE in scopes)
    assert conn._status_capabilities("connected", private) == {"mail": True, "calendar": CALENDAR_SCOPE in scopes}
    assert expires == NOW.replace(hour=13)


def test_complete_message_hash_cannot_claim_different_content():
    with pytest.raises(ValidationError, match="google_message_completion_invalid"):
        GoogleMessageRead(message_id="invented_message", thread_id="invented_thread", subject="", sender="",
            received_at=NOW, is_read=False, observed_at=NOW, status="complete", content=TEXT,
            raw_sha256="a" * 64, content_sha256="b" * 64, custody=binding())


@pytest.mark.parametrize("full, pending, expired", [(True, False, False), (False, False, False),
    (True, True, False), (True, False, True)])
def test_message_status_uses_caller_session_without_network_or_nested_transaction(full, pending, expired):
    conn: Any = object.__new__(GooglePersonalConnection)
    conn.now = lambda: NOW
    conn._enabled = lambda: None
    conn.settings = SimpleNamespace(workspace_google_message_available=True)
    conn._session = lambda: pytest.fail("nested session")
    conn._request = lambda *a, **kw: pytest.fail("status cannot call provider")
    conn._message_account = lambda s, identity: (SimpleNamespace(id=binding().account_id), "a" * 64)
    private = {"subject": "invented_subject", "label": "Gmail", "email": "member@example.invalid",
        "calendar_read": True, "mail_full_read": full}
    conn._open = lambda *args: private
    credential = SimpleNamespace(status="ready", binding_digest="a" * 64, sealed=b"invented-sealed",
        expires_at=NOW.replace(hour=11 if expired else 13))
    def scalar(statement):
        return credential if "google_connection_credentials" in str(statement) else object() if pending else None
    session = SimpleNamespace(scalar=scalar)
    result = conn.message_status(object(), session=session)
    connected = not pending and not expired
    assert result == {"contract_version": 1, "state": "connected" if connected else "sign_in_required",
        "full_mail_read": full and connected,
        "account": {"label": "Gmail", "email": "member@example.invalid"} if connected else None}
