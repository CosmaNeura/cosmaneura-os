"""Resolve ``COSMAS_MANAGED_SECRET_*`` references from the process environment.

Values are expected to arrive from Azure Key Vault (or a synthetic test
binding). This module never logs secret VALUES and never writes them to disk.
"""

from __future__ import annotations

import os
import re

from pydantic import SecretStr

# Same closed pattern Codex uses for managed secret references.
MANAGED_SECRET_REFERENCE_PATTERN = re.compile(
    r"^COSMAS_MANAGED_SECRET_[A-Z][A-Z0-9_]{0,63}$"
)

# Athena FHIR Preview app "Cosmaneura CosmaBot FHIR" — names only; John creates
# the vault secrets. Never put VALUES in source, tests as committed literals of
# real credentials, PR text, or logs.
ATHENA_FHIR_CLIENT_ID_REF = "COSMAS_MANAGED_SECRET_EHR_ATHENA_FHIR_CLIENT_ID"
ATHENA_FHIR_CLIENT_SECRET_REF = "COSMAS_MANAGED_SECRET_EHR_ATHENA_FHIR_CLIENT_SECRET"


def validate_managed_secret_reference_name(name: str) -> str:
    if type(name) is not str or MANAGED_SECRET_REFERENCE_PATTERN.fullmatch(name) is None:
        raise ValueError("managed_secret_reference_invalid")
    return name


class ManagedSecretEnvResolver:
    """C1 ``SecretResolver``: read a managed-secret env binding by reference name."""

    def resolve(self, *, name: str) -> str:
        validate_managed_secret_reference_name(name)
        value = os.environ.get(name)
        if type(value) is not str or not value:
            raise LookupError("managed_secret_missing")
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("managed_secret_invalid")
        return value

    def resolve_secret(self, *, name: str) -> SecretStr:
        return SecretStr(self.resolve(name=name))

    def __repr__(self) -> str:
        return "ManagedSecretEnvResolver()"
