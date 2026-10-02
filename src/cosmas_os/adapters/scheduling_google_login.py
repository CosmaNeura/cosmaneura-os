"""Google sign-in for an existing reviewed Scheduling account.

Authorization-code exchanges are claimed durably before I/O. Unknown exchanges
are never retried automatically. Stored proof and refresh material are AES-GCM
sealed and bound to the exact account, selection and installed configuration.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from time import monotonic
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr
from sqlalchemy import select

from cosmas_os.adapters.scheduling_identity import SchedulingIdentityVerifier
from cosmas_os.adapters.scheduling_runtime import SchedulingStaffCredential
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import (
    CaptureBudget,
    check_capture_deadline,
    current_budget,
)
from cosmas_os.application.core_record_deadline import session_deadline
from cosmas_os.models import AuditEvent, ExternalIdentity, SchedulingAccount
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import SchedulingSelection
from cosmas_os.scheduling_login_models import SchedulingLoginAttempt, SchedulingLoginCredential

CALLBACK_PATH = "/connections/scheduling/google/callback"
AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def exact_origin(value, *, allow_api_path=False):
    parts = urlsplit(value)
    suffix = "/api" if allow_api_path and parts.path == "/api" else ""
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in {None, 443}
        or parts.path != suffix
        or parts.query
        or parts.fragment
        or parts.hostname.endswith(".")
        or not re.fullmatch(r"https://[a-z0-9.-]+" + suffix, value)
        or value != "https://" + parts.hostname + suffix
    ):
        raise ValueError("A fixed HTTPS origin is required")
    return value


class SchedulingGoogleLogin:
    def __init__(
        self,
        settings,
        sessions,
        *,
        google_transport=None,
        scheduling_transport=None,
        now=lambda: datetime.now(UTC),
    ):
        if (
            not settings.workspace_scheduling_available
            or not settings.workspace_scheduling_login_enabled
        ):
            raise ValueError("Authenticated Scheduling must be enabled")
        self.settings, self.sessions, self.now = settings, sessions, now
        self.origin = exact_origin(settings.scheduling_origin, allow_api_path=True)
        self.return_origin = exact_origin(settings.scheduling_login_return_origin)
        callback = urlsplit(settings.scheduling_google_callback_uri)
        exact_origin(f"{callback.scheme}://{callback.netloc}")
        if callback.path != CALLBACK_PATH or callback.query or callback.fragment:
            raise ValueError("Use the fixed Scheduling callback path")
        self.callback_uri = settings.scheduling_google_callback_uri
        self.client_id = settings.scheduling_google_client_id
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,220}\.apps\.googleusercontent\.com", self.client_id):
            raise ValueError("A Google OAuth web client is required")
        if (
            not settings.scheduling_google_client_secret
            or not settings.scheduling_login_encryption_key
        ):
            raise ValueError("Google client and encryption secrets are required")
        self.client_secret = settings.scheduling_google_client_secret
        key = base64.b64decode(
            settings.scheduling_login_encryption_key.get_secret_value(),
            altchars=b"-_",
            validate=True,
        )
        if len(key) != 32:
            raise ValueError("Use a 32-byte Scheduling credential encryption key")
        self._cipher = AESGCM(key)
        self.config_digest = digest(
            canonical(
                [
                    self.origin,
                    self.return_origin,
                    self.callback_uri,
                    self.client_id,
                    digest(self.client_secret.get_secret_value()),
                    digest(settings.scheduling_login_encryption_key.get_secret_value()),
                ]
            )
        )
        self._client = httpx.Client(
            timeout=httpx.Timeout(10),
            follow_redirects=False,
            trust_env=False,
            transport=google_transport,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        try:
            self._verifier = SchedulingIdentityVerifier(self.origin, transport=scheduling_transport)
        except BaseException:
            self._client.close()
            raise
        self._closed = False

    def _enabled(self):
        check_capture_deadline()
        if (
            self._closed
            or not self.settings.workspace_scheduling_available
            or not self.settings.workspace_scheduling_login_enabled
        ):
            raise ConnectorUnavailable("scheduling_sign_in_unavailable")
        current = [
            self.settings.scheduling_origin,
            self.settings.scheduling_login_return_origin,
            self.settings.scheduling_google_callback_uri,
            self.settings.scheduling_google_client_id,
            digest(self.settings.scheduling_google_client_secret.get_secret_value())
            if self.settings.scheduling_google_client_secret
            else "",
            digest(self.settings.scheduling_login_encryption_key.get_secret_value())
            if self.settings.scheduling_login_encryption_key
            else "",
        ]
        if digest(canonical(current)) != self.config_digest:
            raise ConnectorUnavailable("scheduling_sign_in_unavailable")

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

    def _account(self, session, *, identity=None, account_id=None, selection=None):
        self._enabled()
        query = (
            select(SchedulingAccount, ExternalIdentity)
            .join(ExternalIdentity, ExternalIdentity.id == SchedulingAccount.external_identity_id)
            .where(SchedulingAccount.revoked_at.is_(None), ExternalIdentity.active.is_(True))
        )
        if identity is not None:
            if identity.auth_mode != "clerk_jwt" or not identity.external_identity_id:
                raise ws.WorkspaceError("scheduling_sign_in_unavailable", 403)
            query = query.where(
                ExternalIdentity.id == identity.external_identity_id,
                ExternalIdentity.box_id == identity.box_id,
                ExternalIdentity.principal_id == identity.principal_id,
            )
        if account_id is not None:
            query = query.where(SchedulingAccount.id == account_id)
        if selection is not None:
            query = query.where(
                ExternalIdentity.box_id == str(selection.box_id),
                ExternalIdentity.principal_id == str(selection.owner_id),
                SchedulingAccount.practice_id == str(selection.practice_id),
                SchedulingAccount.actor_id == str(selection.expected_actor_id),
                SchedulingAccount.practitioner_id == str(selection.practitioner_id),
                SchedulingAccount.location_id == str(selection.location_id),
                SchedulingAccount.appointment_type_id == str(selection.appointment_type_id),
            )
        # Observe only the owner first, then acquire the same human-first order
        # used by patient setup before locking the account and identity.
        owners = session.execute(query.with_only_columns(
            ExternalIdentity.box_id, ExternalIdentity.principal_id,
        )).all()
        if len(owners) != 1:
            raise ws.WorkspaceError("scheduling_account_review_required", 409)
        box, owner = owners[0]
        ws._human(session, box, owner, creating=True)
        rows = session.execute(query.with_for_update().execution_options(populate_existing=True)).all()
        if len(rows) != 1:
            raise ws.WorkspaceError("scheduling_account_review_required", 409)
        account, external = rows[0]
        if external.box_id != box or external.principal_id != owner:
            raise ws.WorkspaceError("scheduling_account_review_required", 409)
        selected = SchedulingSelection(
            box_id=external.box_id,
            owner_id=external.principal_id,
            practice_id=account.practice_id,
            expected_actor_id=account.actor_id,
            practitioner_id=account.practitioner_id,
            location_id=account.location_id,
            appointment_type_id=account.appointment_type_id,
        )
        binding = digest(
            canonical(
                [self.config_digest, account.id, external.id, selected.model_dump(mode="json")]
            )
        )
        return account, selected, binding

    def _seal(self, value, purpose, account_id, binding, identifier=""):
        nonce = secrets.token_bytes(12)
        aad = canonical(["scheduling-login-v1", purpose, account_id, binding, identifier]).encode()
        return nonce + self._cipher.encrypt(nonce, canonical(value).encode(), aad)

    def _open(self, raw, purpose, account_id, binding, identifier=""):
        if not raw or not 28 <= len(raw) <= 32768:
            raise ValueError
        aad = canonical(["scheduling-login-v1", purpose, account_id, binding, identifier]).encode()
        value = json.loads(self._cipher.decrypt(raw[:12], raw[12:], aad))
        if not isinstance(value, dict):
            raise ValueError
        return value

    def _audit(self, session, selected, account_id, event, outcome):
        session.add(
            AuditEvent(
                box_id=str(selected.box_id),
                aggregate_type="scheduling_account",
                aggregate_id=account_id,
                actor_principal_id=str(selected.owner_id),
                event_type="workspace.scheduling_" + event,
                outcome=outcome,
                detail={},
            )
        )

    def status(self, identity):
        with self._session() as session:
            account, selected, binding = self._account(session, identity=identity)
            credential = session.get(SchedulingLoginCredential, account.id)
            state = "sign_in_required"
            if credential and credential.binding_digest == binding and credential.sealed:
                if credential.status == "ready":
                    state = "connected"
                elif credential.status == "refreshing":
                    state = "sign_in_required"
            pending = session.scalar(
                select(SchedulingLoginAttempt).where(
                    SchedulingLoginAttempt.account_id == account.id,
                    SchedulingLoginAttempt.status.in_(["pending", "exchanging"]),
                    SchedulingLoginAttempt.expires_at > self.now(),
                )
            )
            if pending and pending.binding_digest == binding:
                state = "sign_in_pending" if pending.status == "pending" else "completing_sign_in"
            return {
                "state": state,
                "label": account.label,
                "connected_at": credential.connected_at.isoformat()
                if credential and state == "connected"
                else None,
            }

    def start(self, identity):
        with self._session() as session:
            account, selected, binding = self._account(session, identity=identity)
            now = self.now()
            attempt = session.scalar(
                select(SchedulingLoginAttempt)
                .where(
                    SchedulingLoginAttempt.account_id == account.id,
                    SchedulingLoginAttempt.status.in_(["pending", "exchanging"]),
                )
                .with_for_update()
            )
            if attempt and (attempt.expires_at <= now or attempt.binding_digest != binding):
                attempt.status, attempt.sealed = "failed", None
                session.flush()
                attempt = None
            if attempt and attempt.status == "exchanging":
                raise ws.WorkspaceError("scheduling_sign_in_in_progress", 409)
            if attempt is None:
                attempt = SchedulingLoginAttempt(
                    id=str(uuid4()),
                    account_id=account.id,
                    binding_digest=binding,
                    status="pending",
                    created_at=now,
                    expires_at=now + timedelta(minutes=10),
                )
                private = {
                    "state": secrets.token_urlsafe(32),
                    "nonce": secrets.token_urlsafe(32),
                    "verifier": secrets.token_urlsafe(48),
                }
                attempt.state_digest = digest(private["state"])
                attempt.sealed = self._seal(private, "attempt", account.id, binding, attempt.id)
                session.add(attempt)
                self._audit(session, selected, account.id, "sign_in_started", "pending")
            else:
                private = self._open(attempt.sealed, "attempt", account.id, binding, attempt.id)
            url = (
                AUTHORIZATION_URL
                + "?"
                + urlencode(
                    {
                        "client_id": self.client_id,
                        "redirect_uri": self.callback_uri,
                        "response_type": "code",
                        "scope": "openid email",
                        "state": private["state"],
                        "nonce": private["nonce"],
                        "access_type": "offline",
                        "prompt": "consent select_account",
                        "code_challenge_method": "S256",
                        "code_challenge": base64.urlsafe_b64encode(
                            hashlib.sha256(private["verifier"].encode()).digest()
                        )
                        .rstrip(b"=")
                        .decode(),
                    }
                )
            )
            expires_at = attempt.expires_at.astimezone(UTC).isoformat()
            session.commit()
            return {"authorization_url": url, "expires_at": expires_at}

    def disconnect(self, identity):
        with self._session() as session:
            account, selected, _ = self._account(session, identity=identity)
            credential = session.get(SchedulingLoginCredential, account.id)
            changed = False
            if credential and credential.status != "disconnected":
                changed = True
                credential.status, credential.sealed, credential.refresh_id = (
                    "disconnected",
                    None,
                    None,
                )
            for attempt in session.scalars(
                select(SchedulingLoginAttempt).where(
                    SchedulingLoginAttempt.account_id == account.id,
                    SchedulingLoginAttempt.status.in_(["pending", "exchanging"]),
                )
            ):
                attempt.status, attempt.sealed = "failed", None
                changed = True
            if changed:
                self._audit(session, selected, account.id, "disconnected", "disconnected")
            session.commit()
        return {"state": "disconnected"}

    def _exchange(self, fields):
        self._enabled()
        deadline = monotonic() + 10
        with self._client.stream(
            "POST",
            TOKEN_URL,
            data={
                **fields,
                "client_id": self.client_id,
                "client_secret": self.client_secret.get_secret_value(),
            },
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        ) as response:
            if (
                monotonic() >= deadline
                or response.status_code != 200
                or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                or response.headers.get("content-encoding") not in {None, "identity"}
            ):
                raise ValueError
            raw = bytearray()
            for chunk in response.iter_raw():
                if monotonic() >= deadline or len(raw) + len(chunk) > 32768:
                    raise ValueError
                raw.extend(chunk)
        if monotonic() >= deadline:
            raise ValueError

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict) or not isinstance(value.get("id_token"), str):
            raise ValueError
        return value

    def _verified(self, value, selected, *, nonce=None, subject=None, prior_refresh=None):
        token = value["id_token"]
        if not 1 <= len(token) <= 16384:
            raise ValueError
        # The exact token is cryptographically verified by the fixed Scheduling
        # receiver before any decoded claim below is used as trusted metadata.
        self._verifier.confirm(selected, SecretStr(token))
        return self._verified_claims(value,nonce=nonce,subject=subject,prior_refresh=prior_refresh)

    def _verified_claims(self,value,*,nonce=None,subject=None,prior_refresh=None):
        # Only call after the fixed receiver has verified this exact identity token.
        token=value["id_token"]
        claims = jwt.decode(token, options={"verify_signature": False})
        expires = claims.get("exp")
        if (
            claims.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}
            or claims.get("aud") != self.client_id
            or not isinstance(claims.get("sub"), str)
            or not 1 <= len(claims["sub"]) <= 255
            or type(expires) is not int
            or nonce is not None
            and not hmac.compare_digest(str(claims.get("nonce", "")), nonce)
            or subject is not None
            and claims["sub"] != subject
        ):
            raise ValueError
        expiry = datetime.fromtimestamp(expires, UTC)
        if not self.now() + timedelta(seconds=60) <= expiry <= self.now() + timedelta(days=1):
            raise ValueError
        refresh = value.get("refresh_token", prior_refresh)
        if not isinstance(refresh, str) or not 1 <= len(refresh) <= 8192:
            raise ValueError
        self._enabled()
        return {"token": token, "refresh": refresh, "subject": claims["sub"]}, expiry

    def callback(self, state, code=None, denied=False):
        attempt_id = None
        try:
            if not isinstance(state, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", state) is None:
                raise ValueError
            with self._session() as session:
                # Discover exact digest, then lock the account before the attempt,
                # matching start/disconnect/credential lock order.
                discovered = session.scalar(
                    select(SchedulingLoginAttempt).where(
                        SchedulingLoginAttempt.state_digest == digest(state)
                    )
                )
                if discovered is None:
                    raise ValueError
                account, selected, binding = self._account(
                    session, account_id=discovered.account_id
                )
                session.expire(discovered)
                attempt = session.scalar(
                    select(SchedulingLoginAttempt)
                    .where(SchedulingLoginAttempt.id == discovered.id)
                    .with_for_update()
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
            private_credential, expiry = self._verified(value, selected, nonce=private["nonce"])
            with self._session() as session:
                account, current, current_binding = self._account(session, account_id=account_id)
                attempt = session.get(SchedulingLoginAttempt, attempt_id)
                if (
                    current != selected
                    or current_binding != binding
                    or attempt is None
                    or attempt.status != "exchanging"
                    or attempt.expires_at <= self.now()
                ):
                    raise ValueError
                credential = session.get(SchedulingLoginCredential, account.id)
                if credential is None:
                    credential = SchedulingLoginCredential(account_id=account.id)
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
                    select(SchedulingLoginAttempt)
                    .where(SchedulingLoginAttempt.id == attempt_id)
                    .with_for_update()
                )
                if attempt and attempt.status in {"pending", "exchanging"}:
                    attempt.status, attempt.sealed = "failed", None
                    session.commit()
        except Exception:
            pass  # A retained exchanging row blocks reuse and requires a new sign-in.

    def patient_setup_binding(self, session, identity_id, account):
        """Read the current sealed staff grant in the caller's transaction.

        No refresh, network, second Session or lock upgrade. Token/ciphertext
        rotation does not change this semantic grant; reconnect does.
        """
        from cosmas_os.application.scheduling_patient_setup import PatientSetupBinding

        self._enabled()
        external = session.scalar(select(ExternalIdentity).where(
            ExternalIdentity.id == identity_id, ExternalIdentity.active.is_(True),
        ).with_for_update(read=True).execution_options(populate_existing=True))
        current = session.scalar(select(SchedulingAccount).where(
            SchedulingAccount.id == account.id,
            SchedulingAccount.external_identity_id == identity_id,
            SchedulingAccount.revoked_at.is_(None),
        ).with_for_update(read=True).execution_options(populate_existing=True))
        if external is None or current is None:
            raise ConnectorUnavailable("scheduling_patient_grant_unavailable")
        selected = SchedulingSelection(
            box_id=external.box_id, owner_id=external.principal_id,
            practice_id=current.practice_id, expected_actor_id=current.actor_id,
            practitioner_id=current.practitioner_id, location_id=current.location_id,
            appointment_type_id=current.appointment_type_id,
        )
        binding = digest(canonical([
            self.config_digest, current.id, external.id, selected.model_dump(mode="json"),
        ]))
        credential = session.scalar(select(SchedulingLoginCredential).where(
            SchedulingLoginCredential.account_id == current.id,
        ).with_for_update(read=True).execution_options(populate_existing=True))
        if (credential is None or credential.status != "ready"
            or credential.binding_digest != binding or credential.expires_at <= self.now()):
            raise ConnectorUnavailable("scheduling_patient_grant_unavailable")
        try:
            private = self._open(credential.sealed, "credential", current.id, binding)
            subject = private.get("subject")
            if (set(private) != {"token", "refresh", "subject"}
                or not isinstance(subject, str) or not 1 <= len(subject) <= 255
                or any(ord(c) < 32 or ord(c) == 127 for c in subject)):
                raise ValueError
            grant = digest(canonical([
                "cosmas-scheduling-patient-grant.v1", self.config_digest,
                "https://accounts.google.com", subject, self.client_id,
                "google_staff_identity", selected.model_dump(mode="json"),
                external.issuer, external.subject, external.organization_id,
            ]))
            self._enabled()
            return PatientSetupBinding(account_id=current.id, selection=selected,
                binding_sha256=binding, connected_at=credential.connected_at,
                grant_sha256=grant)
        except Exception:
            raise ConnectorUnavailable("scheduling_patient_grant_unavailable") from None

    def credential(self, selection):
        refresh_id = None
        account_id = None
        try:
            with self._session() as session:
                account, selected, binding = self._account(session, selection=selection)
                account_id = account.id
                credential = session.get(SchedulingLoginCredential, account.id)
                if (
                    credential is None
                    or credential.status != "ready"
                    or credential.binding_digest != binding
                ):
                    raise ValueError
                private = self._open(credential.sealed, "credential", account.id, binding)
                if credential.expires_at >= self.now() + timedelta(seconds=60):
                    return SchedulingStaffCredential(
                        selection=selected,
                        family="google_staff_identity",
                        token=SecretStr(private["token"]),
                        expires_at=credential.expires_at,
                    )
                refresh_id = str(uuid4())
                credential.status, credential.refresh_id = "refreshing", refresh_id
                session.commit()
            value = self._exchange(
                {"grant_type": "refresh_token", "refresh_token": private["refresh"]}
            )
            fresh, expiry = self._verified(
                value, selected, subject=private["subject"], prior_refresh=private["refresh"]
            )
            with self._session() as session:
                account, current, current_binding = self._account(session, account_id=account_id)
                credential = session.get(SchedulingLoginCredential, account.id)
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
            return SchedulingStaffCredential(
                selection=selected,
                family="google_staff_identity",
                token=SecretStr(fresh["token"]),
                expires_at=expiry,
            )
        except Exception:
            if refresh_id and account_id:
                try:
                    with self._session() as session:
                        credential = session.scalar(
                            select(SchedulingLoginCredential)
                            .where(SchedulingLoginCredential.account_id == account_id)
                            .with_for_update()
                        )
                        if credential and credential.refresh_id == refresh_id:
                            credential.status, credential.sealed = "failed", None
                            session.commit()
                except Exception:
                    pass
            raise ConnectorUnavailable("scheduling_identity_unavailable") from None

    def close(self):
        self._closed = True
        try:
            self._verifier.close()
        finally:
            self._client.close()
