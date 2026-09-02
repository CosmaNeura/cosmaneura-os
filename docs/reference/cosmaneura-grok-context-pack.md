# CosmaNeura — Context Pack for Roadmap Authoring (Grok → Codex)
### v1.0 · 30 Aug 2026 · Machine-first companion to Strategy v3 (canonical)

## §0 Instructions to the roadmap model (read first)

You are helping the CEO author a product roadmap that will be executed by coding agents (Codex swarm). Rules:
1. Every **D-x** decision is **SETTLED, not locked**: the roadmap you emit must implement the settled version, but you are expected to stress-test any of them — flow, sequencing, risk, internal contradiction — and file challenges in the **§11 challenge register**. The CEO adjudicates reopening; never silently substitute an alternative into the roadmap itself.
2. Never violate an **INV-x invariant** in emitted roadmap items — most encode legal, safety, or security floors. You may question an invariant in §11 with evidence; until the CEO rules, the roadmap complies.
3. Every roadmap item must map to a **F-x feature ID** (or propose a new F-x explicitly) and emit the **§9 output schema** so Codex can consume it without translation.
4. **OPEN-x** items are CEO decisions, not yours. Where a roadmap branch depends on one, write both branches short-form and mark the dependency.
5. External clocks (**CLK-x**) cannot be compressed by adding engineering. Never schedule dependent work as if they can.
6. When this pack conflicts with any other document, this pack + Strategy v3 win (authority order in §1).

## §1 Document authority order
1. **cosmaneura-strategy-gtm-v3.md** (canonical strategy) + this context pack
2. cosmaneura-business-plan-tam.md (market numbers; 26 footnoted sources)
3. cosmaneura-agent-swarm-operating-model.md (execution pipeline, roles, prerequisites)
4. cosmaneura-market-landscape-gtm.md (v1 — channel/conference inventory, competitor detail; superseded on strategy)
5. cosmaneura-pivot-three-ideas.md / cosmaneura-stress-test-and-ditl.md (historical; superseded — note: the 60–80% revenue-share concept in the stress-test doc is DEAD, see INV-2)

## §2 Company snapshot (facts)
- CosmaNeura Inc., Delaware C-corp. CEO John Clemente (sole founder; fractional CTO candidate "Dom" not yet confirmed signed). Sarasota FL.
- Live product: "Cosmas" AI scribe (audio upload → SOAP note). ~40 unpaid 1099 clinician pilots via MyCatholicDoctor (MCD); ~8,000 encounters; $0 revenue to date.
- Oct 1 2026: paid conversion at $60/seat/mo (Stripe). Kill switch Sept 15 (pre-launch checkpoints unmet → halt).
- Stack: Python/FastAPI/Celery/Postgres/Redis on Azure; Azure OpenAI (gpt-4.1) + AssemblyAI + Recall.ai in the note pipeline; BAA in place with hash-binding + immutable records.
- Azure credits: $100k, expire Jan 2027. Microsoft extension ask scheduled November with consumption dashboards.
- Repos: `cosmaneura-master` (live prod; Stripe code expects $89 — needs $60 SKU; authority-kernel flags OFF), `cosmaneura-scribe` (best security patterns: VNet/private endpoints/managed identity; in-memory dev only), `cosmaneura-scheduling` (rich domain model, not production-ready), `Cosmas-CAB-Tool` (approval/outbox patterns, synthetic data only), `sovereign` (mine for components only).
- Security state: public-PHI readiness 1 of 16 gates passing (NO-GO for self-serve strangers). P0: `cosmaneura-gha-prod` service principal has GitHub pull_request-subject federation WITH Contributor + constrained User Access Administrator over production RG + Terraform-state RG.

## §3 Decision log (D = SETTLED by CEO 30 Aug 2026 · stress-reviewable per §0 rule 1)
- **D-1** Public launch monetizes the existing ~40 on the existing platform; new beta features ship AT launch as conversion incentives. Signal mixing accepted; attribution instrumentation required (survey at conversion, per-feature telemetry, cancellation reasons).
- **D-2** AI coding suggestions: ON for MCD-credentialed providers at launch; OFF for all other users until coder/counsel memo. Provider attests final code; overrides logged; no auto-submission; copy says "documentation-to-code consistency check."
- **D-3** CardChase ships direct-to-design-partner (MCD + invited telehealth practices) inside 60 days; Athena Marketplace application filed Day 0–7; listing lands on the marketplace's own clock (CLK-1).
- **D-4** CardChase HITL approval queue is a PMF feature: every agentic action (send/retry/escalate) requires practice approval; auto-approve rules are earned later by measured accuracy.
- **D-5** Payments tokenized at the processor; SAQ-A scope; PANs never touch CosmaNeura systems.
- **D-6** Toolchain: this pack + v3 → Grok (roadmap) → Codex (execution). Harness TBD (Cursor vs GrokBot); swarm operating model's two-family review pipeline stands meanwhile.

## §4 Invariants (INV — violating any of these is a defect)
- **INV-1** Practice is always the merchant of record for patient payments and program fees.
- **INV-2** No percentage of professional-fee revenue, ever, absent explicit counsel sign-off (fee-splitting, FL §458.331 exposure). CardChase %-of-recovered-patient-payments is a separate question (OPEN-3) — do not build pricing that assumes it.
- **INV-3** A licensed clinician approves anything clinical: final billing codes, patient-facing clinical content, protocol changes. The AI drafts; the human owns.
- **INV-4** All patient-facing agentic sends pass a HITL approval queue (chase loop included, per D-4). SMS = neutral notice + secure deep link; no PHI in message bodies.
- **INV-5** No self-serve onboarding of unknown users' PHI until the 16-gate readiness audit passes (identity, consent, isolation, audit, escalation).
- **INV-6** No parallel agent execution before: P0 IAM fix (remove PR-subject prod federation; split plan/apply identities; protected-branch-only; rotate creds), CI honesty (no green on skipped stages), canonical branches.
- **INV-7** Faith never appears in product copy or marketing.
- **INV-8** Kill gates are preserved: features/products graduate tiers only on measured criteria; Sept 15 kill switch and Oct 1 test date are fixed.
- **INV-9** Design at retail unit economics; credits subsidize timing, never architecture.

## §5 Feature registry (F) — with repo mapping and acceptance seeds
- **F-1 Scribe (GA).** Upload → SOAP. Repo: `cosmaneura-master`. Launch work: $60 Stripe SKU; conversion flow; attribution instrumentation (D-1). Accept: existing pilot user can pay and retain full history; conversion survey fires at first invoice.
- **F-2 Session Prep / Visit Prep & Intake (beta at launch).** Deterministic loop: intake → validated timeline → clinician review → pre-visit brief. Shares the approval-loop engine (F-8). Accept: brief generated ≥24h pre-visit; clinician approve/edit/reject logged; zero unreviewed briefs reach a visit.
- **F-3 AI coding suggestions (beta, MCD-scoped).** Source patterns: `Cosmas-CAB-Tool` (approval/outbox), but note repo has never touched real PHI — production hardening required. Scoping per D-2. Accept: suggestion + rationale displayed; provider attestation captured; override rate dashboarded; feature-flag OFF for non-MCD orgs verified by test.
- **F-4 CardChase (design partner).** Loop: detect (expired card / failed charge / missing card-on-file pre-televisit) → draft outreach → HITL approve (D-4) → send (SMS/email deep link) → tokenized capture (D-5) → confirm → post back to Athena → close or escalate. Recovered-dollars counter is a first-class metric surface. Accept: end-to-end recovery on a real MCD account; every action in the audit log; $0 of PAN data in our systems (attested by architecture review). Marketplace track: application filed (CLK-1), sandbox build, certification checklist.
- **F-5 Ambient/live scribe (coming soon).** Real-time capture (Recall.ai path exists for telehealth). Not launch-blocking.
- **F-6 Scheduling (coming soon).** Repo: `cosmaneura-scheduling` — rich domain, not prod-ready; treat as re-platform onto F-8, not a polish job.
- **F-7 Journey programs / RRM loop (Horizon 2).** Depth strategy; blinded bake-off status = OPEN-1. Specialty depth layers onto F-2's loop per-specialty.
- **F-8 Approval-loop engine (shared substrate — build once).** Queue, draft/approve/edit/reject/escalate states, audit log, notification rails, feature-flag scoping per org. Consumed by F-2, F-3, F-4, F-6, F-7. **Roadmap rule: any item that builds approval logic inside a feature instead of on F-8 is a defect.**
- **F-9 Platform gates.** Identity/consent flows for referral-gated onboarding; the 16-gate PHI readiness closure for true self-serve (INV-5); event store; A2P-registered SMS rail (CLK-4).

## §6 External clocks (CLK — cannot be compressed by engineering)
- **CLK-1** Athena Marketplace: approval typically 6–12 weeks from application (integration vendors quote ~14 to certification); 15–30% revenue share on marketplace-channel sales; HITRUST self-assessment due within 90 days of marketplace GA or delisting.
- **CLK-2** Coder/counsel memo for coding-suggestions public GA (D-2 gate).
- **CLK-3** Azure credits expire Jan 2027; extension ask in November with consumption evidence.
- **CLK-4** A2P 10DLC registration for SMS chase/nudge rails — file immediately.
- **CLK-5** Sept 15 kill switch; Oct 1 paid test; retention curves mature Feb–Mar 2027 (raise exhibit timing).

## §7 Sequence (roadmap skeleton Grok should elaborate, not reorder)
- **0–30d:** F-1 SKU + conversion + instrumentation; F-2/F-3 beta hardening on F-8 v0; CardChase spec w/ MCD (Kathleen) + Athena application + A2P filing; INV-6 prerequisites closed; CLK-2 commissioned.
- **30–60d:** Referral-gated onboarding (F-9 partial); F-4 live with design partner, recovered-dollars counter public to the practice; Athena sandbox; Codex lanes launch per swarm model.
- **60–120d:** Marketplace listing + HITRUST self-assessment; F-2/F-3 GA decisions (CLK-2 in hand); INV-5 gate closure → true self-serve; November CLK-3 ask; OPEN-1 resolved.

## §8 Commercial frame (for roadmap prioritization, not for copy)
- Segments & TAM: 88,925 independent practices / 120,900 physicians; US TAM ~$0.6–1.7B (base ≈$1.0B); SAM $150–280M; SOM yr1 $150–500k, yr3 $3–7M (see TAM doc for footnotes).
- Pricing ladder: $60/seat (scribe) → $250–500/mo fixed (loop tier) → $1,000–1,500/mo (Second Employee tier, gated on measured avoided cost ≥2–3× fee). CardChase pricing = OPEN-3.
- Category language: "AI employee for clinics" — enterprise layer occupied (Thoughtful AI, Hippocratic AI, Tennr); **unowned segment = the 1.36-physician practice.** Never claim "zero competitors"; for CardChase claim the *agentic HITL chase loop, telehealth-native* position (marketplace payment incumbents: Health iPASS, AccessOne, Healee).

## §9 Required roadmap output schema (emit for every item, so Codex can execute)
```
EPIC: <name> — maps to F-x
  STORY: <user story, one sentence>
  FEATURE-ID: F-x | AUDIENCE: MCD-only / paying / public / internal
  DEPENDS-ON: [F-x…, CLK-x…, INV-x…, OPEN-x…]
  LANE: <swarm lane per operating model> | REPO: <target repo>
  ACCEPTANCE: <testable criteria; security/audit criteria mandatory for PHI or payment surfaces>
  DEFINITION-OF-DONE: code + tests written FIRST by test agent + adversarial review (second model family) + human merge
  GATE: <which kill/graduation gate this feeds, if any>
```

## §10 Open questions reserved for the CEO (carry, don't resolve)
- **OPEN-1** RRM blinded bake-off: deferred with a date, or dropped — and if dropped, what is the raise's proof exhibit? (Candidate: CardChase recovered-dollars + paid retention curves, Feb–Mar 2027.)
- **OPEN-2** CardChase scope: payment cards confirmed primary; insurance-card/eligibility image chase in or out of v1 backlog?
- **OPEN-3** CardChase pricing: flat + volume tiers vs %-of-recovered patient payments (needs counsel's one-liner; INV-2 distinction).
- **OPEN-4** Dom signed? (Human merge authority is the swarm's capacity ceiling at 2–3 hrs/day.)
- **OPEN-5** Harness: Cursor cockpit (recommended) vs GrokBot orchestration (unproven on PHI codebase).

## §11 Challenge register (how to stress settled decisions)

Roadmap (Grok) and execution (Codex) models have **equal stress-test privilege** over everything in this pack — settled decisions, invariants, clocks, sequence, features. The emitted roadmap and code still implement the settled version while a challenge is pending; challenges are filed here, not embedded as silent substitutions.

```
CH-<n>: TARGET: D-x / INV-x / CLK-x / SEQ / F-x
  FINDING: <what breaks, contradicts, or underperforms — one sentence>
  SEVERITY: blocker / material / minor
  EVIDENCE: <repo fact, market fact, or math — no vibes>
  ALTERNATIVE: <the specific change proposed>
  SWITCHING-COST: <time / scope / risk of adopting the alternative>
```

CEO adjudication is the only path from a CH entry to a changed D or INV. Accepted challenges produce a v3 changelog entry; rejected challenges are recorded with the reason so downstream agents stop re-raising them.
