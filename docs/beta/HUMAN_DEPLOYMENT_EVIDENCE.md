# D3 human deployment evidence checklist and runbook

Runbook status: **SYNTHETIC LAB PATH APPROVED / NOT EXECUTED**
D3 status: **NOT COMPLETE / NOT DEPLOYED**
PHI status: **NOT AUTHORIZED**
Clerk AuthPort: **DEVELOPMENT CONFIGURED / PRODUCTION DOMAIN BLOCKED**
Non-auth/D5 connectors: **ALL DARK**

This runbook defines evidence a human must produce. It is not an instruction to
deploy before the applicable prerequisites in the concrete
[SYNTHETIC_LAB_CAPABILITY_MANIFEST.md](SYNTHETIC_LAB_CAPABILITY_MANIFEST.md) are
complete. [CAPABILITY_MANIFEST_TEMPLATE.md](CAPABILITY_MANIFEST_TEMPLATE.md)
remains the reusable schema for a later release or mode.
Never paste credentials, secret values, connection strings, PHI, Terraform
state, binary plans, or unsanitized logs into git, chat, tickets, or reports.

This runbook covers two mutually exclusive Terraform modes:

- `synthetic_lab` -> `synthetic-only` -> runtime `DATA_MODE=synthetic`;
- `authorized_beta` -> `phi-authorized` -> runtime
  `DATA_MODE=authorized_beta`.

The accepted `DL-20260903-04` path is `synthetic_lab`. A mode string is a
classification control, not permission to handle PHI. `authorized_beta`
remains blocked until the named-clinic, clinic-approval, applicable BAA, and
separate PHI-authorization references have all passed human review.

## 0. Approval ladder

The phase/mode approvals in `DL-20260903-03` and `DL-20260903-04` authorize the
D3 synthetic-lab work. They do not authorize an unreviewed plan. The human
approval sequence is deliberately staged:

| Stage | Human decision bound to evidence | Result allowed |
|---|---|---|
| Source closure | Reviewed committed SHA, complete local D3 gate, image scan evidence, green GitHub CI | Create no cloud resource |
| Bootstrap | Exact saved bootstrap plan/review hashes, two D3 resource groups, Box UUID, region, deploy identity, registry posture, and cost-alert decision | Apply only the bootstrap/state/runner root |
| Foundation | Exact create-only environment plan hash and null/empty prior-state proof | Create private services and ACA environment with database job/workloads off |
| Identity/release | Foundation-derived origins, production Clerk/Org configuration, source SHA, immutable API/worker and web digests, scan evidence | Prepare release; invite nobody |
| Database | Exact subsequent plan hash and prior lineage/serial | Create/run only the unscheduled preparation job and collect its attestation |
| Workloads | Exact saved workload plan hash, current lineage/serial, structured database attestation, live-network evidence, release evidence, and capability-manifest hash | Deploy digest-pinned web/API/worker |
| Tester admission | Live authority, readiness, audit/purge, restore, rollback, drift, monitoring, and offboarding evidence | Invite approved synthetic-only testers |

Every apply approval identifies the named human reviewer and binds the exact
private plan hash. A coding agent cannot approve on the owner's behalf.

## 1. Hard preflight gate

The human deployer must stop before the **bootstrap apply** unless every item
below that can exist before the foundation is complete:

- [ ] D3 owner authorization is recorded.
- [ ] `deployment_mode` is explicitly recorded in the bootstrap input and
      capability manifest; the later environment plan and resource tags must
      inherit that exact value.
- [ ] A dedicated `box_id` is recorded.
- [x] The separate development Cosmas OS Clerk application and zero-member
      development Beta Lab Organization are recorded. They are evidence of the
      identity design only, not production authority.
- [ ] Human deployer and dedicated beta deployment identity are named.
- [ ] Final region and residency decision is recorded. Central US is only a
      provisional 2026-09-03 finding, not standing approval.
- [ ] Azure Managed Redis `Balanced_B0` availability/quota and current
      two-node HA plus Private Link cost are confirmed in the selected region;
      the instance is TLS-only, `NoCluster`, `NoEviction`, AOF-persistent, and
      public-network-disabled.
- [ ] Network/CIDR/private DNS/egress/operator-access design is approved.
- [ ] The exact owner decision accepts a dedicated production web hostname and
      Clerk authentication policy before foundation planning. The recommended
      package is `beta.cosmaneura.com`, verified email + TOTP + recovery codes,
      SMS disabled, and no wildcard/shared `azurecontainerapps.io` origin.
- [ ] RTO/RPO, backup, retention, purge, monitoring, and support ownership are
      approved.
- [ ] The current **$170–260/month low-traffic planning envelope** is refreshed
      against the exact plan without credits, and the owner approves or revises
      the proposed **$350 aggregate alert across both D3 resource groups** plus
      a human-owned recipient. This alert is not a spending cap.
- [ ] All non-auth/D5 external connectors are DARK unless a later exact gate
      and capability-specific manifest says otherwise; Clerk AuthPort is
      enabled only for the approved Organization/Box when testers are admitted.
- [ ] The deploy contains no Track A resource, state, identity, credential, or
      database dependency.

Before the **workload apply**, the human must additionally stop unless:

- [ ] The foundation-derived dedicated `web_origin` and `api_origin` are
      recorded; production Clerk does not use the shared
      `azurecontainerapps.io` web hostname.
- [ ] The production Cosmas OS Clerk instance and empty production Cosmas Beta
      Lab Organization are configured for that exact origin and map to the
      dedicated Box.
- [ ] The reviewed API/worker and web digests, web release evidence, structured
      `database_preparation_attestation`, and
      `runner_live_network_evidence_reference` are all present.
- [ ] The concrete capability manifest is bound by its committed source path,
      commit SHA, and SHA-256 hash; all non-auth connectors remain dark.

For `synthetic_lab`, additionally confirm:

- [ ] Data classification is `synthetic-only`; PHI authorization is explicitly
      `NOT AUTHORIZED`.
- [ ] Only invented people, appointments, identifiers, images, and money may be
      entered or loaded; testers are told not to enter real clinic or patient
      information.
- [ ] Named-clinic, clinic-approval, BAA, and PHI-authorization references are
      omitted; they must not be replaced with dummy evidence.

For `authorized_beta`, additionally confirm every item below. Any missing item
is a hard stop:

- [ ] Named legal clinic and approved slug are recorded.
- [ ] Clinic authority approval is recorded.
- [ ] Applicable BAA/covered-entity and service-eligibility review is recorded
      by a human.
- [ ] A separate PHI release authorization reference is recorded.

## 2. Plan preparation

Use a new OS beta state boundary and a clean reviewed commit. The human owns all
credentials and executes any authenticated command. Automation or coding agents
must not receive live credentials or PHI.

Record these non-secret facts:

| Evidence | Required value |
|---|---|
| Git repository and full source SHA | **REQUIRED** |
| Reviewed Terraform/OpenTofu version and provider lock hash | **REQUIRED** |
| Deployment mode / data classification | **REQUIRED — exact bootstrap output and environment plan must match** |
| Subscription display name | **REQUIRED; omit IDs from shared reports** |
| New D3 state and workload resource-group names | **REQUIRED; neither may be `cosmaneura-os-synth`** |
| Final region(s) and decision reference | **REQUIRED** |
| Dedicated state backend/path and access boundary | **REQUIRED; never Track A state** |
| Protected runner | **REQUIRED; no VM public IP, exact runner subnet/NSG/NAT, default outbound disabled, Trusted Launch, exact UAMI, Azure Run Command only** |
| Runner toolchain | **REQUIRED; exact Azure CLI, Docker 29, Docker Buildx 0.30.1, Git, and jq apt versions plus checksum-pinned OpenTofu/Trivy recorded by `prepare-protected-runner.sh`** |
| Immutable API/worker and web image digests | **API/worker digest required for database preparation; both required before `deploy_workloads=true`; `sha256`, never `latest`** |
| Web release evidence | **REQUIRED before workloads; source SHA, derived API/web origins, production Clerk publishable configuration, scan, and rollback digests** |
| Production custom-domain evidence | **REQUIRED for production Clerk: protected self-hashed hostname/CNAME/asuid artifact bound to exact source, release, and post-initial-workload state; external DNS and Clerk verification remain human steps** |
| Human deploy identity and scoped-role review | **REQUIRED** |

Save any plan and state only in an approved encrypted/private location with
restrictive permissions. Treat both as sensitive because provider state and
plan material can contain derived credentials.

Bootstrap must use `infra/beta/bootstrap-local-state.sh` with an explicit state
path outside the repository. After bootstrap, initialize the private state
container only through `prepare-protected-runner.sh`; it verifies the VM's
Trusted Launch/UAMI/subnet/NSG/NAT boundary before Azure Run Command executes.
Do not create a public state exception, attach a public IP, use an interactive
identity for environment plans, or register a persistent CI runner.

### Sanitized plan evidence

Before apply, publish only a whitelist-based summary containing:

- UTC timestamp, source SHA, tool versions, lock-file hash, and exact private
  tfvars-file hash;
- exact deployment mode and derived data classification;
- target subscription display name, new D3 state/workload RGs, and approved region(s);
- plan counts: add/change/destroy/replace;
- resource addresses, resource types, and action arrays only;
- explicit confirmation that no D2 or Track A address is changed;
- immutable image digest when enabling workloads, plus non-secret
  SKU/scale/network choices;
- the strict, whitelisted before/after security-posture projection for every
  managed resource change (network exposure, RBAC scope, retention,
  ingress/probes, runtime mode, scale, and monitoring); a newly introduced
  resource type must fail closed until reviewed;
- a SHA-256 hash of the private saved plan or review artifact;
- reviewer decision and evidence ID.

Do not publish raw `terraform show`, before/after values, environment variables,
provider config, plan files, state files, or command transcripts that can carry
secrets. The D3 wrappers categorically reject delete, replacement, and forget
actions; an unexpected D2/Track A action is also a hard stop. A future
destructive recovery requires a separate reviewed procedure and code change.

Plan review record:

| Field | Value |
|---|---|
| Plan UTC | **BLOCKED / REQUIRED** |
| Source SHA | **BLOCKED / REQUIRED** |
| Plan hash | **BLOCKED / REQUIRED** |
| Add / change / destroy / replace | **BLOCKED / REQUIRED** |
| Reviewer and decision | **BLOCKED / REQUIRED** |
| No D2/Track A changes confirmed | **BLOCKED / REQUIRED** |

## 3. Human apply

Only the named human may perform or explicitly supervise the approved apply.
Use the exact saved plan reviewed above; do not regenerate an unreviewed plan at
apply time. Use `transport-to-protected-runner.sh`; it invokes
`apply-first-environment-plan.sh` for the create-only foundation and
`apply-environment-plan.sh` for every later or reconciliation stage. Each
requires a private approval JSON binding the reviewer/reference to the exact
plan hash and expected prior-state lineage/serial (both null only for the first
plan).

Record only:

- human deployer identity by approved organizational identifier;
- UTC start/end and command/tool version;
- source SHA, plan hash, and immutable image digest;
- exit code and sanitized add/change/destroy totals;
- new state/workload resource-group names and resource provisioning states;
- pre/post state serial and SHA-256 hashes, stored without state contents;
- exceptions, retries, and human disposition.

Apply evidence record:

| Field | Value |
|---|---|
| Human deployer | **BLOCKED / REQUIRED** |
| Apply UTC | **BLOCKED / REQUIRED** |
| Approved plan hash matched | **BLOCKED / REQUIRED** |
| Exit code and action totals | **BLOCKED / REQUIRED** |
| Pre/post state serial + hashes | **BLOCKED / REQUIRED** |
| All D3 resources succeeded | **BLOCKED / REQUIRED** |
| No D2/Track A mutation | **BLOCKED / REQUIRED** |

### Manual database preparation

The foundation plan forces `enable_database_preparation_job=false` and
`deploy_workloads=false`, so it contains neither database job nor Key Vault or
Blob workload data-plane writes. After the reviewed API/worker digest exists,
follow [DATABASE_PREPARATION.md](DATABASE_PREPARATION.md). A named human must
apply the preparation-stage plan, then use the protected `database-prepare`
transport operation to start the unscheduled job and retain only its validated,
self-hashed sanitized JSON result. Raw job logs remain root-only on the runner.

| Field | Value |
|---|---|
| Job image digest equals proposed API/worker digest | **BLOCKED / REQUIRED** |
| Azure execution identity and UTC | **BLOCKED / REQUIRED** |
| Job completed once with exit code 0 | **BLOCKED / REQUIRED** |
| Sanitized evidence JSON and SHA-256 | **BLOCKED / REQUIRED** |
| Non-admin, DDL denial, audit mutation denial, and expected head all `true` | **BLOCKED / REQUIRED** |
| Database URLs, credentials, plan/state, and raw diagnostics absent | **BLOCKED / REQUIRED** |

Only that reviewed live record may supply the structured
`database_preparation_attestation` used by the workload plan. It is separate
from `runner_live_network_evidence_reference`, which must come from live
private DNS and endpoint probes on the exact protected runner.

### Reviewed identity bootstrap

After workloads are applied, the private database is migrated, and the exact
Clerk settings are active, the human deployer creates a protected envelope
outside the repository with mode `0600`. The values below are deliberately
invented shape examples, not deployable defaults:

```json
{
  "schema_version": 1,
  "deployment_binding": {
    "source_sha": "FULL_REVIEWED_GIT_COMMIT",
    "release_id": "candidate-b",
    "state_lineage": "00000000-0000-4000-8000-000000000009",
    "state_serial": 3,
    "api_image_digest": "sha256:REVIEWED_64_HEX_DIGEST"
  },
  "bootstrap_manifest": {
    "schema_version": "cosmas-os/d3-beta-bootstrap/v1",
    "box_id": "00000000-0000-4000-8000-000000000001",
    "clinic_display_name": "Cosmas Beta Lab",
    "owner_display_name": "Example Owner",
    "clerk_issuer": "https://clerk.example.invalid",
    "clerk_subject": "user_example_owner",
    "clerk_organization_id": "org_example_beta",
    "reviewed_by": "Example Reviewer",
    "evidence_ref": "deploy:example-review"
  }
}
```

After generating fresh live network evidence for the workload state, the human
runs:

```text
bash ./infra/beta/transport-to-protected-runner.sh bootstrap-identity \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id candidate-b \
  --bootstrap-manifest /protected/ephemeral/beta-bootstrap-envelope.json \
  --artifact-out /protected/ephemeral/beta-bootstrap-evidence.json
```

The existing manifest schema calls this display field `clinic_display_name`.
For `synthetic_lab`, `Cosmas Beta Lab` is an organization label, not a clinic
claim. The transport refuses a manifest inside the repository or readable by
group/other users, binds it to the exact source/release/state/digest, retrieves
runtime secrets only inside the private runner, invokes both idempotent CLI
commands in the exact digest with Azure platform endpoints blocked, and returns
only a self-hashed sanitized result. The seed loads only the repository's fixed
invented queue and refuses `authorized_beta` mode.

## 4. Post-apply verification

For `synthetic_lab`, use invented data for the entire lifetime of the
deployment. For `authorized_beta`, do not use PHI until its separate release
decision has been recorded and the mode-specific plan has passed all guards.

- [ ] API and worker use the exact approved digest; ACR manifest matches.
- [ ] Active revisions are healthy and the prior valid digest is retained as a
      rollback target.
- [ ] Registry pulls use the dedicated D3 managed identity.
- [ ] Secret-reference names and Key Vault version references are correct;
      values are never displayed.
- [ ] Public database access is disabled and private resolution/connectivity is
      demonstrated from the workload and human recovery path.
- [ ] Storage public-container access is disabled; Box-scoped Blob behavior is
      tested without PHI.
- [ ] Clerk login, Org membership, session audience, and authority matrix are
      demonstrated by a human with invented/non-production identities first.
- [ ] The owner-only **Manage access** screen lists only the configured Box's
      reviewed identities; bind, deactivate, reactivate, and ownership transfer
      are demonstrated with opaque evidence references and invented users.
- [ ] Use the protected `offboarding-acceptance` baseline/verify flow for one
      synthetic non-owner. Deactivate the exact binding through the owner-only
      app path using its returned evidence reference, remove the Clerk
      Organization membership, revoke all Clerk sessions, and prove denial in
      a fresh browser session. The Clerk/browser portion is a human attestation,
      not cryptographic proof of the operator's identity; retain only the
      challenge-bound sanitized evidence.
- [ ] Caller-supplied identity headers cannot authenticate a D3 request.
- [ ] `/health` succeeds without exposing dependency credentials or PHI.
- [ ] `/ready` succeeds and proves database connectivity plus the expected
      Alembic head without exposing credentials or PHI.
- [ ] The worker's non-ingress `:8001/ready` probe succeeds only while its
      Celery heartbeat is current, the exact worker answers a broker-mediated
      control ping, and the database is at the expected Alembic head. Record
      status/latency only, never a broker or database URL.
- [ ] The manual database-preparation evidence proves the expected Alembic
      head, non-admin runtime role, DDL denial, and audit mutation denial;
      record its execution identifier, UTC, and sanitized evidence hash only.
- [ ] Audit replay and retention purge are demonstrated.
- [ ] Backup and restore are demonstrated to an isolated, exact-manifest-bound
      target with the protected `pitr-freeze` → `pitr-manifest` → `pitr-start`
      → `pitr-complete`/`pitr-cleanup` → `pitr-resume` sequence. Retain only
      self-hashed sanitized evidence, the distinct owner's manifest approval,
      and writer-freeze/resume evidence; never retain the database URL, raw Box
      identifier, source/target server IDs, or database contents outside the
      protected runner.
- [ ] Run protected `release-rollback` followed immediately by
      `release-forward` against two distinct staged, scan-clean, locked releases.
      Retain both exact digest/source/release bindings, all resulting revision
      IDs, route/readiness/HTTPS health evidence, and the forward zero-drift
      review hash. A mutable tag or a second tag for the same digest is not
      acceptable evidence.
- [ ] Refresh-backed post-apply plan reports zero drift or every difference is
      reviewed and accepted.
- [ ] PHI-safe monitoring, alert delivery, and human operational access are
      tested. The workload plan must contain exactly one common-schema email
      Action Group and enabled API and worker `Replicas < 1` alerts. Use the
      protected `alert-delivery` send/confirm flow. Confirmation must bind the
      unpredictable send challenge, exact send evidence hash, bounded UTC
      timestamp, and explicit owner assertion. Retain only timestamps, resource
      IDs, operation/evidence hashes, and assertion/reference hashes; never
      retain the recipient address or message body.
- [ ] Clerk AuthPort is active only for the approved Organization/Box; all
      non-auth/D5 connector rungs remain DARK.

## 5. Sanitized verification record

| Evidence | Required value |
|---|---|
| Deployment mode and classification match | **BLOCKED / REQUIRED** |
| API/worker revision IDs and health | **BLOCKED / REQUIRED** |
| ACR manifest digest match | **BLOCKED / REQUIRED** |
| `/health` status and non-sensitive body | **BLOCKED / REQUIRED** |
| API `/ready` status and non-sensitive body | **BLOCKED / REQUIRED** |
| Worker private `:8001/ready` status and latency | **BLOCKED / REQUIRED** |
| Database-preparation JSON hash, expected head, and execution ID | **BLOCKED / REQUIRED** |
| Private DNS/connectivity outcomes | **BLOCKED / REQUIRED** |
| Clerk Org/role test evidence ID | **BLOCKED / REQUIRED** |
| Audit replay and purge evidence IDs | **BLOCKED / REQUIRED** |
| Backup/restore evidence ID | **BLOCKED / REQUIRED** |
| Rollback/forward-recovery revision IDs | **BLOCKED / REQUIRED** |
| Post-apply drift counts | **BLOCKED / REQUIRED** |
| Capability manifest hash | **BLOCKED / REQUIRED** |

## 6. PHI release decision

Infrastructure success is not PHI authorization. A human legal/security owner
must record a separate release decision after all applicable prerequisites and
tests pass.

Common readiness rows must become `YES` before synthetic-lab testers are
admitted. Clinic, BAA, and PHI rows remain `N/A` or `NO` for `synthetic_lab`
and are mandatory before any `authorized_beta` plan or use.

| Decision | `synthetic_lab` | `authorized_beta` current state |
|---|---|---|
| D3 infrastructure ready | **REQUIRED before testers; currently NO** | **NO — NOT DEPLOYED** |
| Dedicated Organization and Box bound | **REQUIRED before testers; currently NO** | **NO — BLOCKED** |
| Clerk Org and authority proven | **REQUIRED before testers; currently NO** | **NO — BLOCKED** |
| Human deployment evidenced | **REQUIRED before testers; currently NO** | **NO — BLOCKED** |
| Named clinic and clinic approval | **N/A — lab is non-clinical** | **NO — BLOCKED** |
| BAA prerequisites accepted | **N/A — PHI PROHIBITED** | **NO — BLOCKED** |
| PHI authorized | **NO — NOT AUTHORIZED** | **NO — NOT AUTHORIZED** |

Stop immediately on any credential/PHI exposure, shared Track A dependency,
unreviewed destructive action, credits-only economics, or inability to prove
tenant and human-authority boundaries.
