# AGENTS.md - Cosmas OS Track B guardrails

## Objective

Build and validate a simple, usable practice computer without destabilizing
Track A. The initial repository is synthetic-only and local-only.

## Authority

1. Direct owner instructions
2. `CANONICAL_PRODUCT_DECISIONS.md`
3. Accepted entries in `docs/DECISION_LOG.md`
4. `docs/CANONICAL_ARCHITECTURE_CONTRACT.md`
5. Current code/config evidence for factual implementation claims
6. Uploaded and legacy documents as historical/reference evidence

Never silently substitute a preferred design for a locked decision. A challenge
must identify a concrete fatal counterexample and the smallest compatible
alternative.

## Mandatory phase gate

Before the exact owner message `APPROVE LOCAL SYNTH BUILD`, agents may edit only
the eight Phase 0 files under `docs/validation/`.

They must not scaffold code, install dependencies, run containers, initialize a
remote, or edit another repository. Phase 0 ends with:

```text
BUILD_GATE: WAITING_FOR_OWNER_APPROVAL
```

## Repository boundary

- This repository is the only writable workspace.
- Legacy repositories are read-only evidence.
- Never edit, format, branch, commit, migrate, or push a legacy repository.
- No direct legacy database access, source import, shared migration ownership,
  shared Terraform state, or production deployment identity.
- Future integration is a narrow versioned HTTPS/OpenAPI or first-party MCP
  contract.

## Data and credential boundary

Never place PHI, real patient information, production-like exports, production
identifiers, credentials, `.env` values, database dumps, or vendor tokens in
this repository, prompts, fixtures, tests, logs, screenshots, or reports.

Do not access or mutate Azure, Clerk, Stripe, Athena, Acuity, production
databases, external messaging services, or GitHub production identities without
a later direct owner instruction.

Use invented people, appointments, identifiers, images, and money in synth.

## Product invariants

- One legal Org equals one logical Box.
- The Box identity is the permanent audit root.
- Humans and agents are distinct principal types.
- Agents cannot self-approve, impersonate humans, sign, or submit system-of-
  record work as a human.
- Baseline agents may be disabled/removed, but historical identity is tombstoned.
- F-8 is the only queue and approval substrate.
- Approval binds an immutable action revision and exact payload hash.
- Editing invalidates prior approval.
- Postgres is authoritative for operation intent; worker retries reuse the same
  operation.
- Internal L0 uses fake/local ports.
- External capabilities remain dark until separately activated.
- Pricing is flat SaaS; v1 is insurance ArtifactChase, not payment recovery.
- Product/runtime code must not depend on Cursor's GPT-5.6 SOL endpoint.

## Architecture style after approval

- Prefer a modular monolith.
- Keep domain and application logic independent of FastAPI, Celery, Clerk,
  Azure, Athena, Acuity, and messaging SDKs.
- Use explicit ports and local fake adapters first.
- Use additive migrations and database constraints for invariants.
- Keep Redis/Celery as transport, never the authoritative business record.
- Keep normal UX centered on work and outcomes, not infrastructure or
  compliance vocabulary.
- Do not add Kubernetes, Kafka, a second cloud/IdP, browser automation,
  consumer messengers, payment/PAN, or generalized event sourcing.

## Engineering behavior

- Inspect before changing.
- Preserve unexpected owner changes and stop before overwriting them.
- Keep changes small and testable; separate unrelated outcomes.
- Tests must prove failure and recovery paths, not only happy paths.
- Never claim a command passed unless it ran and its output was checked.
- Record assumptions and exact evidence.
- Do not push, deploy, create cloud resources, or connect real vendors during
  the local synthetic mandate.

## Risk discipline

Treat identity/authority, PHI paths, patient messaging, retention, schema,
external side effects, deployment, and cross-repository contracts as high-risk.
They require explicit tests, recovery behavior, and owner review before a real
environment is considered.
