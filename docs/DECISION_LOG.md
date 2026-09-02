# Owner decision log

This is the append-only log for owner-adjudicated changes after the reconciled
1.9-draft baseline. A proposal becomes authoritative only when its status is
`ACCEPTED` and its evidence identifies a direct owner message or other explicit
owner action.

Do not rewrite accepted entries. Add a later entry that supersedes them.

## Entry format

```text
ID: DL-YYYYMMDD-NN
DATE:
STATUS: PROPOSED | ACCEPTED | REJECTED | SUPERSEDED
RULING:
RATIONALE:
SUPERSEDES:
AFFECTED CONTRACT VERSION:
OWNER ACCEPTANCE EVIDENCE:
IMPLEMENTATION IMPACT:
```

## Baseline accepted rulings

### DL-20260902-01

- **Status:** ACCEPTED
- **Ruling:** Insurance ArtifactChase is v1 and uses flat SaaS pricing; payment
  recovery and percentage-of-recovery pricing are deferred.
- **Rationale:** Reconciles the older payment narrative with the later product
  direction.
- **Supersedes:** Conflicting CardChase and `OPEN-3` language in the historical
  context pack.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message dated 2026-09-01/02.
- **Implementation impact:** No payment/PAN work or recovered-dollar KPI in v1.

### DL-20260902-02

- **Status:** ACCEPTED
- **Ruling:** One Org is the computer Box; the owner seat bootstraps authority,
  and the immutable Box/Org identity is the permanent audit root.
- **Rationale:** Preserves the product's one-practice-computer model without
  redundant tenant fields inside an exclusive Box database.
- **Supersedes:** Any interpretation that presumes a shared multi-tenant data
  plane for the initial implementation.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message dated 2026-09-01/02.
- **Implementation impact:** Box scope becomes explicit at shared boundaries;
  shared-database packing is deferred.

### DL-20260902-03

- **Status:** ACCEPTED
- **Ruling:** The human owner/login and installed baseline agents are distinct
  principals; agents are broadly reusable and owner-removable.
- **Rationale:** Preserves the Box metaphor while making human versus agent
  authority unambiguous.
- **Supersedes:** Historical `Seat` language that conflates human and system
  identities.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message dated 2026-09-01/02.
- **Implementation impact:** Agent removal tombstones history; agents cannot
  self-approve, impersonate, or sign.

### DL-20260902-04

- **Status:** ACCEPTED
- **Ruling:** Initial reliable execution remains local, and compliance is gated
  by enabled capability rather than imposed as a universal owner workflow.
- **Rationale:** Avoids distributed infrastructure and usability-hostile setup
  before external connectors are activated.
- **Supersedes:** Broad readings of the prior review that applied every future
  connector safeguard to the internal L0 product.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message dated 2026-09-01/02.
- **Implementation impact:** Local Postgres operation ledger, invisible
  platform floors, and capability activation manifests later.

### DL-20260902-05

- **Status:** ACCEPTED
- **Ruling:** Owner authorized local synthetic Roadmap Phases 1 and 2 via the
  exact phrase `APPROVE LOCAL SYNTH BUILD`. Phase 0 working assumptions in
  `docs/validation/07-build-gate.md` apply (Python 3.13, Celery/Redis
  transport, local filesystem BlobPort, individual payload-bound approvals,
  local `git init` on `main`, no remote/push, no cloud).
- **Rationale:** Completes the mandatory Phase 0 stop gate with no fatal
  findings (`FEASIBLE_WITH_CONDITIONS`).
- **Supersedes:** None.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message `APPROVE LOCAL SYNTH BUILD`
  dated 2026-09-02.
- **Implementation impact:** Scaffold and prove synthetic Insurance ArtifactChase
  L0 in `cosmaneura-os` only; Track A remains read-only.

### DL-20260902-06

- **Status:** ACCEPTED
- **Ruling:** Owner authorized Deployment stage D1 — synthetic CI and
  release-artifact hardening — without cloud deploy, registry push, or Track A
  mutation.
- **Rationale:** Completes the next gate after local synth L0.
- **Supersedes:** None.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message requesting
  `Synthetic CI/release-artifact hardening` dated 2026-09-02.
-   **Implementation impact:** Add GitHub Actions synth-ci, local CI parity
  script, release image/manifest script, and rollback documentation.

### DL-20260902-07

- **Status:** ACCEPTED
- **Ruling:** Owner authorized the first git commit on `main` and creation of a
  private remote for `cosmaneura-os`, still without cloud deploy, registry
  push, or Track A mutation.
- **Rationale:** Establishes revision identity for CI/release artifacts after
  D1.
- **Supersedes:** The “no remote/push” clause of DL-20260902-05 only; local
  synth and D1 cloud prohibitions remain.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message `First commit and private
  remote` dated 2026-09-02.
- **Implementation impact:** Commit the local synthetic tree; create/push a
  private GitHub repository; keep `.env` and generated release manifests out of
  git.
