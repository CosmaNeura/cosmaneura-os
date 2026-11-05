# Cost lines — production practice hosting (held)

**Status:** documentation and IaC only. No Azure resource in this table has been
applied by this change. The founder must approve every billable line before any
`tofu apply`, image publish, DNS write, or worker enablement.

Prices are public Azure PAYG metadata estimates for **Central US**, **730
hours/month**, checked against the October 31, 2026 enrollment review and the
Managed Redis retail page. They are **not** a quote, reservation price, or
invoice. Taxes, egress, query overage, and shared Consumption free grants are
extra. Re-check retail prices on the apply day.

## Shared production enrollment foundation (one per environment)

Created by `infra/enrollment/foundation` with `environment = "production"`.
Staging uses the same SKUs under separate names and is unchanged by a production
apply.

| Resource | Size / SKU | Est. monthly | Notes |
| --- | --- | ---: | --- |
| PostgreSQL Flexible Server | `B_Standard_B1ms`, 32 GiB, 7-day backup, no HA/geo | ~$18.18 | Central enrollment registry only |
| Log Analytics | PerGB2018, 0.1 GiB/day cap, 30-day retention | ~$2.76 | Cap can truncate; not a retention promise |
| Container Registry | Basic | ~$5.00 | Code images only; no secrets in layers |
| Key Vault | Standard, private endpoint | ~$0.03 + ops | Operations billed separately |
| Storage account (state) | Standard LRS + versioning | ~$0.50–2.00 | Depends on state/plan size |
| Private DNS zones (3) | vault + blob + redis privatelink | ~$1.50 | ~$0.50/zone; queries extra |
| Private endpoint (vault) | 1 endpoint | ~$7.30 | ~$0.01/hour |
| Container Apps environment | Consumption profile only | $0 idle | Workload usage billed under apps/jobs |
| **Foundation subtotal** | | **~$32.55–35** | Matches foundation README revised estimate |

## Per allocated practice workspace (one paying practice = one Box)

Created by `infra/enrollment/allocated-workspace` after a registered practice
accepts the BAA. Production keeps **35-day** PostgreSQL backups; staging keeps 7.

| Resource | Size / SKU | Est. monthly | Notes |
| --- | --- | ---: | --- |
| PostgreSQL Flexible Server | `B_Standard_B1ms`, 32 GiB, 35-day PITR, no HA/geo | ~$22–25 | Higher than staging because of 35-day backup retention |
| Azure Managed Redis | `Balanced_B0`, HA (2 nodes), TLS, NoCluster | ~$26.28 | Retail Central US; East US 2 ~$23.36 |
| Storage account (Box artifacts + hosting receipts) | Standard LRS, private, versioning | ~$1–3 | Depends on artifact volume |
| Key Vault (Box) | Standard, private endpoint, purge protection | ~$0.03 + ops | Secrets named below; values never in git |
| Private endpoints (3) | vault + blob + redis | ~$21.90 | 3 × ~$7.30 |
| Private DNS zone (Postgres) | one per practice FQDN zone | ~$0.50 | Zone owned by the Box module |
| Container Apps (API + worker) | Consumption, 0.5 CPU / 1 GiB each, max 1 replica | usage | Idle near $0; active traffic extra |
| Container App (web) | Consumption, 0.25 CPU / 0.5 GiB, max 1 replica | usage | Static enrollment web image |
| Manual jobs (migrate / reserve) | Consumption jobs | usage | Short-lived; not a standing cost |
| **Per-practice store subtotal (fixed)** | | **~$72–78** | Before Consumption/traffic |

## Combined example (founder yes required)

| Bundle | Resources | Est. monthly |
| --- | --- | ---: |
| Production foundation alone | table above | ~$33–35 |
| Foundation + **1** practice Box | foundation + one allocated workspace | ~$105–113 |
| Foundation + **2** practice Boxes | foundation + two Boxes | ~$177–191 |

Container Apps Consumption, Blob transactions, Key Vault operations, DNS
queries, egress, Cloudflare, Clerk, Stripe, and model inference are **not** in
the fixed subtotals.

## Key Vault secret **names** (values entered by founder only)

Never put values in git, PRs, chat, or Codex prompts. Seed through the existing
ARM `seed_secret.py` path or the Box seed helpers after foundation/Box apply.

### Enrollment foundation vault (`kv-cbot-enr-prd-<suffix>`)

| Secret name | Purpose |
| --- | --- |
| `enrollment-bootstrap-database-url` | Bootstrap role URL (held; not granted to API) |
| `enrollment-migration-database-url` | Migrator role URL |
| `enrollment-database-url` | Runtime role URL |
| `enrollment-clerk-secret-key` | Production Clerk backend key (`sk_live_…`) |
| `enrollment-invitation-secret` | Invitation signing key |
| `enrollment-runtime-admission-secret` | Runtime admission master |
| `enrollment-stripe-secret-key` | Stripe live secret |
| `enrollment-stripe-webhook-secret` | Stripe webhook signing secret |

### Per-practice Box vault (`kvca<practice-uuid-prefix>`)

| Secret name | Purpose |
| --- | --- |
| `database-url` | Box runtime DB |
| `database-admin-url` | Migration/reservation only |
| `redis-url` | Managed Redis URL |
| `enrollment-admission-key` | Practice-bound admission key |
| `owner-manifest` | First-owner reservation manifest |
| `google-connection-client-secret` | Optional Google broker |
| `google-connection-encryption-key` | Optional Google token custody |
| `workspace-llm-api-key` | Optional reviewed GPT-4.1 key |

## Rollback cost note

Destroying a production Box is intentionally hard (`prevent_destroy` on
storage, vault, database). Partial failures keep resources; do not delete state
to “retry.” Stopping before apply costs $0. Stopping after foundation apply
leaves the foundation bill until a reviewed destroy plan (separate founder yes).
