# Canonical product decisions

Status: reconciled owner rulings for Cursor revalidation  
Date: 2026-11-17  
Working version: 1.10-draft

These decisions supersede contradictory statements in the uploaded roadmap,
context pack, brief, and JSON pack. Cursor must challenge a locked decision only
when it can show a concrete fatal counterexample. Preference for another design
is not a fatal counterexample.

## Authority

For this repository, use this order:

1. Direct owner instructions issued after this file.
2. This decision file.
3. Accepted, dated entries in `docs/DECISION_LOG.md`.
4. `docs/CANONICAL_ARCHITECTURE_CONTRACT.md`.
5. Current code/configuration evidence for claims about existing systems.
6. Uploaded product documents as reference and historical rationale.

Code evidence can disprove a claim about what an existing system does. It does
not silently override a product ruling.

## Locked decisions

### D-001 - Separate Track B repository

Cosmas OS lives in a private repository named `cosmaneura-os`.

- It has no shared Git history, database, migrations, deployment identity, or
  Terraform state with Track A.
- Cursor writes only in this repository.
- Legacy repositories may be inspected read-only.
- Future integration uses a narrow, versioned authenticated contract.

### D-002 - Dual-track ownership

Track A remains responsible for company-survival work: production
stabilization, launch preparation, the existing Scribe, the $60 provider-seat
conversion, existing history, IAM remediation, and production operations.

Track B owns the new practice-computer substrate: F-8, the queue, installed
agents, the local operation ledger, Insurance ArtifactChase, and future ports.

Track B does not delay Track A. If staffing forces a choice, Track A wins.

### D-003 - Flat SaaS and Insurance ArtifactChase

- ArtifactChase v1 chases missing, stale, or unverified insurance artifacts.
- V1 is not payment-card recovery.
- Commercial pricing is flat SaaS. Exact tiers and packaging remain open.
- No percentage-of-recovery, professional-fee share, or recovered-dollar
  pricing is implemented.
- Payment recovery is a future disabled adapter and handles no PAN in v1.
- V1 metrics are artifact readiness before visits, staff time saved, chase
  completion, visits preserved, approval time, duplicate/incorrect outreach,
  support burden, and paid retention.

### D-004 - One legal Org equals one logical Box

An Org is the covered-entity or BAA-scoped legal practice boundary, not a
marketing brand. One Org owns one logical Cosmas computer Box.

The Box is the execution, data, policy, queue, and audit context. It is not one
VM per user.

The initial owner-seat binding bootstraps the Box. In v1, `box_id` is the stable
system representation of the Org ID, not a second tenant identifier. It remains
the permanent audit root so ownership can later transfer without rewriting
history.

When one database/schema is exclusive to one Box, child records may inherit Box
scope and need not repeat `org_id`. At every shared boundary - logs, centralized
queues, blob namespaces, backups, support tooling, cross-Box coordination, or a
future shared database - Box scope must be explicit and enforced.

### D-005 - Humans and agents are distinct principals

Use one internal `Principal` abstraction with non-interchangeable subtypes:

- `HumanSeat`: a human login and its grants.
- `AgentPrincipal`: an installed Scribe, Chief, Chaser, or later capability.

Agent principals cannot authenticate as humans, approve themselves, sign, or
submit system-of-record actions as a human. Clinical submissions require the
appropriate licensed human. Administrative work routes to the configured
owner or operations approver.

### D-006 - Baseline agents are installed but owner-removable

Scribe, Chief, and Chaser may be installed by default because their functions
are broadly reusable. The owner may disable or remove them from active use.

Removal is a product-level delete but an internal tombstone: historical audit
identity and version references remain readable. Reinstallation creates a new
installation identity or version.

### D-007 - Policy precedence

Effective behavior resolves in this order:

```text
non-removable platform safety rules
-> universal agent charter
-> specialty policy overlay
-> Org-owner configuration
```

Lower layers may restrict behavior but cannot grant authority forbidden above
them. Deny wins. Actions pin the policy and charter versions used.

### D-008 - F-8 is the only user-facing work and approval substrate

Features create tickets and immutable action revisions. They do not implement
feature-local queues. Authentication, reads, and inbound observations do not
require human approval merely to occur; they remain scoped and auditable and
may create F-8 work. Outbound side-effecting mutations pass deterministic
authorization and the operation ledger.

For the initial Insurance ArtifactChase slice, a human approves the exact
action revision or a clearly displayed batch of exact revisions. Editing a
payload invalidates the prior approval.

Standing `AUTO_TEMPLATE` authority remains disabled in the first slice.
`AUTO_DRAFT` remains on the staff surface. System-of-record writes always
require the named human.

### D-009 - Local reliable execution first

L0 uses a Postgres-backed operation ledger and the existing worker pattern if
validated. Kafka, Service Bus, and a generalized distributed event platform
are out of scope.

Approval atomically creates a stable operation intent. Repeated clicks and
worker retries reuse the same operation. Changed payloads create new revisions
and approvals. Unknown external outcomes are reconciled rather than blindly
repeated.

### D-010 - Internal-first, capability-gated compliance

The internal work loop is built first. Compliance obligations attach to the
capabilities that cause them and remain dark when those capabilities are dark.

Baseline controls such as identity boundaries, auditability, deterministic
authorization, secret hygiene, safe logging, backups, and retention are
invisible platform defaults. Patient messaging, uploads, external processors,
Athena/Acuity, payment, Teams, and evidence retrieval each carry their own
activation prerequisites.

Owner setup remains small:

1. Choose or enable an agent.
2. Choose its approver.
3. Enable allowed channels.
4. Confirm the practice policy.

### D-011 - Ports and independent ladders

Domain code depends on ports rather than vendor SDKs. Port rungs advance
independently by Box.

The initial build uses fake/local `AuthPort`, `SchedulePort`, `RecordPort`,
`NotifyPort`, and `BlobPort` implementations. Athena, Acuity, real email/SMS,
A2P, Teams, payments, and evidence retrieval are not part of the first slice.

### D-012 - Three environments

- `synth_os`: local/CI, synthetic fixtures, zero PHI and production credentials,
  Cursor development allowed.
- `early_adopter_beta`: isolated OS environment, human deployment, capability-
  specific prerequisites, no coding-agent access to live PHI or credentials.
- `cosmas_mcd_prod`: remains Track A; OS reaches it only through a later
  approved contract after the production IAM gate.

### D-013 - Product usability is a design constraint

Infrastructure, tenant identifiers, operation IDs, queues, and compliance
vocabulary do not appear in normal practice workflow. The primary interface is
the clinic's work queue. Safety and retry machinery should be invisible until
human attention is genuinely required.

### DL-20261117-01 - Owner decisions, November 17, 2026

John Clemente, CEO, November 17, 2026. Recorded in `docs/DECISION_LOG.md`
as `DL-20261117-01`.

PENDING / OPEN-JOHN (Fable H4): the precise definition of "this workstream"
awaits John's confirmation. Do not invent a scope sentence until then.

Items 6 and 7 incorporate the owner follow-up recorded as `DL-20261117-02`.

These decisions set product scope. They do not change the build gate or
the synthetic-data rule. Build and test against invented pages and
invented patients only.

1. A read-only browser extension that reads pages in the signed-in user's
   own browser session is in scope. Unattended automation and agent-held
   EMR logins remain deferred.
2. Provider-triggered form fill is approved for V1, not V0. It fills visible
   fields only after an explicit user click and never clicks Save, Submit,
   Send or Sign.
3. Actions started from the phone stage work at the desktop. They never
   send. CosmaBot never signs or transmits a prescription; it may prepare
   one for the prescriber to sign in the EMR. (N6: "the phone stage" is not
   a lift of the deferred Native mobile/Capacitor item; that remains deferred.)
4. A small on-device model is permitted in the desktop app for three kinds
   of work: perception (recognising screens, patients and changes),
   protection (PHI minimisation, pre-fill checks, mismatch warnings), and
   short on-screen help for staff (what is missing, what changed, call
   notes, answers about what is on screen). It does not draft clinical
   notes, choose codes or make clinical judgments. No model weights of
   Chinese origin, including derivatives. The cloud remains the reasoning
   layer. Every consequential on-device output is verified by code or
   escalated.
   Gloss (Fable N3; owner text unchanged): "call notes" here means short
   on-screen staff help, not drafting clinical notes. "Consequential" means
   any on-device output that could affect a clinical or system-of-record
   action. "Chinese origin, including derivatives" covers developer,
   fine-tune, distillation and quantisation provenance; the specific
   on-device model is still pending John's pick.
5. Desktop targets are Windows and Mac. Development starts on Mac for two
   weeks and moves to Windows from week three. Platform-specific code sits
   behind interfaces. (Fable N4: start date for the two-week Mac window is
   pending; Windows signing and distribution are not covered by the
   October 30 text alone.)
6. PENDING / OPEN-JOHN (Fable H1): Yes, maybe for initial beta we rely on
   legacy but going forward we need independent recording and notes.
   Substance of legacy-for-beta sequencing is awaiting John's decision;
   until then do not treat this line as permission to add, remove or change
   any dependency on the legacy platform.
7. Scribe remains a separate product that shares the recorder. New Scribe
   sign-ups use CosmaBot identity (confirmed, `DL-20261117-02`). This sets
   direction only. Existing Scribe users, their logins and their access
   are not changed, migrated or walled. Turning this on for live sign-ups
   is a live identity change under decision 10.
8. Device compliance checks are deferred to V2 and are described as
   compliance checks, not security monitoring.
9. CosmaBot never asks a practice to disable screen locks or EMR session
   timeouts.
10. For this workstream: no production deploys, no store submissions and no
    live identity changes without my explicit instruction in the task.
    ("my" = John Clemente.)

## Validation-required technology hypothesis

The intended direction is a modular monolith using FastAPI, Postgres,
SQLAlchemy/Alembic or the existing evidence-supported equivalent, Celery,
Redis, Docker Compose, and Pytest, with a simple web queue.

Cursor must validate rather than assume:

- Python 3.12 versus the current legacy requirement of Python 3.13.
- The lowest-complexity UI that remains compatible with current patterns.
- Celery/Redis durability and recovery behavior.
- Azurite versus a simpler local Blob adapter for the first slice.
- Azure Container Apps versus App Service for a later beta.
- OpenAPI/HTTPS versus first-party MCP for the eventual Track A boundary.

## Open owner decisions

- Exact flat-SaaS tiers and seat packaging.
- First early-adopter organization.
- Named approver matrix by work lane and specialty.
- Individual versus displayed-batch approval UX.
- Patient email versus A2P sequencing.
- Actual Athena/Acuity access and practice identifiers.
- Physical packing of Boxes after the first isolated beta.
- Product runtime model/provider.
- Quantitative product graduation and kill thresholds.

Conservative defaults apply until adjudicated: local fake adapters, individual
payload-bound decisions, dedicated first beta Box, no live connectors, no
cross-Box networking, and no automatic patient sends.

## Explicitly deferred

- Kubernetes or microservice decomposition
- Kafka or a generalized event-sourcing platform
- Shared multi-Org runtime
- Second EHR
- Unattended automation and agent-held EMR logins
- Provider-triggered form fill (V1, not V0)
- Evidence/open-web retrieval zone
- Teams
- Native mobile/Capacitor (N6: decision 3's "phone stage" does not lift this)
- Payment-card chase or PAN handling
- Claims
- RRM workbook demo
- Full self-service onboarding
- PENDING / OPEN-JOHN (Fable H1): Rebuilding the existing Scribe inside OS
  (independent recording and notes per DL-20261117-01 item 6 is not this;
  sequencing pending owner decision)
- Device compliance checks (V2; described as compliance checks, not
  security monitoring)
- Signing or transmitting a prescription (never; DL-20261117-01 item 3).
  Stage for prescription preparation is pending.
