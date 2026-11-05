# Production practice hosting (held — docs/IaC only)

This runbook prepares a **separate** production enrollment foundation and
automatic per-practice allocated workspaces for real practice data. It does
**not** authorize apply, image publish, DNS changes, worker enablement, or
secret value entry. Founder cost approval is required first:
[allocated-workspace/COST.md](allocated-workspace/COST.md).

Sign-in and account contracts stay with the signup/enrollment path already on
`main` and any open native/account PRs. This module does **not** invent Clerk
audiences, Stripe products, or onboarding routes. Production account origins
remain:

| Surface | Origin |
| --- | --- |
| Onboarding / returning sign-in | `https://app.cosmas.ai` (`/onboarding`, `/sign-in`) |
| Enrollment API | `https://enrollment-api.cosmas.ai` |
| Clerk | `https://clerk.cosmas.ai`, `pk_live_` |
| Practice web | `https://<practice-uuid>.workspace.cosmas.ai/chief` |
| Practice API | `https://api.<practice-uuid>.workspace.cosmas.ai` |

Native clients that open real-data Boxes require the production realm binding
and a non-empty Clerk token audience (see open PR for native real-data, when
present). Do not weaken that contract here.

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

## Prerequisites (still held)

1. Founder **yes** on every cost line in `COST.md`.
2. Reviewed production Clerk (`clerk.cosmas.ai`, live keys) and Stripe live
   catalog already chosen by the enrollment host — values only in Key Vault.
3. `production_qualified` receipt and matching `production_sha256` before any
   public production registration enablement (`infra/enrollment/render.mjs`).
4. Dedicated private worker host, managed identity, and persistent state root
   per `allocator-host/README.md`.
5. Digest-pinned API and `allocated-workspace-job` images in the **production**
   ACR, with Trivy acceptance — publish is a separate founder-operated step.
6. Cloudflare zone credential for `cosmas.ai` as a protected `0600` file path
   reference only (never in JSON/git).

## Operator sequence (Codex / founder on Mac — do not run from this agent)

Paste-ready steps live in the Project store Codex handoff. Summary:

1. `az login` to the reviewed subscription/tenant.
2. Prepare/plan the **production** foundation under a protected directory
   outside the repo; stop after plan and compare cost lines.
3. Only after founder yes: apply the exact encrypted plan hash; export
   `foundation.json` (must include `blob_private_dns_zone_id` and
   `redis_private_dns_zone_id`).
4. Seed foundation Key Vault secrets **by name** (values from founder local
   files only).
5. Publish reviewed images to `acrcbotenrprd<suffix>.azurecr.io`.
6. Qualify enrollment runtime / database-job separately; keep registration
   closed until `production_qualified`.
7. Materialize allocator-host source; leave `enabled: false` until a held
   acceptance run is approved.
8. DNS CNAMEs for `<uuid>.workspace.cosmas.ai` and
   `api.<uuid>.workspace.cosmas.ai` only after the worker owns those exact
   records.

## Expected results

- Resource group `rg-cosmabot-enrollment-production-<suffix>` exists with
  `clinical_data=true`.
- Foundation export lists vault/blob/redis private DNS zone IDs under that RG.
- No practice Box is created until an owner accepts the BAA and the private
  worker runs with `enabled: true` against production coordinates.
- Practice runtime `DATA_MODE=authorized_beta` with BAA evidence refs only
  (identifiers, never agreement bodies in env).

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

Leave these as the enrollment render/API already define them:

- `ENROLLMENT_DATA_MODE=production` only with `production_qualified` and Stripe
  live mode.
- Workspace origin policy `practice-uuid-production-v1`.
- Confirmation flow after hosting still measures native transport and owner
  binding before card/trial gates.

Do not add new public registration fields that submit a Box URL, proof, or
ready bit.
