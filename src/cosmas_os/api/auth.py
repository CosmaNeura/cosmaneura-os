from __future__ import annotations

import hmac
from collections import OrderedDict
from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Protocol
from uuid import UUID

import jwt
from jwt import PyJWKClient, PyJWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.config import Settings
from cosmas_os.domain.enums import PrincipalState, PrincipalType
from cosmas_os.models import ExternalIdentity, Principal


class AuthenticationFailed(Exception):
    """The request did not carry a valid, verifiable identity."""


class AccessDenied(Exception):
    """A verified identity is not bound to the requested beta boundary."""


@dataclass(frozen=True)
class RequestIdentity:
    box_id: str
    principal_id: str
    auth_mode: str
    organization_id: str | None = None
    external_identity_id: str | None = None


class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict[str, Any]: ...


def native_clerk_origin(runtime: Settings, origins: list[str]) -> str | None:
    """Select a native transport; the Origin header does not establish identity."""
    if (len(origins) != 1 or runtime.cosmas_env != "early_adopter_beta"
            or runtime.auth_mode != "clerk_jwt" or not runtime.workspace_enabled
            or not runtime.workspace_authenticated_enabled or not runtime.workspace_hosted_enabled):
        return None
    origin = origins[0]
    enabled = {
        "capacitor://localhost": runtime.workspace_apple_hosted_transport_enabled,
        "app://cosmas": runtime.workspace_desktop_hosted_transport_enabled,
    }
    if (enabled.get(origin) and origin in runtime.allowed_origins
            and origin in runtime.authorized_parties):
        return origin
    return None


class _JwksState:
    """Process-shared JWKS state for one configured endpoint."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.cache_lock = Lock()
        self.refresh_lock = Lock()
        self.signing_keys: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self.unknown_kids: OrderedDict[str, float] = OrderedDict()
        self.refresh_stop = Event()


class ClerkTokenVerifier:
    """Verify Clerk session JWTs against one explicitly configured instance."""

    _KID_CACHE_LIMIT = 128
    _UNKNOWN_KID_TTL_SECONDS = 30.0
    _JWKS_REFRESH_INTERVAL_SECONDS = 240.0
    _JWKS_REFRESH_RETRY_SECONDS = 30.0
    _JWKS_MAX_STALE_SECONDS = 900.0
    _shared_states_lock = Lock()
    _shared_states: dict[str, _JwksState] = {}

    def __init__(
        self,
        runtime_settings: Settings,
        *,
        jwks_client: Any | None = None,
        start_background_refresh: bool = True,
        native_origin: str | None = None,
    ) -> None:
        if (
            not runtime_settings.clerk_jwks_url
            or not runtime_settings.clerk_issuer
            or runtime_settings.clerk_session_configuration_errors()
        ):
            raise RuntimeError("Clerk verifier configuration is incomplete")
        if native_origin is not None and native_clerk_origin(runtime_settings, [native_origin]) != native_origin:
            raise RuntimeError("Native Clerk transport is not configured")
        self._settings = runtime_settings
        self._native_origin = native_origin
        initialize_state = True
        if jwks_client is None and start_background_refresh:
            # functools.lru_cache may invoke the wrapped factory more than once
            # during a concurrent cold start. Share one state so those duplicate
            # verifier instances cannot multiply initial fetches or refresh loops.
            with self._shared_states_lock:
                state = self._shared_states.get(runtime_settings.clerk_jwks_url)
                if state is None:
                    state = _JwksState(
                        PyJWKClient(
                            runtime_settings.clerk_jwks_url,
                            cache_jwk_set=True,
                            timeout=5,
                        )
                    )
                    self._shared_states[runtime_settings.clerk_jwks_url] = state
                else:
                    initialize_state = False
        else:
            state = _JwksState(
                jwks_client
                or PyJWKClient(
                    runtime_settings.clerk_jwks_url,
                    cache_jwk_set=True,
                    timeout=5,
                )
            )

        self._jwks = state.client
        self._cache_lock = state.cache_lock
        self._jwks_refresh_lock = state.refresh_lock
        self._signing_keys = state.signing_keys
        self._unknown_kids = state.unknown_kids
        self._refresh_stop = state.refresh_stop

        if not initialize_state:
            return
        initial_refresh_succeeded = self._refresh_signing_keys()
        if start_background_refresh:
            Thread(
                target=self._refresh_loop,
                args=(initial_refresh_succeeded,),
                name="clerk-jwks-refresh",
                daemon=True,
            ).start()

    def _unknown_kid_is_cached(self, kid: str, now: float) -> bool:
        expires_at = self._unknown_kids.get(kid)
        if expires_at is None:
            return False
        if expires_at <= now:
            self._unknown_kids.pop(kid, None)
            return False
        self._unknown_kids.move_to_end(kid)
        return True

    def _remember_unknown_kid(self, kid: str, expires_at: float) -> None:
        self._unknown_kids[kid] = expires_at
        self._unknown_kids.move_to_end(kid)
        while len(self._unknown_kids) > self._KID_CACHE_LIMIT:
            self._unknown_kids.popitem(last=False)

    def _cached_signing_key(self, kid: str, now: float) -> Any | None:
        cached = self._signing_keys.get(kid)
        if cached is None:
            return None
        signing_key, stale_at = cached
        if stale_at <= now:
            self._signing_keys.pop(kid, None)
            return None
        self._signing_keys.move_to_end(kid)
        return signing_key

    def _replace_signing_keys(self, signing_keys: list[Any], stale_at: float) -> None:
        self._signing_keys.clear()
        for signing_key in signing_keys[-self._KID_CACHE_LIMIT :]:
            kid = signing_key.key_id
            if isinstance(kid, str) and kid:
                self._signing_keys[kid] = (signing_key, stale_at)
                self._unknown_kids.pop(kid, None)

    def _refresh_signing_keys(self) -> bool:
        if not self._jwks_refresh_lock.acquire(blocking=False):
            return False
        try:
            try:
                signing_keys = self._jwks.get_signing_keys(refresh=True)
            except (PyJWTError, ValueError, TypeError):
                return False
            with self._cache_lock:
                self._replace_signing_keys(
                    signing_keys,
                    monotonic() + self._JWKS_MAX_STALE_SECONDS,
                )
            return True
        finally:
            self._jwks_refresh_lock.release()

    def _refresh_loop(self, initial_refresh_succeeded: bool) -> None:
        delay = (
            self._JWKS_REFRESH_INTERVAL_SECONDS
            if initial_refresh_succeeded
            else self._JWKS_REFRESH_RETRY_SECONDS
        )
        while not self._refresh_stop.wait(delay):
            succeeded = self._refresh_signing_keys()
            delay = (
                self._JWKS_REFRESH_INTERVAL_SECONDS
                if succeeded
                else self._JWKS_REFRESH_RETRY_SECONDS
            )

    def _get_signing_key(self, kid: str) -> Any:
        # Unknown kids are rejected from the local snapshot. Only the independent
        # refresh loop performs network I/O, so arbitrary kid values cannot turn
        # unauthenticated requests into an outbound fetch storm.
        with self._cache_lock:
            now = monotonic()
            cached_key = self._cached_signing_key(kid, now)
            if cached_key is not None:
                return cached_key
            if not self._unknown_kid_is_cached(kid, now):
                self._remember_unknown_kid(kid, now + self._UNKNOWN_KID_TTL_SECONDS)
        raise AuthenticationFailed("invalid bearer token")

    def verify(self, token: str) -> dict[str, Any]:
        if not token or len(token) > 8192 or self._settings.clerk_session_configuration_errors():
            raise AuthenticationFailed("invalid bearer token")
        native_origin = self._native_origin
        if native_origin is not None and native_clerk_origin(self._settings, [native_origin]) != native_origin:
            raise AuthenticationFailed("native Clerk transport is unavailable")
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (
                header.get("alg") != "RS256"
                or not isinstance(kid, str)
                or not kid
                or len(kid) > 255
            ):
                raise AuthenticationFailed("invalid bearer token")
            signing_key = self._get_signing_key(kid)
            options: Any = {
                "require": ["exp", "iat", "nbf", "iss", "sub", "sid"] + ([] if native_origin else ["azp"]),
                "verify_aud": True,
            }
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self._settings.clerk_issuer,
                audience=None if self._settings.clerk_session_policy == "shared_staging" else self._settings.clerk_audience,
                options=options,
                leeway=5,
            )
        except AuthenticationFailed:
            raise
        except (PyJWTError, ValueError, TypeError) as exc:
            raise AuthenticationFailed("invalid bearer token") from exc

        subject = claims.get("sub")
        session_id = claims.get("sid")
        authorized_party = claims.get("azp")
        # The shared development instance issues default sessions without aud.
        # Require complete absence, including rejection of null/empty claims;
        # verify_aud above still rejects tokens intended for another API.
        if (not isinstance(subject, str) or not subject or len(subject) > 255
                or not isinstance(session_id, str) or not session_id or len(session_id) > 255
                or self._settings.clerk_session_policy == "shared_staging" and "aud" in claims):
            raise AuthenticationFailed("invalid bearer token")
        # Clerk native clients authenticate with Authorization and cannot send
        # Origin alongside it. Their signed session JWT can therefore omit azp.
        # Only the selected native transport admits absence; null/wrong/present
        # claims remain invalid, and issuer/audience/session/org are still checked.
        if native_origin is not None:
            party_allowed = "azp" not in claims or authorized_party == native_origin
        else:
            party_allowed = isinstance(authorized_party, str) and authorized_party in self._settings.authorized_parties
        if not party_allowed:
            raise AuthenticationFailed("invalid bearer token")

        organization_id = _organization_id(claims)
        expected_org = self._settings.clerk_organization_id
        if not expected_org or not hmac.compare_digest(organization_id, expected_org):
            raise AccessDenied("identity is outside the configured organization")
        return claims


def _organization_id(claims: dict[str, Any]) -> str:
    legacy = claims.get("org_id")
    compact = claims.get("o")
    compact_id = compact.get("id") if isinstance(compact, dict) else None
    values = [value for value in (legacy, compact_id) if isinstance(value, str) and value]
    if not values or len(set(values)) != 1:
        raise AccessDenied("a single organization identity is required")
    return values[0]


def _valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _active_human(session: Session, principal_id: str, box_id: str) -> Principal:
    principal = session.scalar(
        select(Principal).where(Principal.id == principal_id, Principal.box_id == box_id)
    )
    if not principal:
        raise AccessDenied("identity is not assigned to this Box")
    if (
        principal.principal_type != PrincipalType.HUMAN.value
        or principal.state != PrincipalState.ACTIVE.value
    ):
        raise AccessDenied("an active human identity is required")
    return principal


def authenticate_request(
    session: Session,
    runtime_settings: Settings,
    *,
    authorization: str | None,
    box_header: str | None,
    actor_header: str | None,
    verifier: TokenVerifier | None = None,
) -> RequestIdentity:
    if runtime_settings.auth_mode == "synth_headers":
        if runtime_settings.cosmas_env != "synth_os":
            raise AuthenticationFailed("synthetic header authentication is disabled")
        if not _valid_uuid(box_header) or not _valid_uuid(actor_header):
            raise AuthenticationFailed("synthetic Box and actor headers are required")
        assert box_header is not None and actor_header is not None
        _active_human(session, actor_header, box_header)
        return RequestIdentity(
            box_id=box_header,
            principal_id=actor_header,
            auth_mode="synth_headers",
        )

    if runtime_settings.auth_mode != "clerk_jwt":
        raise AuthenticationFailed("authentication mode is unavailable")
    if box_header or actor_header:
        raise AuthenticationFailed("caller-supplied identity headers are not accepted")
    if not authorization:
        raise AuthenticationFailed("bearer token required")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise AuthenticationFailed("bearer token required")

    token_verifier = verifier or ClerkTokenVerifier(runtime_settings)
    claims = token_verifier.verify(token)
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise AuthenticationFailed("invalid bearer token")
    organization_id = _organization_id(claims)
    issuer = runtime_settings.clerk_issuer
    expected_org = runtime_settings.clerk_organization_id
    if not issuer or not expected_org:
        raise AuthenticationFailed("authentication configuration is unavailable")
    if not hmac.compare_digest(organization_id, expected_org):
        raise AccessDenied("identity is outside the configured organization")

    binding = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == "clerk",
            ExternalIdentity.issuer == issuer,
            ExternalIdentity.subject == subject,
            ExternalIdentity.organization_id == organization_id,
            ExternalIdentity.active.is_(True),
        )
    )
    if not binding:
        raise AccessDenied("identity is not provisioned")
    if not runtime_settings.beta_box_id or not hmac.compare_digest(
        binding.box_id, runtime_settings.beta_box_id
    ):
        raise AccessDenied("identity is outside the configured Box")
    _active_human(session, binding.principal_id, binding.box_id)
    return RequestIdentity(
        box_id=binding.box_id,
        principal_id=binding.principal_id,
        auth_mode="clerk_jwt",
        organization_id=organization_id,
        external_identity_id=binding.id,
    )
