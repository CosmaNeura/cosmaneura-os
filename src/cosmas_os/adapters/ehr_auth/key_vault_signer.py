"""Key Vault remote signer configured only by ``COSMAS_MANAGED_SECRET_*`` name.

The private key never leaves Azure Key Vault. This adapter holds the managed
secret reference name and a remote digest-signer client (typically Azure Key
Vault ``CryptographyClient``). No secret VALUES are stored in code, env dumps
written by this module, or logs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cryptography.hazmat.primitives import hashes

from cosmas_os.ports.key_signer import (
    ALLOWED_JWT_SIGN_ALGORITHMS,
    JwtSignAlgorithm,
)

# Same closed pattern Codex uses for managed secret references.
MANAGED_SECRET_REFERENCE_PATTERN = re.compile(
    r"^COSMAS_MANAGED_SECRET_[A-Z][A-Z0-9_]{0,63}$"
)

_KID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_HASH: dict[str, hashes.HashAlgorithm] = {
    "RS256": hashes.SHA256(),
    "RS384": hashes.SHA384(),
}

# Azure Key Vault SignatureAlgorithm string values used by CryptographyClient.
_VAULT_ALG: dict[str, str] = {
    "RS256": "RS256",
    "RS384": "RS384",
}


def validate_managed_secret_reference_name(name: str) -> str:
    """Accept only Codex-style ``COSMAS_MANAGED_SECRET_*`` reference names."""
    if type(name) is not str or MANAGED_SECRET_REFERENCE_PATTERN.fullmatch(name) is None:
        raise ValueError("managed_secret_reference_invalid")
    return name


@runtime_checkable
class RemoteDigestSigner(Protocol):
    """Sign a precomputed digest inside Key Vault (or a test double).

    Implementations must not accept or return private key material.
    """

    def sign_digest(self, *, algorithm: str, digest: bytes) -> bytes:
        """Return the signature for ``digest`` using vault algorithm name."""
        ...


@dataclass(frozen=True, slots=True)
class ManagedSecretKeyReference:
    """Vault key identity expressed only as a managed-secret reference name."""

    reference_name: str
    kid: str

    def __post_init__(self) -> None:
        validate_managed_secret_reference_name(self.reference_name)
        if type(self.kid) is not str or _KID.fullmatch(self.kid) is None:
            raise ValueError("kid_invalid")


class KeyVaultRemoteKeySigner:
    """RS384/RS256 signer that never loads a private key into process memory.

    ``reference`` names the Key Vault key John must create. ``remote`` performs
    the vault ``sign`` operation (injected so CI never calls live Azure).
    """

    def __init__(
        self,
        *,
        reference: ManagedSecretKeyReference,
        remote: RemoteDigestSigner,
    ) -> None:
        if type(reference) is not ManagedSecretKeyReference:
            raise ValueError("managed_secret_key_reference_required")
        if not isinstance(remote, RemoteDigestSigner):
            raise ValueError("remote_digest_signer_required")
        self._reference = reference
        self._remote = remote

    @property
    def kid(self) -> str:
        return self._reference.kid

    @property
    def reference_name(self) -> str:
        return self._reference.reference_name

    def sign(self, *, data: bytes, algorithm: JwtSignAlgorithm = "RS384") -> bytes:
        if type(data) is not bytes or not data:
            raise ValueError("sign_data_required")
        if algorithm not in ALLOWED_JWT_SIGN_ALGORITHMS:
            raise ValueError("sign_algorithm_unsupported")
        digest = hashes.Hash(_HASH[algorithm])
        digest.update(data)
        signature = self._remote.sign_digest(
            algorithm=_VAULT_ALG[algorithm],
            digest=digest.finalize(),
        )
        if type(signature) is not bytes or not signature:
            raise ValueError("remote_signature_invalid")
        return signature

    def __repr__(self) -> str:
        return (
            "KeyVaultRemoteKeySigner("
            f"reference_name={self._reference.reference_name!r}, "
            f"kid={self._reference.kid!r})"
        )
