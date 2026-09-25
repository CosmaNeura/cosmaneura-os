#!/usr/bin/env python3
"""Validate the public synthetic D3 web build contract (Python 3.10+)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

MAX_CONFIG_BYTES = 8192
BUILD_KEYS = (
    "VITE_CLERK_PUBLISHABLE_KEY",
    "VITE_WORKSPACE_HOSTED_API_ORIGIN",
    "VITE_WORKSPACE_WEB_ORIGIN",
    "VITE_WORKSPACE_DATA_MODE",
    "VITE_COSMANEURA_WEB_ORIGIN",
    "VITE_CAPTURE_UPLOAD_ORIGINS",
    "VITE_WORKSPACE_CAPTURE_MODE",
)
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
_PUBLISHABLE_KEY = re.compile(r"pk_live_[A-Za-z0-9+/=_-]{1,512}")


class WebBuildError(ValueError):
    """The public input cannot be used by the protected D3 builder."""


def exact_origin(value: str) -> bool:
    if len(value) > 253:
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        return bool(
            parsed.scheme == "https"
            and value == "https://" + host
            and _HOST.fullmatch(host)
            and not host.endswith(".localhost")
            and not re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", host.rsplit(".", 1)[-1])
        )
    except ValueError:
        return False


def validate_config(candidate: object, *, api_origin: str | None = None,
                    web_origin: str | None = None) -> dict[str, str]:
    if not isinstance(candidate, dict) or set(candidate) != set(BUILD_KEYS):
        raise WebBuildError("exactly the seven public web build fields are required")
    if any(not isinstance(value, str) for value in candidate.values()):
        raise WebBuildError("public web build fields must be strings")
    config = {key: candidate[key] for key in BUILD_KEYS}
    if not _PUBLISHABLE_KEY.fullmatch(config["VITE_CLERK_PUBLISHABLE_KEY"]):
        raise WebBuildError("a bounded production Clerk publishable key is required")
    if config["VITE_WORKSPACE_DATA_MODE"] != "synthetic":
        raise WebBuildError("the protected D3 build requires synthetic data mode")
    if config["VITE_WORKSPACE_CAPTURE_MODE"] not in {"synthetic", "browser_microphone"}:
        raise WebBuildError("unsupported web capture mode")
    for key in ("VITE_WORKSPACE_HOSTED_API_ORIGIN", "VITE_WORKSPACE_WEB_ORIGIN",
                "VITE_COSMANEURA_WEB_ORIGIN"):
        if not exact_origin(config[key]):
            raise WebBuildError(f"{key} must be an exact credential-free HTTPS origin")
    core_host = urlsplit(config["VITE_COSMANEURA_WEB_ORIGIN"]).hostname
    assert core_host is not None
    if not core_host.rsplit(".", 1)[-1][0].isalpha():
        raise WebBuildError("Core web origin must use a domain name")
    origins = config["VITE_CAPTURE_UPLOAD_ORIGINS"].split(",")
    if not 1 <= len(origins) <= 4 or len(set(origins)) != len(origins) or not all(
        exact_origin(origin) for origin in origins
    ):
        raise WebBuildError("capture requires one to four distinct exact HTTPS upload origins")
    if (api_origin is None) != (web_origin is None):
        raise WebBuildError("both foundation origins are required for binding")
    if api_origin is not None and web_origin is not None:
        if not exact_origin(api_origin) or not exact_origin(web_origin):
            raise WebBuildError("foundation origins are invalid")
        if (config["VITE_WORKSPACE_HOSTED_API_ORIGIN"] != api_origin
                or config["VITE_WORKSPACE_WEB_ORIGIN"] != web_origin):
            raise WebBuildError("web build origins differ from the exact foundation outputs")
    return config


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise WebBuildError("duplicate public web build field")
        value[key] = item
    return value


def load_config(path: Path, **bindings: str | None) -> dict[str, str]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise WebBuildError("use a regular public web build JSON file")
            raw = handle.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            raise WebBuildError("public web build JSON exceeds its size limit")
        candidate = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise WebBuildError("public web build JSON is unavailable or invalid") from None
    return validate_config(candidate, **bindings)


def config_sha256(config: dict[str, str]) -> str:
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":")) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def docker_argument_lines(config: dict[str, str]) -> list[str]:
    return [f"{key}={config[key]}" for key in BUILD_KEYS]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("validate", "sha256", "docker-args"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--api-origin")
    parser.add_argument("--web-origin")
    args = parser.parse_args()
    try:
        config = load_config(args.path, api_origin=args.api_origin, web_origin=args.web_origin)
        if args.operation == "sha256":
            print(config_sha256(config))
        elif args.operation == "docker-args":
            print("\n".join(docker_argument_lines(config)))
    except WebBuildError as error:
        print(f"Web build refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
