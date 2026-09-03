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

### DL-20260903-03

- **Status:** ACCEPTED
- **Ruling:** Owner authorized D3 planning and implementation via the exact
  phrase `APPROVE D3 ISOLATED EARLY-ADOPTER BETA`. D3 must be a separate,
  isolated environment and must not be an in-place promotion of
  `cosmaneura-os-synth`.
- **Rationale:** Advance from the verified non-PHI D2 runtime toward one
  early-adopter beta while preserving Box, identity, data, and Track A
  boundaries.
- **Supersedes:** None. D4-D6, connector activation, D2 destruction, Track A
  integration, and any PHI use remain separately gated.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message
  `APPROVE D3 ISOLATED EARLY-ADOPTER BETA` dated 2026-09-03.
- **Implementation impact:** Prepare a dedicated D3 resource group, state,
  identity, database, storage scope, workloads, authentication boundary,
  recovery evidence, and capability manifest. Before any D3 Azure mutation or
  PHI-capable deployment, record the real named clinic, its dedicated Box and
  Clerk Organization, applicable BAA prerequisites, and human deploy evidence.
  Never invent these inputs; coding agents receive no live PHI or live
  credentials.

### DL-20260903-04

- **Status:** ACCEPTED
- **Ruling:** The first D3 slice is a non-PHI **Cosmas Beta Lab** for the owner
  and invited outside testers. Identity uses a new, separate Cosmas OS Clerk
  application with Organizations enabled; the existing MyCatholicDoctor Clerk
  application, users, keys, sessions, and domains remain unchanged. The Beta
  Lab Organization maps to one synthetic-only Cosmas Box. The initial
  enrollment path is direct invitation/re-invitation; no MyCatholicDoctor user
  export or bulk migration is authorized.
- **Rationale:** Enables real usability testing without waiting for a named
  clinic, BAA, or PHI authorization and preserves a clean identity and data
  boundary from MyCatholicDoctor.
- **Supersedes:** The named-clinic and BAA prerequisites in the implementation
  impact of `DL-20260903-03` only for a strictly synthetic, non-PHI Beta Lab.
  They remain mandatory before any clinic or PHI-capable deployment.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner message approving the recommended
  synthetic-only Cosmas Beta Lab path dated 2026-09-03.
- **Implementation impact:** Add fail-closed Clerk frontend integration and a
  reviewed multi-user enrollment/offboarding path; deploy only to a separate
  D3 lab boundary with invented data. Testers may review, edit, and decide only
  the fixed invented queue; schedule import, PatientLink creation, new chase
  creation, and uploads remain blocked in `synthetic_lab`. Keep all non-auth
  external connectors dark, keep MyCatholicDoctor and Track A untouched, and
  require separate human approval and handling before any bulk user migration.

### DL-20260903-05

- **Status:** ACCEPTED
- **Ruling:** Owner explicitly authorized creation of a new **Cosmas OS** Clerk
  application in the CosmaNeura account with B2B project type, email-only
  authentication, and Organizations enabled, followed by configuration of the
  synthetic **Cosmas Beta Lab** Organization. MyCatholicDoctor provider testers
  and any user migration are deferred until the application is closer to
  functional.
- **Rationale:** Establish the isolated identity boundary needed for the
  synthetic lab without touching the existing Cosmas/MyCatholicDoctor identity
  environment or inviting users prematurely.
- **Supersedes:** The prohibition on creating the specific new Clerk structure
  in `DL-20260903-04`; it does not authorize production-domain invention,
  invitations, bulk migration, Track A access, PHI, or connector activation.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner confirmation dated 2026-09-03.
- **Implementation impact:** A separate Cosmas OS development application and
  zero-member Cosmas Beta Lab Organization were created. Email verification-code
  login, invite-only access, required Organization membership, disabled
  user-created Organizations, and session audience `cosmas-os-beta-api` were
  configured. The existing Cosmas application was not changed. Production
  instance creation remains blocked on the exact approved HTTPS application
  domain; no placeholder domain was entered and no invitation was sent.

### DL-20260903-06

- **Status:** ACCEPTED
- **Ruling:** Add a native mobile closed-beta tranche after the browser-based
  D3 gate and before the D4 one-clinic pilot. Package the proven web approval
  queue with Capacitor for iOS TestFlight and Android closed testing; preserve
  the same synthetic-only authorization until a separate PHI gate is approved.
- **Rationale:** Mobile access is part of the product roadmap, but validating
  the shared browser workflow and identity boundary first avoids creating two
  platform-specific failure surfaces during the initial D3 deployment.
- **Supersedes:** The indefinite mobile deferral in the roadmap scope cuts;
  mobile remains outside the initial D3 web launch and all current cloud work.
- **Affected contract version:** 1.9-draft
- **Owner acceptance evidence:** Direct owner agreement with the recommended
  post-D3, pre-D4 placement dated 2026-09-03.
- **Implementation impact:** Add Deployment 3M with TestFlight and Android
  closed-test gates, encrypted short-lived device storage, mobile identity and
  offboarding tests, store-release evidence, and a separately reviewed Scribe
  integration. No mobile build, store enrollment, signing, or upload is
  authorized by this scheduling decision alone.
