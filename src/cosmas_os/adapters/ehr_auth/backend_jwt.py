"""SMART Backend Services / athena 2-legged JWT client-assertion token client.

Builds a private_key_jwt assertion (iss=sub=client_id, aud=token URL, random
jti, exp ≤ 5 minutes, kid header), signs it through a ``KeySigner`` (RS384
default; RS256 allowed), exchanges it for an access token, and caches that
token in process memory until 60 seconds before expiry.

Never writes the access token or assertion private key to disk, the database,
logs, HTTP responses, or any device.
"""

from __future__ import annotations

import base64
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from cosmas_os.plugins.ehr.manifest import VendorId
from cosmas_os.ports.key_signer import (
    ALLOWED_JWT_SIGN_ALGORITHMS,
    DEFAULT_JWT_SIGN_ALGORITHM,
    JwtSignAlgorithm,
    KeySigner,
)

logger = logging.getLogger(__name__)

# C1 auth style name for this auth kind (plan ticket wording: backend_jwt).
AUTH_KIND_BACKEND_JWT: Literal["smart_backend_services"] = "smart_backend_services"

CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
GRANT_TYPE = "client_credentials"

MAX_ASSERTION_LIFETIME_SECONDS = 300
TOKEN_REFRESH_SKEW_SECONDS = 60
DEFAULT_CLOCK_SKEW_SECONDS = 30
MAX_TOKEN_BYTES = 8192
MAX_SCOPE_CHARS = 2048

_CLIENT_ID = re.compile(r"^[A-Za-z0-9._~-]{1,256}$")
_SYSTEM_READ_SCOPE = re.compile(r"^system/[A-Za-z][A-Za-z0-9]{0,63}\.read$")
_JTI = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class BackendJwtAuthError(Exception):
    """Closed auth failures with no token, assertion, or credential content."""

    _CODES = frozenset({
        "invalid_client",
        "invalid_request",
        "expired_assertion",
        "clock_skew",
        "unsupported_scope",
        "unauthorized",
        "token_unavailable",
        "invalid_response",
        "timeout",
        "unavailable",
        "not_configured",
        "scope_wildcard_refused",
    })

    def __init__(self, code: str) -> None:
        if code not in self._CODES:
            code = "invalid_response"
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"BackendJwtAuthError(code={self.code!r})"


def normalize_system_read_scopes(scopes: frozenset[str] | set[str] | tuple[str, ...] | list[str]) -> frozenset[str]:
    """Accept only exact ``system/<Resource>.read`` scopes; refuse wildcards."""
    if not scopes:
        raise BackendJwtAuthError("invalid_request")
    normalized: set[str] = set()
    for scope in scopes:
        if type(scope) is not str:
            raise BackendJwtAuthError("invalid_request")
        if "*" in scope:
            raise BackendJwtAuthError("scope_wildcard_refused")
        if _SYSTEM_READ_SCOPE.fullmatch(scope) is None:
            raise BackendJwtAuthError("invalid_request")
        normalized.add(scope)
    return frozenset(normalized)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _require_https_token_url(token_url: str) -> str:
    if type(token_url) is not str or len(token_url) > 512:
        raise BackendJwtAuthError("invalid_request")
    parts = urlsplit(token_url)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
        # Tests may use http://127.0.0.1 mock servers; allow loopback http only.
        if not (
            parts.scheme == "http"
            and parts.hostname in {"127.0.0.1", "localhost", "::1"}
            and not parts.username
            and not parts.password
        ):
            raise BackendJwtAuthError("invalid_request")
    if parts.fragment:
        raise BackendJwtAuthError("invalid_request")
    return token_url


@dataclass(frozen=True, slots=True, repr=False)
class BackendJwtConfig:
    """Sandbox backend-services client configuration. No private key material."""

    client_id: str
    token_url: str
    scopes: frozenset[str]
    algorithm: JwtSignAlgorithm = DEFAULT_JWT_SIGN_ALGORITHM
    assertion_lifetime_seconds: int = MAX_ASSERTION_LIFETIME_SECONDS
    clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS

    def __post_init__(self) -> None:
        if type(self.client_id) is not str or _CLIENT_ID.fullmatch(self.client_id) is None:
            raise ValueError("client_id_invalid")
        object.__setattr__(self, "token_url", _require_https_token_url(self.token_url))
        object.__setattr__(self, "scopes", normalize_system_read_scopes(self.scopes))
        if self.algorithm not in ALLOWED_JWT_SIGN_ALGORITHMS:
            raise ValueError("sign_algorithm_unsupported")
        if not (1 <= self.assertion_lifetime_seconds <= MAX_ASSERTION_LIFETIME_SECONDS):
            raise ValueError("assertion_lifetime_invalid")
        if not (0 <= self.clock_skew_seconds <= 120):
            raise ValueError("clock_skew_invalid")


@dataclass(slots=True)
class _CachedToken:
    value: SecretStr
    expires_at_monotonic: float
    granted_scopes: frozenset[str]


class BackendJwtTokenClient:
    """Fetch and cache SMART backend-services access tokens in process memory."""

    def __init__(
        self,
        *,
        config: BackendJwtConfig,
        signer: KeySigner,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
        monotonic: Callable[[], float] | None = None,
        wall_time: Callable[[], float] | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if type(config) is not BackendJwtConfig:
            raise ValueError("backend_jwt_config_required")
        if not isinstance(signer, KeySigner):
            raise ValueError("key_signer_required")
        if type(signer.kid) is not str or not signer.kid:
            raise ValueError("kid_invalid")
        self._config = config
        self._signer = signer
        self._transport = transport
        self._http_client = http_client
        self._monotonic = monotonic or time.monotonic
        self._wall_time = wall_time or time.time
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self._cache: _CachedToken | None = None

    @property
    def token_url(self) -> str:
        return self._config.token_url

    @property
    def requested_scopes(self) -> frozenset[str]:
        return self._config.scopes

    def clear_cached_token(self) -> None:
        """Drop the in-memory token (used after HTTP 401 from a resource server)."""
        with self._lock:
            self._cache = None

    def get_access_token(self, *, force_refresh: bool = False) -> SecretStr:
        with self._lock:
            now = self._monotonic()
            if (
                not force_refresh
                and self._cache is not None
                and now < self._cache.expires_at_monotonic
            ):
                return self._cache.value
            token = self._fetch_token_locked()
            return token.value

    def granted_scopes(self) -> frozenset[str] | None:
        with self._lock:
            if self._cache is None:
                return None
            return self._cache.granted_scopes

    def unsupported_resources_for_grant(self) -> frozenset[str]:
        """Resource types requested but absent from the granted scope string."""
        granted = self.granted_scopes()
        if granted is None:
            return frozenset()
        missing = self._config.scopes - granted
        resources: set[str] = set()
        for scope in missing:
            # system/Patient.read → Patient
            resources.add(scope.removeprefix("system/").removesuffix(".read"))
        return frozenset(resources)

    def access_token_for_resource(
        self,
        *,
        force_refresh: bool = False,
    ) -> SecretStr:
        """Return a token, raising ``unsupported_scope`` when grant is narrower."""
        token = self.get_access_token(force_refresh=force_refresh)
        missing = self.unsupported_resources_for_grant()
        if missing:
            raise BackendJwtAuthError("unsupported_scope")
        return token

    def refresh_after_unauthorized(self) -> SecretStr:
        """Clear cache and fetch a new token after a resource-server HTTP 401."""
        self.clear_cached_token()
        return self.get_access_token(force_refresh=True)

    def _fetch_token_locked(self) -> _CachedToken:
        assertion = self._build_client_assertion()
        form = {
            "grant_type": GRANT_TYPE,
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "client_assertion": assertion,
            "scope": " ".join(sorted(self._config.scopes)),
        }
        began = self._monotonic()
        try:
            response = self._post_token(form)
        except httpx.TimeoutException as exc:
            raise BackendJwtAuthError("timeout") from exc
        except httpx.HTTPError as exc:
            raise BackendJwtAuthError("unavailable") from exc

        if response.status_code >= 500:
            raise BackendJwtAuthError("unavailable")

        payload = self._parse_json_object(response)
        if response.status_code >= 400:
            self._cache = None
            raise BackendJwtAuthError(self._map_oauth_error(payload, response.status_code))

        access_token = payload.get("access_token")
        token_type = payload.get("token_type")
        expires_in = payload.get("expires_in")
        if (
            type(access_token) is not str
            or not (1 <= len(access_token) <= MAX_TOKEN_BYTES)
            or not access_token.isascii()
            or any(c.isspace() for c in access_token)
            or type(token_type) is not str
            or token_type.lower() != "bearer"
            or type(expires_in) is not int
            or expires_in < 1
            or expires_in > 86_400
        ):
            raise BackendJwtAuthError("invalid_response")

        granted = self._parse_granted_scopes(payload.get("scope"))
        refresh_skew = min(TOKEN_REFRESH_SKEW_SECONDS, max(1, expires_in // 10))
        cached = _CachedToken(
            value=SecretStr(access_token),
            expires_at_monotonic=began + expires_in - refresh_skew,
            granted_scopes=granted,
        )
        self._cache = cached
        # Log only non-secret outcome metadata.
        logger.info(
            "ehr_backend_jwt_token_acquired",
            extra={
                "token_type": "Bearer",
                "expires_in": expires_in,
                "scope_count": len(granted),
                "kid_present": True,
            },
        )
        return cached

    def _parse_granted_scopes(self, raw: object) -> frozenset[str]:
        if raw is None:
            # Some token servers omit scope; treat as exact requested grant.
            return self._config.scopes
        if type(raw) is not str or len(raw) > MAX_SCOPE_CHARS:
            raise BackendJwtAuthError("invalid_response")
        if not raw.strip():
            raise BackendJwtAuthError("unsupported_scope")
        parts = raw.split()
        granted: set[str] = set()
        for part in parts:
            if "*" in part:
                raise BackendJwtAuthError("scope_wildcard_refused")
            if _SYSTEM_READ_SCOPE.fullmatch(part) is None:
                raise BackendJwtAuthError("invalid_response")
            granted.add(part)
        # Narrower than requested is allowed at grant time; unknown extras are not.
        # Callers that need every resource use access_token_for_resource().
        if not granted <= self._config.scopes:
            raise BackendJwtAuthError("invalid_response")
        return frozenset(granted)

    def _map_oauth_error(self, payload: dict, status_code: int) -> str:
        error = payload.get("error")
        if error == "invalid_client":
            return "invalid_client"
        if error in {"invalid_grant", "invalid_token"}:
            description = payload.get("error_description")
            text = description if type(description) is str else ""
            lowered = text.lower()
            if "expir" in lowered:
                return "expired_assertion"
            if "skew" in lowered or "clock" in lowered or "nbf" in lowered or "iat" in lowered:
                return "clock_skew"
            return "expired_assertion"
        if error == "invalid_scope":
            return "unsupported_scope"
        if error == "unauthorized_client":
            return "invalid_client"
        if status_code == 401:
            return "unauthorized"
        return "invalid_request"

    def _parse_json_object(self, response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise BackendJwtAuthError("invalid_response") from exc
        if type(payload) is not dict:
            raise BackendJwtAuthError("invalid_response")
        return payload

    def _post_token(self, form: dict[str, str]) -> httpx.Response:
        if self._http_client is not None:
            return self._http_client.post(
                self._config.token_url,
                data=form,
                headers={"Accept": "application/json"},
            )
        with httpx.Client(
            transport=self._transport,
            timeout=self._timeout,
            trust_env=False,
        ) as client:
            return client.post(
                self._config.token_url,
                data=form,
                headers={"Accept": "application/json"},
            )

    def _build_client_assertion(self) -> str:
        now = int(self._wall_time())
        skew = self._config.clock_skew_seconds
        iat = now - skew
        exp = iat + self._config.assertion_lifetime_seconds
        if exp - iat > MAX_ASSERTION_LIFETIME_SECONDS:
            exp = iat + MAX_ASSERTION_LIFETIME_SECONDS
        jti = secrets.token_urlsafe(24)
        if _JTI.fullmatch(jti) is None:
            # Extremely unlikely; regenerate once.
            jti = secrets.token_hex(16)
        header = {
            "alg": self._config.algorithm,
            "kid": self._signer.kid,
            "typ": "JWT",
        }
        payload = {
            "iss": self._config.client_id,
            "sub": self._config.client_id,
            "aud": self._config.token_url,
            "jti": jti,
            "iat": iat,
            "exp": exp,
        }
        signing_input = (
            f"{_b64url(self._json_bytes(header))}.{_b64url(self._json_bytes(payload))}"
        ).encode("ascii")
        signature = self._signer.sign(data=signing_input, algorithm=self._config.algorithm)
        return f"{signing_input.decode('ascii')}.{_b64url(signature)}"

    @staticmethod
    def _json_bytes(value: dict) -> bytes:
        import json

        return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def __repr__(self) -> str:
        return (
            "BackendJwtTokenClient("
            f"client_id={self._config.client_id!r}, "
            f"token_url_host={urlsplit(self._config.token_url).hostname!r}, "
            f"kid={self._signer.kid!r})"
        )


class SmartBackendJwtAuthProvider:
    """``BackendAuthProvider`` adapter for C1's ``auth_kind`` / smart_backend_services."""

    def __init__(self, clients: dict[VendorId, BackendJwtTokenClient]) -> None:
        if type(clients) is not dict or not clients:
            raise ValueError("backend_jwt_clients_required")
        for vendor_id, client in clients.items():
            if vendor_id not in {"athena", "elation", "tebra", "atlas_md"}:
                raise ValueError("unknown_vendor_id")
            if type(client) is not BackendJwtTokenClient:
                raise ValueError("backend_jwt_token_client_required")
        self._clients = dict(clients)

    @property
    def auth_kind(self) -> str:
        return AUTH_KIND_BACKEND_JWT

    def access_token(self, *, vendor_id: VendorId, audience: str) -> str:
        client = self._clients.get(vendor_id)
        if client is None:
            raise BackendJwtAuthError("not_configured")
        # SMART requires JWT aud == token URL; audience must match the client.
        if audience != client.token_url:
            raise BackendJwtAuthError("invalid_request")
        secret = client.access_token_for_resource()
        return secret.get_secret_value()

    def attach_to(self, connector) -> None:
        """Minimal C1 glue: set ``auth_provider`` on a ``DeclaredEhrConnector``."""
        manifest = connector.capability_manifest()
        if AUTH_KIND_BACKEND_JWT not in manifest.auth_styles:
            raise BackendJwtAuthError("not_configured")
        connector.auth_provider = self
