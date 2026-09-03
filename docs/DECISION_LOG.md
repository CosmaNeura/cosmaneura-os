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

### DL-20260902-08

- **Status:** ACCEPTED
- **Ruling:** Owner authorized Deployment stage D2 — optional non-PHI Azure
  development — with OS-named resources only, synthetic data, and
  human-approved deploy. No MCD/Track A production connection, no Clerk/PHI,
  no real vendors, no registry push to Track A identities.
- **Rationale:** Advances past D1 after company private remote exists.
- **Supersedes:** None. D3+ remain gated.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message `I authorize D2` dated
  2026-09-02.
- **Implementation impact:** Owner selected D2 depth **3** (IaC scaffold only),
  region **B** (`eastus`, RG `cosmaneura-os-synth`, subscription
  `bab2a709-1fcb-4c87-a9fc-802f7477ec13`), tooling **1** (Terraform). No
  `terraform apply` until a later explicit deploy message. Design:
  `docs/superpowers/specs/2026-09-02-d2-terraform-scaffold-design.md`; plan:
  `.azure/deployment-plan.md`.

### DL-20260902-09

- **Status:** ACCEPTED
- **Ruling:** Owner authorized D2 live apply via exact message `deploy now` —
  create OS-named non-PHI synth resources in subscription
  `bab2a709-1fcb-4c87-a9fc-802f7477ec13`, region `eastus`, RG
  `cosmaneura-os-synth` only. No Track A mutation, no Clerk/PHI/vendors, no
  MCD production join.
- **Rationale:** Completes the gated apply step after validated Terraform
  scaffold.
- **Supersedes:** The “no apply” clause of the D2 depth-3 scaffold choice only.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message `deploy now` dated
  2026-09-02.
- **Implementation impact:** `terraform apply` for `infra/`; retain secrets out
  of git; record outputs in BUILD_REPORT / deployment-plan.

### DL-20260903-01

- **Status:** ACCEPTED
- **Ruling:** Owner authorized repository hygiene for the existing D2 tree:
  tighten ignores, correct D2 documentation, commit and push the non-secret
  D2 source and evidence to `CosmaNeura/cosmaneura-os` `main`, and verify
  `synth-ci`. The handoff confirms that most D2 resources remain in `eastus`,
  PostgreSQL recovered in `centralus` after `ParameterOutOfRange`, and the
  prior `deploy now` authorization is consumed. This authorization does not
  permit Azure mutation, ACR push, app wiring, vendor activation, PHI, or
  Track A changes.
- **Rationale:** Preserve the already-applied non-PHI D2 infrastructure source
  and handoff in the company repository before any later gated phase.
- **Supersedes:** None. D2 residual and D3-D6 remain separately gated.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Owner pasted the Codex D3-to-complete-build
  handoff containing the explicit hygiene gate on 2026-09-03.
- **Implementation impact:** Commit and push the current D2 docs, Terraform,
  deployment plan, and handoff without local secrets, state, tools, or plan
  artifacts; require green GitHub Actions on the pushed SHA. D2 residual work
  remains blocked until `AUTHORIZE D2 ACR PUSH AND APP WIRING`.

### DL-20260903-02

- **Status:** ACCEPTED
- **Ruling:** Owner authorized the D2 non-PHI synth residual via the exact
  phrase `AUTHORIZE D2 ACR PUSH AND APP WIRING`: build and push the Track B OS
  image only to `cosmasossynthacrrkpt0e.azurecr.io`, digest-pin API and worker,
  wire the existing synth PostgreSQL/Redis settings through Key Vault and the
  OS managed identity, migrate the synth `cosmas_os` database, and smoke-test
  the API and worker. Review a Terraform plan before applying app/image/secret
  changes.
- **Rationale:** Replace the D2 placeholder runtime with the already-built
  synthetic product while preserving the phase and repository boundaries.
- **Supersedes:** The D2-residual prohibition in `DL-20260903-01` only. D3-D6,
  destroy, Clerk, vendors, PHI, and Track A remain separately gated.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message
  `AUTHORIZE D2 ACR PUSH AND APP WIRING` dated 2026-09-03.
- **Implementation impact:** Produce an immutable ACR digest, update only the
  OS synth Terraform configuration/state after showing its sanitized plan,
  run additive migrations with invented data only, verify `/health` returns
  `synth_os`, verify the worker process, and document the rollback digest.
