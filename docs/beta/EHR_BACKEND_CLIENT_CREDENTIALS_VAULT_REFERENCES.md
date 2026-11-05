# EHR backend client-credentials — Azure Key Vault references John must create

Sandbox / synthetic only. No live connector uses these yet. Nothing is
deployed by the C2 code ticket. John creates the Key Vault secrets himself for
the athena Developer Portal app **Cosmaneura CosmaBot FHIR** and never pastes
client secrets or access tokens into chat, email, PRs, or the repository.

## Naming rule (reuse Codex; do not invent a scheme)

Credential references use the existing managed-secret namespace:

```text
COSMAS_MANAGED_SECRET_[A-Z][A-Z0-9_]{0,63}
```

The environment variable name is the reference. Values are supplied by the host
secret manager / Key Vault binding at deploy time. Source, docs, and examples
list names only — never secret VALUES.

## Vault secrets for athena 2-legged client-credentials

| Reference name | What John creates in Key Vault | Notes |
| --- | --- | --- |
| `COSMAS_MANAGED_SECRET_EHR_ATHENA_FHIR_CLIENT_ID` | Secret holding the athena app **client id** for Cosmaneura CosmaBot FHIR | Preview / sandbox app. |
| `COSMAS_MANAGED_SECRET_EHR_ATHENA_FHIR_CLIENT_SECRET` | Secret holding the athena app **client secret** | Private. Never paste into chat or git. |

## Token handling

- Grant: `client_credentials`
- Scopes: exact `system/<Resource>.read` only (no wildcards, no write)
- Access token cache: process memory only; refresh **60 seconds** before expiry
- Never write the access token or client secret to disk, Postgres, logs, responses, or devices

## Signed-key / JWT client assertion

Not part of this ticket. A later ticket may add private_key_jwt / JWKS. Until
then CosmaBot does not sign JWT client assertions for EHR auth.

## Used by

- C2 token client (`adapters.ehr_auth`)
- C7 athena Certified FHIR R4 Preview adapter (`adapters.athena_fhir_r4`) —
  mock transport only; no live Preview call in CI; route wiring is C8

## What this code will not do

- Call live athena or live Azure from CI
- Commit or print secret VALUES
- Enable production origins or real practice data
