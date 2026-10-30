# 00 — Source inventory and current evidence

Date: 2026-09-02  
Workspace: `~/Desktop/cosmaneura-os`  
Git: not initialized (documentation-only handoff)  
Host: Python 3.14.7 available; Node v22.23.2; uv present; Docker 29.7.2 present

## Handoff files present

| Path | Role | Read |
|---|---|---|
| `AGENTS.md` | Phase 0 write gate and invariants | yes |
| `CANONICAL_PRODUCT_DECISIONS.md` | Locked rulings 1.9-draft | yes |
| `CURSOR_MASTER_PROMPT.md` | Full mandate | yes |
| `README.md` | Bootstrap | yes |
| `docs/CANONICAL_ARCHITECTURE_CONTRACT.md` | Proposed contract | yes |
| `docs/DECISION_LOG.md` | DL-20260902-01…04 | yes |
| `docs/VALIDATION_PROTOCOL.md` | Phase 0 protocol | yes |
| `docs/BUILD_AND_DEPLOYMENT_ROADMAP.md` | Creation/deployment plan | yes |
| `docs/PRIOR_FEASIBILITY_REVIEW.md` | Prior review | yes |
| `docs/SOURCE_RECONCILIATION.md` | Provenance + R-001…R-008 | yes |
| `spec/canonical_contract.json` | Machine summary | yes |
| `.cursor/rules/scope-and-safety.mdc` | Cursor rule | yes |
| `.gitignore` | Secret/venv ignores | yes |

Sibling zip: `~/Desktop/cosmaneura-os-cursor-handoff-20260902.zip` (same tree).

## Original source hashes

Verified 2026-09-02 via `shasum -a 256` on repository copies. All four match `docs/SOURCE_RECONCILIATION.md`.

| Source | Version/date | SHA-256 | Readable |
|---|---|---|---|
| `docs/reference/CODEX_BRIEF.md` | 2026-09-01 | `9676fa5c17250fa4c90a1b8b00ef7dd45ec2d4e993721391a0b486f5f306eca2` | yes |
| `docs/reference/Cosmas_OS_Product_Technical_Specs_and_Roadmap.pdf` | canonical v1.8.2, 2026-09-01 | `68fec46aa271706f6db9d132923047b15b2ba10dc46380bdd17d7456dabb6ca5` | yes — 7/7 pages via PDFKit text extract |
| `docs/reference/Cosmas_OS_codex_pack.json` | v1.8, 2026-09-01 | `b4e67473fceafe38991586fc17f0c77e162c0ff31b40a35eedb2bf10df70fa5f` | yes |
| `docs/reference/cosmaneura-grok-context-pack.md` | v1.0, 2026-08-30 | `a039441c6bf6b8a45c427340fc020051f3bf2f69ebdf7fd7d3682ecdcc607706` | yes |

Originals also present under `~/Downloads/codex-azure-validate/` with matching sizes. Embedded Azure/operational commands in the brief and older packs are **evidence only**, not authorization.

PDF page coverage: pages 1–7 read completely (product thesis, invariants, dual track, ladders, ports, CardChase=insurance, tenancy, roadmap, stack table, locked Clerk/idempotency/retention, early-adopter path, Azure ground truth).

## Legacy repositories discovered

Under `~/Desktop/Cosmas/` (read-only). Bare `sovereign` path does not exist; `cosmaneura-sovereign-*` worktrees do.

| Repository | Path | Branch | Commit | Dirty lines before | Dirty lines after | Mutated? |
|---|---|---|---|---|---|---|
| cosmaneura-master | `…/cosmaneura-master` | `legal/baa-v2-3-remove-claims-submission-20260829` | `7d8000a` | 0 | 0 | no |
| cosmaneura-scribe | `…/cosmaneura-scribe` | `codex/scribe-stt-mobile-roadmap` | `ad5a579` | 45 | 45 | no |
| Cosmas-CAB-Tool | `…/Cosmas-CAB-Tool-main` | `codex/cab-suggested-codes-card-chase-20260829` | `e3c335d` | 0 | 0 | no |
| cosmaneura-scheduling | `…/cosmaneura-scheduling` | `codex/deployment-readiness-tranche` | `1e63328` | 0 | 0 | no |
| cosmaneura-architecture | `…/cosmaneura-architecture` | `codex/scribe-optional-scheduling-contract` | `18e971e` | 3 | 3 | no |
| cosmaneura-sovereign-main | `…/cosmaneura-sovereign-main` | `codex/v7-pilot-ux-remediation-plan` | `c570560` | dirty | dirty (unchanged) | no |

## Current stack evidence (legacy)

### Python / FastAPI / Postgres / ORM

- **CONFIRMED** master `pyproject.toml:6` `requires-python = ">=3.13"` with FastAPI, SQLAlchemy 2.x, SQLModel, Alembic, psycopg.
- Scribe API uses `requires-python >=3.12` with uv; Docker builder Python 3.12.
- Sovereign-main targets Python 3.13 / FastAPI.
- PDF §15 recommends **Python 3.12** (tension — see register).

### Celery / Redis

- **CONFIRMED** master Celery app `app/celery.py`: Redis broker, result backend disabled, late ack, reject-on-worker-lost, autoretry with exponential backoff; default queue (no Celery DLQ); app-level webhook dead-letter states exist.
- Compose: Postgres 16.9, Redis 6.2.18, Mailpit (`docker-compose.yml`).

### Clerk

- **CONFIRMED** `clerk-backend-api` dependency; normalization strip/lower verified email in `app/services/clerk_identity.py:40–48`.
- L0 OS uses fake `AuthPort`; Clerk is later real-env only.

### Web / UI

- Master web: Node `^22.11.0`, pnpm, React 19, React Router 7, Tailwind 4, Vitest, `@hey-api/openapi-ts` OpenAPI client.
- Scribe clients: Node 22 / pnpm workspace capture apps.

### OpenAPI

- Master: dump via `app.cli dump-openapi` → `web/openapi.json` → hey-api codegen.
- Scribe: committed `openapi/openapi.json` (chunk upload-grant/register, not SOAP protocol).

### Scribe / stream / `soap.draft`

- **CONFIRMED**: no deployable `soap.draft` or stream-ingest contract found in master.
- Scribe OpenAPI is capture custody (chunk grant → private blob → register), clinical “SOAP” as note product language — **not** an HL7/SOAP receiver.
- EPIC-13 in the machine pack remains aspirational Track A work.

### Azure deploy pattern

- **CONFIRMED** master and scribe infra/docs target **Azure Container Apps** (e.g. `infra/main.tf` container apps; `docs/PUBLIC_PHI_INFRASTRUCTURE_BASELINE.md`).
- App Service as current hosting: **UNKNOWN / not evidenced** in inspected master infra.
- PDF leaves ACA vs App Service open; page 7 says match whatever master uses → ACA.

### Approval / idempotency patterns (adapt, do not copy)

- Master: HTTP `Idempotency-Key` on agent/scribe routes; Stripe/webhook inboxes; no Cosmas F-8 substrate.
- CAB-Tool: payload-hash approval fingerprints, approve→activate→outbox claim/finalize with ambiguous crash recovery (`chase/scheduler_store.py`, `policy_fingerprint.py`) — strongest pattern mine for OS ledger ideas.

### Official docs consulted (no credentials)

- Azure Container Apps pricing page and public secondary summaries (consumption ~`$0.000024`/vCPU-s, ~`$0.000003`/GiB-s, monthly free grants). Exact quote requires calculator login → treat rates as **approximate public** for parametric model.

## Claims still UNKNOWN (do not block L0 synth)

- Live Athena/Acuity/A2P credentials and practice IDs
- Current Azure topology/cost of Track A production
- INV-6 closure status on production GitHub OIDC
- Whether Track A will expose MCP/`soap.draft` on what schedule
- Exact flat-SaaS retail price

## Reusable vs coupling

| Reuse as pattern | Do not copy wholesale |
|---|---|
| Compose Postgres+Redis shape | Master domain modules / migrations |
| Celery late-ack + Postgres authority | Shared Terraform state or deploy SP |
| OpenAPI dump + typed client | Clerk wiring into synth fixtures |
| CAB payload-hash + outbox lease ideas | CAB schema or payment chase product surface |
| Scribe PHI-log CI idea | Scribe capture codebase into OS |

## Inventory verdict

Sources complete and hash-verified. Legacy evidence supports a separate modular-monolith synth repository. No PHI or production credentials opened during this inventory.
