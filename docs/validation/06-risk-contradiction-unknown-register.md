# 06 — Risk, contradiction, and unknown register

Date: 2026-09-02  
Legend: `CONFIRMED` | `CONTRADICTS` | `UNKNOWN` | `BLOCKED` | `DECISION_REQUIRED`

| ID | Class | Item | Source A | Source B / evidence | Impact | Recommended resolution | Blocks local synth? |
|---|---|---|---|---|---|---|---|
| R-001 | `CONFIRMED` | V1 = insurance chase | Grok CardChase payment | PDF §9, D-003 | Product | Keep insurance; payment gated | No |
| R-002 | `CONFIRMED` | Flat SaaS | Grok OPEN-3 | PDF/pack/D-003 | Pricing | Tiers open; no % | No |
| R-003 | `CONFIRMED` | Box scope | Multi-tenant habit | D-004 | Schema | Exclusive DB inherit; shared needs `box_id` | No |
| R-004 | `CONFIRMED` | Principals | Pack Seat | D-005 | AuthZ | HumanSeat ≠ AgentPrincipal | No |
| R-005 | `CONFIRMED` | Approval grain | Ticket-list HITL | D-008 | UX | Exact revision; batch later optional | No |
| R-006 | `CONTRADICTS`→resolved | Idempotency | PDF ticket+action+hash | Crash-after-success; D-009 | Dup sends | Operation ledger + UNKNOWN | No |
| R-007 | `CONFIRMED` | Compliance | Broad gates | D-010 | Burden | Capability manifests | No |
| R-008 | `CONFIRMED` | IdP/worker | PDF Entra/Functions options | Master Clerk+Celery; PDF §16–18 | Stack | Fake auth L0; Celery | No |
| T-PY | `DECISION_REQUIRED` | Python version | PDF 3.12 | Master ≥3.13 | Tooling | Default **3.13** in build gate | No |
| T-UI | `DECISION_REQUIRED` | UI stack | Capacitor in PDF early | Lowest complexity | Speed | Minimal React queue; Capacitor deferred | No |
| T-BLOB | `DECISION_REQUIRED` | Blob local | Azurite option | Simplicity | Deps | Local FS adapter first | No |
| T-SOAP | `UNKNOWN` | soap.draft/stream MCP | Pack EPIC-13 | Not in master code | Integration timing | Do not depend for L0 | No |
| T-ACA | `CONFIRMED` | Beta host | PDF ACA\|App Service | Master ACA | Ops | Prefer ACA later | No |
| U-ATH | `UNKNOWN` | Athena/Acuity access | Pack UNKNOWN IDs | No live probe (forbidden) | Connector schedule | L0 CSV schedule | No |
| U-COST | `UNKNOWN` | Exact Azure SKU $ | Public approx rates | No calculator login | Beta budget | Parametric ranges only | No |
| U-INV6 | `UNKNOWN` | INV-6 closed? | Brief claims open | Not verified in Azure | Prod join | Irrelevant to synth | No |
| U-CLERK-NORM | `CONFIRMED` pattern | Email normalize | — | master clerk_identity.py | Later real auth | Copy idea later, not now | No |
| U-CELERY-DLQ | `CONFIRMED` limited | Celery DLQ | Expectation | Master: app inbox DL, not Celery DLQ | Recovery design | Ledger + UNKNOWN, not Celery DLQ | No |
| RISK-PHI | `CONFIRMED` control | Fixture hygiene | PDF §16 | Protocol | Breach via git | Fixture scanners; invented data only | No if enforced |
| RISK-COUPLE | `CONFIRMED` control | Copying Track A | Convenience | D-001 | Destabilize A | Patterns only | No if enforced |
| RISK-UX | `CONFIRMED` watch | Infra leak into UI | D-013 | Prior review | Adoption | Queue UX review Gate 2 | No |
| RISK-STAFF | `CONFIRMED` watch | Track B delays A | D-002 | Roadmap kill | Survival | Pause B if conflict | No |
| FATAL | `CONFIRMED` | Fatal locked flaw | — | Phase 0 scan | Build stop | **none found** | No |

## Material contradictions still visible in historical text

Agents must not re-implement these superseded ideas:

1. Payment-card recovered-dollars as v1 KPI.
2. Percentage-of-recovery pricing.
3. Entra as second IdP.
4. Idempotency = only `ticket_id + action + payload_hash` without operation identity.
5. Ticket-list acceptance as silent standing send authority.
6. Python 3.12 as mandatory if it conflicts with chosen 3.13 baseline (document choice).

## Blocked items

**None** for local synthetic L0.

## Decisions that look open but do not block synth

Exact SaaS tiers; first beta org; approver matrix; batch UX; email vs A2P; Athena IDs; post-beta packing; product LLM; kill thresholds.
