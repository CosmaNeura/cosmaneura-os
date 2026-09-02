# 01 — Authority and reconciliation

Date: 2026-09-02  
Authority order applied: direct owner prompt → `CANONICAL_PRODUCT_DECISIONS.md` → accepted `DECISION_LOG` → architecture contract → code evidence → historical sources.

## Authority check

| Layer | Status |
|---|---|
| Direct owner Phase 0 mandate | Active; no `APPROVE LOCAL SYNTH BUILD` received |
| Canonical product decisions 1.9-draft | Read; treated as locked unless fatal flaw |
| Decision log DL-20260902-01…04 | Accepted baseline intact; no later ACCEPTED entries |
| Architecture contract 1.9-draft | Proposed; validated below — no silent overrides |
| Code evidence | Used only for implementation facts |
| Historical sources | Evidence; embedded Azure/swarm commands not executed |

Code can disprove “what master does today.” It cannot silently replace D-001…D-013.

## Re-check of known conflicts (R-001…R-008)

### R-001 — Payment recovery vs insurance artifacts

| | |
|---|---|
| Classification | `CONFIRMED` resolved |
| Sources | Grok pack F-4 CardChase payment narrative; PDF §9 + pack EPIC-5 insurance ArtifactChase; D-003 |
| Impact | V1 product shape |
| Blocks local synth? | No |
| Resolution | Insurance ArtifactChase; payment/PAN deferred (EPIC-10 gated) |

### R-002 — Pricing

| | |
|---|---|
| Classification | `CONFIRMED` resolved |
| Sources | Grok OPEN-3; PDF “Flat SaaS only”; pack `open3: SETTLED_flat_saas`; D-003 |
| Impact | Commercial model |
| Blocks local synth? | No |
| Resolution | Flat SaaS; exact tiers remain open; no percentage pricing |

### R-003 — Org identity / tenant keys

| | |
|---|---|
| Classification | `CONFIRMED` resolved for L0 |
| Sources | Prior multi-tenant `org_id` habit; D-004; PDF “one computer per Org” |
| Impact | Schema design |
| Blocks local synth? | No |
| Resolution | Exclusive Box DB/schema may inherit scope; `box_id` mandatory at shared boundaries; shared DB is a future architecture decision |

### R-004 — Human seats vs agents

| | |
|---|---|
| Classification | `CONFIRMED` resolved |
| Sources | Pack `Seat` language for humans and system roles; D-005/D-006 |
| Impact | Principal model |
| Blocks local synth? | No |
| Resolution | `HumanSeat` vs `AgentPrincipal`; agents cannot approve/sign/impersonate; removal tombstones |

### R-005 — Ticket-list approval / templates

| | |
|---|---|
| Classification | `CONFIRMED` resolved for first slice with working assumption |
| Sources | Pack Disaggregation “ticket list HITL”; D-008 exact revision approval; PDF automation classes |
| Impact | Approval UX |
| Blocks local synth? | No |
| Working assumption | First slice uses **individual** payload-bound approve/edit/reject/escalate. Displayed batch allowed later if every revision visible and bound. `AUTO_TEMPLATE` dark; `AUTO_DRAFT` cannot send |

### R-006 — Idempotency formula

| | |
|---|---|
| Classification | `CONTRADICTS` historical PDF formula; `CONFIRMED` owner resolution |
| Sources | PDF §16 `idempotency_key = ticket_id + action + payload_hash`; prior review crash-after-success; D-009; architecture §6 |
| Impact | Duplicate send / UNKNOWN handling |
| Blocks local synth? | No if ledger model used |
| Resolution | Stable `operation_id` + payload-bound approval + uniqueness + receipts + `UNKNOWN` reconciliation. Payload hash binds approval but is not sole idempotency key |

### R-007 — Compliance breadth

| | |
|---|---|
| Classification | `CONFIRMED` resolved |
| Sources | Broad prior review lists; D-010; PDF L0 “no new EHR” |
| Impact | Setup burden |
| Blocks local synth? | No |
| Resolution | Invisible platform floors + capability activation gates; patient messaging/uploads dark until enabled |

### R-008 — Clerk/Entra and Celery/Functions

| | |
|---|---|
| Classification | `CONFIRMED` with code evidence |
| Sources | PDF §15 Entra/Functions as open choices; PDF §16–18 Clerk + Celery locked; master Celery+Clerk |
| Impact | Identity and worker choice |
| Blocks local synth? | No |
| Resolution | Fake AuthPort for L0; real IdP = Clerk later. Worker hypothesis = Celery/Redis (master-confirmed), Postgres authoritative |

## Additional tensions found this pass

| ID | Classification | Finding | Blocks synth? |
|---|---|---|---|
| T-PY | `DECISION_REQUIRED` (non-blocking) | PDF §15 Python 3.12 vs master `>=3.13` | No — pick baseline in build gate |
| T-SOAP | `UNKNOWN` | `soap.draft` / stream MCP not present in master | No — L0 does not need Track A tools |
| T-SEAT | `CONTRADICTS` historical | Pack still uses `Seat` for agents; canonical uses AgentPrincipal | No — follow D-005 |
| T-ACA | `CONFIRMED` | Master uses Container Apps; PDF still mentions App Service option | No for synth; prefer ACA for later beta |

## Fatal-flaw scan of locked decisions

No locked decision prevents a coherent isolated deterministic L0 product. Unfinished Athena/Acuity, INV-6, marketplace clocks, and exact SaaS tiers are not fatal for local synth.

## Authority outcome

Proceed under 1.9-draft rulings. Record working assumptions in `07-build-gate.md`. Do not reopen R-001…R-008 without a concrete fatal counterexample.
