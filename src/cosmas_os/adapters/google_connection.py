"""Personal Google/Gmail metadata connection using the existing durable OAuth state.

Read mappings and delegated auth pattern follow Activepieces community Gmail
(MIT attribution in docs/third-party/activepieces-LICENSE.txt) and Google's
published OAuth/OpenID/Gmail contracts. No mailbox write or service account exists.
"""

import base64
import hashlib
import json
import re
import secrets
from contextlib import nullcontext
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select

from cosmas_os.adapters.microsoft_connection import (
    MicrosoftPersonalConnection,
    canonical,
    digest,
    exact_origin,
)
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import CaptureBudget, capture_budget, current_budget
from cosmas_os.google_connection_models import GoogleConnectionAttempt, GoogleConnectionCredential
from cosmas_os.models import ExternalIdentity
from cosmas_os.ports.google_message import (
    GoogleMessageBinding,
    GoogleMessageRead,
    GoogleMessageSelection,
)

CALLBACK_PATH = "/connections/google/callback"
SCOPES = "openid email https://www.googleapis.com/auth/gmail.metadata"
FULL_MAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GMAIL_ORIGIN = "https://gmail.googleapis.com"
MESSAGES_PATH = "/gmail/v1/users/me/messages"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
MESSAGE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_EXPECTED_GOOGLE_GRANT: ContextVar[set[str] | None] = ContextVar("expected_google_grant", default=None)


class GooglePersonalConnection(MicrosoftPersonalConnection):
    Attempt = GoogleConnectionAttempt
    Credential = GoogleConnectionCredential
    provider = "google"

    def __init__(self, settings, sessions, *, transport=None, now=lambda: datetime.now(UTC)):
        self.settings, self.sessions, self.now = settings, sessions, now
        if (
            not settings.workspace_available
            or not settings.workspace_authenticated_enabled
            or settings.auth_mode != "clerk_jwt"
            or not settings.workspace_google_connection_enabled
        ):
            raise ValueError("Authenticated Google connection must be enabled")
        self.client_id = settings.google_connection_client_id
        if (
            not isinstance(self.client_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com", self.client_id)
            is None
        ):
            raise ValueError("Use the reviewed Google OAuth client ID")
        self.return_origin = exact_origin(settings.google_connection_return_origin)
        callback = urlsplit(settings.google_connection_callback_uri)
        exact_origin(f"{callback.scheme}://{callback.netloc}")
        if callback.path != CALLBACK_PATH or callback.query or callback.fragment:
            raise ValueError("Use the fixed Google callback path")
        self.callback_uri = settings.google_connection_callback_uri
        if (
            not settings.google_connection_client_secret
            or not settings.google_connection_encryption_key
        ):
            raise ValueError("Google client and encryption secrets are required")
        self.client_secret = settings.google_connection_client_secret
        key = base64.b64decode(
            settings.google_connection_encryption_key.get_secret_value(),
            altchars=b"-_",
            validate=True,
        )
        if len(key) != 32:
            raise ValueError("Use a 32-byte credential encryption key")
        self._cipher = AESGCM(key)
        self.authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
        self.token_url = "https://oauth2.googleapis.com/token"
        self.config_digest = digest(canonical(self._configuration()))
        self._transport, self._closed = transport, False

    def _configuration(self):
        s = self.settings
        return [
            s.google_connection_client_id,
            s.google_connection_callback_uri,
            s.google_connection_return_origin,
            digest(s.google_connection_client_secret.get_secret_value())
            if s.google_connection_client_secret
            else "",
            digest(s.google_connection_encryption_key.get_secret_value())
            if s.google_connection_encryption_key
            else "",
        ]

    def status(self, identity, *, include_capabilities=False):
        return self._read_status(
            identity, capabilities=self._status_capabilities if include_capabilities else None
        )

    @staticmethod
    def _status_capabilities(state, private):
        connected = state == "connected"
        return {
            "mail": connected,
            "calendar": connected and private.get("calendar_read") is True,
        }

    def _enabled(self):
        from cosmas_os.application.capture_deadline import check_capture_deadline
        from cosmas_os.ports.bot_capabilities import ConnectorUnavailable

        check_capture_deadline()
        if (
            self._closed
            or not self.settings.workspace_available
            or not self.settings.workspace_authenticated_enabled
            or self.settings.auth_mode != "clerk_jwt"
            or not self.settings.workspace_google_connection_enabled
            or digest(canonical(self._configuration())) != self.config_digest
        ):
            raise ConnectorUnavailable("google_connection_unavailable")

    def _authorization_fields(self, private):
        return {
            "client_id": self.client_id,
            "redirect_uri": self.callback_uri,
            "response_type": "code",
            "scope": SCOPES + " " + CALENDAR_SCOPE + (" " + FULL_MAIL_SCOPE if private.get("full_mail") is True else ""),
            "state": private["state"],
            "access_type": "offline",
            "prompt": "consent select_account",
            "include_granted_scopes": "false",
            "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(
                hashlib.sha256(private["verifier"].encode()).digest()
            )
            .rstrip(b"=")
            .decode(),
        }

    def start_full_mail(self, identity):
        """A separate human action; never upgrades a pending metadata attempt."""
        self._full_mail_enabled()
        return self._start(identity, full_mail=True)

    def start(self, identity):
        return self._start(identity, full_mail=False)

    def _start(self, identity, *, full_mail):
        # Select the pending consent type under the same owner/account lock as creation.
        with self._session() as session:
            account, selected, binding = self._account(session, identity=identity)
            now = self.now()
            attempt = session.scalar(select(self.Attempt).where(self.Attempt.account_id == account.id,
                self.Attempt.status.in_(["pending", "exchanging"])).with_for_update())
            if attempt and (attempt.expires_at <= now or attempt.binding_digest != binding):
                attempt.status, attempt.sealed = "failed", None
                session.flush()
                attempt = None
            if attempt and attempt.status == "exchanging":
                raise ws.WorkspaceError("google_sign_in_in_progress", 409)
            if attempt:
                private = self._open(attempt.sealed, "attempt", account.id, binding, attempt.id)
                if (private.get("full_mail") is True) != full_mail:
                    raise ws.WorkspaceError("google_sign_in_in_progress", 409)
            else:
                attempt = self.Attempt(id=str(uuid4()), account_id=account.id, binding_digest=binding,
                    status="pending", created_at=now, expires_at=now + timedelta(minutes=10))
                private: dict[str, Any] = {"state": secrets.token_urlsafe(32), "verifier": secrets.token_urlsafe(48)}
                if full_mail:
                    private["full_mail"] = True
                attempt.state_digest = digest(private["state"])
                attempt.sealed = self._seal(private, "attempt", account.id, binding, attempt.id)
                session.add(attempt)
                self._audit(session, selected, account.id, "full_mail_sign_in_started" if full_mail else "sign_in_started", "pending")
            url = self.authorization_url + "?" + urlencode(self._authorization_fields(private))
            expires_at = attempt.expires_at.astimezone(UTC).isoformat()
            if full_mail:
                self._full_mail_enabled()
            session.commit()
            return {"authorization_url": url, "expires_at": expires_at}

    def callback(self, state, code=None, denied=False):
        expected: set[str] | None = None
        try:
            if isinstance(state, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", state):
                with self._session() as session:
                    attempt = session.scalar(select(self.Attempt).where(self.Attempt.state_digest == digest(state)))
                    if attempt and attempt.status == "pending":
                        account, _, binding = self._account(session, account_id=attempt.account_id)
                        private = self._open(attempt.sealed, "attempt", account.id, binding, attempt.id)
                        if private.get("full_mail") is True:
                            expected = set[str](SCOPES.split()) | {CALENDAR_SCOPE, FULL_MAIL_SCOPE}
        except Exception:
            return False
        marker = _EXPECTED_GOOGLE_GRANT.set(expected)
        try:
            return super().callback(state, code, denied)
        finally:
            _EXPECTED_GOOGLE_GRANT.reset(marker)

    @staticmethod
    def _grant_scopes(private) -> set[str]:
        scopes: set[str] = set(SCOPES.split())
        if private.get("calendar_read") is True:
            scopes.add(CALENDAR_SCOPE)
        if private.get("mail_full_read") is True:
            scopes.add(FULL_MAIL_SCOPE)
        if "granted_scopes" in private and private["granted_scopes"] != sorted(scopes):
            raise ValueError("Google sealed permissions unavailable")
        return scopes

    def credential(self, identity):
        # Refresh has the exact previous semantic grant, never silently downgrades it.
        expected: set[str] | None = None
        with self._session() as session:
            account, _, binding = self._account(session, identity=identity)
            credential = session.get(self.Credential, account.id)
            if credential and credential.status == "ready" and credential.binding_digest == binding:
                expected = self._grant_scopes(self._open(credential.sealed, "credential", account.id, binding))
        marker = _EXPECTED_GOOGLE_GRANT.set(expected)
        try:
            return super().credential(identity)
        finally:
            _EXPECTED_GOOGLE_GRANT.reset(marker)

    def _message_account(self, session, identity):
        """Current read authority without upgrading the caller's shared locks."""
        self._enabled()
        if identity.auth_mode != "clerk_jwt" or not identity.external_identity_id:
            raise ws.WorkspaceError("google_connection_unavailable", 403)
        ws._human(session, identity.box_id, identity.principal_id)
        account = session.scalar(select(ExternalIdentity).where(
            ExternalIdentity.id == identity.external_identity_id,
            ExternalIdentity.box_id == identity.box_id,
            ExternalIdentity.principal_id == identity.principal_id,
            ExternalIdentity.active.is_(True),
        ).with_for_update(read=True).execution_options(populate_existing=True))
        if account is None:
            raise ws.WorkspaceError("google_connection_unavailable", 403)
        binding = digest(canonical([self.config_digest, account.id, account.box_id,
            account.principal_id, account.issuer, account.subject, account.organization_id]))
        return account, binding

    def message_binding(self, identity, *, require_full=False, session=None):
        """Private source checks never refresh credentials or contact Google."""
        self._enabled()
        if require_full:
            self._full_mail_enabled()
        with self._session() if session is None else nullcontext(session) as current:
            account, binding = self._message_account(current, identity)
            credential = current.scalar(select(self.Credential).where(self.Credential.account_id == account.id)
                .with_for_update(read=True).execution_options(populate_existing=True))
            if not credential or credential.status != "ready" or credential.binding_digest != binding or credential.expires_at <= self.now():
                raise ws.WorkspaceError("google_connection_changed", 409)
            private = self._open(credential.sealed, "credential", account.id, binding)
            scopes = self._grant_scopes(private)
            if require_full and private.get("mail_full_read") is not True:
                raise ws.WorkspaceError("google_mail_consent_required", 409)
            connected_at = credential.connected_at.astimezone(UTC)
            self._enabled()
            if require_full:
                self._full_mail_enabled()
            return GoogleMessageBinding(account_id=account.id, binding_digest=binding, connected_at=connected_at,
                grant_sha256=digest(canonical(["cosmas-google-message-grant.v1", account.id, binding,
                    connected_at.isoformat(), private["subject"], sorted(scopes)])))

    def message_status(self, identity, *, session=None):
        """Body-connector status is a local check, including pending explicit consent."""
        self._full_mail_enabled()
        with self._session() if session is None else nullcontext(session) as current:
            account, binding = self._message_account(current, identity)
            credential = current.scalar(select(self.Credential).where(self.Credential.account_id == account.id)
                .with_for_update(read=True).execution_options(populate_existing=True))
            pending = current.scalar(select(self.Attempt).where(self.Attempt.account_id == account.id,
                self.Attempt.status.in_(["pending", "exchanging"]),
                self.Attempt.expires_at > self.now(), self.Attempt.binding_digest == binding))
            private = None
            if pending is None and credential and credential.status == "ready" and credential.binding_digest == binding and credential.expires_at > self.now():
                private = self._open(credential.sealed, "credential", account.id, binding)
                self._grant_scopes(private)
            self._full_mail_enabled()
            return {"contract_version": 1, "state": "connected" if private is not None else "sign_in_required",
                "full_mail_read": private is not None and private.get("mail_full_read") is True,
                "account": {"label": self._text(private["label"], 256), "email": self._text(private["email"], 320)} if private is not None else None}

    def _request(self, method, url, *, token=None, fields=None, params=None, check=None):
        self._enabled()
        if check:
            check()
        path = url.removeprefix(GMAIL_ORIGIN)
        gmail = url.startswith(GMAIL_ORIGIN) and (
            path == MESSAGES_PATH
            or path.startswith(MESSAGES_PATH + "/")
            and MESSAGE_ID.fullmatch(path.removeprefix(MESSAGES_PATH + "/")) is not None
        )
        if not (
            (method == "POST" and url == self.token_url and token is None and params is None)
            or (
                method == "GET"
                and (url in {USERINFO_URL, CALENDAR_URL} or gmail)
                and fields is None
                and isinstance(token, str)
            )
        ):
            raise ValueError("Unsupported Google operation")
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        budget = current_budget() or CaptureBudget(10)
        deadline = min(budget.expires_at, monotonic() + 10)

        async def read():
            import asyncio

            async with asyncio.timeout_at(deadline):
                async with httpx.AsyncClient(
                    timeout=min(10, budget.check()),
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                ) as client:
                    async with client.stream(
                        method, url, data=fields, params=params, headers=headers
                    ) as response:
                        if (
                            response.status_code != 200
                            or response.headers.get("content-type", "").split(";", 1)[0]
                            != "application/json"
                            or response.headers.get("content-encoding") not in {None, "identity"}
                        ):
                            raise ValueError("Google read unavailable")
                        raw = bytearray()
                        async for chunk in response.aiter_raw():
                            self._enabled()
                            if check:
                                check()
                            if len(raw) + len(chunk) > 65536:
                                raise ValueError("Google response unavailable")
                            raw.extend(chunk)
                        return bytes(raw)

        raw = budget.run(read)
        self._enabled()
        if check:
            check()

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Invalid Google response")
                result[key] = value
            return result

        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError("Invalid Google response")
        return value

    def _exchange(self, fields):
        return self._request(
            "POST",
            self.token_url,
            fields={
                **fields,
                "client_id": self.client_id,
                "client_secret": self.client_secret.get_secret_value(),
            },
        )

    def _verified(self, value, selected, *, subject=None, prior_refresh=None):
        token, refresh, expires, scopes = (
            value.get("access_token"),
            value.get("refresh_token", prior_refresh),
            value.get("expires_in"),
            value.get("scope"),
        )
        if not isinstance(scopes, str) or len(scopes) > 2048:
            raise ValueError("Google permissions unavailable")
        granted = {
            "email" if scope == "https://www.googleapis.com/auth/userinfo.email" else scope
            for scope in scopes.split()
        }
        expected = _EXPECTED_GOOGLE_GRANT.get()
        if (expected is not None and granted != expected) or (
            expected is None and granted not in (set(SCOPES.split()), set(SCOPES.split()) | {CALENDAR_SCOPE})
        ):
            raise ValueError("Google permissions unavailable")
        if (
            value.get("token_type", "").lower() != "bearer"
            or not isinstance(token, str)
            or not 1 <= len(token) <= 16384
            or any(ord(c) < 33 or ord(c) > 126 for c in token)
            or not isinstance(refresh, str)
            or not 1 <= len(refresh) <= 8192
            or type(expires) is not int
            or not 61 <= expires <= 86400
        ):
            raise ValueError("Google credential unavailable")
        me = self._request("GET", USERINFO_URL, token=token)
        account_subject = me.get("sub")
        if (
            not isinstance(account_subject, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,255}", account_subject) is None
            or subject is not None
            and account_subject != subject
            or me.get("email_verified") is not True
        ):
            raise ValueError("Google account identity unavailable")
        email = self._text(me.get("email"), 320)
        if not email or "@" not in email:
            raise ValueError("Google email unavailable")
        return {
            "token": token,
            "refresh": refresh,
            "subject": account_subject,
            "label": "Gmail",
            "email": email,
            "calendar_read": CALENDAR_SCOPE in granted,
            "mail_full_read": FULL_MAIL_SCOPE in granted,
            "granted_scopes": sorted(granted),
        }, self.now() + timedelta(seconds=expires)

    def _read_current(self, identity, private, binding, account_id, *, audit: bool | Literal["calendar", "full_mail"] = False) -> None:
        with self._session() as session:
            account, selected, current_binding = self._account(session, identity=identity)
            credential = session.get(self.Credential, account.id)
            if (
                account.id != account_id
                or current_binding != binding
                or credential is None
                or credential.status != "ready"
                or credential.binding_digest != binding
                or credential.expires_at <= self.now()
                or self._open(credential.sealed, "credential", account.id, binding) != private
            ):
                raise ws.WorkspaceError("google_connection_changed", 409)
            if audit:
                event = "calendar_read" if audit == "calendar" else "full_mail_read" if audit == "full_mail" else "mail_read"
                self._audit(session, selected, account.id, event, "read")
                session.commit()

    @staticmethod
    def _mail_header(value, limit):
        if not isinstance(value, str) or len(value) > 8192:
            raise ValueError("Invalid Gmail header")
        value = re.sub(r"\r?\n[ \t]+", " ", value)
        decoded = str(make_header(decode_header(value)))
        return GooglePersonalConnection._text(decoded, limit)

    def mail(self, identity):
        if current_budget() is None:
            with capture_budget(CaptureBudget(40)):
                return self.mail(identity)
        private, binding, account_id = self.credential(identity)
        def current():
            self._read_current(identity, private, binding, account_id)

        current()
        data = self._request(
            "GET",
            GMAIL_ORIGIN + MESSAGES_PATH,
            token=private["token"],
            params={
                "maxResults": "10",
                "labelIds": "INBOX",
                "includeSpamTrash": "false",
                "fields": "messages(id),nextPageToken",
            },
        )
        current()
        rows, page = data.get("messages", []), data.get("nextPageToken")
        if (
            not isinstance(rows, list)
            or len(rows) > 10
            or page is not None
            and (not isinstance(page, str) or not 1 <= len(page) <= 4096)
        ):
            raise ValueError("Invalid Gmail list")
        identifiers = []
        for row in rows:
            identifier = row.get("id") if isinstance(row, dict) else None
            if (
                not isinstance(identifier, str)
                or MESSAGE_ID.fullmatch(identifier) is None
                or identifier in identifiers
            ):
                raise ValueError("Invalid Gmail message reference")
            identifiers.append(identifier)
        items = []
        for identifier in identifiers:
            current()
            message = self._request(
                "GET",
                GMAIL_ORIGIN + MESSAGES_PATH + "/" + identifier,
                token=private["token"],
                params={
                    "format": "metadata",
                    "metadataHeaders": ["Subject", "From"],
                    "fields": "id,internalDate,labelIds,payload/headers",
                },
            )
            current()
            if message.get("id") != identifier:
                raise ValueError("Gmail message changed")
            labels, milliseconds, payload = (
                message.get("labelIds"),
                message.get("internalDate"),
                message.get("payload"),
            )
            if (
                not isinstance(labels, list)
                or len(labels) > 100
                or any(not isinstance(label, str) or len(label) > 128 for label in labels)
                or not isinstance(milliseconds, str)
                or not re.fullmatch(r"[0-9]{1,16}", milliseconds)
                or not isinstance(payload, dict)
            ):
                raise ValueError("Invalid Gmail metadata")
            headers = payload.get("headers", [])
            if not isinstance(headers, list) or len(headers) > 2:
                raise ValueError("Invalid Gmail headers")
            selected = {}
            for header in headers:
                if not isinstance(header, dict) or not isinstance(header.get("name"), str):
                    raise ValueError("Invalid Gmail header")
                name = header["name"].lower()
                if name not in {"subject", "from"} or name in selected:
                    raise ValueError("Unexpected Gmail header")
                selected[name] = self._mail_header(header.get("value"), 4096)
            received = datetime.fromtimestamp(int(milliseconds) / 1000, tz=UTC)
            if received > self.now() + timedelta(minutes=5):
                raise ValueError("Invalid Gmail date")
            items.append(
                {
                    "id": identifier,
                    "subject": self._text(selected.get("subject", ""), 998),
                    "sender": self._text(parseaddr(selected.get("from", ""))[1], 320),
                    "received_at": received.isoformat(),
                    "is_read": "UNREAD" not in labels,
                }
            )
        self._read_current(identity, private, binding, account_id, audit=True)
        return {
            "kind": "mail",
            "account": {"label": private["label"], "email": private["email"]},
            "items": items,
            "more": page is not None,
            "observed_at": self.now().isoformat(),
        }

    def calendar(self, identity):
        from cosmas_os.adapters.google_calendar import read_calendar

        if current_budget() is None:
            with capture_budget(CaptureBudget(40)):
                return self.calendar(identity)
        private, binding, account_id = self.credential(identity)
        if private.get("calendar_read") is not True:
            raise ws.WorkspaceError("google_calendar_consent_required", 409)
        return read_calendar(self, identity, private, binding, account_id)

    @staticmethod
    def _plain_body(payload):
        """Never follow an attachment reference or turn HTML into clinical evidence."""
        texts, count = [], 0
        reason = None
        independent_html = False
        alternative_html = 0
        def walk(part, depth=0, *, html_alternative=False):
            nonlocal count, reason, independent_html, alternative_html
            count += 1
            if count > 16 or depth > 4:
                reason = "oversize"
                return
            if not isinstance(part, dict):
                reason = "ambiguous"
                return
            mime, body, children = part.get("mimeType"), part.get("body", {}), part.get("parts", [])
            if part.get("filename") or isinstance(body, dict) and body.get("attachmentId"):
                reason = "attachment"
                return
            if not isinstance(mime, str) or not isinstance(body, dict) or not isinstance(children, list):
                reason = "ambiguous"
                return
            size = body.get("size", 0)
            if type(size) is not int or size < 0:
                reason = "invalid_encoding"
                return
            if mime.startswith("multipart/"):
                if mime not in {"multipart/alternative", "multipart/mixed", "multipart/related"} or body.get("data") or not children:
                    reason = "unsupported_mime"
                    return
                if len(children) > 16:
                    reason = "oversize"
                    return
                before_texts, before_html = len(texts), alternative_html
                for child in children:
                    walk(child, depth + 1, html_alternative=mime == "multipart/alternative")
                if mime == "multipart/alternative" and alternative_html > before_html and len(texts) == before_texts:
                    independent_html = True  # No plain representation within this alternative group.
                return
            if children:
                reason = "ambiguous"
                return
            if mime == "text/html":
                # Only a direct alternative may represent the same plain text.
                # HTML in mixed/related content can carry separate message facts.
                independent_html |= not html_alternative
                alternative_html += html_alternative
                return
            if mime != "text/plain":
                reason = "unsupported_mime"
                return
            data = body.get("data")
            if not isinstance(data, str) or not re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", data):
                reason = "invalid_encoding"
                return
            if len(data) > 28_000 or size > 20_000:
                reason = "oversize"
                return
            try:
                raw = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
                if len(raw) != size or base64.urlsafe_b64encode(raw).decode().rstrip("=") != data.rstrip("="):
                    raise ValueError
                text = raw.decode("utf-8", errors="strict").replace("\r\n", "\n")
                if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in text):
                    raise ValueError
            except (ValueError, UnicodeError):
                reason = "invalid_encoding"
                return
            texts.append(text)
        walk(payload)
        if reason:
            return None, reason
        if not texts:
            return None, "html_only"
        if len(texts) != 1 or independent_html:
            return None, "ambiguous"
        return texts[0], None

    def read_message(self, identity, selection: GoogleMessageSelection):
        """Read precisely one previously observed message; the application owns selection."""
        self._full_mail_enabled()
        selection = GoogleMessageSelection.model_validate(selection)
        if current_budget() is None:
            with capture_budget(CaptureBudget(40)):
                return self.read_message(identity, selection)
        private, binding, account_id = self.credential(identity)
        if private.get("mail_full_read") is not True:
            raise ws.WorkspaceError("google_mail_consent_required", 409)
        custody = self.message_binding(identity, require_full=True)
        def current():
            self._full_mail_enabled()
            self._read_current(identity, private, binding, account_id)

        current()
        message = self._request("GET", GMAIL_ORIGIN + MESSAGES_PATH + "/" + selection.message_id,
            token=private["token"], params={"format": "full",
                "fields": "id,threadId,historyId,internalDate,labelIds,payload"},
            check=current)
        current()
        if self.message_binding(identity, require_full=True) != custody:
            raise ws.WorkspaceError("google_connection_changed", 409)
        thread, labels, milliseconds, payload = (message.get("threadId"), message.get("labelIds"),
            message.get("internalDate"), message.get("payload"))
        if message.get("id") != selection.message_id or not isinstance(thread, str) or not MESSAGE_ID.fullmatch(thread) or (
            selection.thread_id is not None and selection.thread_id != thread
            or not isinstance(labels, list) or len(labels) > 100
            or any(not isinstance(label, str) or len(label) > 128 for label in labels)
            or not isinstance(milliseconds, str) or not re.fullmatch(r"[0-9]{1,16}", milliseconds)
            or not isinstance(payload, dict)
        ):
            raise ValueError("Invalid selected Gmail message")
        headers = payload.get("headers", [])
        if not isinstance(headers, list) or len(headers) > 100:
            raise ValueError("Invalid Gmail headers")
        selected = {}
        for header in headers:
            if not isinstance(header, dict) or not isinstance(header.get("name"), str):
                raise ValueError("Invalid Gmail header")
            name = header["name"].lower()
            if name not in {"subject", "from"}:
                continue
            if name in selected:
                raise ValueError("Ambiguous Gmail header")
            selected[name] = self._mail_header(header.get("value"), 4096)
        subject = self._text(selected.get("subject", ""), 998)
        sender = self._text(parseaddr(selected.get("from", ""))[1], 320)
        received = datetime.fromtimestamp(int(milliseconds) / 1000, tz=UTC)
        if received > self.now() + timedelta(minutes=5):
            raise ValueError("Invalid Gmail date")
        text, reason = self._plain_body(payload)
        content = f"Subject: {subject}\nFrom: {sender}\nReceived: {received.isoformat()}\n\n{text}" if text is not None else None
        if content is not None and len(content) > 5000:
            content, reason = None, "oversize"
        current()
        if self.message_binding(identity, require_full=True) != custody:
            raise ws.WorkspaceError("google_connection_changed", 409)
        value = GoogleMessageRead(message_id=selection.message_id, thread_id=thread, history_id=message.get("historyId"),
            subject=subject, sender=sender, received_at=received, is_read="UNREAD" not in labels,
            observed_at=self.now(), status="complete" if content is not None else "needs_human",
            content=content, reason=reason, raw_sha256=digest(canonical(message)),
            content_sha256=digest(content) if content is not None else None, custody=custody)
        self._full_mail_enabled()
        self._read_current(identity, private, binding, account_id, audit="full_mail")
        return value

    def _full_mail_enabled(self):
        self._enabled()
        if getattr(self.settings, "workspace_google_message_available", False) is not True:
            raise ws.WorkspaceError("google_message_unavailable", 503)

    def close(self):
        self._closed = True
