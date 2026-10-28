"""Bounded public-key fetch for the explicitly selected standalone Clerk issuer."""

import json
from time import monotonic

import httpx
import jwt

from cosmas_os.config import Settings


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key field")
        value[key] = item
    return value


class StandaloneClerkKeys:
    """Only the reviewed JWKS URL; no redirect, proxy, fallback or private key."""

    def __init__(self, runtime: Settings):
        runtime.validate_runtime_configuration()
        if runtime.cosmas_env != "standalone_clerk_synthetic":
            raise RuntimeError("Standalone Clerk key transport requires its explicit profile")
        url = runtime.clerk_jwks_url
        if not url:
            raise RuntimeError("Standalone Clerk JWKS URL is required")
        self._url = url

    def get_signing_keys(self, *, refresh: bool = False):
        try:
            body = bytearray()
            deadline = monotonic() + 5.0
            with httpx.Client(timeout=5.0, follow_redirects=False, trust_env=False) as client:
                with client.stream("GET", self._url, headers={
                        "Accept": "application/json", "Accept-Encoding": "identity"}) as response:
                    if (response.status_code != 200
                            or response.headers.get("content-encoding", "identity") != "identity"
                            or monotonic() >= deadline):
                        raise ValueError("key response unavailable")
                    # Inspect each raw network chunk. A slow trickle cannot hide
                    # behind an 8 KiB iterator buffer and renew the read timeout.
                    for chunk in response.iter_raw():
                        if monotonic() >= deadline or len(body) + len(chunk) > 65536:
                            raise ValueError("key response too large")
                        body.extend(chunk)
            value = json.loads(body, object_pairs_hook=_unique)
            keys = value.get("keys") if isinstance(value, dict) else None
            if not isinstance(keys, list) or not 1 <= len(keys) <= 128:
                raise ValueError("invalid public key set")
            seen = set()
            for key in keys:
                if (not isinstance(key, dict) or key.get("kty") != "RSA"
                        or key.get("alg") not in {None, "RS256"} or key.get("use") not in {None, "sig"}
                        or not isinstance(key.get("kid"), str) or not 1 <= len(key["kid"]) <= 255
                        or key["kid"] in seen or {"d", "p", "q", "dp", "dq", "qi", "oth", "k"}.intersection(key)):
                    raise ValueError("invalid public signing key")
                seen.add(key["kid"])
            parsed = jwt.PyJWKSet.from_dict(value).keys
            if len(parsed) != len(keys) or any(key.key.key_size < 2048 for key in parsed):
                raise ValueError("public signing key is too small")
            return parsed
        except (httpx.HTTPError, jwt.PyJWTError, ValueError, TypeError, AttributeError) as exc:
            raise jwt.PyJWKClientError("Standalone Clerk public keys are unavailable") from exc
