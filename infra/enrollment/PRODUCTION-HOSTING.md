# Production practice hosting (docs/IaC only — apply via Codex)

This runbook prepares a **separate** production enrollment foundation and
automatic per-practice allocated workspaces for real practice data. Cloud agents
do **not** apply Azure, publish images, change DNS, enable the worker, or enter
secret values. Apply runs only on the founder’s Mac via the Project store Codex
handoff after the Beta Tester staging pass.

**Cost approval:** **F1 + P1 YES**; **P2 / U1 / U2 held**. Details:
[allocated-workspace/COST.md](allocated-workspace/COST.md). **Stripe stays test
mode** for this pass.

Sign-in and account contracts stay with the signup/enrollment path and draft
[PR #311](https://github.com/CosmaNeura/cosmaneura-os/pull/311) (native sign-in /
account contract). This module does **not** invent Clerk audiences, Stripe
products, or onboarding routes. Production account origins remain:

| Surface | Origin |
| --- | --- |
| Onboarding / returning sign-in | `https://app.cosmas.ai` (`/onboarding`, `/sign-in`) |
| Enrollment API | `https://enrollment-api.cosmas.ai` |
| Clerk | `https://clerk.cosmas.ai`, `pk_live_` |
| Practice web | `https://<practice-uuid>.workspace.cosmas.ai/chief` |
| Practice API | `https://api.<practice-uuid>.workspace.cosmas.ai` |

Native clients that open real-data Boxes require the production realm binding
and a non-empty Clerk token audience (see **#311**). Do not weaken that
contract here.

## What main already has

- Environment table in `src/cosmas_os/enrollment/environments.py` and matching
  Terraform guards in `allocated-workspace/main.tf`.
- Foundation `environment = staging | production` with separate names/tags.
- Hosting worker configuration contract `cosmas-private-hosting.v1` that refuses
  mixed staging/production inputs.
- Allocator-host preparation that never enables the worker.

## Coded gap closed by the companion change

The foundation previously exported only the Vault private DNS zone, while
`HostingConfiguration` and allocated-workspace already required Blob and Redis
zone IDs inside the same enrollment resource group. The foundation now creates
and exports all three shared zones. Production `prepare.py` also pins
`environment` + matching `state_namespace` into `inputs.tfvars.json` so a
reviewed production prepare cannot fall through to staging Terraform defaults.

## Prerequisites

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

## Operator sequence (Codex / founder on Mac — do not run from this agent)

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

## Expected results

- Resource group `rg-cosmabot-enrollment-production-<suffix>` exists with
  `clinical_data=true` (**F1**).
- Foundation export lists vault/blob/redis private DNS zone IDs under that RG.
- Exactly **one** practice Box store set (**P1**) after BAA + worker enable for
  that UUID; **no** second Box.
- Practice runtime `DATA_MODE=authorized_beta` with BAA evidence refs only
  (identifiers, never agreement bodies in env).
- Stripe still test mode; broad production registration still closed.

## Rollback

- **Before apply:** delete the protected bootstrap directory; cost $0.
- **After foundation apply, before workloads:** keep state; open a reviewed
  destroy plan only with founder yes (vault/DB/storage have `prevent_destroy`).
- **After a partial Box apply:** keep custody files and state; do not rotate
  credentials or delete state to retry. At most three retained job attempts per
  `allocated-workspace/README.md`.
- **Never** force-push `main`, weaken CI, or point production workers at
  staging foundations.

## Signup / account contract hooks

Leave these as the enrollment render/API and **#311** already define them:

- Account hosts: `app.cosmas.ai` / `enrollment-api.cosmas.ai` / `clerk.cosmas.ai`.
- Workspace origin policy `practice-uuid-production-v1`.
- Production native requires non-empty Clerk `aud`.
- `ENROLLMENT_DATA_MODE=production` with `production_qualified` is a separate
  gate; this F1+P1 pass keeps Stripe **test** and does not flip live acquisition.
- Confirmation flow after hosting still measures native transport and owner
  binding before card/trial gates.

Do not add new public registration fields that submit a Box URL, proof, or
ready bit.
