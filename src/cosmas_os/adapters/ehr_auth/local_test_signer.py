"""Ephemeral RSA signer for synthetic tests. Keys are never written to disk."""

from __future__ import annotations

import re

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from cosmas_os.ports.key_signer import (
    ALLOWED_JWT_SIGN_ALGORITHMS,
    JwtSignAlgorithm,
)

_KID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_HASH: dict[str, hashes.HashAlgorithm] = {
    "RS256": hashes.SHA256(),
    "RS384": hashes.SHA384(),
}


class LocalTestKeySigner:
    """Generate an in-memory RSA key at construction. Never commit or persist it."""

    def __init__(self, *, kid: str = "local-test-ehr-jwt", key_size: int = 2048) -> None:
        if type(kid) is not str or _KID.fullmatch(kid) is None:
            raise ValueError("kid_invalid")
        if key_size < 2048:
            raise ValueError("key_size_too_small")
        self._kid = kid
        self._private = rsa.generate_private_key(public_exponent=65537, key_size=key_size)

    @property
    def kid(self) -> str:
        return self._kid

    def public_numbers(self) -> tuple[int, int]:
        """Return (n, e) for mock token servers that verify assertions in tests."""
        numbers = self._private.public_key().public_numbers()
        return numbers.n, numbers.e

    def sign(self, *, data: bytes, algorithm: JwtSignAlgorithm = "RS384") -> bytes:
        if type(data) is not bytes or not data:
            raise ValueError("sign_data_required")
        if algorithm not in ALLOWED_JWT_SIGN_ALGORITHMS:
            raise ValueError("sign_algorithm_unsupported")
        digest = hashes.Hash(_HASH[algorithm])
        digest.update(data)
        return self._private.sign(
            digest.finalize(),
            padding.PKCS1v15(),
            Prehashed(_HASH[algorithm]),
        )

    def __repr__(self) -> str:
        return f"LocalTestKeySigner(kid={self._kid!r})"
