"""Owned local runtime boundary for the standalone synthetic practice proof."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jwt
from sqlalchemy import text
from sqlalchemy.engine import Engine

from cosmas_os.api.auth import AuthenticationFailed, ClerkTokenVerifier
from cosmas_os.config import Settings
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION


def standalone_request_allowed(method: str, path: str) -> bool:
    """The first proof admits only local setup and notebook mutation surfaces."""
    if method in {"GET", "HEAD", "OPTIONS"}:
        return True
    if method != "POST":
        return False
    if path in {"/practice-access/setup/complete", "/provider-team", "/workspaces",
                "/workspaces/private-drafts", "/workspaces/private-drafts/resolve"}:
        return True
    identifier = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    bot = r"(?:scribe|visit_prep|follow_up|chief|" + identifier + r")"
    return bool(re.fullmatch(r"/workspaces/" + identifier
        + r"/(entries|notes|title(?:/resolve)?|appointment-link(?:/resolve)?|work-links|conversations/"
        + bot + r"/read)", path))


def _owned_root(runtime: Settings) -> Path:
    runtime.validate_runtime_configuration()
    if runtime.cosmas_env != "standalone_synthetic":
        raise RuntimeError("Standalone runtime profile is required")
    root = Path(runtime.standalone_root)
    if (not root.is_dir() or root.is_symlink() or root.stat().st_mode & 0o077
            or any(part.is_symlink() for part in (root, *root.parents))):
        raise RuntimeError("Standalone root must be a private owned directory")
    marker = root / "instance.json"
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_mode & 0o077:
        raise RuntimeError("Standalone instance marker must be private")
    if json.loads(marker.read_text()) != {
            "schema": "cosmabot-standalone-runtime/v1", "instance_id": runtime.standalone_instance_id}:
        raise RuntimeError("Standalone instance marker does not match")
    for child in (root / "blobs", root / "keys"):
        if not child.is_dir() or child.is_symlink() or child.stat().st_mode & 0o077:
            raise RuntimeError("Standalone state directories must be private and owned")
    return root


class LocalPublicKeys:
    """Immutable public keys; never performs discovery, refresh or network I/O."""

    def __init__(self, runtime: Settings) -> None:
        root = _owned_root(runtime)
        path = root / "keys" / "jwks.json"
        if (path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077
                or path.stat().st_size > 16384):
            raise RuntimeError("Standalone public key file must be private and bounded")
        value = json.loads(path.read_text())
        keys = value.get("keys") if isinstance(value, dict) else None
        if (not isinstance(keys, list) or not 1 <= len(keys) <= 8 or set(value) != {"keys"}):
            raise RuntimeError("Standalone public key set is invalid")
        prefix = f"cosmabot-standalone:{runtime.standalone_instance_id}:"
        seen = set()
        for key in keys:
            if (not isinstance(key, dict) or set(key) != {"kty", "kid", "use", "alg", "n", "e"}
                    or key.get("kty") != "RSA" or key.get("alg") != "RS256" or key.get("use") != "sig"
                    or not isinstance(key.get("kid"), str) or not key["kid"].startswith(prefix)
                    or not key["kid"][len(prefix):] or key["kid"] in seen):
                raise RuntimeError("Standalone keys must be public and instance-specific")
            seen.add(key["kid"])
        try:
            self._keys = jwt.PyJWKSet.from_dict(value).keys
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise RuntimeError("Standalone public key set is invalid") from exc
        if any(key.key.key_size < 2048 for key in self._keys):
            raise RuntimeError("Standalone RSA keys require at least 2048 bits")

    def get_signing_keys(self, *, refresh: bool = False) -> list[Any]:
        return list(self._keys)


class StandaloneTokenVerifier(ClerkTokenVerifier):
    """Pin owned public keys for the process lifetime; JWT lifetimes still apply."""

    def __init__(self, runtime: Settings) -> None:
        keys = LocalPublicKeys(runtime)
        self._local_signing_keys = {key.key_id: key for key in keys.get_signing_keys()}
        super().__init__(runtime, jwks_client=keys, start_background_refresh=False)

    def _get_signing_key(self, kid: str) -> Any:
        # Static offline keys have no refresh service. Do not inherit a remote
        # JWKS freshness deadline that would silently disable local sign-in.
        # Rotation is an explicit configuration review and process restart.
        try:
            return self._local_signing_keys[kid]
        except KeyError:
            raise AuthenticationFailed("invalid bearer token") from None


def validate_standalone_runtime(runtime: Settings, engine: Engine) -> None:
    """Validate before API readiness; never migrate or create application state."""
    _owned_root(runtime)
    LocalPublicKeys(runtime)
    if engine.url.render_as_string(hide_password=False) != runtime.database_url:
        raise RuntimeError("Standalone engine is not the configured owned database")
    with engine.connect() as connection:
        marker = connection.scalar(text("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()"))
        if marker != "cosmabot-standalone:" + runtime.standalone_instance_id:
            raise RuntimeError("Standalone database ownership marker does not match")
        role = connection.execute(text("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
        ddl = connection.execute(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE'), has_database_privilege(current_user, current_database(), 'CREATE'), has_database_privilege(current_user, current_database(), 'TEMPORARY')")).one()
        if any(role) or any(ddl):
            raise RuntimeError("Standalone API requires a restricted data-only database role")
        revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        if revisions != [EXPECTED_SCHEMA_REVISION]:
            raise RuntimeError("Standalone schema requires an explicit owned migration")
