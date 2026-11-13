"""Start only the owned standalone API from two bounded mounted JSON files."""

import json
import os
import re
import stat
import sys
from pathlib import Path

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
# Must match render.mjs classifyAccountDeleteProfile exactly.
STAGING_WEB_ORIGIN = "https://staging.cosmas.ai"
REVIEW_WEB_ORIGIN = "https://beta.cosmas.ai"
REVIEW_CLERK_ISSUER = "https://clerk.beta.cosmas.ai"
STAGING_SESSION_POLICY = "shared_staging"
REVIEW_SESSION_POLICY = "audience"


class Refused(Exception):
    """Do not include configuration values or underlying exceptions in output."""


def classify_account_delete_profile(
    *,
    policy: str | None,
    web_origin: str | None,
    cors: str | None,
    issuer: str | None,
) -> str | None:
    """Return 'staging', 'review', or None. Parity with render.mjs.

    Review requires web_origin==beta.cosmas.ai (or CORS first origin equal to
    it when web_origin is omitted), audience policy, no staging origin in CORS,
    and issuer https://clerk.beta.cosmas.ai as an added condition (never sole
    admit). Mixed CORS or shared_staging+beta is refused (None).
    """
    cors_list = [part.strip() for part in (cors or "").split(",") if part.strip()]
    origins = set(cors_list)
    if web_origin:
        origins.add(web_origin)
    has_staging = STAGING_WEB_ORIGIN in origins
    has_review = REVIEW_WEB_ORIGIN in origins
    if has_staging and has_review:
        return None
    if policy == STAGING_SESSION_POLICY and has_review:
        return None
    # When web_origin is omitted (runtime CORS-only), first origin must be beta —
    # never admit on mere membership (Opus parity with render web_origin match).
    review_web = (
        (web_origin == REVIEW_WEB_ORIGIN)
        if web_origin is not None
        else (bool(cors_list) and cors_list[0] == REVIEW_WEB_ORIGIN)
    )
    if (
        policy == REVIEW_SESSION_POLICY
        and review_web
        and has_review
        and not has_staging
        and (issuer or "") == REVIEW_CLERK_ISSUER
    ):
        return "review"
    if policy == STAGING_SESSION_POLICY or has_staging:
        return "staging"
    return None


def account_delete_kind(checked) -> str | None:
    return classify_account_delete_profile(
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
    return (
        classify_account_delete_profile(
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
    candidate_optional = OPTIONAL_PRIVATE_NAMES | ACCOUNT_DELETE_PRIVATE_NAMES
    # Host key must never appear in the public mount (review or staging).
    public_leak_names = PRIVATE_NAMES | candidate_optional | {REVIEW_ACCOUNT_DELETE_HOST_KEY}
    if (not PRIVATE_NAMES.issubset(private) or set(private) - PRIVATE_NAMES - candidate_optional
            or public_leak_names.intersection(public)):
        raise Refused()
    if any(
        not isinstance(value, str) or not value or value != value.strip()
        for value in private.values()
    ):
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
        os.chdir("/app")
        if Path(".env").exists():
            raise Refused()
        sys.path.insert(0, "/app/src")
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
