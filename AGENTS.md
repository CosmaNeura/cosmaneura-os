# AGENTS.md - Cosmas OS Track B guardrails

## Objective

Build and validate a simple, usable practice computer without destabilizing
Track A. Development data in this repository stays synthetic.

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

John Clemente approved passing the Phase 0 docs-only limit. Agents may write
code, install dependencies, and run tests in this repository.

Before that approval, agents could edit only the eight Phase 0 files under
`docs/validation/` until the owner message `APPROVE LOCAL SYNTH BUILD`, and
could not scaffold code, install dependencies, or run tests. That limit is
marked passed:

```text
BUILD_GATE: LOCAL_SYNTH_BUILD_APPROVED
```

Do not edit another repository. Authority for infrastructure, live Clerk
settings, signed Mac and iPhone builds, and production deploy is the October
30, 2026 decision in the next section.

## Owner decision, October 30, 2026

On Friday, October 30, 2026, at 9:04am ET, John Clemente, CEO, decided that
Cursor agents working in this repository may do the following without asking
John or Shawn first:

1. Apply infrastructure changes.
2. Change live Clerk settings.
3. Publish signed Mac and iPhone builds.
4. Deploy to production.

Agents work from branch to finish line. They branch, commit, push their own
branch, open a pull request, fix CI, and keep going. They stop only when a
required credential or physical device is not available to them.

Development, tests, logs, notes, commits, and chat use synthetic patient data
only. Never put real patient data in code history.

Agents keep CI, Trivy scanning, and the main branch ruleset intact. Agents do
not force-push `main`. When an unexpected owner change is already in the tree,
agents leave that change in place and continue the rest of the work.

This decision is also recorded as `DL-20261030-01`.

## Repository boundary

- This repository is the only writable workspace.
- Legacy repositories are read-only evidence.
- Never edit, format, branch, commit, migrate, or push a legacy repository.
- No direct legacy database access, source import, shared migration ownership,
  or shared Terraform state. Infrastructure and deploy work for this product
  stays in this repository.
- Future integration is a narrow versioned HTTPS/OpenAPI or first-party MCP
  contract.

## Data and credential boundary

Product runtime and coding agents are different.

- Product runtime. CosmaBot / Cosmas, running in a customer's production
  environment, may handle and pass real patient data between its own agents
  when the product requires it. That handling sits under the customer's
  agreement and the product's own security controls. Code may be written to
  do that.
- Coding agents, including Cursor agents writing this repository. Use invented
  or synthetic patient data. Do not put real patient details in code, tests,
  fixtures, commits, pull request text, logs, screenshots, reports, or chat.
  Do not ask John, Shawn, or anyone else to confirm that data is synthetic or
  non-PHI. Use synthetic data and continue.

Do not commit credentials, `.env` values, database dumps, vendor tokens, or
real production identifiers.

Cursor agents may apply infrastructure changes, change live Clerk settings,
publish signed Mac and iPhone builds, and deploy to production without asking
John or Shawn first, as recorded on October 30, 2026. That authority still
forbids copying real patient data into code, tests, fixtures, commits, pull
request text, logs, or chat.

Use invented people, appointments, identifiers, images, and money in synth
work.

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
- Preserve unexpected owner changes. Leave those edits in place and continue
  the rest of the work.
- Keep changes small and testable; separate unrelated outcomes.
- Tests must prove failure and recovery paths, not only happy paths.
- Never claim a command passed unless it ran and its output was checked.
- Record assumptions and exact evidence.
- Branch, commit, push the agent's own branch, open a pull request, and fix CI
  until the task reaches its finish line. Stop only when a required credential
  or physical device is not available.
- Do not force-push `main`.
- Do not weaken CI, Trivy scanning, or the main branch ruleset.
- Apply infrastructure, change live Clerk settings, publish signed Mac and
  iPhone builds, and deploy to production when the task calls for them.
- Draft-light CI: run the relevant tests inside the cloud agent before
  pushing; push once per round. A red `synth-ci-gate` on an unlabelled draft
  means light mode, not a CI failure. Add the `ci:full` label before asking
  for Fable review. Never post commit statuses or check runs. Never add
  workflow files on branches. Do not treat a cancelled superseded draft run
  as a product defect. Adding any label to a PR re-triggers Synth CI and
  cancels the run in flight.

## Risk discipline

Treat identity/authority, PHI paths, patient messaging, retention, schema,
external side effects, deployment, and cross-repository contracts as high-risk.
They require explicit tests and recovery behavior. Agents carry that work
through under the October 30, 2026 decision.

## Install, lint, and tests

From the repository root. These commands match `.github/workflows/synth-ci.yml`.
They do not need secrets or real keys. Backend checks start a temporary
database and invent their own password. Cloud agents prepare a fresh machine
with the `install` command in `.cursor/environment.json`. That install adds
Redis when `redis-server` is missing. The `start` command runs
`scripts/start-cloud-agent-services.sh`, which starts Postgres on
`127.0.0.1:54329` (database `cosmas_os`) and Redis on `127.0.0.1:63799` when
those ports are not already accepting connections.

Install:

```bash
uv sync --extra dev --extra efax-inbound --extra mcp --extra calendar-import
./scripts/install-client-deps.sh
```

Lint:

```bash
uv run ruff check src tests
uv run pyright src
```

Tests. Repeat the backend command once for each suite: `backend-1`,
`backend-2`, `backend-3`, `backend-4`, `signed-ui-1`, `signed-ui-2`,
`signed-ui-3`. On this machine `pg_config --bindir` is
`/usr/lib/postgresql/16/bin`.

```bash
uv run python scripts/check-backend-local.py --suite backend-1 --postgres-bin "$(pg_config --bindir)" --pytest-timeout 3600 --stack-dump-after 300
cd web && corepack pnpm test
```

## Coding rules from review findings (Fable, 12 Nov 2026)
These come from Fable's most common review holes. Breaking one is a HOLE in review. The full review policy is in docs/review-policy.md.

### 1. Tests must kill mutations (most common hole)
- DO: for every guard, fence, refusal or validator you add or change, write a test that FAILS if
  the condition is inverted, the branch is deleted, the early return is removed, or the constant changes.
- DO: list the mutations you tried and the test that caught each one in the PR body.
- DON'T: rely on string checks that a file "contains" a guard. Test the behaviour.
- DON'T: wrap test helpers in broad `except`/`BaseException` blocks that swallow assertion errors.

### 2. Every proving test must run in CI
- DO: make sure every test the PR relies on as proof is collected by a CI workflow or wrapper
  at the PR's head (pytest paths, node `*.test.mjs`, Swift tests). Name the job that runs it.
- DO: if CI can't run it (Mac or Simulator only), say so in the PR body and attach the run log.
- DON'T: add a test file that no workflow runs and count it as proof.

### 3. Keep validators in parity
- DO: when the same rule lives in more than one place (Python, JS/Node, Swift, Terraform, shell),
  change all of them in the same PR, and keep a parity test that parses each copy and fails on drift
  (hosts, allow-lists, profile names, counts).
- DON'T: update one language's validator and leave another for later.

### 4. No raw paths around profile-aware loaders
- DO: read profiles, settings and identities only through the profile-aware loader.
- DON'T: call a raw validator, read the file directly, match by substring, or add an exemption
  list that skips the guard or scan. If you need an exception, it needs its own test and a line in the PR body.

### 5. Test every fence on both sides
- DO: test both the allowed path and the refused path of every fence, flag and refusal,
  including the unknown or omitted profile case.
- DO: make fail-closed paths actually closed: no silent fallback, no swallowed error,
  no `continue-on-error`.

### 6. Match identities against what actually shipped
- DO: check bundle IDs, Clerk hosts, keychain names, profile names, file counts and hashes
  against the built artifact (composed Info.plist, composition.json, rendered env), not only the source.
- DO: when a count or hash pin changes, explain exactly which files caused it.
- DON'T: change a shipped identity for existing live users unless John named that change.

### 7. Docs, citations and scope
- DO: update comments, docs and file:line citations in the same PR as the code they describe.
- DO: list every changed file outside the ticket's stated scope in the PR body, with a reason.

### 8. Before you push
- Run the relevant tests in your agent first, and push once per round.
- Synthetic data only, never PHI. No new secrets, no model changes, no CI or ruleset weakening.
- On high-risk tickets (docs/review-policy.md section 2a), wait for Fable's plan PASS before the first push.
