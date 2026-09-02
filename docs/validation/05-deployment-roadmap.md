# 05 — Deployment roadmap and parametric cost

Date: 2026-09-02  
No IaC created in Phase 0. Exact SaaS price/tiers remain open.

## Stages

| Stage | Authorization | Contents |
|---|---|---|
| D0 Local synth | `APPROVE LOCAL SYNTH BUILD` | Compose, fake adapters, zero cloud |
| D1 Synthetic CI | Separate CI enablement | Pinned image digest, ephemeral DB tests, release manifest, no auto-deploy |
| D2 Optional non-PHI Azure | Separate owner decision | OS-named RG only; synthetic data; human deploy |
| D3 Isolated early-adopter beta | Separate deployment approval | Dedicated Box, Clerk Org, BAA, human deploy, L0 ports |
| D4 One-clinic L0 pilot | After D3 gate | Measure readiness KPIs; no EHR write required |
| D5 Connector rungs | Per-adapter gates | Schedule/Record/Notify climb independently |
| D6 Track A integration | After Track A IAM gate | Versioned HTTPS/OpenAPI or MCP; no shared DB/SP |

## Local synth (only stage in first mandate)

- Docker Compose: API, worker, Postgres, Redis (Mailpit optional; fake NotifyPort sufficient)
- Local BlobPort filesystem volume
- Seed command for invented Org/Box
- CI later: ruff/pyright/pytest/migration/E2E/fixture-scan; fail if skipped

## Container Apps vs App Service (later beta)

| Evidence | Result |
|---|---|
| Master/scribe infra | Azure Container Apps |
| PDF §15/§18 | ACA or App Service; “match master” |
| Recommendation | **Container Apps** for OS beta to match Track A ops skill and scale-to-zero option |

App Service remains an alternative only if a later owner constraint appears; not preferred.

## Logical Box vs physical packing

One logical Box ≠ permanently dedicated full Azure stack forever.

| Packing | Isolation | When |
|---|---|---|
| Dedicated DB + storage prefix + workloads per Box | Strongest | First early adopter |
| Shared platform, exclusive schema/DB + `box_id` on shared edges | Lower unit cost | After isolation design decision |
| Shared multi-Org DB rows | Deferred | Requires new architecture decision |

## Parametric cost model (no Azure credits, USD approx.)

Assumptions (disclose as assumptions, not quotes):

- Consumption Container Apps active rates ~`$0.000024`/vCPU-s and ~`$0.000003`/GiB-s (public secondary summaries of Azure pricing; confirm in calculator before purchase).
- Always-on small API+worker: ~0.5–1.0 vCPU and 1–2 GiB combined → order **~$40–120/mo** compute before free grants.
- Azure Database for PostgreSQL Flexible Server burstable / small: order **~$25–80/mo** for one small instance (region/SKU dependent — mark **UNKNOWN exact** without calculator).
- Redis: Azure Cache basic **~$15–40/mo** or Container Apps-sidecar Redis for tiny beta (**trade reliability**).
- Blob + Key Vault + Log Analytics: order **~$5–30/mo** at low volume.
- Clerk: existing plan reuse or development instance — **UNKNOWN** until chosen.
- Support: founder-led early beta ≈ **0.1–0.3 FTE**; retail support later must be priced into SaaS.

### Per-Box monthly infra ranges (illustrative)

| Scenario | Compute | Data | Observability/misc | Infra subtotal |
|---|---|---|---|---|
| Dedicated small beta Box | $40–120 | $30–100 | $10–40 | **~$80–260** |
| Shared platform, 5 Boxes (amortized) | $60–150 total | $50–120 total | $20–50 | **~$26–64 / Box** |
| Scale-to-zero API, always-on worker minimal | lower bound shrinks | DB still dominates | — | DB-bound |

Credits ($100k Track A, expire Jan 2027) **must not** define architecture (INV-9 / D economics).

### Break-even combinations (parametric; no final price)

Let `P` = flat monthly price per Box (or per practice SKU), `C` = infra+support allocated cost per Box, `N` = paying Boxes.

Contribution-positive when `P > C`. Examples:

| Assumed C | Break-even P | Notes |
|---|---|---|
| $100 dedicated | P > $100 | One-clinic beta barely covers infra alone |
| $40 shared packing | P > $40 | Leaves room for support if P in mid hundreds |
| $200 fully loaded support | P > $200 | Realistic if founder time counted |

Track A $60/seat scribe SKU is a **different product**; OS flat SaaS packaging remains open. Do not force OS price = $60.

## Connector and Track A notes

- L0 pilot does not require Athena certification.
- Patient email/A2P each need capability manifests before enablement.
- Track A integration waits for INV-6-class IAM hygiene; OS stays usable offline.

## Deployment kill signals

Cost model only works with credits; shared packing proposed without tenant enforcement; coding agents given live PHI/credentials; beta requires full EHR write to demo value.
