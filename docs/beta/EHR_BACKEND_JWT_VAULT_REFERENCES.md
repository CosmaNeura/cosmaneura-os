# EHR backend JWT — Azure Key Vault references John must create

Sandbox / synthetic only. No live connector uses these yet. Nothing is
deployed by the C2 code ticket. John creates the Key Vault objects himself and
never pastes private key material, client secrets, or access tokens into chat,
email, PRs, or the repository.

## Naming rule (reuse Codex; do not invent a scheme)

Credential and key references use the existing managed-secret namespace:

```text
COSMAS_MANAGED_SECRET_[A-Z][A-Z0-9_]{0,63}
```

The environment variable name is the reference. Values are supplied by the host
secret manager / Key Vault binding at deploy time. Source, docs, and examples
list names only — never secret VALUES.

## Vault objects for athena SMART backend services (2-legged / backend_jwt)

| Reference name | What John creates in Key Vault | Notes |
| --- | --- | --- |
| `COSMAS_MANAGED_SECRET_EHR_ATHENA_CLIENT_ID` | Secret holding the athena Developer Portal **client id** (Preview 2-legged app) | Not a private key. Still managed through the same reference pattern. |
| `COSMAS_MANAGED_SECRET_EHR_ATHENA_JWT_KID` | Secret holding the public key id (`kid`) registered with athena | Matches the JWT header `kid`. |
| `COSMAS_MANAGED_SECRET_EHR_ATHENA_JWT_KEY` | **Key Vault Key** (RSA, sign/verify) used for remote RS384 signing | Private key material must never leave the vault. CosmaBot signs via Key Vault cryptography APIs only. Register the matching public key / JWKS with athena. |

Optional later vendors follow the same pattern, for example
`COSMAS_MANAGED_SECRET_EHR_<VENDOR>_JWT_KEY`. Do not create them until that
vendor's connector ticket asks for them.

## Algorithms

- Preferred: **RS384**
- Allowed: **RS256**
- Assertion lifetime: at most **5 minutes**
- Access token cache: process memory only, refresh **60 seconds** before expiry

## What this code will not do

- Call live athena or live Azure from CI
- Write access tokens to disk, Postgres, logs, HTTP responses, or devices
- Commit local test keys (those exist only in memory during tests)
- Enable production origins or real practice data
