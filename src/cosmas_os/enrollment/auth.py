"""Signed pre-Org Clerk identity using the existing RS256/JWKS/session policy primitives.

Organization claims do not grant enrollment authority. Verified live Clerk session/user
evidence establishes the human and primary email; the registry establishes practice roles.
"""
from __future__ import annotations

from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import quote

import httpx
import jwt

from .config import EnrollmentSettings
from .domain import EnrollmentError, HumanIdentity


class ClerkEnrollmentVerifier:
    def __init__(self, settings: EnrollmentSettings, *, client: httpx.Client | None = None,
                 jwks_client: Any | None = None):
        if settings.auth_errors():
            raise EnrollmentError("identity_not_configured", "Enrollment identity is not configured.", 503)
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(10, connect=5), follow_redirects=False)
        self.jwks = jwks_client or jwt.PyJWKClient(settings.clerk_issuer.rstrip("/") + "/.well-known/jwks.json", timeout=5)
        self.keys: dict[str, Any] = {}
        self.keys_valid_until = 0.0
        self.refresh_after = 0.0
        self.lock = Lock()
        self.refresh_keys()

    def refresh_keys(self) -> None:
        # Refresh at most once every four minutes; arbitrary unknown kids never
        # cause network fetches. Last successful snapshot expires after 15 minutes.
        with self.lock:
            current = monotonic()
            if current < self.refresh_after:
                return
            self.refresh_after = current + 240
            try:
                keys = self.jwks.get_signing_keys(refresh=True)
                self.keys = {k.key_id: k.key for k in keys[-128:] if isinstance(k.key_id, str)}
                self.keys_valid_until = current + 900
            except (jwt.PyJWTError, ValueError, TypeError):
                # Configuration remains visible as unavailable until keys are fetched.
                return

    @property
    def ready(self) -> bool:
        return bool(self.keys and monotonic() < self.keys_valid_until)

    def _get(self, path: str) -> dict[str, Any]:
        try:
            response = self.client.get("https://api.clerk.com/v1" + path, headers={
                "Authorization": "Bearer " + self.settings.clerk_secret_key.get_secret_value(),
            })
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("invalid Clerk response")
            return data
        except Exception as exc:
            raise EnrollmentError("identity_unavailable", "Identity verification is temporarily unavailable.", 503) from exc

    def verify(self, token: str) -> HumanIdentity:
        if not token or len(token) > 8192:
            raise EnrollmentError("invalid_identity", "Sign in to continue.", 401)
        self.refresh_keys()
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not 1 <= len(kid) <= 255 or not self.ready:
                raise ValueError("invalid header")
            key = self.keys.get(kid)
            if key is None:
                raise ValueError("unknown key")
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.settings.clerk_issuer,
                                audience=None, leeway=5,
                                options={"require": ["exp", "iat", "nbf", "iss", "sub", "sid", "azp"], "verify_aud": True})
            sub, sid = claims.get("sub"), claims.get("sid")
            if (not isinstance(sub, str) or not 1 <= len(sub) <= 255
                    or not isinstance(sid, str) or not 1 <= len(sid) <= 255
                    or "aud" in claims
                    or claims.get("azp") not in self.settings.clerk_authorized_parties):
                raise ValueError("invalid claims")
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise EnrollmentError("invalid_identity", "Sign in to continue.", 401) from exc
        session = self._get("/sessions/" + quote(sid, safe=""))
        if session.get("id") != sid or session.get("user_id") != sub or session.get("status") != "active":
            raise EnrollmentError("session_inactive", "Your session ended. Sign in again.", 401)
        user = self._get("/users/" + quote(sub, safe=""))
        if user.get("id") != sub or user.get("banned") is True or user.get("locked") is True:
            raise EnrollmentError("invalid_identity", "This account is unavailable.", 401)
        primary = user.get("primary_email_address_id")
        addresses = user.get("email_addresses")
        email = next((a.get("email_address") for a in addresses if isinstance(a, dict)
                      and a.get("id") == primary and (a.get("verification") or {}).get("status") == "verified"), None) if isinstance(addresses, list) else None
        if not isinstance(email, str) or not 3 <= len(email) <= 320 or "@" not in email:
            raise EnrollmentError("verified_email_required", "Verify your primary email to continue.", 403)
        name = " ".join(str(user.get(k) or "") for k in ("first_name", "last_name")).strip()
        return HumanIdentity(self.settings.clerk_issuer, sub, sid, email.strip().lower(), name[:160])
