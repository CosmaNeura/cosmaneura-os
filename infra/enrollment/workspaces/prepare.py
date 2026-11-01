"""Prepare protected Box passwords/URLs and public-only build inputs, with no cloud calls."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from urllib.parse import quote


def read_private(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 65536
        ):
            raise ValueError("protected regular owner file required")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read(65537)
    finally:
        os.close(fd)


def write_private(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)


def prepare(directory: Path) -> dict:
    root = Path(__file__).resolve().parents[3]
    if (
        not directory.is_absolute()
        or directory.exists()
        or directory.is_symlink()
        or directory.resolve().is_relative_to(root)
    ):
        raise ValueError("fresh private directory outside source required")
    directory.mkdir(mode=0o700)
    write_private(directory / "encryption.passphrase", secrets.token_urlsafe(64).encode())
    for key in ("a", "b"):
        write_private(directory / f"admin-{key}.password", secrets.token_urlsafe(48).encode())
        write_private(directory / f"runtime-{key}.password", secrets.token_urlsafe(48).encode())
    return {"prepared": True, "practices": 2, "cloud_calls": False, "qualified": False}


def urls(directory: Path, namespace: str, key: str, redis_host: str, redis_key: Path) -> dict:
    import re

    if (
        key not in {"a", "b"}
        or not re.fullmatch(r"[a-z0-9]{6,8}", namespace)
        or directory.is_symlink()
        or stat.S_IMODE(directory.stat().st_mode) != 0o700
        or not re.fullmatch(
            rf"redis-cews-stg-{namespace}-{key}\.[a-z0-9.-]+\.redis\.azure\.net", redis_host
        )
    ):
        raise ValueError("protected per-Box credential preparation required")
    host = f"psql-cews-stg-{namespace}-{key}.postgres.database.azure.com"
    values = {}
    for role, login in (("admin", "box_bootstrap"), ("runtime", "box_runtime")):
        password = read_private(directory / f"{role}-{key}.password").decode()
        if not password or any(ord(char) < 33 or ord(char) > 126 for char in password):
            raise ValueError("protected Box password required")
        url = f"postgresql+psycopg://{login}:{quote(password, safe='')}@{host}:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
        values[f"{role}-{key}.url"] = url.encode()
    password = read_private(redis_key).decode().strip()
    if not password or any(ord(char) < 32 for char in password):
        raise ValueError("protected managed Redis credential required")
    values[f"redis-{key}.url"] = (
        f"rediss://:{quote(password, safe='')}@{redis_host}:10000/0?ssl_cert_reqs=required".encode()
    )
    # Validate every input and destination before writing the first URL.
    if any((directory / name).exists() or (directory / name).is_symlink() for name in values):
        raise ValueError("fresh protected URL outputs required")
    for name, value in values.items():
        write_private(directory / name, value)
    return {"urls_prepared": True, "seeded": False, "qualified": False}


def terraform_environment(directory: Path) -> dict[str, str]:
    if directory.is_symlink() or stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise ValueError("protected directory required")
    if any(
        key.startswith(("TF_", "ARM_")) or key in {"TOFU_ENCRYPTION", "AZURE_CONFIG_DIR"}
        for key in os.environ
    ):
        raise ValueError("ambient deploy/debug overrides refused")
    read_private(directory / "encryption.passphrase")
    passwords = {
        key: read_private(directory / f"admin-{key}.password").decode() for key in ("a", "b")
    }
    return {
        **os.environ,
        "TF_VAR_postgres_admin_passwords": json.dumps(passwords),
        "TF_VAR_encryption_key_file": str(directory / "encryption.passphrase"),
        "TF_INPUT": "0",
        "TF_WORKSPACE": "default",
        "TF_DATA_DIR": str(directory / "provider-data"),
        "ARM_USE_CLI": "true",
        "ARM_USE_MSI": "false",
        "ARM_USE_OIDC": "false",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "urls", "tofu"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--namespace")
    parser.add_argument("--practice", choices=["a", "b"])
    parser.add_argument("--redis-host")
    parser.add_argument("--redis-key-file", type=Path)
    parser.add_argument("--tofu-argument", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.operation == "prepare":
            result = prepare(args.directory)
        elif args.operation == "urls":
            result = urls(
                args.directory, args.namespace, args.practice, args.redis_host, args.redis_key_file
            )
        else:
            import shutil
            import subprocess

            # Operator-only route; preparing source/tests never invokes it.
            if not args.tofu_argument or args.tofu_argument[0] not in {
                "init",
                "plan",
                "apply",
                "output",
            }:
                raise ValueError("explicit bounded Terraform operation required")
            binary = shutil.which("tofu")
            if not binary:
                raise ValueError("OpenTofu required")
            subprocess.run(
                [binary, *args.tofu_argument],
                cwd=Path(__file__).parent,
                env=terraform_environment(args.directory),
                check=True,
                umask=0o077,
            )
            result = {"operator_command_completed": True, "workspace_ready": False}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(
            json.dumps({"error": "workspace_preparation_failed", "class": type(error).__name__}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
