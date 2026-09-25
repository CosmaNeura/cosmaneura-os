"""Load mounted credentials only inside the API/worker process, then exec it.

The renderer imports the same validation functions. Nothing here calls a provider
or prints a Settings/validation exception, which can contain credential values.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import quote

API_UID = 10001
SECRET_LIMIT = 32768
BASE = {
    "COSMAS_ENV": "early_adopter_beta",
    "DATA_MODE": "synthetic",
    "AUTH_MODE": "clerk_jwt",
    "BLOB_BACKEND": "azure",
    "SYNTH_SEED": "false",
    "SYNC_WORKER": "false",
    "EXECUTION_BACKEND": "celery",
    "WORKSPACE_ENABLED": "true",
    "WORKSPACE_AUTHENTICATED_ENABLED": "true",
    "WORKSPACE_HOSTED_ENABLED": "true",
    "WORKSPACE_DRAFT_RECOVERY_REQUIRED": "true",
    "WORKSPACE_TEAM_SETUP_ENABLED": "true",
    "WORKSPACE_ROUTINES_ENABLED": "true",
    "WORKSPACE_LLM_BACKEND": "azure_gpt41",
}
FORBIDDEN_PUBLIC = {
    "DATABASE_URL",
    "REDIS_URL",
    "BLOB_ROOT",
    "COMPACT_WEB_ROOT",
    "COSMAS_CLOCK_NOW",
    "MANAGED_SERVICES_CONFIG_PATH",
    "HUMAN_DEPLOY_EVIDENCE_REF",
    "CLINIC_APPROVAL_REF",
    "BAA_EVIDENCE_REF",
    "PHI_AUTHORIZATION_REF",
}


class Refused(ValueError):
    """Messages are fixed diagnostic codes, never input/exception reprs."""


def read_json(path: Path):
    def unique(pairs):
        result = {}

        for key, value in pairs:
            if key in result:
                raise Refused("duplicate_json_key")
            result[key] = value
        return result

    return json.loads(path.read_text(), object_pairs_hook=unique)


def read_private(path: Path, uid: int) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != uid
                or stat.S_IMODE(metadata.st_mode) != 0o400
                or metadata.st_nlink != 1
                or not 0 < metadata.st_size <= SECRET_LIMIT
            ):
                raise Refused("protected_file_permissions")
            raw = stream.read(SECRET_LIMIT + 1)
        value = raw.decode("utf-8")
        if value.endswith("\n"):
            value = value[:-1]
        if not value or "\x00" in value:
            raise Refused("protected_file_content")
        return value
    except (OSError, UnicodeError):
        raise Refused("protected_file_unavailable") from None


def setting_contract():
    from cosmas_os.config import Settings

    fields = Settings.model_fields
    secrets = {name.upper() for name, item in fields.items() if "SecretStr" in str(item.annotation)}
    booleans = {name.upper() for name, item in fields.items() if item.annotation is bool}
    public = {name.upper() for name in fields} - secrets - FORBIDDEN_PUBLIC
    return Settings, public, secrets, booleans


def validate_public(configuration: dict) -> None:
    if set(configuration) != {"environment", "secret_names", "runtime_identity_client_id"}:
        raise Refused("runtime_configuration_shape")
    values, names = configuration["environment"], configuration["secret_names"]
    _, public, secrets, booleans = setting_contract()
    if not isinstance(values, dict) or set(values) - public:
        raise Refused("public_environment_names")
    if any(
        not isinstance(value, str) or len(value) > 16384 or "\x00" in value
        for value in values.values()
    ):
        raise Refused("public_environment_values")
    if not booleans.issubset(values) or any(
        values[key] not in {"true", "false"} for key in booleans
    ):
        raise Refused("explicit_feature_selection_required")
    if any(values.get(key) != value for key, value in BASE.items()):
        raise Refused("hosted_synthetic_profile_required")
    if (
        not isinstance(names, list)
        or any(not isinstance(name, str) for name in names)
        or len(names) != len(set(names))
        or any(
            not (
                name in secrets | {"HUMAN_DEPLOY_EVIDENCE_REF"}
                or re.fullmatch(r"COSMAS_MANAGED_SECRET_[A-Z][A-Z0-9_]{0,63}", name)
            )
            for name in names
        )
        or "HUMAN_DEPLOY_EVIDENCE_REF" not in names
    ):
        raise Refused("secret_environment_names")
    for child, parent in (
        ("WORKSPACE_PREP_WORK_ENABLED", "WORKSPACE_PREP_ENABLED"),
        ("WORKSPACE_RESEARCH_IO_ENABLED", "WORKSPACE_RESEARCH_ENABLED"),
        ("INBOX_HANDOFF_ENABLED", "INBOX_WORK_ENABLED"),
        ("VENDOR_IO_ENABLED", "VENDOR_WORK_ENABLED"),
        ("VENDOR_EVENTS_ENABLED", "VENDOR_WORK_ENABLED"),
        ("FINANCE_IO_ENABLED", "FINANCE_WORK_ENABLED"),
        ("FINANCE_EVENTS_ENABLED", "FINANCE_WORK_ENABLED"),
    ):
        if values[child] == "true" and values[parent] != "true":
            raise Refused("workspace_feature_dependency")
    if (
        any(
            values[name] == "true"
            for name in (
                "VENDOR_IO_ENABLED",
                "VENDOR_EVENTS_ENABLED",
                "FINANCE_IO_ENABLED",
                "FINANCE_EVENTS_ENABLED",
            )
        )
        and "MANAGED_SERVICES_CONFIG_JSON" not in names
    ):
        raise Refused("managed_account_manifest_required")
    if "WORKSPACE_LLM_API_KEY" not in names:
        raise Refused("model_credential_required")
    from uuid import UUID

    try:
        value = configuration["runtime_identity_client_id"]
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise Refused("runtime_identity_required") from None


def load_environment(configuration: dict, directory: Path) -> dict[str, str]:
    validate_public(configuration)
    credentials = {
        key: read_private(directory / key, API_UID)
        for key in ["DATABASE_PASSWORD", "REDIS_PASSWORD", *configuration["secret_names"]]
    }
    for key in ("DATABASE_PASSWORD", "REDIS_PASSWORD"):
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", credentials[key])
            or len(set(credentials[key])) < 12
        ):
            raise Refused("service_password_strength")
    values = dict(configuration["environment"])
    values.update({key: credentials[key] for key in configuration["secret_names"]})
    values["DATABASE_URL"] = (
        "postgresql+psycopg://cosmas:"
        + quote(credentials["DATABASE_PASSWORD"], safe="")
        + "@postgres:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    )
    values["REDIS_URL"] = (
        "rediss://:"
        + quote(credentials["REDIS_PASSWORD"], safe="")
        + "@redis:6379/0?ssl_cert_reqs=required"
    )
    Settings, _, _, _ = setting_contract()

    class IsolatedSettings(Settings):
        @classmethod
        def settings_customise_sources(
            cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
        ):
            return (init_settings,)

    try:
        known = {
            key.lower(): value
            for key, value in values.items()
            if key.lower() in Settings.model_fields
        }
        selected = IsolatedSettings(**known)
        selected.validate_runtime_configuration()
        if not selected.workspace_available:
            raise Refused("hosted_workspace_unavailable")
    except Exception:
        raise Refused("application_configuration_refused") from None
    values["AZURE_CLIENT_ID"] = configuration["runtime_identity_client_id"]
    return values


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"api", "worker", "validate", "prepare"}:
        raise Refused("entrypoint_role")
    if sys.argv[1] == "prepare":
        directory = Path("/run/cosmabot/secrets")
        runtime_password = read_private(directory / "DATABASE_PASSWORD", API_UID)
        admin_password = read_private(directory / "POSTGRES_PASSWORD", API_UID)
        if runtime_password == admin_password:
            raise Refused("database_roles_must_be_separate")
        suffix = "@postgres:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONPATH": "/app/src",
            "PYTHONDONTWRITEBYTECODE": "1",
            "COSMAS_ENV": "early_adopter_beta",
            "DATABASE_URL": "postgresql+psycopg://cosmas:"
            + quote(runtime_password, safe="")
            + suffix,
            "DATABASE_ADMIN_URL": "postgresql+psycopg://postgres:"
            + quote(admin_password, safe="")
            + suffix,
        }
        command = [
            "python",
            "-m",
            "cosmas_os.cli",
            "prepare-beta-database",
            "--confirm-forward-only",
        ]
        os.execvpe(command[0], command, environment)
        return 1
    configuration = read_json(Path("/opt/cosmabot/runtime/runtime.json"))
    values = load_environment(configuration, Path("/run/cosmabot/secrets"))
    if sys.argv[1] == "validate":
        return 0
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": "/app/src",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        **values,
    }
    command = (
        [
            "uvicorn",
            "cosmas_os.api.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            "1",
        ]
        if sys.argv[1] == "api"
        else [
            "celery",
            "-A",
            "cosmas_os.worker.celery_app:celery_app",
            "worker",
            "--loglevel=WARNING",
            "--concurrency=1",
        ]
    )
    os.execvpe(command[0], command, environment)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print(
            "CosmaBot runtime inputs refused; inspect protected configuration locally.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
