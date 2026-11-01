"""Port for asymmetric signing used by SMART backend-services JWT assertions.

Implementations must never log private key material. The Key Vault signer keeps
the private key inside the vault and only returns signatures. The local test
signer holds an ephemeral in-memory key for synthetic tests only.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

JwtSignAlgorithm = Literal["RS384", "RS256"]

ALLOWED_JWT_SIGN_ALGORITHMS: frozenset[str] = frozenset({"RS384", "RS256"})
DEFAULT_JWT_SIGN_ALGORITHM: JwtSignAlgorithm = "RS384"


@runtime_checkable
class KeySigner(Protocol):
    """Sign opaque bytes for a JWT assertion. Never return or log private keys."""

    @property
    def kid(self) -> str:
        """Key id placed in the JWT header ``kid`` field."""
        ...

    def sign(self, *, data: bytes, algorithm: JwtSignAlgorithm = "RS384") -> bytes:
        """Return the raw signature bytes for ``data`` using ``algorithm``."""
        ...
