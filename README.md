# CosmaBot / CosmasOS

CosmaBot is a standalone desktop and mobile app for a configurable team of
clinical and practice coworkers. Its workspace combines private notes, chat,
team settings, research and tracked operational work.

CosmaBot connects to the main Cosmaneura platform through authenticated APIs.
Platform features such as SOAP notes remain owned by Cosmaneura. Scribe is a
main capture and documentation connector for CosmaBot users. This repository
does not contain the Core or Scribe server applications or share their databases.
See [application boundaries](docs/COSMABOT_ARCHITECTURE.md).

**Source integration, September 25:** this branch brings previously local
CosmaBot implementation into the owning repository. It is an integration
candidate, not a deployed or fully qualified operational beta. Desktop and mobile
are both required for initial release. See [scope and validation](docs/beta/COSMABOT_SOURCE_INTEGRATION.md).

## Build the current standalone app

- Hosted workspace: [complete beta build](docs/operational-beta-build.md) and
  [public release inputs](docs/beta/WEB_RELEASE.md). `Dockerfile.web` selects the
  complete `operational-beta-v1` profile; use its current public build arguments.
- Mac and iPhone: [native build inputs](docs/operational-native-build.md), then
  [Mac archive packaging](docs/desktop-release-packaging.md). Both clients are
  required for release. Existing capture components remain at the paused snapshot.
- Backend validation: [local checks](docs/local-checks.md). Record the exact
  reviewed commit and results locally; GitHub is used for source and PR evidence.

The foundation commands and D1–D3 history below describe earlier synthetic slices.
They do not establish current operational-beta deployment or device acceptance.

Cosmas OS Track B: a locally runnable synthetic practice computer plus the
fail-closed source and infrastructure preparation for an isolated D3
early-adopter beta. Repository fixtures remain invented. No PHI, production
credentials, or live Athena/Acuity/Clerk/messaging belong in this tree.

## One-command local start

```bash
./scripts/dev-up.sh
```

Requires: `uv`, Python 3.13, Node 24+ and Corepack; Docker (`docker-compose`)
when local services are not already running. Reuses healthy Postgres + Redis
endpoints started by the cloud-agent hook, or starts only missing containers,
runs migrations, seeds a clinic, and serves the API on `:8000`.

In another terminal:

```bash
./scripts/install-client-deps.sh
cd web && corepack pnpm dev
```

Open http://localhost:5173 for the local synthetic owner work queue. It creates
one invented pending chase automatically so the approve/edit/reject/escalate,
close, and history flow can be tested in the browser. The synth path does not
load Clerk and continues to use only the local synthetic identity headers.

## Demo (full ArtifactChase L0)

```bash
docker-compose up -d postgres redis
uv sync --extra dev
uv run alembic upgrade head
uv run python -m cosmas_os.cli demo-artifact-chase
```

## Tests

Run backend checks locally against fresh, isolated PostgreSQL databases:

```bash
uv run --no-sync python scripts/check-backend-local.py
```

See [local checks](docs/local-checks.md) for PostgreSQL discovery, selected tests,
network confinement and the recorded commit, results and cleanup evidence.
The checker separates workspace, database administration and queue recovery
profiles automatically. Reviews and validation evidence are local.

Frontend and static checks:

```bash
uv run ruff check src tests
uv run pyright src
./scripts/install-client-deps.sh
cd web && corepack pnpm test && corepack pnpm build
```

For the complete local D3 source check (application tests, mode tests and
validation for both isolated OpenTofu roots, and a non-root runtime image):

```bash
./scripts/d3-self-test.sh
```

This command does not authenticate to Azure or Clerk, deploy anything, or use
PHI.

## Historical synthetic CI / release artifact (D1)

```bash
./scripts/ci-local.sh
./scripts/release-artifact.sh
```

- GitHub Actions: [`.github/workflows/synth-ci.yml`](.github/workflows/synth-ci.yml)
- Rollback / migration recovery: [`docs/RELEASE_AND_ROLLBACK.md`](docs/RELEASE_AND_ROLLBACK.md)
- D1 manifests land in `artifacts/releases/` (local-only); the separately
  authorized D2 Azure image is described below.

## D2 Azure synth infrastructure (deployed)

```bash
# See infra/README.md — plan is the default; every later mutation is gated
```

- Plan: [`.azure/deployment-plan.md`](.azure/deployment-plan.md)
- Code: [`infra/`](infra/)
- Resource group `cosmaneura-os-synth` is deployed; most resources are in
  `eastus`, while PostgreSQL is in `centralus` after the subscription rejected
  Flexible Server provisioning in `eastus`.
- API revision `ca-api-cosmasossynth--0000001` and worker revision
  `ca-worker-cosmasossynth--0000001` are healthy on the same immutable image:
  `cosmasossynthacrrkpt0e.azurecr.io/cosmas-os@sha256:af48b5b22b15d64f5592405a7ac041237224fb7a1ed05b8041e0b60f5a5ca6be`.
- Key Vault/UAMI connection wiring is active, the synth database is at
  `0001_initial (head)`, and `/health` returns HTTP 200 for `synth_os`.

This remains a public **synthetic-only** runtime, not a beta: it has no Clerk
authentication, trusts caller-provided identity headers, permits wildcard
CORS, and retains the D2 public PostgreSQL `AllowAzureServices` rule. Blob
bytes use ephemeral per-replica `/tmp/cosmas-os-blobs`; the provisioned Azure
Blob container is not yet consumed.

## D3 isolated beta candidate (bootstrap deployed; application pending)

The owner authorized D3 planning and implementation in `DL-20260903-03`;
`DL-20260903-04` selected the strictly non-PHI Cosmas Beta Lab as the first
slice.
The repository now contains:

- a Clerk JWT verification boundary with exact issuer, audience, authorized
  party, Organization, and reviewed server-side subject-to-Box binding;
- a conditional Clerk React login boundary that requires an explicit HTTPS API
  URL, a Clerk publishable key, a signed-in session, and an active Organization
  before loading beta work;
- a managed-identity Azure Blob adapter with Box-prefixed object keys;
- additive migration `0002_external_identities`, a protected first-owner
  bootstrap, and authenticated owner-only identity lifecycle APIs;
- a separate manual, unscheduled, digest-pinned in-network database job that
  applies the sole expected Alembic head and proves the runtime role cannot
  perform DDL or mutate audit history;
- strict beta startup validation, exact CORS origins, current-schema
  readiness, non-root containers, and synthetic-only beta seeding;
- separate `infra/beta/bootstrap` and `infra/beta/environment` roots with no
  D2 or Track A state/resource sharing;
- protected procedures for workflow and physical-purge acceptance, alert
  delivery, isolated point-in-time restore, exact-digest rollback/forward
  recovery, tester offboarding, and staged custom-domain binding; and
- prerequisite, capability-manifest, human-deploy, recovery, and cost gates.

This is deliberately **not yet an application deployment**. The isolated D3
bootstrap/state boundary, dedicated Box assignment, and private protected
runner exist. The application path still needs Azure capacity resolution, a
committed and locally reviewed/tested successor release, the separately approved foundation,
production Cosmas OS Clerk instance and Organization, database preparation,
workload/domain plans, and human acceptance evidence. `centralus`, private ACR,
`beta.cosmaneura.com`, and the strict Clerk/cost/recovery operating choices are
accepted inputs; live capacity, routing, exact-plan cost, and service evidence
remain required. The separate development Clerk application and zero-member
development Beta Lab Organization provide no production authority. A named
clinic, clinic approval, BAA evidence, and PHI-authorization reference are not
prerequisites for this strictly synthetic path; they remain mandatory for any
clinic or PHI-capable beta. Startup and workload deployment fail closed when
the selected mode's evidence is incomplete. PHI remains unauthorized; all
external connectors remain dark.
See [`docs/beta/README.md`](docs/beta/README.md) and
[`infra/beta/README.md`](infra/beta/README.md). The staged database runbook is
[`docs/beta/DATABASE_PREPARATION.md`](docs/beta/DATABASE_PREPARATION.md).

The beta web build requires `VITE_COSMAS_ENV=early_adopter_beta`, an approved
HTTPS `VITE_API_BASE`, and `VITE_CLERK_PUBLISHABLE_KEY`. These are build-time
browser values; only the Clerk **publishable** key belongs there. If any value
is missing or invalid, the page remains blocked and makes no Clerk or Cosmas API
request. Once signed in, each Cosmas API request obtains a fresh uncached Clerk
token for the active Organization and sends it only as a bearer token. Never
add a Clerk secret key, Box ID, or principal ID to frontend configuration.

## What the local L0 slice proves

1. Seed one Org Box with owner + Scribe/Chief/Chaser  
2. Import synthetic appointments  
3. Attest PatientLink  
4. Detect missing insurance artifact → F-8 ticket + neutral message  
5. Approve / edit / reject / escalate in one queue  
6. Payload-bound approval → one local operation via fake NotifyPort  
7. Double-click / retry does not duplicate the effect  
8. Synthetic front/back upload + human verification → `IMAGE_ON_FILE`  
9. Close ticket + audit timeline  
10. Injectable clock purge with non-PHI receipt  

## Layout

```text
src/cosmas_os/   domain, application, ports, adapters, api, worker
web/             minimal React owner queue
migrations/      Alembic
fixtures/synthetic/
docs/validation/ Phase 0 evidence (complete)
```

## Authority

See `AGENTS.md`, `CANONICAL_PRODUCT_DECISIONS.md`, and `docs/DECISION_LOG.md`.
GPT-5.6 SOL is a development agent only — not a product runtime dependency.

## Remote

Private GitHub: `git@github.com:CosmaNeura/cosmaneura-os.git` (Track B only).

## Still not authorized

Any D3 Azure mutation before its recorded human prerequisites, PHI use, D4-D6,
D2 destruction, Track A edits, Clerk invitations/production activation beyond
`DL-20260903-05`, other live-vendor activation, and an application LLM. D3
source preparation and the empty Clerk development structure are authorized;
those later actions are not implied.

Private incoming-message handoffs use the existing F8 work/responsibility engine.
INBOX_WORK_ENABLED and INBOX_HANDOFF_ENABLED default to false; the installed inbound
read registry remains empty. Source-bound internal publication is not a vendor send.
