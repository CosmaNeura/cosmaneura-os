"""2-legged OAuth client-credentials token client for EHR backend reads.

Uses a client id and client secret resolved only by ``COSMAS_MANAGED_SECRET_*``
reference names (Key Vault bindings). The access token stays in process memory
until 60 seconds before expiry. Never write the token or secret to disk, the
database, logs, HTTP responses, or any device.

Signed-key / JWT client-assertion auth is intentionally not implemented here;
that path waits for a later ticket.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from cosmas_os.adapters.ehr_auth.managed_secret_env import (
    validate_managed_secret_reference_name,
)
from cosmas_os.plugins.ehr.hooks import SecretResolver
from cosmas_os.plugins.ehr.manifest import VendorId

logger = logging.getLogger(__name__)

# C1 auth style for this auth kind (2-legged client secret).
AUTH_KIND_CLIENT_CREDENTIALS: Literal["oauth2_client_credentials"] = (
    "oauth2_client_credentials"
)

GRANT_TYPE = "client_credentials"
TOKEN_REFRESH_SKEW_SECONDS = 60
MAX_TOKEN_BYTES = 8192
MAX_SCOPE_CHARS = 2048
MAX_CLIENT_ID_CHARS = 256
MAX_CLIENT_SECRET_CHARS = 4096

_SYSTEM_READ_SCOPE = re.compile(r"^system/[A-Za-z][A-Za-z0-9]{0,63}\.read$")


class ClientCredentialsAuthError(Exception):
    """Closed auth failures with no token or credential content."""

    _CODES = frozenset({
        "invalid_client",
        "invalid_request",
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
        return f"ClientCredentialsAuthError(code={self.code!r})"


def normalize_system_read_scopes(
    scopes: frozenset[str] | set[str] | tuple[str, ...] | list[str],
) -> frozenset[str]:
    """Accept only exact ``system/<Resource>.read`` scopes; refuse wildcards."""
    if not scopes:
        raise ClientCredentialsAuthError("invalid_request")
    normalized: set[str] = set()
    for scope in scopes:
        if type(scope) is not str:
            raise ClientCredentialsAuthError("invalid_request")
        if "*" in scope:
            raise ClientCredentialsAuthError("scope_wildcard_refused")
        if _SYSTEM_READ_SCOPE.fullmatch(scope) is None:
            raise ClientCredentialsAuthError("invalid_request")
        normalized.add(scope)
    return frozenset(normalized)


def _require_token_url(token_url: str) -> str:
    if type(token_url) is not str or len(token_url) > 512:
        raise ClientCredentialsAuthError("invalid_request")
    parts = urlsplit(token_url)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
        if not (
            parts.scheme == "http"
            and parts.hostname in {"127.0.0.1", "localhost", "::1"}
            and not parts.username
            and not parts.password
        ):
            raise ClientCredentialsAuthError("invalid_request")
    if parts.fragment:
        raise ClientCredentialsAuthError("invalid_request")
    return token_url


@dataclass(frozen=True, slots=True, repr=False)
class ClientCredentialsConfig:
    """Sandbox client-credentials configuration. Holds reference NAMES only."""

    client_id_ref: str
    client_secret_ref: str
    token_url: str
    scopes: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "client_id_ref", validate_managed_secret_reference_name(self.client_id_ref)
        )
        object.__setattr__(
            self,
            "client_secret_ref",
            validate_managed_secret_reference_name(self.client_secret_ref),
        )
        if self.client_id_ref == self.client_secret_ref:
            raise ValueError("client_id_and_secret_refs_must_differ")
        object.__setattr__(self, "token_url", _require_token_url(self.token_url))
        object.__setattr__(self, "scopes", normalize_system_read_scopes(self.scopes))


@dataclass(slots=True)
class _CachedToken:
    value: SecretStr
    expires_at_monotonic: float
    granted_scopes: frozenset[str]


class ClientCredentialsTokenClient:
    """Fetch and cache OAuth client-credentials access tokens in process memory."""

    def __init__(
        self,
        *,
        config: ClientCredentialsConfig,
        secrets: SecretResolver,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
        monotonic: Callable[[], float] | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if type(config) is not ClientCredentialsConfig:
            raise ValueError("client_credentials_config_required")
        if not isinstance(secrets, SecretResolver):
            raise ValueError("secret_resolver_required")
        self._config = config
        self._secrets = secrets
        self._transport = transport
        self._http_client = http_client
        self._monotonic = monotonic or time.monotonic
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
            return self._fetch_token_locked().value

    def refresh_after_unauthorized(self) -> SecretStr:
        self.clear_cached_token()
        return self.get_access_token(force_refresh=True)

    def _read_client_credentials(self) -> tuple[str, str]:
        try:
            client_id = self._secrets.resolve(name=self._config.client_id_ref)
            client_secret = self._secrets.resolve(name=self._config.client_secret_ref)
        except LookupError as exc:
            raise ClientCredentialsAuthError("not_configured") from exc
        except ValueError as exc:
            raise ClientCredentialsAuthError("not_configured") from exc
        if (
            type(client_id) is not str
            or not (1 <= len(client_id) <= MAX_CLIENT_ID_CHARS)
            or any(c.isspace() for c in client_id)
            or type(client_secret) is not str
            or not (1 <= len(client_secret) <= MAX_CLIENT_SECRET_CHARS)
        ):
            raise ClientCredentialsAuthError("not_configured")
        return client_id, client_secret

    def _fetch_token_locked(self) -> _CachedToken:
        client_id, client_secret = self._read_client_credentials()
        form = {
            "grant_type": GRANT_TYPE,
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": " ".join(sorted(self._config.scopes)),
        }
        began = self._monotonic()
        try:
            response = self._post_token(form)
        except httpx.TimeoutException as exc:
            raise ClientCredentialsAuthError("timeout") from exc
        except httpx.HTTPError as exc:
            raise ClientCredentialsAuthError("unavailable") from exc

        if response.status_code >= 500:
            raise ClientCredentialsAuthError("unavailable")

        payload = self._parse_json_object(response)
        if response.status_code >= 400:
            self._cache = None
            raise ClientCredentialsAuthError(
                self._map_oauth_error(payload, response.status_code)
            )

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
            raise ClientCredentialsAuthError("invalid_response")

        granted = self._parse_granted_scopes(payload.get("scope"))
        refresh_skew = min(TOKEN_REFRESH_SKEW_SECONDS, max(1, expires_in // 10))
        cached = _CachedToken(
            value=SecretStr(access_token),
            expires_at_monotonic=began + expires_in - refresh_skew,
            granted_scopes=granted,
        )
        self._cache = cached
        logger.info(
            "ehr_client_credentials_token_acquired",
            extra={
                "token_type": "Bearer",
                "expires_in": expires_in,
                "scope_count": len(granted),
                "client_id_ref": self._config.client_id_ref,
            },
        )
        return cached

    def _parse_granted_scopes(self, raw: object) -> frozenset[str]:
        if raw is None:
            return self._config.scopes
        if type(raw) is not str or len(raw) > MAX_SCOPE_CHARS:
            raise ClientCredentialsAuthError("invalid_response")
        if not raw.strip():
            raise ClientCredentialsAuthError("unsupported_scope")
        granted: set[str] = set()
        for part in raw.split():
            if "*" in part:
                raise ClientCredentialsAuthError("scope_wildcard_refused")
            if _SYSTEM_READ_SCOPE.fullmatch(part) is None:
                raise ClientCredentialsAuthError("invalid_response")
            granted.add(part)
        if not granted <= self._config.scopes:
            raise ClientCredentialsAuthError("invalid_response")
        return frozenset(granted)

    def _map_oauth_error(self, payload: dict, status_code: int) -> str:
        error = payload.get("error")
        if error in {"invalid_client", "unauthorized_client"}:
            return "invalid_client"
        if error == "invalid_scope":
            return "unsupported_scope"
        if status_code == 401:
            return "unauthorized"
        return "invalid_request"

    def _parse_json_object(self, response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ClientCredentialsAuthError("invalid_response") from exc
        if type(payload) is not dict:
            raise ClientCredentialsAuthError("invalid_response")
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

    def __repr__(self) -> str:
        return (
            "ClientCredentialsTokenClient("
            f"client_id_ref={self._config.client_id_ref!r}, "
            f"token_url_host={urlsplit(self._config.token_url).hostname!r})"
        )


class ClientCredentialsAuthProvider:
    """``BackendAuthProvider`` for C1's ``oauth2_client_credentials`` auth kind."""

    def __init__(self, clients: dict[VendorId, ClientCredentialsTokenClient]) -> None:
        if type(clients) is not dict or not clients:
            raise ValueError("client_credentials_clients_required")
        for vendor_id, client in clients.items():
            if vendor_id not in {"athena", "elation", "tebra", "atlas_md"}:
                raise ValueError("unknown_vendor_id")
            if type(client) is not ClientCredentialsTokenClient:
                raise ValueError("client_credentials_token_client_required")
        self._clients = dict(clients)

    @property
    def auth_kind(self) -> str:
        return AUTH_KIND_CLIENT_CREDENTIALS

    def access_token(self, *, vendor_id: VendorId, audience: str) -> str:
        client = self._clients.get(vendor_id)
        if client is None:
            raise ClientCredentialsAuthError("not_configured")
        if audience != client.token_url:
            raise ClientCredentialsAuthError("invalid_request")
        return client.get_access_token().get_secret_value()

    def attach_to(self, connector) -> None:
        """Minimal C1 glue: set ``auth_provider`` on a ``DeclaredEhrConnector``."""
        manifest = connector.capability_manifest()
        if AUTH_KIND_CLIENT_CREDENTIALS not in manifest.auth_styles:
            raise ClientCredentialsAuthError("not_configured")
        connector.auth_provider = self
