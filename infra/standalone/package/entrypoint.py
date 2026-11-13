"""Start only the owned standalone API from two bounded mounted JSON files."""

import json
import os
import re
import stat
import sys
from pathlib import Path

# Absolute image layout (Dockerfile COPY src ./src). Tests may patch APP_ROOT.
APP_ROOT = Path("/app")
APP_SRC = APP_ROOT / "src"

PUBLIC = Path("/run/cosmabot-standalone/api-public.json")
PRIVATE = Path("/run/cosmabot-standalone/api-private.json")
PRIVATE_NAMES = {"DATABASE_URL", "HUMAN_DEPLOY_EVIDENCE_REF"}
MODEL_PRIVATE_NAMES = {"WORKSPACE_LLM_API_KEY"}
GOOGLE_PRIVATE_NAMES = {"GOOGLE_CONNECTION_CLIENT_SECRET", "GOOGLE_CONNECTION_ENCRYPTION_KEY"}
MICROSOFT_PRIVATE_NAMES = {"MICROSOFT_CONNECTION_CLIENT_SECRET", "MICROSOFT_CONNECTION_ENCRYPTION_KEY"}
# Optional private name for hosted account delete on staging and the
# production-review host (beta.cosmas.ai). Other audience profiles refuse it.
# CLERK_SECRET_KEY stays refused on every profile.
ACCOUNT_DELETE_ENV_NAME = "ACCOUNT_DELETE_CLERK_SECRET_KEY"
ACCOUNT_DELETE_PRIVATE_NAMES = {ACCOUNT_DELETE_ENV_NAME}
# Production-review (#356) host key name. Azure Key Vault object name is
# CLERK-ACCOUNT-DELETION-SECRET (hyphens); host file / env alias uses underscores.
# Remapped to ACCOUNT_DELETE_ENV_NAME before Settings. Staging never accepts it.
REVIEW_ACCOUNT_DELETE_HOST_KEY = "CLERK_ACCOUNT_DELETION_SECRET"
REVIEW_ACCOUNT_DELETE_VAULT_OBJECT = "CLERK-ACCOUNT-DELETION-SECRET"
# Back-compat alias for tests that still import the old constant name.
REVIEW_ACCOUNT_DELETE_KV_NAME = REVIEW_ACCOUNT_DELETE_HOST_KEY
OPTIONAL_PRIVATE_NAMES = MODEL_PRIVATE_NAMES | GOOGLE_PRIVATE_NAMES | MICROSOFT_PRIVATE_NAMES

_SHARED_BOUND = False
# Shared predicate names are intentionally absent until _bind_shared_predicate
# runs (or __getattr__ lazy-binds them). Assigning None here would make
# __getattr__ dead code — attribute access would return None without binding.


class Refused(Exception):
    """Do not include configuration values or underlying exceptions in output."""


def _bind_shared_predicate() -> None:
    """Import the shared predicate after /app/src is on sys.path (python -I safe)."""
    global _SHARED_BOUND
    global STAGING_WEB_ORIGIN, REVIEW_WEB_ORIGIN, REVIEW_CLERK_ISSUER
    global STAGING_SESSION_POLICY, REVIEW_SESSION_POLICY
    global classify_review_profile, classify_account_delete_profile
    if _SHARED_BOUND and "classify_review_profile" in globals() and classify_review_profile is not None:
        return
    from cosmas_os.production_review_profile import (  # noqa: I001
        REVIEW_CLERK_ISSUER as _issuer,
        REVIEW_SESSION_POLICY as _review_policy,
        REVIEW_WEB_ORIGIN as _review_web,
        STAGING_SESSION_POLICY as _staging_policy,
        STAGING_WEB_ORIGIN as _staging_web,
        classify_review_profile as _classify,
    )

    STAGING_WEB_ORIGIN = _staging_web
    REVIEW_WEB_ORIGIN = _review_web
    REVIEW_CLERK_ISSUER = _issuer
    STAGING_SESSION_POLICY = _staging_policy
    REVIEW_SESSION_POLICY = _review_policy
    classify_review_profile = _classify
    # Thin alias — no private classify body.
    classify_account_delete_profile = _classify
    _SHARED_BOUND = True


def __getattr__(name: str):
    """Lazy bind for tests that read shared constants before main()."""
    if name in {
        "STAGING_WEB_ORIGIN",
        "REVIEW_WEB_ORIGIN",
        "REVIEW_CLERK_ISSUER",
        "STAGING_SESSION_POLICY",
        "REVIEW_SESSION_POLICY",
        "classify_review_profile",
        "classify_account_delete_profile",
    }:
        _bind_shared_predicate()
        return globals()[name]
    raise AttributeError(name)


def account_delete_kind(checked) -> str | None:
    _bind_shared_predicate()
    return classify_review_profile(
        policy=getattr(checked, "clerk_session_policy", None),
        web_origin=None,
        cors=getattr(checked, "cors_allowed_origins", None),
        issuer=getattr(checked, "clerk_issuer", None),
    )


def account_delete_profile(checked) -> bool:
    """True when staging or exclusive production-review admits the delete name."""
    return account_delete_kind(checked) is not None


def review_account_delete_profile(checked) -> bool:
    """True only for the exclusive production-review delete profile."""
    return account_delete_kind(checked) == "review"


def review_account_delete_host(public: dict) -> bool:
    """True when public fields classify as exclusive production-review."""
    _bind_shared_predicate()
    return (
        classify_review_profile(
            policy=public.get("CLERK_SESSION_POLICY"),
            web_origin=None,
            cors=public.get("CORS_ALLOWED_ORIGINS"),
            issuer=public.get("CLERK_ISSUER"),
        )
        == "review"
    )


def remap_review_account_delete_private(private: dict, *, review: bool) -> dict:
    """Map review host key name into ACCOUNT_DELETE_CLERK_SECRET_KEY (names only).

    Staging and non-review profiles refuse CLERK_ACCOUNT_DELETION_SECRET.
    Both names together are refused. Values are never logged.
    """
    has_alias = REVIEW_ACCOUNT_DELETE_HOST_KEY in private
    has_env = ACCOUNT_DELETE_ENV_NAME in private
    if not has_alias:
        return private
    if not review or has_env:
        raise Refused()
    remapped = dict(private)
    remapped[ACCOUNT_DELETE_ENV_NAME] = remapped.pop(REVIEW_ACCOUNT_DELETE_HOST_KEY)
    return remapped


def _normalize_account_delete_secret(private: dict) -> dict:
    """Treat padded/whitespace delete secrets as absent; never refuse boot for padding.

    Non-delete private values may keep surrounding whitespace (staging wall fix).
    app.py strips the delete secret at use time.
    """
    if ACCOUNT_DELETE_ENV_NAME not in private:
        return private
    value = private[ACCOUNT_DELETE_ENV_NAME]
    if not isinstance(value, str):
        raise Refused()
    stripped = value.strip()
    out = dict(private)
    if not stripped:
        out.pop(ACCOUNT_DELETE_ENV_NAME)
    elif stripped != value:
        out[ACCOUNT_DELETE_ENV_NAME] = stripped
    return out


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Refused()
        value[key] = item
    return value


def read_json(path: Path, *, private: bool):
    if any(parent.is_symlink() for parent in path.parents):
        raise Refused()
    limit = 32768 if private else 131072
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        mode = stat.S_IMODE(info.st_mode)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit
                or info.st_uid not in {0, os.geteuid()} or mode & 0o022
                or private and (info.st_uid != os.geteuid() or mode not in {0o400, 0o600})):
            raise Refused()
        raw = bytearray()
        while len(raw) <= limit:
            chunk = os.read(descriptor, min(8192, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > limit or len(raw) != info.st_size or os.fstat(descriptor).st_size != info.st_size:
            raise Refused()
    finally:
        os.close(descriptor)
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise Refused()
    return value


def load_configuration(public_path=PUBLIC, private_path=PRIVATE):
    # Imported only after main clears inherited environment. The second process
    # below receives the selected values before importing the application module.
    _bind_shared_predicate()
    from cosmas_os.config import Settings

    public = read_json(public_path, private=False)
    private = read_json(private_path, private=True)
    # Staging and exclusive production-review may optionally carry
    # ACCOUNT_DELETE_CLERK_SECRET_KEY. Production-review may instead mount the
    # #356 host key CLERK_ACCOUNT_DELETION_SECRET (vault object
    # CLERK-ACCOUNT-DELETION-SECRET), remapped below.
    # CLERK_SECRET_KEY is never an allowed private name.
    review = review_account_delete_host(public)
    private = remap_review_account_delete_private(private, review=review)
    private = _normalize_account_delete_secret(private)
    candidate_optional = OPTIONAL_PRIVATE_NAMES | ACCOUNT_DELETE_PRIVATE_NAMES
    # Host key must never appear in the public mount (review or staging).
    public_leak_names = PRIVATE_NAMES | candidate_optional | {REVIEW_ACCOUNT_DELETE_HOST_KEY}
    if (not PRIVATE_NAMES.issubset(private) or set(private) - PRIVATE_NAMES - candidate_optional
            or public_leak_names.intersection(public)):
        raise Refused()
    # Non-empty strings only. Do NOT refuse on surrounding whitespace for
    # non-delete secrets (staging wall). Delete-key padding handled above.
    if any(not isinstance(value, str) or not value for value in private.values()):
        raise Refused()
    known = {name.upper() for name in Settings.model_fields}
    secret_names = {name.upper() for name, field in Settings.model_fields.items()
                    if "SecretStr" in str(field.annotation)}
    if (set(public) - known or secret_names.intersection(public)
            or any(not isinstance(value, str | bool | int) for value in public.values())
            or public.get("COSMAS_ENV") not in {"standalone_clerk_synthetic", "standalone_synthetic"}):
        raise Refused()
    supplied = {**public, **private}

    class MountedSettings(Settings):
        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, env_settings,
                                       dotenv_settings, file_secret_settings):
            return (init_settings,)

    checked = MountedSettings(**{key.lower(): value for key, value in supplied.items()})
    expected_private = set(PRIVATE_NAMES)
    if checked.cosmas_env == "standalone_clerk_synthetic":
        if checked.workspace_llm_backend == "azure_gpt41":
            expected_private.update(MODEL_PRIVATE_NAMES)
        if checked.workspace_google_connection_enabled:
            expected_private.update(GOOGLE_PRIVATE_NAMES)
        if checked.workspace_microsoft_connection_enabled:
            expected_private.update(MICROSOFT_PRIVATE_NAMES)
    allowed = account_delete_profile(checked)
    if ACCOUNT_DELETE_PRIVATE_NAMES.intersection(private):
        if not allowed:
            raise Refused()
        expected_private.update(ACCOUNT_DELETE_PRIVATE_NAMES)
    if set(private) != expected_private:
        raise Refused()
    checked.validate_runtime_configuration()
    # Only the exact selected feature's mounted credentials reach the process;
    # ambient Settings, proxies and unrelated credentials are never inherited.
    environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app/src",
                   "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1"}
    environment.update({key: str(value).lower() if isinstance(value, bool) else str(value)
                        for key, value in supplied.items()})
    return environment


def main():
    try:
        # Existing staging uses UID 10001. This image requires its separately
        # allocated runtime UID, supplied explicitly by the reviewed host unit.
        if os.geteuid() <= 10001 or len(sys.argv) != 2 or not re.fullmatch(r"[0-9]{4,5}", sys.argv[1]):
            raise Refused()
        port = int(sys.argv[1])
        if not 1024 <= port <= 65535:
            raise Refused()
        os.environ.clear()
        os.chdir(APP_ROOT)
        if (APP_ROOT / ".env").exists():
            raise Refused()
        # python -I ignores PYTHONPATH; bind shared predicate only inside this try
        # so ImportError becomes the fixed refusal (exit 78), not a traceback.
        src = str(APP_SRC)
        if src not in sys.path:
            sys.path.insert(0, src)
        _bind_shared_predicate()
        environment = load_configuration()
    except Exception:
        print("Standalone API configuration refused.", file=sys.stderr)
        return 78
    command = ["/usr/local/bin/python", "-B", "-m", "uvicorn", "cosmas_os.api.app:app",
               "--host", "127.0.0.1", "--port", str(port), "--workers", "1", "--no-access-log",
               "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
    os.execve(command[0], command, environment)


if __name__ == "__main__":
    raise SystemExit(main())
