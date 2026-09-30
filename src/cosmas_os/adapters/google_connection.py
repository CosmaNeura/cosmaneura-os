"""Personal Google/Gmail metadata connection using the existing durable OAuth state.

Read mappings and delegated auth pattern follow Activepieces community Gmail
(MIT attribution in docs/third-party/activepieces-LICENSE.txt) and Google's
published OAuth/OpenID/Gmail contracts. No mailbox write or service account exists.
"""

import base64
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr
from time import monotonic
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cosmas_os.adapters.microsoft_connection import (
    MicrosoftPersonalConnection,
    canonical,
    digest,
    exact_origin,
)
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import CaptureBudget, capture_budget, current_budget
from cosmas_os.google_connection_models import GoogleConnectionAttempt, GoogleConnectionCredential

CALLBACK_PATH = "/connections/google/callback"
SCOPES = "openid email https://www.googleapis.com/auth/gmail.metadata"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GMAIL_ORIGIN = "https://gmail.googleapis.com"
MESSAGES_PATH = "/gmail/v1/users/me/messages"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
MESSAGE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


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
            "scope": SCOPES + " " + CALENDAR_SCOPE,
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

    def _request(self, method, url, *, token=None, fields=None, params=None):
        self._enabled()
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
                            if len(raw) + len(chunk) > 65536:
                                raise ValueError("Google response unavailable")
                            raw.extend(chunk)
                        return bytes(raw)

        raw = budget.run(read)
        self._enabled()

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
        if granted not in (set(SCOPES.split()), set(SCOPES.split()) | {CALENDAR_SCOPE}):
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
        }, self.now() + timedelta(seconds=expires)

    def _read_current(self, identity, private, binding, account_id, *, audit=False):
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
                self._audit(session, selected, account.id, "calendar_read" if audit == "calendar" else "mail_read", "read")
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

    def close(self):
        self._closed = True
