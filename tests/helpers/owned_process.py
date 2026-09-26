"""Validate the pytest runner's explicit local process-fixture boundaries."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def owned_root(value: str | Path) -> Path:
    """Accept a real child of the exact --basetemp supplied by the test runner."""
    active = os.environ.get("PYTEST_CURRENT_TEST", "")
    approved = os.environ.get("COSMAS_TEST_TMP_ROOT", "")
    if "::" not in active or not active.endswith((" (setup)", " (call)", " (teardown)")):
        raise PermissionError("An active pytest process fixture is required")
    if not approved:
        raise PermissionError("The runner must provide its exact pytest temporary root")
    base, root = Path(approved), Path(value)
    try:
        valid = (
            base.is_absolute()
            and root.is_absolute()
            and base.resolve(strict=True) == base
            and root.resolve(strict=True) == root
            and base.is_dir()
            and root.is_dir()
            and root != base
            and root.is_relative_to(base)
        )
    except (OSError, RuntimeError):
        valid = False
    if not valid:
        raise PermissionError("The process fixture must be a real child of the pytest temporary root")
    return root


def database_socket() -> tuple[str, int]:
    """Permit only the runner's explicit literal-loopback PostgreSQL test endpoint."""
    if any(os.environ.get(name) for name in ("PGHOSTADDR", "PGSERVICE")):
        raise PermissionError("PostgreSQL host-address and service overrides are not authorized")
    try:
        url = urlsplit(os.environ.get("DATABASE_URL", ""))
        valid = (
            url.scheme == "postgresql+psycopg"
            and url.hostname in {"127.0.0.1", "::1"}
            and url.port is not None
            and 1 <= url.port <= 65535
            and re.fullmatch(r"/w1a_[A-Za-z0-9_]+", url.path) is not None
            and not url.query
            and not url.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise PermissionError("An explicit loopback w1a_ PostgreSQL test database is required")
    assert url.hostname is not None and url.port is not None
    return url.hostname, url.port


def matches_endpoint(host: object, port: object, endpoint: tuple[str, int]) -> bool:
    """DNS callers may use ASCII bytes and decimal service strings for the same socket."""
    return host in (endpoint[0], endpoint[0].encode("ascii")) and port in (
        endpoint[1], str(endpoint[1])
    )
