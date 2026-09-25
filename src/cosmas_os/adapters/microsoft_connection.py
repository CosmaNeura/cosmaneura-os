"""Personal Microsoft email and calendar connection.

Delegated OAuth and Graph read mappings adapted from Activepieces community
Outlook connectors; see docs/third-party/activepieces-LICENSE.txt and
docs/microsoft-personal-connection.md. No Graph write operation is exposed.

Authorization-code exchanges are claimed durably before I/O. Unknown exchanges
are never retried automatically. Stored proof and refresh material are AES-GCM
sealed and bound to the exact account, selection and installed configuration.
"""

import base64
import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select

from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import (
    CaptureBudget,
    check_capture_deadline,
    current_budget,
)
from cosmas_os.application.core_record_deadline import session_deadline
from cosmas_os.microsoft_connection_models import (
    MicrosoftConnectionAttempt,
    MicrosoftConnectionCredential,
)
from cosmas_os.models import AuditEvent, ExternalIdentity
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable

CALLBACK_PATH = "/connections/microsoft/callback"
SCOPES = "offline_access User.Read Mail.Read Calendars.Read"
GRAPH_ORIGIN = "https://graph.microsoft.com"
GRAPH_PATHS = {"/v1.0/me", "/v1.0/me/mailFolders/inbox/messages", "/v1.0/me/calendarView"}


@dataclass(frozen=True)
class MicrosoftOwner:
    box_id: str
    owner_id: str


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def exact_origin(value):
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in {None, 443}
        or parts.path
        or parts.query
        or parts.fragment
        or parts.hostname.endswith(".")
        or not re.fullmatch(r"https://[a-z0-9.-]+", value)
        or value != "https://" + parts.hostname
    ):
        raise ValueError("A fixed HTTPS origin is required")
    return value


class MicrosoftPersonalConnection:
    # Provider subclasses reuse durable claims and private custody, never credentials.
    Attempt: Any = MicrosoftConnectionAttempt
    Credential: Any = MicrosoftConnectionCredential
    provider = "microsoft"

    def __init__(self, settings, sessions, *, transport=None, now=lambda: datetime.now(UTC)):
        self.settings, self.sessions, self.now = settings, sessions, now
        if (
            not settings.workspace_available
            or not settings.workspace_authenticated_enabled
            or settings.auth_mode != "clerk_jwt"
            or not settings.workspace_microsoft_connection_enabled
        ):
            raise ValueError("Authenticated Microsoft connection must be enabled")
        self.tenant = str(UUID(settings.microsoft_connection_tenant_id))
        self.client_id = str(UUID(settings.microsoft_connection_client_id))
        self.return_origin = exact_origin(settings.microsoft_connection_return_origin)
        callback = urlsplit(settings.microsoft_connection_callback_uri)
        exact_origin(f"{callback.scheme}://{callback.netloc}")
        if callback.path != CALLBACK_PATH or callback.query or callback.fragment:
            raise ValueError("Use the fixed Microsoft callback path")
        self.callback_uri = settings.microsoft_connection_callback_uri
        if (
            not settings.microsoft_connection_client_secret
            or not settings.microsoft_connection_encryption_key
        ):
            raise ValueError("Microsoft client and encryption secrets are required")
        self.client_secret = settings.microsoft_connection_client_secret
        key = base64.b64decode(
            settings.microsoft_connection_encryption_key.get_secret_value(),
            altchars=b"-_",
            validate=True,
        )
        if len(key) != 32:
            raise ValueError("Use a 32-byte credential encryption key")
        self._cipher = AESGCM(key)
        self.authorization_url = (
            f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/authorize"
        )
        self.token_url = f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"
        self.config_digest = digest(canonical(self._configuration()))
        self._client = httpx.Client(
            timeout=httpx.Timeout(10),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        self._closed = False

    def _configuration(self):
        s = self.settings
        return [
            s.microsoft_connection_tenant_id,
            s.microsoft_connection_client_id,
            s.microsoft_connection_callback_uri,
            s.microsoft_connection_return_origin,
            digest(s.microsoft_connection_client_secret.get_secret_value())
            if s.microsoft_connection_client_secret
            else "",
            digest(s.microsoft_connection_encryption_key.get_secret_value())
            if s.microsoft_connection_encryption_key
            else "",
        ]

    def _enabled(self):
        check_capture_deadline()
        if (
            self._closed
            or not self.settings.workspace_available
            or not self.settings.workspace_authenticated_enabled
            or self.settings.auth_mode != "clerk_jwt"
            or not self.settings.workspace_microsoft_connection_enabled
            or digest(canonical(self._configuration())) != self.config_digest
        ):
            raise ConnectorUnavailable(self.provider + "_connection_unavailable")

    @contextmanager
    def _session(self):
        self._enabled()
        session = self.sessions()
        try:
            with session_deadline(
                session, current_budget() or CaptureBudget(30), allow_writes=True
            ):
                yield session
        finally:
            session.close()

    def _account(self, session, *, identity=None, account_id=None):
        self._enabled()
        query = select(ExternalIdentity).where(ExternalIdentity.active.is_(True))
        if identity is not None:
            if identity.auth_mode != "clerk_jwt" or not identity.external_identity_id:
                raise ws.WorkspaceError(self.provider + "_connection_unavailable", 403)
            query = query.where(
                ExternalIdentity.id == identity.external_identity_id,
                ExternalIdentity.box_id == identity.box_id,
                ExternalIdentity.principal_id == identity.principal_id,
            )
        elif account_id is None:
            raise ws.WorkspaceError(self.provider + "_connection_unavailable", 403)
        if account_id is not None:
            query = query.where(ExternalIdentity.id == account_id)
        account = session.scalar(query.with_for_update())
        if account is None:
            raise ws.WorkspaceError(self.provider + "_connection_unavailable", 403)
        ws._human(session, account.box_id, account.principal_id, creating=True)
        selected = MicrosoftOwner(account.box_id, account.principal_id)
        binding = digest(
            canonical(
                [
                    self.config_digest,
                    account.id,
                    selected.box_id,
                    selected.owner_id,
                    account.issuer,
                    account.subject,
                    account.organization_id,
                ]
            )
        )
        return account, selected, binding

    def _seal(self, value, purpose, account_id, binding, identifier=""):
        nonce = secrets.token_bytes(12)
        aad = canonical(
            [self.provider + "-connection-v1", purpose, account_id, binding, identifier]
        ).encode()
        return nonce + self._cipher.encrypt(nonce, canonical(value).encode(), aad)

    def _open(self, raw, purpose, account_id, binding, identifier=""):
        if not raw or not 28 <= len(raw) <= 32768:
            raise ValueError
        aad = canonical(
            [self.provider + "-connection-v1", purpose, account_id, binding, identifier]
        ).encode()
        value = json.loads(self._cipher.decrypt(raw[:12], raw[12:], aad))
        if not isinstance(value, dict):
            raise ValueError
        return value

    def _audit(self, session, selected, account_id, event, outcome):
        session.add(
            AuditEvent(
                box_id=str(selected.box_id),
                aggregate_type=self.provider + "_connection",
                aggregate_id=account_id,
                actor_principal_id=str(selected.owner_id),
                event_type="workspace." + self.provider + "_" + event,
                outcome=outcome,
                detail={},
            )
        )

    def status(self, identity):
        with self._session() as session:
            account, selected, binding = self._account(session, identity=identity)
            credential = session.get(self.Credential, account.id)
            state = "sign_in_required"
            if credential and credential.binding_digest == binding and credential.sealed:
                if credential.status == "ready":
                    private = self._open(credential.sealed, "credential", account.id, binding)
                    state = "connected"
                elif credential.status == "refreshing":
                    state = "sign_in_required"
            pending = session.scalar(
                select(self.Attempt).where(
                    self.Attempt.account_id == account.id,
                    self.Attempt.status.in_(["pending", "exchanging"]),
                    self.Attempt.expires_at > self.now(),
                )
            )
            if pending and pending.binding_digest == binding:
                state = "sign_in_pending" if pending.status == "pending" else "completing_sign_in"
            return {
                "state": state,
                "account": {"label": private["label"], "email": private["email"]}
                if state == "connected"
                else None,
                "connected_at": credential.connected_at.isoformat()
                if credential and state == "connected"
                else None,
            }

    def start(self, identity):
        with self._session() as session:
            account, selected, binding = self._account(session, identity=identity)
            now = self.now()
            attempt = session.scalar(
                select(self.Attempt)
                .where(
                    self.Attempt.account_id == account.id,
                    self.Attempt.status.in_(["pending", "exchanging"]),
                )
                .with_for_update()
            )
            if attempt and (attempt.expires_at <= now or attempt.binding_digest != binding):
                attempt.status, attempt.sealed = "failed", None
                session.flush()
                attempt = None
            if attempt and attempt.status == "exchanging":
                raise ws.WorkspaceError(self.provider + "_sign_in_in_progress", 409)
            if attempt is None:
                attempt = self.Attempt(
                    id=str(uuid4()),
                    account_id=account.id,
                    binding_digest=binding,
                    status="pending",
                    created_at=now,
                    expires_at=now + timedelta(minutes=10),
                )
                private = {
                    "state": secrets.token_urlsafe(32),
                    "verifier": secrets.token_urlsafe(48),
                }
                attempt.state_digest = digest(private["state"])
                attempt.sealed = self._seal(private, "attempt", account.id, binding, attempt.id)
                session.add(attempt)
                self._audit(session, selected, account.id, "sign_in_started", "pending")
            else:
                private = self._open(attempt.sealed, "attempt", account.id, binding, attempt.id)
            url = self.authorization_url + "?" + urlencode(self._authorization_fields(private))
            expires_at = attempt.expires_at.astimezone(UTC).isoformat()
            session.commit()
            return {"authorization_url": url, "expires_at": expires_at}

    def _authorization_fields(self, private):
        return {
            "client_id": self.client_id,
            "redirect_uri": self.callback_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": private["state"],
            "prompt": "select_account",
            "response_mode": "query",
            "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(
                hashlib.sha256(private["verifier"].encode()).digest()
            )
            .rstrip(b"=")
            .decode(),
        }

    def disconnect(self, identity):
        with self._session() as session:
            account, selected, _ = self._account(session, identity=identity)
            credential = session.get(self.Credential, account.id)
            changed = False
            if credential and credential.status != "disconnected":
                changed = True
                credential.status, credential.sealed, credential.refresh_id = (
                    "disconnected",
                    None,
                    None,
                )
            for attempt in session.scalars(
                select(self.Attempt).where(
                    self.Attempt.account_id == account.id,
                    self.Attempt.status.in_(["pending", "exchanging"]),
                )
            ):
                attempt.status, attempt.sealed = "failed", None
                changed = True
            if changed:
                self._audit(session, selected, account.id, "disconnected", "disconnected")
            session.commit()
        return {"state": "disconnected"}

    def _request(self, method, url, *, token=None, fields=None, params=None):
        self._enabled()
        if not (
            (method == "POST" and url == self.token_url and token is None)
            or (
                method == "GET"
                and url.removeprefix(GRAPH_ORIGIN) in GRAPH_PATHS
                and url.startswith(GRAPH_ORIGIN)
                and fields is None
                and isinstance(token, str)
            )
        ):
            raise ValueError("Unsupported Microsoft operation")
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if token is not None:
            headers.update(Authorization="Bearer " + token, Prefer='outlook.timezone="UTC"')
        deadline = monotonic() + 10
        with self._client.stream(
            method, url, data=fields, params=params, headers=headers
        ) as response:
            if (
                response.status_code != 200
                or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                or response.headers.get("content-encoding") not in {None, "identity"}
            ):
                raise ValueError("Microsoft read unavailable")
            raw = bytearray()
            for chunk in response.iter_raw():
                self._enabled()
                if monotonic() >= deadline or len(raw) + len(chunk) > (
                    32768 if method == "POST" else 262144
                ):
                    raise ValueError("Microsoft response unavailable")
                raw.extend(chunk)
        self._enabled()
        if monotonic() >= deadline:
            raise ValueError("Microsoft response unavailable")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Invalid Microsoft response")
                result[key] = value
            return result

        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError("Invalid Microsoft response")
        return value

    def _exchange(self, fields):
        return self._request(
            "POST",
            self.token_url,
            fields={
                **fields,
                "client_id": self.client_id,
                "client_secret": self.client_secret.get_secret_value(),
                "scope": SCOPES,
            },
        )

    def _verified(self, value, selected, *, subject=None, prior_refresh=None):
        token = value.get("access_token")
        refresh = value.get("refresh_token", prior_refresh)
        expires = value.get("expires_in")
        scopes = value.get("scope")
        if not isinstance(scopes, str) or len(scopes) > 2048:
            raise ValueError("Microsoft permissions unavailable")
        granted = {scope.removeprefix(GRAPH_ORIGIN + "/") for scope in scopes.split()}
        if not {"User.Read", "Mail.Read", "Calendars.Read"} <= granted or granted - set(
            SCOPES.split()
        ):
            raise ValueError("Microsoft permissions unavailable")
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
            raise ValueError("Microsoft credential unavailable")
        me = self._request(
            "GET",
            GRAPH_ORIGIN + "/v1.0/me",
            token=token,
            params={"$select": "id,displayName,mail,userPrincipalName"},
        )
        account_subject = str(UUID(me["id"]))
        if subject is not None and account_subject != subject:
            raise ValueError("Microsoft account changed")
        label = self._text(me.get("displayName") or "Microsoft account", 256)
        email = self._text(me.get("mail") or me.get("userPrincipalName") or "", 320)
        if not email:
            raise ValueError("Microsoft account email unavailable")
        return {
            "token": token,
            "refresh": refresh,
            "subject": account_subject,
            "label": label,
            "email": email,
        }, self.now() + timedelta(seconds=expires)

    @staticmethod
    def _text(value, limit):
        if (
            not isinstance(value, str)
            or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Invalid Microsoft response")
        return value

    def _claim_current(self, account_id, selected, binding, *, attempt_id=None, refresh_id=None):
        """Recheck durable authority before the second provider request."""
        with self._session() as session:
            account, current, current_binding = self._account(session, account_id=account_id)
            if current != selected or current_binding != binding:
                raise ValueError("Microsoft connection changed")
            if attempt_id is not None:
                attempt = session.get(self.Attempt, attempt_id)
                if (
                    attempt is None
                    or attempt.account_id != account.id
                    or attempt.binding_digest != binding
                    or attempt.status != "exchanging"
                    or attempt.expires_at <= self.now()
                ):
                    raise ValueError("Microsoft connection changed")
            else:
                credential = session.get(self.Credential, account.id)
                if (
                    credential is None
                    or credential.binding_digest != binding
                    or credential.status != "refreshing"
                    or credential.refresh_id != refresh_id
                ):
                    raise ValueError("Microsoft connection changed")

    def callback(self, state, code=None, denied=False):
        attempt_id = None
        try:
            if not isinstance(state, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", state) is None:
                raise ValueError
            with self._session() as session:
                # Discover exact digest, then lock the account before the attempt,
                # matching start/disconnect/credential lock order.
                discovered = session.scalar(
                    select(self.Attempt).where(self.Attempt.state_digest == digest(state))
                )
                if discovered is None:
                    raise ValueError
                account, selected, binding = self._account(
                    session, account_id=discovered.account_id
                )
                session.expire(discovered)
                attempt = session.scalar(
                    select(self.Attempt).where(self.Attempt.id == discovered.id).with_for_update()
                )
                if (
                    attempt is None
                    or attempt.status != "pending"
                    or attempt.expires_at <= self.now()
                    or attempt.binding_digest != binding
                ):
                    raise ValueError
                attempt_id, account_id = attempt.id, account.id
                private = self._open(attempt.sealed, "attempt", account.id, binding, attempt.id)
                if denied:
                    attempt.status, attempt.sealed = "failed", None
                    self._audit(session, selected, account.id, "sign_in_finished", "declined")
                    session.commit()
                    return False
                if (
                    not isinstance(code, str)
                    or not 1 <= len(code) <= 4096
                    or any(ord(c) < 33 or ord(c) > 126 for c in code)
                ):
                    raise ValueError
                attempt.status = "exchanging"
                session.commit()
            value = self._exchange(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.callback_uri,
                    "code_verifier": private["verifier"],
                }
            )
            self._claim_current(account_id, selected, binding, attempt_id=attempt_id)
            private_credential, expiry = self._verified(value, selected)
            with self._session() as session:
                account, current, current_binding = self._account(session, account_id=account_id)
                attempt = session.get(self.Attempt, attempt_id)
                if (
                    current != selected
                    or current_binding != binding
                    or attempt is None
                    or attempt.status != "exchanging"
                    or attempt.expires_at <= self.now()
                ):
                    raise ValueError
                credential = session.get(self.Credential, account.id)
                if credential is None:
                    credential = self.Credential(account_id=account.id)
                    session.add(credential)
                credential.binding_digest, credential.status, credential.refresh_id = (
                    binding,
                    "ready",
                    None,
                )
                credential.sealed = self._seal(
                    private_credential, "credential", account.id, binding
                )
                credential.connected_at, credential.expires_at = self.now(), expiry
                attempt.status, attempt.sealed = "ready", None
                self._audit(session, current, account.id, "sign_in_finished", "connected")
                session.commit()
            return True
        except Exception:
            if attempt_id:
                self._fail_attempt(attempt_id)
            return False

    def _fail_attempt(self, attempt_id):
        try:
            with self._session() as session:
                attempt = session.scalar(
                    select(self.Attempt).where(self.Attempt.id == attempt_id).with_for_update()
                )
                if attempt and attempt.status in {"pending", "exchanging"}:
                    attempt.status, attempt.sealed = "failed", None
                    session.commit()
        except Exception:
            pass  # A retained exchanging row blocks reuse and requires a new sign-in.

    def credential(self, identity):
        refresh_id = None
        account_id = None
        try:
            with self._session() as session:
                account, selected, binding = self._account(session, identity=identity)
                account_id = account.id
                credential = session.get(self.Credential, account.id)
                if (
                    credential is None
                    or credential.status != "ready"
                    or credential.binding_digest != binding
                ):
                    raise ValueError
                private = self._open(credential.sealed, "credential", account.id, binding)
                if credential.expires_at >= self.now() + timedelta(seconds=60):
                    return private, binding, account.id

                refresh_id = str(uuid4())
                credential.status, credential.refresh_id = "refreshing", refresh_id
                session.commit()
            value = self._exchange(
                {"grant_type": "refresh_token", "refresh_token": private["refresh"]}
            )
            self._claim_current(account_id, selected, binding, refresh_id=refresh_id)
            fresh, expiry = self._verified(
                value, selected, subject=private["subject"], prior_refresh=private["refresh"]
            )
            with self._session() as session:
                account, current, current_binding = self._account(session, account_id=account_id)
                credential = session.get(self.Credential, account.id)
                if (
                    current != selected
                    or current_binding != binding
                    or credential is None
                    or credential.status != "refreshing"
                    or credential.refresh_id != refresh_id
                ):
                    raise ValueError
                credential.sealed = self._seal(fresh, "credential", account.id, binding)
                credential.expires_at, credential.status, credential.refresh_id = (
                    expiry,
                    "ready",
                    None,
                )
                self._audit(session, selected, account.id, "credential_refreshed", "connected")
                session.commit()
            return fresh, binding, account_id

        except Exception:
            if refresh_id and account_id:
                try:
                    with self._session() as session:
                        credential = session.scalar(
                            select(self.Credential)
                            .where(self.Credential.account_id == account_id)
                            .with_for_update()
                        )
                        if credential and credential.refresh_id == refresh_id:
                            credential.status, credential.sealed = "failed", None
                            session.commit()
                except Exception:
                    pass
            raise ConnectorUnavailable(self.provider + "_connection_unavailable") from None

    def _read(self, identity, kind):
        private, binding, account_id = self.credential(identity)
        now = self.now()
        if kind == "mail":
            path = "/v1.0/me/mailFolders/inbox/messages"
            params = {
                "$top": "25",
                "$select": "id,subject,from,receivedDateTime,isRead",
                "$orderby": "receivedDateTime desc",
            }
        else:
            path = "/v1.0/me/calendarView"
            params = {
                "$top": "25",
                "$select": "id,subject,start,end,isCancelled,isAllDay",
                "$orderby": "start/dateTime",
                "startDateTime": now.isoformat(),
                "endDateTime": (now + timedelta(days=7)).isoformat(),
            }
        data = self._request("GET", GRAPH_ORIGIN + path, token=private["token"], params=params)
        rows = data.get("value")
        if not isinstance(rows, list) or len(rows) > 25:
            raise ValueError("Invalid Microsoft response")
        items = []
        for row in rows:
            item = {
                "id": self._text(row["id"], 2048),
                "subject": self._text(row.get("subject") or "", 998),
            }
            if kind == "mail":
                sender = row.get("from", {}).get("emailAddress", {})
                if type(row.get("isRead")) is not bool:
                    raise ValueError("Invalid Microsoft response")
                item.update(
                    sender=self._text(sender.get("address") or "", 320),
                    received_at=self._timestamp(row["receivedDateTime"]),
                    is_read=row["isRead"],
                )
            else:
                if any(type(row.get(key)) is not bool for key in ("isCancelled", "isAllDay")):
                    raise ValueError("Invalid Microsoft response")

                def utc_time(value):
                    if value["timeZone"] != "UTC":
                        raise ValueError("Invalid Microsoft timezone")
                    return self._timestamp(value["dateTime"] + "Z")

                item.update(
                    starts_at=utc_time(row["start"]),
                    ends_at=utc_time(row["end"]),
                    cancelled=row["isCancelled"],
                    all_day=row["isAllDay"],
                )
            items.append(item)
        # Fence disclosure after network I/O: a changed account, disconnect,
        # refreshed credential or revoked current membership invalidates this read.
        with self._session() as session:
            account, selected, current_binding = self._account(session, identity=identity)
            credential = session.get(self.Credential, account.id)
            if (
                account.id != account_id
                or current_binding != binding
                or credential is None
                or credential.status != "ready"
                or credential.binding_digest != binding
                or self._open(credential.sealed, "credential", account.id, binding) != private
            ):
                raise ws.WorkspaceError(self.provider + "_connection_changed", 409)
            self._audit(session, selected, account.id, kind + "_read", "read")
            session.commit()
        return {
            "kind": kind,
            "account": {"label": private["label"], "email": private["email"]},
            "items": items,
            "more": bool(data.get("@odata.nextLink")),
            "observed_at": now.isoformat(),
        }

    @staticmethod
    def _timestamp(value):
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError("Invalid Microsoft time")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("Invalid Microsoft time")
        return parsed.astimezone(UTC).isoformat()

    def mail(self, identity):
        return self._read(identity, "mail")

    def calendar(self, identity):
        return self._read(identity, "calendar")

    def close(self):
        self._closed = True
        self._client.close()
