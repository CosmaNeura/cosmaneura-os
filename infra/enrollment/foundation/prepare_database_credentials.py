#!/usr/bin/env python3
"""Write three separate bootstrap/migration/runtime URL files; never print them."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

from prepare import private_read, private_write
from seed_secret import foundation


def prepare(f: dict, password_file: Path, directory: Path) -> dict:
    if not directory.is_absolute() or directory.exists() or directory.is_symlink() or directory.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError("fresh protected directory outside repository required")
    host = f.get("postgres_fqdn", "")
    if (not re.fullmatch(r"psql-cosmabot-enrollment-staging-[a-z0-9]{6,8}\.postgres\.database\.azure\.com", host)
            or f.get("postgres_database") != "cosmabot_enrollment"):
        raise ValueError("owned dedicated PostgreSQL coordinates required")
    admin = private_read(password_file).decode()
    if not 32 <= len(admin) <= 128:
        raise ValueError("protected bootstrap password required")
    directory.mkdir(mode=0o700)
    for role, password in (("bootstrap", admin), ("migrator", secrets.token_urlsafe(48)), ("runtime", secrets.token_urlsafe(48))):
        url = (f"postgresql+psycopg://enrollment_{role}:{quote(password, safe='')}@{host}:5432/cosmabot_enrollment"
               "?sslmode=verify-full&sslrootcert=%2Fetc%2Fssl%2Fcerts%2Fca-certificates.crt")
        private_write(directory / f"{role}.url", url.encode())
    return {"credentials_prepared": True, "separate_logins": 3, "seeded": False, "qualified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundation", type=Path, required=True)
    parser.add_argument("--admin-password-file", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(foundation(args.foundation), args.admin_password_file, args.directory), sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({"error": "enrollment_credentials_preparation_failed", "class": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
