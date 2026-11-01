"""Sandbox-only base URL gate for the shared FHIR read client.

Production and ambiguous hosts are refused unless ``allow_production`` is
explicitly set True by a later, separately activated qualification path. The
default stays sandbox-only so this package cannot reach live patient systems.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# Host markers that identify synthetic / sandbox FHIR bases.
_SANDBOX_MARKERS = (
    "sandbox",
    "synthetic",
    "mock",
    "localhost",
    "127.0.0.1",
    ".invalid",
    "example.com",
    "example.org",
    "test.",
)

# Host markers that identify production / live FHIR bases.
_PRODUCTION_MARKERS = (
    "prd.",
    ".prd.",
    "-prd.",
    "prod.",
    ".prod.",
    "-prod.",
    "production",
    "live.",
    ".live.",
)


def _hostname(value: str) -> str | None:
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.username or parts.password or parts.query or parts.fragment:
        return None
    host = parts.hostname
    if host is None or not host:
        return None
    if parts.scheme == "https":
        if parts.port not in (None, 443):
            return None
        return host.lower()
    if parts.scheme == "http" and host.lower() in {"localhost", "127.0.0.1"}:
        if parts.port not in (None, 80) and not (1024 <= (parts.port or 0) <= 65535):
            return None
        return host.lower()
    return None


def is_production_base_url(base_url: str) -> bool:
    host = _hostname(base_url)
    if host is None:
        return False
    return any(marker in host for marker in _PRODUCTION_MARKERS)


def is_sandbox_base_url(base_url: str) -> bool:
    host = _hostname(base_url)
    if host is None:
        return False
    if is_production_base_url(base_url):
        return False
    return any(marker in host for marker in _SANDBOX_MARKERS)


def assert_allowed_base_url(base_url: str, *, allow_production: bool = False) -> str:
    """Normalize and accept a FHIR base URL, or raise ValueError."""
    if type(base_url) is not str or not base_url.isascii() or any(c in base_url for c in " \t\r\n\\"):
        raise ValueError("fhir_base_url_invalid")
    host = _hostname(base_url)
    if host is None:
        raise ValueError("fhir_base_url_invalid")
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if any(part in {".", ".."} for part in path.split("/")):
        raise ValueError("fhir_base_url_invalid")
    normalized = f"{parts.scheme}://{parts.netloc}{path}"
    if is_sandbox_base_url(normalized):
        return normalized
    if allow_production is True and is_production_base_url(normalized):
        return normalized
    if allow_production is True and host is not None:
        # Explicit production opt-in still refuses clearly malformed hosts only;
        # non-sandbox hosts without production markers stay refused until named.
        raise ValueError("fhir_base_url_not_sandbox")
    if is_production_base_url(normalized):
        raise ValueError("fhir_base_url_production_refused")
    raise ValueError("fhir_base_url_not_sandbox")


def same_origin(base_url: str, candidate: str) -> bool:
    """True when a Bundle next link stays on the accepted FHIR base origin+path prefix."""
    try:
        base = urlsplit(base_url)
        other = urlsplit(candidate)
    except ValueError:
        return False
    if (base.scheme, base.netloc) != (other.scheme, other.netloc):
        return False
    if other.username or other.password or other.fragment:
        return False
    prefix = base.path.rstrip("/")
    path = other.path
    return path == prefix or path.startswith(prefix + "/")
