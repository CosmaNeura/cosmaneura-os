# Production enrollment hosting

This document covers two founder-operated surfaces that share production
enrollment infrastructure but must not be confused:

1. **Account hosts** — `app.cosmas.ai` / `enrollment-api.cosmas.ai` (signup,
   sign-in, BAA, Checkout). DNS/TLS wiring below.
2. **Practice Boxes** — per-UUID `*.workspace.cosmas.ai` allocated workspaces
   (docs/IaC; apply via Codex after cost yes).

Cloud agents do **not** apply Azure, publish images, change DNS, enable the
worker, or enter secret values. Apply runs only on the founder’s Mac via the
Project store Codex handoffs. **Stripe stays TEST** until an explicit founder
live switch. Public acquisition does not open because DNS exists.

Staging remains in [STAGING-HOSTING.md](STAGING-HOSTING.md). Native sign-in /
account contract: merged
[PR #311](https://github.com/CosmaNeura/cosmaneura-os/pull/311). Flat CosmaBot
pricing (**$300/seat/month**, 14-day trial, card at Checkout) is the enrollment
offer in [#314](https://github.com/CosmaNeura/cosmaneura-os/pull/314) /
`DL-20261105-01`.

## Intended production origins

| Role | Origin |
| --- | --- |
| Account / signup / sign-in | `https://app.cosmas.ai` (`/onboarding`, `/sign-in`) |
| Enrollment API | `https://enrollment-api.cosmas.ai` |
| Clerk frontend API | `https://clerk.cosmas.ai` (`pk_live_` in production) |
| Practice web (per UUID) | `https://<practice_uuid>.workspace.cosmas.ai` (`/chief`) |
| Practice API (per UUID) | `https://api.<practice_uuid>.workspace.cosmas.ai` |

Marketing hosts such as `https://cosmas.ai` are outside this repository. They
must keep the waitlist live until production admission is intentionally open,
then point signup CTAs at `https://app.cosmas.ai/onboarding` (Worker
`SIGNUP_ENABLED=true`). Guessed marketing paths like `/signup` or `/download`
on cosmas.ai are not served by this app.

Native clients that open real-data Boxes require the production realm binding
and a non-empty Clerk token audience (see **#311**). Do not weaken that
contract here.

---

## A. Account hosts — DNS and TLS

Public DNS is published by the founder through the owned DNS provider;
Terraform never changes the DNS zone. This section does **not** invent live
record values.

### Renderer contract

```text
environment: production
app_origin: https://app.cosmas.ai
api_origin: https://enrollment-api.cosmas.ai
```

`render.mjs` refuses other production account origins. Readiness flags
(`activation_available`, `stripe_acquisition_enabled`, `production_qualified`)
stay false until the staged journey receipt and production qualification
receipts exist.

### DNS / TLS steps (founder console)

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

Practice workspace DNS (`*.workspace.cosmas.ai`) follows section B. Reserved
names such as `api.workspace.cosmas.ai` must not be used as a practice.

### Activation gate

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

### Stripe TEST vs live

- Keep `ENROLLMENT_STRIPE_LIVE_MODE=false` and TEST catalog/webhook secrets for
  CosmaBot qualification (one `$300` per-seat price; see
  `docs/STRIPE_TEST_QUALIFICATION.md`).
- Production `data_mode=production` still refuses granting access from TEST
  Stripe state until the founder’s live switch and production receipts exist.
- Do not create or mutate live Stripe products, prices, or webhooks from this
  repository work.

---

## B. Practice Boxes — foundation / allocated workspace (docs/IaC)

This runbook prepares a **separate** production enrollment foundation and
automatic per-practice allocated workspaces for real practice data.

**Cost approval:** **F1 + P1 YES**; **P2 / U1 / U2 held**. Details:
[allocated-workspace/COST.md](allocated-workspace/COST.md). **Stripe stays test
mode** for this pass.

This module does **not** invent Clerk audiences, Stripe products, or
onboarding routes.

### What main already has

- Environment table in `src/cosmas_os/enrollment/environments.py` and matching
  Terraform guards in `allocated-workspace/main.tf`.
- Foundation `environment = staging | production` with separate names/tags.
- Hosting worker configuration contract `cosmas-private-hosting.v1` that refuses
  mixed staging/production inputs.
- Allocator-host preparation that never enables the worker.

### Coded gap closed by the companion change

The foundation previously exported only the Vault private DNS zone, while
`HostingConfiguration` and allocated-workspace already required Blob and Redis
zone IDs inside the same enrollment resource group. The foundation now creates
and exports all three shared zones. Production `prepare.py` also pins
`environment` + matching `state_namespace` into `inputs.tfvars.json` so a
reviewed production prepare cannot fall through to staging Terraform defaults.

### Prerequisites

1. **F1 + P1** founder yes already recorded; **P2 / U1 / U2** still held
   ([COST.md](allocated-workspace/COST.md)).
2. Beta Tester **staging pass** completed (synthetic staging foundation /
   allocation checks) before any production apply.
3. Production Clerk hosts per **#311**; Stripe **test** secret names seeded for
   this pass (live Stripe not approved here).
4. `production_qualified` receipt and matching `production_sha256` before any
   public production registration enablement (`infra/enrollment/render.mjs`) —
   not granted by F1+P1 alone.
5. Dedicated private worker host, managed identity, and persistent state root
   per `allocator-host/README.md`.
6. Digest-pinned API and `allocated-workspace-job` images in the **production**
   ACR, with Trivy acceptance — publish is a separate founder-operated step.
7. Cloudflare zone credential for `cosmas.ai` as a protected `0600` file path
   reference only (never in JSON/git).

### Operator sequence (Codex / founder on Mac — do not run from this agent)

Paste-ready steps: Project store
`docs/codex-handoff-production-hosting.md` (**F1+P1 only**). Summary:

1. Complete Beta Tester staging pass; keep a protected staging-pass receipt.
2. `az login` to the reviewed subscription/tenant.
3. Prepare/plan the **production** foundation (F1); apply the exact encrypted
   plan hash; export `foundation.json` (must include `blob_private_dns_zone_id`
   and `redis_private_dns_zone_id`).
4. Seed foundation Key Vault secrets **by name** (Stripe **test** values).
5. Publish minimum reviewed images to `acrcbotenrprd<suffix>.azurecr.io`.
6. Keep registration/acquisition closed; Stripe test mode.
7. Materialize allocator-host source; enable worker only for **one** P1 Box.
8. DNS CNAMEs for that one `<uuid>.workspace.cosmas.ai` pair only.
9. **Stop.** Do not allocate a second Box (P2) or other unapproved spend.

### Expected results

- Resource group `rg-cosmabot-enrollment-production-<suffix>` exists with
  `clinical_data=true` (**F1**).
- Foundation export lists vault/blob/redis private DNS zone IDs under that RG.
- Exactly **one** practice Box store set (**P1**) after BAA + worker enable for
  that UUID; **no** second Box.
- Practice runtime `DATA_MODE=authorized_beta` with BAA evidence refs only
  (identifiers, never agreement bodies in env).
- Stripe still test mode; broad production registration still closed.

### Rollback

- **Before apply:** delete the protected bootstrap directory; cost $0.
- **After foundation apply, before workloads:** keep state; open a reviewed
  destroy plan only with founder yes (vault/DB/storage have `prevent_destroy`).
- **After a partial Box apply:** keep custody files and state; do not rotate
  credentials or delete state to retry. At most three retained job attempts per
  `allocated-workspace/README.md`.
- **Never** force-push `main`, weaken CI, or point production workers at
  staging foundations.

### Signup / account contract hooks

Leave these as the enrollment render/API and **#311** already define them:

- Account hosts: `app.cosmas.ai` / `enrollment-api.cosmas.ai` / `clerk.cosmas.ai`
  (section A).
- Workspace origin policy `practice-uuid-production-v1`.
- Production native requires non-empty Clerk `aud`.
- `ENROLLMENT_DATA_MODE=production` with `production_qualified` is a separate
  gate; this F1+P1 pass keeps Stripe **test** and does not flip live acquisition.
- Confirmation flow after hosting still measures native transport and owner
  binding before card/trial gates.

Do not add new public registration fields that submit a Box URL, proof, or
ready bit.

## Related docs

- `docs/STRIPE_TEST_QUALIFICATION.md`
- `docs/STAGING_ONBOARDING_DELIVERY.md`
- `docs/ONBOARDING_IMPLEMENTATION.md`
- `infra/enrollment/STAGING-HOSTING.md`
- `infra/enrollment/README.md`
- `infra/enrollment/allocated-workspace/COST.md`
