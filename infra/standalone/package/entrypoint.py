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
OPTIONAL_PRIVATE_NAMES = MODEL_PRIVATE_NAMES | GOOGLE_PRIVATE_NAMES


class Refused(Exception):
    """Do not include configuration values or underlying exceptions in output."""


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
    if (not PRIVATE_NAMES.issubset(private) or set(private) - PRIVATE_NAMES - OPTIONAL_PRIVATE_NAMES
            or (PRIVATE_NAMES | OPTIONAL_PRIVATE_NAMES).intersection(public)):
        raise Refused()
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
