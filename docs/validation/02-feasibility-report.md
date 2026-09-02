# 02 — Feasibility report

Date: 2026-09-02  
**Overall verdict: `FEASIBLE_WITH_CONDITIONS`**

Conditions are engineering working assumptions and later-environment gates — not blockers for local synthetic L0.

## Verdict rationale

A separate Track B modular monolith can implement Box/principals, F-8, a Postgres operation ledger, fake ports, and a complete Insurance ArtifactChase L0 workflow without vendors, PHI, or Track A mutation. Legacy evidence confirms the hypothesized stack family. Prior “120-day everything” scope remains non-credible as a single release; gated increments are credible.

## Dimension results

| Topic | Class | Summary |
|---|---|---|
| Separate repository boundary | `CONFIRMED` | Correct isolation; no shared git/DB/TF/SP with Track A |
| Modular monolith | `CONFIRMED` | Fits FastAPI domain/ports/adapters; avoids premature microservices |
| Python 3.12 vs 3.13 | `DECISION_REQUIRED` | PDF 3.12; master/sovereign 3.13; host has 3.14 — recommend **3.13** for Track A pattern alignment |
| F-8 state/transaction model | `CONFIRMED` | Coherent; CAB patterns validate payload-hash + outbox ideas |
| One-Org/one-Box scope | `CONFIRMED` | Exclusive DB for synth/beta-1; `box_id` on shared boundaries |
| Human/agent principals + owner transfer | `CONFIRMED` | Enforceable with tombstones and last-owner successor rule |
| Operation ledger crash/retry/UNKNOWN | `CONFIRMED` | Postgres authority + Celery transport; supersedes PDF-only key formula |
| Synthetic ArtifactChase without vendors | `CONFIRMED` | SchedulePort CSV + NotifyPort fake + local BlobPort |
| Ports / independent ladders | `CONFIRMED` | L0 dark above Org rung; fail closed |
| Retention/purge | `CONFIRMED` | Injectable clock + purge receipt without PHI |
| Small-practice queue / owner gestures | `CONFIRMED` with UX condition | See usability; hide infra jargon |
| Synthetic CI without credentials | `CONFIRMED` | Fixture scan + no network secrets |
| Container Apps vs App Service (later beta) | `CONFIRMED` preference | Match master → **Container Apps** |
| Unit economics (parametric) | `UNKNOWN` exact; ranges feasible | See deployment roadmap; no final price invented |
| Creation/deployment sequencing | `CONFIRMED` | Phase 0→1+2 local mandate; cloud separate |
| Track A/B integration | `CONFIRMED` constrained | HTTPS/OpenAPI or MCP later; `soap.draft` absent today |
| Fatal locked-decision flaw | `CONFIRMED` none found | — |

## Conditions (must hold during implementation)

1. **Postgres is authoritative** for operations; Redis/Celery are transport only.
2. **Approval binds immutable ActionRevision + payload hash**; edits create new revisions.
3. **L0 adapters only** — no Athena, Acuity, Clerk, Azure, real messaging, or application LLM.
4. **Normal UI** shows work/people/agents/outcomes — not `box_id`, operation IDs, or compliance jargon.
5. **No Track A writes**; no PHI/production fixtures.
6. **Python baseline** recorded as 3.13 unless owner overrides before scaffold.
7. **UI baseline** = smallest React+Vite owner queue compatible with master OpenAPI client habit, without Clerk in synth.

## Usability — first owner journey (synthetic)

Minimum gestures for one chase:

1. Open queue (seeded Box already provisioned in demo).
2. Attest PatientLink once for the invented patient/source pair.
3. Review proposed chase message revision.
4. Approve (or edit→new revision→approve, reject, escalate).
5. Observe delivery outcome in-app (fake NotifyPort).
6. Verify uploaded front/back fixtures → mark `IMAGE_ON_FILE`.
7. See closed ticket + audit timeline.

Infrastructure leak risks to hide: operation IDs, Celery, Redis, `UNKNOWN` internals (surface as “needs attention” only when human action required), `box_id`, policy version hashes.

Batch approval: safe only when each revision’s target and full content are visible and individually bound — **not** required for first slice.

## Cost / burden (high level)

- Local synth cost ≈ developer time + laptop Docker; no Azure credits required.
- Isolated beta infra (parametric, no credits): see `05-deployment-roadmap.md`.
- Support assumption for early beta: founder-led, ≤1 clinic, not 24/7 ops.

## Kill signals (from roadmap, still valid)

Approval/setup cost ≥ staff time saved; practice cannot understand proposed action; ordinary retries need manual babysitting; flat-SaaS cost model fails without credits; Track B delays Track A survival work.

## Conclusion

**`FEASIBLE_WITH_CONDITIONS`.** Local synthetic Insurance ArtifactChase L0 should proceed after exact owner phrase `APPROVE LOCAL SYNTH BUILD`. Cloud, connectors, and pricing remain later gates.
