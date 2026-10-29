# Build and deployment roadmap

Status: Phase 0 validation is complete. John Clemente approved local code,
installs, and tests. This roadmap does not authorize a deploy.

The roadmap is gate-driven. Calendar ranges are planning hypotheses, not
promises. External-system timing is never treated as an engineering estimate.

The single owner phrase `APPROVE LOCAL SYNTH BUILD` authorizes creation Roadmap
Phases 1 and 2 as one local mandate. Gate 1 is a mandatory internal checkpoint;
failure stops the build, but success does not require a second owner phrase.
Phase 3 hardening may continue only to the extent approved in the Phase 0 build
gate. Nothing in this document authorizes cloud deployment.

## Track boundaries

### Track A - existing repositories

Continues independently:

- production stabilization and IAM;
- existing Scribe and history;
- $60/provider-seat conversion;
- launch preparation and current feature work;
- current production deployment and operations.

### Track B - this repository

Owns:

- Box/principal/charter substrate;
- F-8 queue and approval;
- local operation ledger;
- synthetic Insurance ArtifactChase;
- future OS ports/adapters;
- OS-specific audit and deployment.

Track B never writes Track A during the initial build. Track A never imports
Track B during this task.

## Creation roadmap

### Phase 0 - independent revalidation

Indicative range: 1-3 focused days, depending on source availability.

Deliverables:

- complete source and workspace inventory;
- reconciled authority/conflict register;
- technical feasibility report;
- validated target architecture;
- revised creation and deployment roadmaps;
- cost/usability analysis;
- explicit build gate.

Exit gate:

- no unresolved fatal contradiction;
- owner approval `APPROVE LOCAL SYNTH BUILD` has been given.

The Phase 0 ban on product code, dependency installation, and container start
has passed. Deploys and IaC apply still need a yes from John or Shawn.

### Phase 1 - local synthetic foundation

Indicative range after approval: 1-2 weeks for a focused implementation,
subject to Cursor's validation.

Proposed stack:

- modular FastAPI application;
- Postgres and migrations;
- Redis/Celery only if confirmed as the simplest compatible worker pattern;
- local Blob adapter or Azurite if its value justifies the dependency;
- smallest useful owner queue;
- Docker Compose;
- deterministic synthetic fixtures.

Implement:

- singleton `BoxContext` provisioning;
- `Principal`, `HumanSeat`, and `AgentInstallation`;
- enable/disable/tombstone behavior;
- versioned charters/configuration;
- F-8 state machine;
- immutable action revisions and decisions;
- append-only audit rows;
- local operation ledger and worker recovery;
- fake/local ports;
- no real auth or vendor connection.

Gate 1:

- a clean clone starts with one documented command;
- migrations apply to an empty database;
- one fake Box is provisioned deterministically;
- all tests pass without credentials or network access;
- fixture scan and manual review find no PHI or production identifiers.

### Phase 2 - complete synthetic ArtifactChase slice

Indicative range: 1-2 additional weeks.

Workflow:

1. Import synthetic appointments through manual/CSV `SchedulePort` L0.
2. Human attests a synthetic `PatientLink`.
3. Chaser detects a missing artifact.
4. F-8 creates a ticket and neutral message revision.
5. Owner approves, edits, rejects, or escalates.
6. Approved revision creates one local operation.
7. Fake `NotifyPort` records a delivery outcome.
8. Synthetic front/back images enter the local artifact store.
9. Human verifies and marks `IMAGE_ON_FILE`.
10. Ticket closes and audit timeline reconstructs the work.
11. Test clock advances and the purge worker deletes working copies while
    retaining a non-PHI deletion receipt.

Required failure demonstrations:

- unconfirmed patient link;
- edit invalidating approval;
- duplicate click;
- worker crash/restart;
- unknown delivery result;
- rejection and escalation;
- disabled Chaser;
- purge retry.

Gate 2:

- no duplicate logical send under repeated click/retry;
- no agent self-approval;
- exact executed revision matches approval;
- no infrastructure identifiers in normal UI;
- complete happy-path and failure-path E2E tests pass.

### Phase 3 - local usability and release hardening

Indicative range: 1-3 weeks of iteration with realistic synthetic workdays.

Focus:

- short first-run setup;
- one clear queue;
- intelligible exact or batch approval;
- background recovery invisible unless attention is required;
- failed connector work remains actionable;
- agent removal is understandable and reversible through reinstall;
- audit is available without becoming the primary UI.

CI should include only useful gates:

- formatting/lint/type check;
- unit and integration tests;
- migration graph/apply test;
- contract tests for ports;
- selected E2E flows;
- secret/fixture scan;
- container build;
- required jobs fail when skipped.

Gate 3:

- owner can demonstrate the complete workflow without developer assistance;
- measured queue/approval effort is less than the synthetic work it replaces;
- release artifact is reproducible and pinned;
- recovery and rollback are documented.

## Deployment roadmap

### Deployment 0 - local only

- Docker Compose and synthetic fixtures.
- Fake adapters only.
- No cloud/vendor credentials.
- Product shape may change quickly.

This is the only deployment authorized by the initial Cursor build approval.

### Deployment 1 - synthetic CI/release artifact

- Build a pinned container image.
- Record image digest and source revision.
- Apply migrations to an ephemeral database.
- Run full synthetic tests.
- Emit a release manifest.
- Do not deploy automatically.

Gate:

- same artifact passes local and CI;
- rollback and migration recovery are documented;
- no production secret is needed.

### Deployment 2 - optional non-PHI Azure development

Only after a separate owner decision:

- use OS-named resources and identity only;
- follow verified current Azure patterns rather than inventing a new platform;
- contain synthetic data;
- human-approved deployment;
- no connection to MCD production.

This environment is optional. It should not exist merely to make the roadmap
look cloud-complete.

### Deployment 3 - isolated early-adopter beta

Only after a separate deployment approval and validated capability manifest.

Likely components, subject to Phase 0/current evidence:

- API workload;
- worker workload;
- Postgres;
- Redis if still required;
- isolated Blob storage;
- Key Vault;
- minimal PHI-safe monitoring;
- Clerk Org;
- dedicated beta deployment identity.

The first D3 slice is the synthetic-only Cosmas Beta Lab. It receives one
isolated Box/database or schema/storage boundary; shared logs, backups, blobs,
jobs, and support tooling carry `box_id`. Any later clinic deployment uses a
separate `authorized_beta` evidence gate and must not reuse the lab boundary.

Gate:

- applicable enabled-capability prerequisites complete;
- login and authority matrix demonstrated;
- audit replay, purge, backup/restore and rollback demonstrated;
- no coding agent has live PHI or credentials;
- parametric cost ranges and support assumptions show at least one plausible
  flat-SaaS packing scenario without Azure credits; exact pricing remains an
  owner decision.

### Deployment 3M - native mobile closed beta

After the browser-based D3 gate passes and before the one-clinic D4 pilot,
package the proven web queue as the roadmap's Capacitor approver shell. This
tranche does not delay the initial D3 web launch and does not expand its
synthetic-only data authorization.

- iOS distribution through TestFlight;
- Android distribution through a closed testing track;
- approve, edit, reject, and queue review on device;
- encrypted device storage with a short retention period;
- no persistent bearer tokens, PHI, or production credentials in app bundles;
- reuse Scribe capture only after its separate interface and security review.

Gate:

- D3 browser workflow, identity boundary, and rollback have passed first;
- physical-device authentication, Organization switching, session revocation,
  offboarding, upgrade, and rollback tests pass on both platforms;
- store signing, privacy disclosures, tester cohorts, and support ownership are
  human-controlled and documented.

### Deployment 4 - one-clinic L0 pilot

Enable only what is needed:

- owner/approver and baseline agents;
- queue;
- manual/CSV schedule input;
- in-app/staff channel or one deliberately approved patient channel;
- insurance working-copy flow;
- no EHR write.

Measure:

- artifacts complete before visits;
- staff minutes saved;
- approval/edit/reject time;
- wrong or duplicate outreach;
- visits preserved;
- support burden;
- paid retention where applicable.

Gate:

- workflow saves more time than setup/approval consumes;
- no wrong-patient or duplicate-send safety event;
- support and infrastructure cost support flat-SaaS economics.

### Deployment 5 - connector rungs

Add one adapter at a time:

1. `SchedulePort`: manual/CSV -> confirmed Acuity or Athena read.
2. `RecordPort`: read -> document attach -> later governed structured action.
3. `NotifyPort`: fake/in-app -> secure email -> A2P SMS.
4. Track A Scribe/tool receiver.
5. Teams pointer-only adapter if evidence still supports it.

Each adapter requires:

- fake and sandbox contract tests;
- bounded timeout and retry behavior;
- explicit `UNKNOWN` reconciliation;
- capability manifest and prerequisites;
- graceful degradation to L0;
- human-reviewed activation.

No adapter is allowed to corrupt F-8 state or make L0 unavailable.

### Deployment 6 - Track A integration

Waits for Track A's own IAM and human-review gates.

- receiver-first versioned contract;
- no direct database;
- no shared migrations, deploy identity, or secrets;
- Master remains usable when OS is unavailable;
- OS retains work when Master is unavailable;
- integration changes to Track A use its own review/deploy doctrine.

## Scope cuts that protect usability and delivery

Defer until the local loop earns expansion:

- native mobile/Capacitor;
- Teams;
- open-web evidence retrieval;
- real WorkbookPort/RRM demo;
- payments and PAN;
- claims/prescriptions;
- second EHR;
- browser automation;
- shared multi-Org runtime;
- Kubernetes, Kafka, microservices or a generalized event-sourcing platform;
- full self-service onboarding;
- rebuilding Scribe.

## Kill/reconsider signals

Reconsider the slice or product claim if:

- approval and setup consume as much work as the workflow saves;
- the practice cannot understand what an agent will do before approval;
- safe retry requires manual intervention on ordinary operations;
- the Box abstraction cannot be kept separate from infrastructure jargon;
- a realistic flat-SaaS cost model fails without credits;
- the first workflow depends on an external clock despite an L0 alternative;
- Track B work begins delaying Track A survival work.
