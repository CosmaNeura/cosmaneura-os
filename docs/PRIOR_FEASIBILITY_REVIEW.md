# Consolidated prior feasibility review

This memo combines the product, architecture, and adversarial review already
performed before the Cursor handoff. Cursor must independently revalidate it.

## Overall conclusion

The product concept and core technical direction are feasible. A modular
monolith using the existing Python/FastAPI/Postgres/Celery/Redis conventions can
support an L0 practice Box, shared F-8 workflow, local operation ledger, and
ports/adapters.

The realistic near-term outcome is a local synthetic vertical slice followed by
one carefully bounded early-adopter Box. The full 120-day vision is feasible
only as gated increments; it is not credible if every optional adapter, native
client, evidence zone, and EHR rung is treated as concurrent scope.

## Validated strengths

- One shared approval-and-action loop instead of feature-specific queues
- Human authority for clinical and system-of-record actions
- L0-first ladders that avoid making Athena certification a product dependency
- Ports that isolate vendor-specific integration work
- Separate synth, beta, and production environments
- Synthetic-only agent development with zero production credentials
- Reuse of an established language, cloud, database, worker, and identity stack
- Explicit retention intentions and graceful degradation when ports are dark
- Flat SaaS economics rather than revenue share
- Internal-first workflow that does not expose infrastructure complexity to a
  small practice

## Findings reconciled by the owner

- V1 is insurance ArtifactChase, not payment recovery.
- Pricing is flat SaaS; recovered dollars are not the V1 KPI.
- The Org is the computer Box. Redundant tenant columns are not required inside
  a truly exclusive Box data store.
- The owner is a human login; Scribe, Chief, and Chaser are installed baseline
  agent principals that the owner may remove.
- Local execution is preferred initially; reliable idempotency can be provided
  by a small Postgres operation ledger without distributed infrastructure.
- Compliance must be capability-gated and largely invisible rather than a
  universal administrative burden.
- Track A and Track B are both viable. Track A remains the survival priority;
  Track B is a synthetic parallel lane, not its replacement.

## Conditions that remain important

### Box boundary

The Box model is sufficient when its database/schema, storage identity, and
execution context are exclusive. `box_id` must still survive owner transfer and
must accompany data whenever it enters shared logs, queues, blobs, backups,
support tools, or cross-Box services.

### Principal and audit model

Human and agent identities must remain distinguishable. Removing an agent or
human must not destroy historical audit meaning. Clinical approval must route
to the appropriate licensed human even when the account owner controls the Box.

### Approval and execution

Approval should bind an immutable action revision. A worker retry or repeated
click should recover the same operation. An uncertain external outcome should
be reconciled rather than duplicated.

### Patient-facing capability

The internal kernel can be built without solving every future connector. When
patient outreach and upload are enabled, that specific capability needs its
message, consent/configuration, secure-link, upload, and retention prerequisites.

### Physical economics

One logical Box should not silently imply a permanently dedicated full Azure
stack for every one-seat practice. Cursor should estimate beta and later retail
cost without Azure credits and distinguish logical isolation from physical
packing.

## Feasibility by stage

| Stage | Prior verdict |
|---|---|
| Documentation reconciliation | Complete in this handoff; Cursor must verify |
| Local synthetic kernel | High feasibility |
| Synthetic Insurance ArtifactChase | High feasibility |
| Small-practice owner queue | High feasibility with deliberate UX constraint |
| CI with no production credentials | High feasibility |
| Isolated one-clinic L0 beta | Conditional on the enabled capability gates and deployment evidence |
| Athena/Acuity rungs | Technically feasible; timing unvalidated and externally dependent |
| Shared multi-Org production | Deferred; requires a new isolation and unit-economics decision |
| Full AI employee vision | Incrementally feasible, not one release |

## Prior recommendation

Proceed with the separate Track B repository and local synthetic validation.
Do not deploy, connect external systems, or modify Track A during the first
build. Prove one complete workflow, measure approval burden and usability, and
only then raise one connector rung at a time.
