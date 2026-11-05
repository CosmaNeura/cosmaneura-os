# Production account hosting (DNS and TLS wiring)

This source owns production CosmaBot account hosts
`app.cosmas.ai` and `enrollment-api.cosmas.ai`, separate from practice
workspaces under `*.workspace.cosmas.ai`. Public DNS is published by the
founder/operator through the owned DNS provider; Terraform never changes the
DNS zone. This document does **not** invent live DNS records or flip
acquisition. Stripe remains **TEST** until an explicit founder live switch.

Staging remains documented in [STAGING-HOSTING.md](STAGING-HOSTING.md). Native
sign-in prerequisites stay in the Codex handoff for the sign-in contract.

## Intended production origins

| Role | Origin |
| --- | --- |
| Account / signup / sign-in | `https://app.cosmas.ai` |
| Enrollment API | `https://enrollment-api.cosmas.ai` |
| Clerk frontend API | `https://clerk.cosmas.ai` |
| Practice web (per UUID) | `https://<practice_uuid>.workspace.cosmas.ai` |
| Practice API (per UUID) | `https://api.<practice_uuid>.workspace.cosmas.ai` |

Account paths on the account host:

- `/onboarding` — new practice signup
- `/sign-in` — returning CosmaBot account
- `/` — account-only builds route into account setup

Marketing hosts such as `https://cosmas.ai` are outside this repository. They
must point their signup/download CTAs at `https://app.cosmas.ai/onboarding` (and
documented Mac/iPhone download URLs once published). Guessed marketing paths
like `/signup` or `/download` on cosmas.ai are not served by this app.

## Renderer contract

Production manifests use:

```text
environment: production
app_origin: https://app.cosmas.ai
api_origin: https://enrollment-api.cosmas.ai
```

`render.mjs` refuses other production account origins. Readiness flags
(`activation_available`, `stripe_acquisition_enabled`, `production_qualified`)
stay false until the staged journey receipt and production qualification
receipts exist. Wiring DNS alone does not open trial activation.

## DNS / TLS steps (founder console)

Mirror the staging two-step pattern without inventing Azure suffix values:

1. Deploy production enrollment apps with custom domains **unbound**.
2. Export the actual CNAME and `asuid` TXT values from the protected runtime
   output (same shape as staging: account + API).
3. Publish exact records at the owned DNS provider for:
   - `app.cosmas.ai` (+ `asuid.app.cosmas.ai`)
   - `enrollment-api.cosmas.ai` (+ `asuid.enrollment-api.cosmas.ai`)
4. Re-apply with custom-domain binding enabled only after authoritative
   resolution matches those exported values.
5. Confirm managed TLS before any acquisition flag flip.

Practice workspace DNS (`*.workspace.cosmas.ai`) is separate and follows the
allocated-workspace / production practice hosting path. Reserved names such as
`api.workspace.cosmas.ai` must not be used as a practice.

## Activation gate (why staging can still show false)

Public `activation_available` becomes true only when **all** of the following
hold at runtime:

1. `ENROLLMENT_ACTIVATION_AVAILABLE=true`
2. `ENROLLMENT_PROVISIONING_ENABLED=true`
3. `ENROLLMENT_STRIPE_ACQUISITION_ENABLED=true`
4. Registration admission has no blockers
5. Stripe catalog/portal/webhook verify (TEST mode until founder live switch)
6. Workspace confirmer is configured

The public config also returns `activation_blockers` listing which gate is
still closed. Staging intentionally keeps acquisition/activation false under
the Development intake preflight; the full `journey_sha256` receipt is required
before those readiness flags may be true in the renderer.

## Stripe TEST vs live

- Keep `ENROLLMENT_STRIPE_LIVE_MODE=false` and TEST catalog/webhook secrets for
  all CosmaBot qualification work in this milestone.
- Production `data_mode=production` still refuses granting access from TEST
  Stripe state until the founder’s live switch and production receipts exist.
- Do not create or mutate live Stripe products, prices, or webhooks from this
  repository work.

## Related docs

- `docs/STRIPE_TEST_QUALIFICATION.md`
- `docs/STAGING_ONBOARDING_DELIVERY.md`
- `docs/ONBOARDING_IMPLEMENTATION.md`
- `infra/enrollment/STAGING-HOSTING.md`
- `infra/enrollment/README.md`
