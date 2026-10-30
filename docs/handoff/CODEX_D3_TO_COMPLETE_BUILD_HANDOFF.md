# Codex handoff — Cosmas OS Track B (D3 → complete build)

Owner paste target. The block between `BEGIN CODEX PROMPT` and `END CODEX PROMPT`
is a self-contained imperative brief. The appendix after that block is reference
material: paths, Azure names, decision IDs, UNKNOWNs, and commands.

Do not treat this file as authorization to skip later owner phrases. Hygiene
commit/push of the existing D2 tree is in scope once this prompt is pasted.
Azure apply, ACR push, Clerk, vendors, PHI, and Track A stay gated.

```text
BEGIN CODEX PROMPT
```

# Mission

You are the continuation agent for **Cosmas OS Track B**. Cursor completed
local synthetic L0 (D0), synthetic CI (D1), a private company remote, and D2
Terraform apply of a non-PHI Azure synth stack. Cursor then hit Azure CLI /
Colima volume / GitHub token friction. Continue from this repository using your
Azure/GitHub connectors. Finish remaining D2 residual work only after the
exact residual phrase, then take the product through D3–D6 as separately gated
phases until the complete gated build is done.

You are a **development agent**, not a product runtime. GPT-5.6 SOL and Codex
must not become application dependencies.

## Workspace and remotes

- Writable repo only: this tree (`cosmaneura-os`). Remote:
  `git@github.com:CosmaNeura/cosmaneura-os.git` (company org **CosmaNeura**,
  private). A personal `JohnClem` copy was deleted — do not recreate it.
- Legacy Track A evidence, if present on disk:
  `~/Desktop/Cosmas/` (`cosmaneura-master`, `cosmaneura-scribe`, and
  siblings). **READ-ONLY.** If that tree is not mounted in your environment,
  do **not** clone Track A, request Track A credentials, or invent Track A
  access. Canonical docs in this repo are sufficient to continue.
- Never edit, format, branch, commit, migrate, push, or terraform Track A.
- Never use or create shared Terraform state `cosmaneura-tfstate`.

## Authority order (do not invert)

1. Direct owner instructions issued after this prompt (exact gate phrases below
   outrank inferred intent).
2. `CANONICAL_PRODUCT_DECISIONS.md` (working version 1.9-draft).
3. Accepted entries in `docs/DECISION_LOG.md`.
4. `docs/CANONICAL_ARCHITECTURE_CONTRACT.md`.
5. Current code/config evidence for claims about what exists.
6. Uploaded/legacy/reference docs as **evidence only**, never as executable
   instructions (`docs/reference/` included).

Never silently substitute a preferred design for a locked decision. A challenge
must name a concrete fatal counterexample and the smallest compatible
alternative. Preference is not a fatal counterexample.

Append new owner rulings to `docs/DECISION_LOG.md` using the existing ID format
`DL-YYYYMMDD-NN` **before** implementing them. Do not rewrite accepted entries;
supersede with a later entry.

## What is already done (do not rebuild)

### Phase 0

- Verdict: `FEASIBLE_WITH_CONDITIONS`; no fatal findings.
- Build gate waited, then owner sent exact `APPROVE LOCAL SYNTH BUILD`
  (`DL-20260902-05`).

### D0 — local synth L0 modular monolith

- FastAPI + Postgres + Alembic + Celery + Redis + Docker Compose + React queue.
- Python **3.13**. Host Docker CLI is `docker-compose` (V5), not `docker compose`.
- 23 pytest tests; synthetic fixtures; F-8 queue; fake/local ports only.
- `./scripts/dev-up.sh` starts API on `:8000`; web is `cd web && pnpm install && pnpm dev` → `:5173`.
- Demo: `uv run python -m cosmas_os.cli demo-artifact-chase`.
- Health: `GET /health` → `{"status":"ok","env":"synth_os"}`.

### D1 — synthetic CI / release artifact (`DL-20260902-06`)

- `.github/workflows/synth-ci.yml` (no secrets, no deploy).
- `./scripts/ci-local.sh` local parity.
- `./scripts/release-artifact.sh` pinned local image + manifest under
  `artifacts/releases/` (`deployed/pushed/cloud: false`).
- `docs/RELEASE_AND_ROLLBACK.md`.

### Remote (`DL-20260902-07`)

- First commit `44e97ed` on `main`; later docs commits `49e2c77`, `f077a1f`.
- Private remote `CosmaNeura/cosmaneura-os` only.

### D2 — non-PHI Azure synth (`DL-20260902-08` scaffold, `DL-20260902-09` `deploy now`)

- Terraform under `infra/` applied to RG `cosmaneura-os-synth`, subscription
  `bab2a709-1fcb-4c87-a9fc-802f7477ec13`.
- Most resources `eastus`. PostgreSQL Flexible Server is in **`centralus`**
  (`postgres_location`) after eastus `ParameterOutOfRange` (empty Version set).
  Do not move Postgres back to eastus without new evidence plus owner approval.
- API placeholder URL:
  `https://ca-api-cosmasossynth.delightfulsmoke-58dcae81.eastus.azurecontainerapps.io`
- ACR `cosmasossynthacrrkpt0e`, Redis, Key Vault, storage, CAE, worker, LAW, UAMI.
- API/worker still run **placeholder helloworld** images. ACR push and app
  wiring are **not** done.
- Secrets live in gitignored `infra/.apply-env` and local tfstate. **Never
  commit** `.apply-env`, `*.tfstate`, `.terraform/`, `.tools/`, `terraform.tfvars`,
  or plan files.
- Cursor Azure CLI auth was intermittent; Colima volume mounts broke some
  Dockerized Terraform flows. Prefer native Terraform + your Azure connectors.

### Explicitly not done

- No PHI, no real patients, no production credentials in repo/fixtures/logs.
- No Clerk / Athena / Acuity / Stripe / A2P / Teams live wiring.
- No Track A mutation, shared DB, shared SP, or shared tfstate.
- No application LLM.
- D3+ not authorized by D2.

## Why you (Codex) and not Cursor

Cursor completed D0–D2 then stalled on Azure connectivity, Colima bind-mounts,
and `gh` token friction. Use your Azure and GitHub connectors to continue
**OS-named resources only** until D6. Do not invent Track A IAM, production
GitHub OIDC, `cosmaneura-gha-prod`, or `cosmaneura-tfstate` access.

## Hard product invariants (non-negotiable)

- One legal Org = one logical Box. `box_id` is the permanent audit root.
- Humans (`HumanSeat`) and agents (`AgentPrincipal`) are distinct; agents cannot
  self-approve, impersonate, sign, or submit SoR work as a human.
- Baseline agents (Scribe, Chief, Chaser) may be disabled/removed; history is
  tombstoned.
- **F-8 is the only queue and approval substrate.** Features do not grow private
  queues.
- Approval binds an immutable action revision and exact payload hash. Edit
  invalidates prior approval. Individual payload-bound decisions unless a later
  accepted DL entry changes that.
- Postgres is authoritative for operation intent; Redis/Celery are transport.
  Worker retries reuse the same operation. Unknown external outcomes reconcile;
  they are not blindly repeated.
- Internal L0 uses fake/local ports. External capabilities stay dark until a
  D5-class activation.
- Modular monolith. Domain/application have no FastAPI/Celery/Clerk/Azure/Athena
  imports. Explicit ports; fake adapters first. Additive Alembic migrations.
- Flat SaaS. V1 is insurance ArtifactChase, not payment/PAN recovery.
- UX is the practice work queue. Hide `box_id`, operation IDs, and compliance
  jargon from normal workflow.
- Do **not** add Kubernetes, Kafka, a second cloud/IdP, browser automation,
  consumer messengers, payment/PAN, generalized event sourcing, shared multi-Org
  runtime, or a rebuilt Scribe inside OS.

## Stop / kill signals (halt and report; do not improvise)

Stop immediately if any of these occur:

- Fatal contradiction with locked decisions, or an unexpected owner file change
  you would overwrite.
- PHI, real patient data, production credentials, `.env` secrets, vendor tokens,
  or production-like dumps appear or would be written.
- Any step requires mutating a repository, Azure identity, or Terraform state
  **outside** this Track B repo / `cosmaneura-os-synth`.
- Proposed design only works if Azure credits exist (INV-9 / D economics).
- Shared packing of Boxes without explicit `box_id` enforcement at shared edges.
- Coding agents would receive live PHI or live credentials (forbidden in beta).
- Beta/pilot value is claimed to require full EHR write.
- Approval/setup cost equals or exceeds time saved; practice cannot understand
  the exact action before approve; ordinary retries need manual unstick.
- Track B work would delay Track A survival work (Track A wins).
- You need Track A production access, Clerk production, Athena/Acuity live IDs,
  or Stripe to “just keep going.”
- `terraform apply` / `destroy` / ACR push / vendor enablement without the
  matching exact owner phrase below.

## Exact owner approval phrases (wait for these; do not paraphrase)

| Gate | Exact owner message required | What it authorizes |
|---|---|---|
| Hygiene (this paste) | Pasting this prompt | Commit/push **existing D2 docs+infra** (no secrets/state). Verify Actions. No Azure mutate. |
| D2 residual | `AUTHORIZE D2 ACR PUSH AND APP WIRING` | Digest-pin OS image to OS ACR; replace helloworld; KV/env wire; synth migrate; `/health` smoke. Still `synth_os`, non-PHI, no Clerk/vendors. |
| D2 destroy / retire | `DESTROY COSMANEURA-OS-SYNTH` | `terraform destroy` of this RG only. |
| D3 | `APPROVE D3 ISOLATED EARLY-ADOPTER BETA` | Isolated early-adopter environment. Still needs named clinic, BAA, Clerk Org, and human deploy evidence before PHI. |
| D4 | `APPROVE D4 ONE-CLINIC L0 PILOT` | Measure L0 KPIs at one clinic. No EHR write required. |
| D5 one rung | `APPROVE D5 CONNECTOR RUNG <PORT> <RUNG>` e.g. `APPROVE D5 CONNECTOR RUNG SchedulePort L1` | One adapter ladder step with a capability manifest. Never a bundle of rungs. |
| D6 | `APPROVE D6 TRACK A INTEGRATION` | Versioned HTTPS/OpenAPI or first-party MCP **after** Track A IAM gate. No shared DB/SP/tfstate. |

If the owner says “continue”, “finish Azure”, or “do D3” without the exact
phrase, **ask for the phrase**. Do not treat this handoff as D3–D6 approval.

---

# Work package

Execute in order. Finish each gate’s exit criteria before starting the next
authorized gate. Record evidence in `BUILD_REPORT.md` and
`.azure/deployment-plan.md` without secrets.

## 0. Immediate hygiene (authorized by this paste)

**Goal:** Get the D2 tree onto `CosmaNeura/cosmaneura-os` `main` with CI green.
No Azure mutation.

1. Inspect `git status`. Expected at handoff (2026-09-02 evening):
   - Branch `main` tracking `origin/main`.
   - Modified: `.gitignore`, `BUILD_REPORT.md`, `README.md`,
     `docs/DECISION_LOG.md`, `docs/RELEASE_AND_ROLLBACK.md`.
   - Untracked: `.azure/`, `docs/superpowers/`, `infra/*.tf` and friends,
     `docs/handoff/` (this file).
   - Local only (must stay uncommitted): `infra/.apply-env`,
     `infra/terraform.tfstate*`, `infra/.terraform/`, `.tools/`, `.env`.
2. Tighten gitignore before commit:
   - Keep existing Terraform secret/state ignores.
   - Ignore `infra/tfplan*`, `infra/*.tfplan`, crash logs.
   - Ignore generated `artifacts/releases/manifest-*.json` (keep directory
     intent documented; do not commit manifests that embed local image IDs
     unless the owner later wants a sanitized example).
3. **Never add:** `infra/.apply-env`, `*.tfstate`, `.terraform/`, `.tools/`,
   `terraform.tfvars`, `override.tf`, credentials, PHI, `.env`.
4. Update stale README D2 section: apply **already happened**; residual is
   image push + wiring, not scaffold.
5. Commit on `main` with a message that records D2 apply + `postgres_location=centralus`
   recovery + this handoff. Push `origin main`.
6. Verify GitHub Actions `synth-ci` is green on that SHA. If red, fix in this
   repo only (no skip, no `continue-on-error`).
7. Confirm `terraform.tfvars.example` still has **no password**. Confirm
   `postgres_location = "centralus"` is in code and example.

**Exit criteria**

- D2 Terraform source, `.azure/deployment-plan.md`, decision log DL-08/09,
  BUILD_REPORT D2 section, and this handoff are on `origin/main`.
- `synth-ci` green.
- `git ls-files` contains no `.apply-env`, tfstate, `.tools`, or secrets.
- Track A untouched.

**Not in this step:** `terraform apply`, ACR login/push, Key Vault writes,
Container Apps revision changes.

## 1. D2 residual — optional, still `synth_os` (wait for exact phrase)

Phrase: `AUTHORIZE D2 ACR PUSH AND APP WIRING`

Stay on OS-named resources in `cosmaneura-os-synth` only. Invented data only.

1. `terraform plan` (not apply) against current state; show the owner the diff
   before any apply that changes images or secrets.
2. Build `cosmas-os` from this repo’s `Dockerfile`. Push to
   `cosmasossynthacrrkpt0e.azurecr.io` with an immutable digest. Do not use
   Track A ACRs.
3. Set `api_image` / `worker_image` to **digest-pinned** ACR references
   (not `:latest`, not helloworld).
4. Wire API/worker env from Key Vault / UAMI: `DATABASE_URL`, `REDIS_URL`,
   `COSMAS_ENV=synth_os`, `BLOB_ROOT` (Azure Blob later; filesystem-in-container
   acceptable for residual synth). No Clerk, no vendor keys.
5. Run `alembic upgrade head` against synth Postgres `cosmas_os` only. Seed
   **invented** fixtures if needed. Never copy Track A data.
6. Smoke `GET https://ca-api-cosmasossynth.delightfulsmoke-58dcae81.eastus.azurecontainerapps.io/health`.
   Worker process should be alive (not helloworld).
7. Keep `enable_public_postgres` documented as synth-only; D3 must tighten.
8. Update BUILD_REPORT + deployment-plan checklist items for ACR push / wiring.
   No secrets in git.

**Exit criteria**

- Apps run the OS image digest, not helloworld.
- `/health` returns ok for `synth_os`.
- Migrations applied to synth DB; no PHI.
- Images digest-pinned; rollback path documented (prior digest).
- Still no Clerk/Athena/Acuity/Stripe.

**Kill:** any need for Track A registry, production KV, or real patient seed.

## 2. D3 — isolated early-adopter beta (wait for exact phrase)

Phrase: `APPROVE D3 ISOLATED EARLY-ADOPTER BETA`

This is **not** an in-place promotion of `cosmaneura-os-synth` by renaming tags.
D3 is a separate isolated environment (new RG / identity / Box) unless the owner
explicitly rules otherwise in an accepted DL entry.

Before mutating Azure for D3, collect and record (do not invent):

- Named first early-adopter organization (currently OPEN).
- Dedicated Box (strongest packing: dedicated DB + storage prefix + workloads).
- Clerk **Org** for that practice (human IdP). Coding agents get **no** live
  PHI or live credentials.
- BAA / covered-entity prerequisites for whatever capabilities will be **on**.
  L0 ports stay fake until D5. If the first beta is still L0-only, say so in
  the capability manifest and keep Athena/Acuity/email dark.
- Human deploy (you may prepare; a human performs or explicitly confirms
  production-like apply).
- Stronger isolation than D2: no public Postgres if PHI may exist; Box scope on
  logs, blobs, backups, support tools.
- Cost: use parametric ranges in `docs/validation/05-deployment-roadmap.md`.
  Do **not** assume Track A ~$100k credits (expire Jan 2027) as architecture.
  Dedicated small beta Box illustrative infra **~$80–260/mo** without credits.
  Exact SKU dollars are UNKNOWN until calculator evidence.
- Demonstrate: login + authority matrix; audit replay; purge; backup/restore;
  rollback of digest-pinned revision.

Likely D3 components (from roadmap; confirm against current Azure evidence):

- API + worker Container Apps, Postgres, Redis if still required, isolated
  Blob, Key Vault, PHI-safe monitoring, Clerk Org, dedicated deploy identity.

**Exit criteria**

- Applicable enabled-capability prerequisites complete and listed.
- One dedicated Box; `box_id` on every shared edge.
- Humans and agents remain distinct; F-8 remains the only approval surface.
- Audit, purge, backup/restore, rollback demonstrated with **non-production**
  or authorized beta data — never dump PHI into this git repo.
- Coding agents cannot reach live PHI/credentials.
- At least one plausible flat-SaaS packing scenario **without** Azure credits.
- Capability matrix updated; dark connectors still fail closed.

**Kill:** credits-only economics; shared packing without tenant enforcement;
agents with live PHI; “need EHR write to show value.”

## 3. D4 — one-clinic L0 pilot (wait for exact phrase)

Phrase: `APPROVE D4 ONE-CLINIC L0 PILOT`

Enable only what is needed:

- Owner/approver + baseline agents.
- Queue.
- Manual/CSV schedule input.
- In-app/staff channel, **or** one deliberately approved patient channel
  (that channel is a D5 NotifyPort rung, not a silent extra).
- Insurance working-copy flow.
- **No EHR write.**

Measure (D-003 / roadmap; no recovered-dollar KPI):

- Artifacts complete before visits.
- Staff minutes saved.
- Approval / edit / reject time.
- Wrong or duplicate outreach.
- Visits preserved.
- Support burden.
- Paid retention where applicable.

**Exit criteria**

- Workflow saves more time than setup/approval consumes.
- No wrong-patient or duplicate-send safety event.
- Support + infra cost still support flat SaaS without credits.
- L0 remains usable if every external adapter is fake or disabled.

## 4. D5 — connector rungs, one at a time (wait for per-rung phrase)

Phrase pattern: `APPROVE D5 CONNECTOR RUNG <PORT> <RUNG>`

Climb independently by Box. Suggested order (do not bundle):

1. `SchedulePort`: L0 CSV/manual → L1 confirmed Acuity or Athena **read**.
2. `RecordPort`: L0 local draft → L1 read → L2 document attach → later governed write.
3. `NotifyPort`: L0 fake/in-app → L1 secure email → L2 A2P SMS.
4. Track A Scribe/tool receiver (also needs D6 if it crosses repos).
5. Teams pointer-only only if evidence still supports it (deferred by default).

Each rung requires:

- Fake **and** sandbox contract tests.
- Bounded timeout and retry; `UNKNOWN` reconciliation; no blind resend.
- A **capability manifest** (prerequisites, BAA/vendor status, fail-closed
  behavior, owner approver, dark-by-default).
- Graceful degradation to L0. F-8 state must remain uncorrupted.
- Human-reviewed activation. `AUTO_TEMPLATE` stays dark in the first slices.
  `AUTO_DRAFT` stays on the staff surface. SoR writes need the named human.

**Exit criteria per rung**

- Manifest merged; tests prove fail-closed when dark and recovery when UNKNOWN.
- L0 demo still passes with that adapter disabled.
- No PAN, no second EHR, no browser automation.

## 5. D6 — Track A integration (wait for exact phrase **and** Track A IAM gate)

Phrase: `APPROVE D6 TRACK A INTEGRATION`

Additional precondition: Track A’s own IAM / human-review gate (historical
**INV-6**: PR-subject prod federation, split plan/apply identities, protected
branches, credential rotation). **UNKNOWN whether INV-6 is closed.** You must
not “fix” Track A IAM from this repo. You must not widen an existing Track A
SP. Ask the owner for Track A evidence; do not probe production.

Contract rules:

- Receiver-first **versioned** HTTPS/OpenAPI **or** bounded first-party MCP.
- No shared database, migrations, deploy identity, secrets, or Terraform state.
- `correlation_id`, `box_id`, actor, operation ID, outcome may cross the
  boundary. PHI stays out of ordinary logs.
- Master remains usable when OS is down. OS retains work when Master is down.
- Track A code changes use Track A review/deploy doctrine, performed by Track A
  owners — not by silently editing `~/Desktop/Cosmas/*`.

**Exit criteria**

- Published versioned contract + fake adapter in synth.
- No shared tfstate/SP/DB.
- Dual-unavailability tests documented.
- OS resources remain OS-named.

---

# How to operate this repo

## Local synth

```bash
cd <cosmaneura-os>
./scripts/dev-up.sh          # Postgres+Redis, migrate, seed, API :8000
# other terminal:
cd web && pnpm install && pnpm dev   # queue :5173
uv run python -m cosmas_os.cli demo-artifact-chase
```

Compose file uses `docker-compose` (not the v2 plugin). Ports: Postgres
`54329`, Redis `63799`, API `8000`, web `5173`. Copy `.env.example` → `.env`
locally; never commit `.env`.

## CI

```bash
./scripts/ci-local.sh        # ruff, pyright, migrate, pytest, demo, web
./scripts/release-artifact.sh  # local image + manifest; does not push
```

GitHub Actions: `.github/workflows/synth-ci.yml` on `main` / PRs. All jobs
required. No production secrets. No deploy.

## Terraform

```bash
cd infra
terraform init -backend=false   # local state only; never cosmaneura-tfstate
terraform fmt -check
terraform validate
# secrets: source gitignored infra/.apply-env or TF_VAR_postgres_admin_password
terraform plan                 # review with owner
# terraform apply            # only with matching owner phrase
# terraform destroy          # only DESTROY COSMANEURA-OS-SYNTH
```

Plan vs apply: **plan is the default**. Apply is an exception. State is local
today; a future OS-named backend is allowed, Track A backend is not.

## Decision log

Path: `docs/DECISION_LOG.md`. Status `ACCEPTED` + owner evidence required
before a ruling is authoritative. Next IDs continue `DL-20260902-10` or
`DL-YYYYMMDD-01` on a new date.

## Docs to keep honest after each gate

- `BUILD_REPORT.md` — commands actually run and exact results (no secrets).
- `.azure/deployment-plan.md` — Azure facts.
- `docs/CAPABILITY_MATRIX.md` — ON vs DARK.
- `docs/RELEASE_AND_ROLLBACK.md` — digest pin + migrate/rollback.
- `README.md` — match reality (D2 is deployed, not scaffold-only).

---

# What you must NOT do

- PHI, real patients, production-like exports, real MRNs, live vendor tokens,
  production identifiers in git, prompts, fixtures, tests, logs, screenshots,
  or reports. Use invented people, appointments, images, and money.
- Access or mutate Azure **outside** `cosmaneura-os-synth` / future OS-named
  D3 RG; no Track A RGs, no MCD prod join.
- Clerk / Stripe / Athena / Acuity / messaging live calls before the matching
  D3/D5 phrases.
- Commit `infra/.apply-env`, tfstate, `.tools/`, `.env`, Key Vault secret
  values, Postgres admin passwords.
- Share Terraform state with Track A (`cosmaneura-tfstate`).
- Mutate Track A repos or production GitHub deploy identities.
- Kubernetes, Kafka, Service Bus-as-business-record, second IdP, payment/PAN,
  Capacitor, Teams (unless later evidence + owner), evidence/open-web zone.
- Auto-deploy from CI to Azure.
- Depend on Cursor GPT-5.6 SOL (or Codex) inside product runtime.
- Claim a command passed unless you ran it and checked output.

When blocked, report: what you observed, which gate you are in, which exact
phrase or UNKNOWN is missing, and the smallest next owner decision.

```text
END CODEX PROMPT
```

---

# Appendix — structured reference

## A. Paths (this repo)

| Path | Role |
|---|---|
| `AGENTS.md` | Track B guardrails |
| `CANONICAL_PRODUCT_DECISIONS.md` | Locked D-001–D-013 + opens |
| `docs/DECISION_LOG.md` | Append-only accepted rulings |
| `docs/CANONICAL_ARCHITECTURE_CONTRACT.md` | Contract 1.9-draft |
| `docs/BUILD_AND_DEPLOYMENT_ROADMAP.md` | Creation Phases 0–3; deploy D0–D6 |
| `docs/validation/03-target-architecture.md` | Validated L0 shape |
| `docs/validation/05-deployment-roadmap.md` | D0–D6 table, cost, kill signals |
| `docs/validation/06-risk-contradiction-unknown-register.md` | UNKNOWNs |
| `docs/validation/07-build-gate.md` | `FEASIBLE_WITH_CONDITIONS`; historical wait |
| `docs/CAPABILITY_MATRIX.md` | ON / DARK |
| `docs/RELEASE_AND_ROLLBACK.md` | Image + migration recovery |
| `docs/THREAT_AND_RECOVERY.md` | L0 threats |
| `docs/RETENTION.md` | Purge +7d working copies |
| `docs/DEMO_WALKTHROUGH.md` | ArtifactChase demo |
| `BUILD_REPORT.md` | Executed command evidence |
| `.azure/deployment-plan.md` | D2 Azure plan (status: Deployed) |
| `infra/` | Terraform azurerm ~> 4 |
| `infra/README.md` | init/plan; apply gated |
| `docs/superpowers/specs/2026-09-02-d2-terraform-scaffold-design.md` | D2 design |
| `src/cosmas_os/` | Domain, application, ports, adapters, api, worker |
| `web/` | Minimal React owner queue |
| `migrations/` | Alembic (0001_initial) |
| `fixtures/synthetic/` | Invented data |
| `scripts/dev-up.sh` | Local API start |
| `scripts/ci-local.sh` | Local synth-ci |
| `scripts/release-artifact.sh` | Local image + manifest |
| `.github/workflows/synth-ci.yml` | Required synth jobs |
| `docs/reference/` | Historical sources — evidence only |
| `docs/handoff/CODEX_D3_TO_COMPLETE_BUILD_HANDOFF.md` | This file |

Writable workspace: `~/Desktop/cosmaneura-os` (or Codex clone of
`CosmaNeura/cosmaneura-os`).

Read-only Track A (if present): `~/Desktop/Cosmas/`.

## B. Azure synth resources (D2, non-PHI)

| Item | Value |
|---|---|
| Subscription | `bab2a709-1fcb-4c87-a9fc-802f7477ec13` |
| Resource group | `cosmaneura-os-synth` (`eastus`) |
| Tags | `track=B`, `product=cosmas-os`, `env=synth_os`, `phi=false` |
| Postgres location | `centralus` (`var.postgres_location`) |
| Postgres | `pg-cosmasossynth-rkpt0e.postgres.database.azure.com` v16, DB `cosmas_os`, SKU `B_Standard_B1ms` |
| Postgres admin login | `cosmas_os_admin` (password not in git) |
| API URL | `https://ca-api-cosmasossynth.delightfulsmoke-58dcae81.eastus.azurecontainerapps.io` |
| API app | `ca-api-cosmasossynth` (scale-to-zero allowed; helloworld until residual) |
| Worker app | `ca-worker-cosmasossynth` (min 1 replica; helloworld until residual) |
| CAE | `cae-cosmasossynth-rkpt0e` |
| ACR | `cosmasossynthacrrkpt0e.azurecr.io` |
| Redis | `redis-cosmasossynth-rkpt0e.redis.cache.windows.net` Basic C0 |
| Key Vault | `https://kvcosmasossynthrkpt0e.vault.azure.net/` (`kvcosmasossynthrkpt0e`) |
| Storage | `cosmasossynthstrkpt0e` |
| LAW | `law-cosmasossynth-rkpt0e` |
| UAMI | `id-cosmasossynth` |
| Current images | `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest` |
| Public Postgres | `enable_public_postgres=true` (tighten before D3 PHI) |
| State | Local `infra/terraform.tfstate` (gitignored) |
| Forbidden state | Track A `cosmaneura-tfstate` |
| Quota note | `Microsoft.Quota` was **not** registered; ARG used as fallback |

All listed RG resources were `Succeeded` after recovery apply. First apply
failed on eastus Flexible Server `ParameterOutOfRange`; recovery added 3
Postgres resources in centralus. **No destroy.**

## C. Decision IDs

| ID | Status | Ruling (short) |
|---|---|---|
| D-001 | locked | Separate Track B repo; no shared git/DB/tfstate with A |
| D-002 | locked | Dual-track; A wins if staffing conflict |
| D-003 | locked | Flat SaaS; ArtifactChase ≠ payment recovery |
| D-004 | locked | One Org = one Box; `box_id` audit root |
| D-005 | locked | Distinct human/agent principals |
| D-006 | locked | Baseline agents removable; tombstone |
| D-007 | locked | Policy deny-wins; pin versions |
| D-008 | locked | F-8 sole approval substrate; edit invalidates |
| D-009 | locked | Local ledger; Postgres authority |
| D-010 | locked | Capability-gated compliance |
| D-011 | locked | Ports; independent ladders; L0 fakes |
| D-012 | locked | Envs: `synth_os`, `early_adopter_beta`, `cosmas_mcd_prod` |
| D-013 | locked | Usability: hide infra/compliance jargon |
| DL-20260902-01 | ACCEPTED | Insurance chase + flat SaaS |
| DL-20260902-02 | ACCEPTED | Org = Box |
| DL-20260902-03 | ACCEPTED | Distinct principals; tombstone |
| DL-20260902-04 | ACCEPTED | Local execution; capability-gated compliance |
| DL-20260902-05 | ACCEPTED | `APPROVE LOCAL SYNTH BUILD` → D0 |
| DL-20260902-06 | ACCEPTED | D1 synth CI / release artifact |
| DL-20260902-07 | ACCEPTED | First commit + private CosmaNeura remote |
| DL-20260902-08 | ACCEPTED | D2 IaC; depth 3, region B eastus, Terraform; no apply yet |
| DL-20260902-09 | ACCEPTED | `deploy now` live apply OS-named synth RG |

Next log entry should be `DL-20260902-10` or a new date prefix.

Owner phrases already consumed: `APPROVE LOCAL SYNTH BUILD`; Synthetic
CI/release-artifact hardening; First commit and private remote; `I authorize D2`;
`deploy now`.

## D. Git snapshot at handoff (do not assume still true — re-check)

```text
main...origin/main
HEAD: f077a1f Point remote docs at CosmaNeura org instead of personal account.
Prior: 49e2c77 Record private remote… ; 44e97ed Initial synthetic tree + D1

Modified (unstaged): .gitignore, BUILD_REPORT.md, README.md,
  docs/DECISION_LOG.md, docs/RELEASE_AND_ROLLBACK.md
Untracked: .azure/, docs/superpowers/, infra/*.tf, infra/README.md,
  infra/.terraform.lock.hcl, infra/terraform.tfvars.example, infra/tfplan-recovery,
  docs/handoff/ (once written)
Gitignored (must remain so): infra/.apply-env, infra/*.tfstate,
  infra/.terraform/, .tools/, .env
```

`infra/tfplan-recovery` was untracked and is a plan artifact — gitignore it;
do not commit.

## E. Open UNKNOWNs and owner decisions

From `docs/validation/06-risk-contradiction-unknown-register.md` and
`CANONICAL_PRODUCT_DECISIONS.md` “Open owner decisions”. Conservative defaults
already apply (individual approvals, dedicated first beta Box, no live
connectors, no cross-Box networking, no automatic patient sends).

| ID | Item | Blocks local synth? | Blocks D3+ ? |
|---|---|---|---|
| U-ATH | Actual Athena/Acuity access and practice IDs | No | Blocks Schedule/Record L1+ |
| U-COST | Exact Azure SKU dollars (parametric only) | No | D3 economics must stay ranges until calculator |
| U-INV6 | Track A IAM gate closed? | No | **Blocks D6.** Do not probe prod to find out. |
| T-SOAP | `soap.draft` / stream MCP existence | No | Do not assume for D6 |
| — | Exact flat-SaaS tiers / seat packaging | No | Commercial, not a code gate |
| — | First early-adopter organization | No | **Blocks named D3 clinic** |
| — | Named approver matrix by lane/specialty | No | Use owner as sole approver until set |
| — | Individual vs displayed-batch approval UX | No | Default individual (build gate) |
| — | Patient email vs A2P sequencing | No | D5 NotifyPort |
| — | Physical packing after first isolated beta | No | First beta = dedicated Box |
| — | Product runtime model/provider | No | LLM stays dark |
| — | Quantitative graduation / kill thresholds | No | Use qualitative kill signals until set |
| — | Clerk plan / instance for beta | No | D3 AuthPort |
| T-ACA | ACA vs App Service | Resolved prefer ACA | Match D2 |

Do not re-litigate superseded historical ideas: payment recovered-dollars KPI,
%-of-recovery pricing, Entra as second IdP, ticket-list as standing send
authority, Python 3.12 as mandatory.

## F. Capability matrix (current L0)

ON: Box/principals/F-8, SchedulePort CSV, NotifyPort fake, BlobPort local FS,
AuthPort fake, PatientLink, ArtifactChase → `IMAGE_ON_FILE`, retention purge.

DARK (fail closed): Athena/Acuity, real email/SMS/A2P, Teams, payment/PAN,
Evidence/Workbook, Clerk/Azure app wiring, application LLM, `AUTO_TEMPLATE`,
`AUTO_DRAFT` send off staff surface.

D2 Azure exists as **infra**; product Clerk/Azure adapters remain DARK until
wired under residual/D3 phrases.

## G. Local stack facts

| Item | Value |
|---|---|
| Python | 3.13 (`requires-python = ">=3.13"`) |
| Node | 22 (CI `22`; pnpm 9.15.9) |
| Postgres image | `postgres:16.9` host port 54329 |
| Redis image | `redis:6.2.18` host port 63799 |
| Tests | 23 pytest, plus ruff/pyright/web |
| Compose CLI | `docker-compose` |
| Health | `GET /health` |

## H. Cost ranges (assumptions, not quotes)

Dedicated small beta Box: compute ~$40–120, data ~$30–100, obs/misc ~$10–40,
infra subtotal **~$80–260/mo**. Credits must not define architecture.

## I. Suggested D5 capability manifest fields

Create under `docs/capabilities/` when a D5 phrase arrives (not before):

```text
port, rung, box_id scope, prerequisites (BAA, vendor app, Clerk, A2P brand),
failure mode (fail closed), UNKNOWN reconciliation, timeout/retry,
degradation to L0, tests, owner approver, status DARK|SANDBOX|ON
```

## J. Cursor operational debt (for Codex connectors)

- Azure CLI login in Cursor was intermittent.
- Colima bind-mounts broke Dockerized `hashicorp/terraform:1.9` workflows;
  prefer host Terraform 1.9+ or Codex Azure tooling.
- `gh` token friction on the Cursor agent; use org `CosmaNeura` not `JohnClem`.
- Do not copy Track A service principals to “make apply work.”

## K. Definition of “complete build” for this handoff

Complete means: D2 residual (if owner authorizes) + D3 isolated beta proven +
D4 one-clinic L0 KPI gate + D5 rungs only as individually approved + D6
contract only after Track A IAM gate — all without PHI in git, without Track A
mutation from this agent, and without skipping exact owner phrases.
