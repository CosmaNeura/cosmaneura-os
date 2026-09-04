# D3 human deployment evidence checklist and runbook

Runbook status: **SYNTHETIC LAB PATH APPROVED / BOOTSTRAP EXECUTED / APPLICATION PENDING**
D3 status: **NOT COMPLETE / APPLICATION NOT DEPLOYED**
PHI status: **NOT AUTHORIZED**
Clerk AuthPort: **DEVELOPMENT CONFIGURED / PRODUCTION POLICY ACCEPTED / EXECUTION PENDING**
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

## 1. Completed bootstrap evidence and remaining pre-foundation gate

The bootstrap apply is complete. These checkboxes describe current evidence,
not an unexecuted template:

- [x] D3 owner authorization, `synthetic_lab`, and the `synthetic-only` boundary
      are recorded.
- [x] A dedicated `box_id`, two D3 resource groups, deploy identity, isolated
      state boundary, and private protected runner are recorded in protected
      bootstrap evidence.
- [x] The separate development Cosmas OS Clerk application and zero-member
      development Beta Lab Organization are recorded. They are identity-design
      evidence only, not production authority.
- [x] Central US is the accepted single-region resource-placement choice; this
      is not a legal-residency or capacity claim.
- [x] The private network/operator design, private ACR posture,
      `beta.cosmaneura.com`, verified-email + TOTP + recovery-code Clerk policy,
      SMS prohibition, best-effort recovery/support posture, and $350 combined
      notification threshold are accepted bounded operating choices.
- [x] All non-auth/D5 connectors are dark, PHI is unauthorized, and the D3
      boundary has no D2 or Track A dependency.

The human must stop before the **foundation plan or apply** unless every item
below is complete:

- [ ] The successor source is committed, GitHub CI is green, and the exact SHA
      is bound in protected release evidence.
- [ ] The two exact named Azure capacity requests are authorized, submitted,
      and resolved; Container Apps has at least four sandbox cores and Managed
      Redis `Balanced_B0` is advertised in Central US.
- [ ] Capacity, selected-SKU, Private Link, and exact-plan cost evidence is
      refreshed without assuming credits; a human-owned recipient for the
      accepted $350 combined alert is recorded privately.
- [ ] The protected runner's source, identity, toolchain, private state path,
      no-public-IP posture, and network boundary are freshly reverified.
- [ ] The named accountable support owner and private escalation route are
      recorded before tester admission.

Before the **initial workload apply**, the human must additionally stop unless:

- [ ] The foundation-derived `api_origin` and default web host plus the selected
      dedicated `web_origin` are recorded; production Clerk never treats the
      shared `azurecontainerapps.io` hostname as an application origin.
- [ ] The production Cosmas OS Clerk instance and empty production Cosmas Beta
      Lab Organization use the approved preliminary auth/Org policy, map to the
      dedicated Box, and supply the reviewed publishable key for the web build.
- [ ] The reviewed API/worker and web digests, web release evidence, structured
      `database_preparation_attestation`, and
      `runner_live_network_evidence_reference` are all present.
- [ ] The concrete capability manifest is bound by its committed source path,
      commit SHA, and SHA-256 hash; all non-auth connectors remain dark.

Before the **DNS-ready workload promotion** or any tester admission, also stop
unless:

- [ ] The initial web revision produced protected CNAME/`asuid` evidence for
      the selected hostname, and a human independently verified those exact DNS
      records and Azure certificate state.
- [ ] Clerk's exact custom application origin and redirects are configured and
      read back; no wildcard, shared ACA, MyCatholicDoctor, or Track A origin is
      present.
- [ ] A fresh workload generation and exact approval change only the reviewed
      DNS-ready progression fields and current live-network evidence.

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
  managed resource change (network exposure, exact RBAC scope/role/principal,
  retention,
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
requires a private duplicate-free, self-hashed v2 approval binding the exact
source, release, stage, plan/review/tfvars hashes, state tuple, owner assertion,
authorization and claim hashes, and content-addressed bundle. Foundation also
binds the readiness, human-review, cost, package-manifest, and approval-request
hashes. Its effective expiry is the minimum of every carried expiry and is
rechecked immediately before mutation. The runner atomically consumes it with
a root-owned apply-attempt claim; an interrupted/unknown apply requires explicit
inspection and recovery rather than an ordinary retry.

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

After the final DNS-ready workload generation is applied, `workload-verify` is
fresh and successful for that exact state, the private database is migrated,
and the exact Clerk settings are active, the human deployer creates a protected
envelope outside the repository with mode `0600`. The values below are
deliberately invented shape examples, not deployable defaults:

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

After generating fresh live network evidence and the required workload
attestation for the same state, the human runs:

```text
/bin/bash -p ./infra/beta/transport-to-protected-runner.sh bootstrap-identity \
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
runtime secrets only inside the private runner, invokes both bootstrap commands
twice in the exact digest with Azure platform endpoints blocked, and compares
two self-hashed readbacks with stable Box, principal, Clerk-binding, audit,
appointment, patient-link, and pending-ticket counts. Any count change is a
hard failure. The returned evidence contains only those counts and hashes. The
seed loads only the repository's fixed invented queue and refuses
`authorized_beta` mode.

## 4. Post-apply verification

For `synthetic_lab`, use invented data for the entire lifetime of the
deployment. For `authorized_beta`, do not use PHI until its separate release
decision has been recorded and the mode-specific plan has passed all guards.

- [ ] API and worker use the exact approved digest; ACR manifest matches.
- [ ] Protected `workload-verify` is `verified` for the exact current
      source/release/state/Box: API, worker, and web revisions/images match;
      managed-environment subnet/internal/Log Analytics topology, tags, runtime
      environment and secret references, commands/args, probe definitions,
      CPU/memory/ephemeral-storage bounds, scale bounds, and three-revision
      rollback retention match; traffic is 100%
      to one ready revision; public API/web health succeeds; and the worker is
      non-ingress and ready. A new verification performs live reads; only
      artifact retrieval is cached. The resident attestation is revalidated
      before identity bootstrap or any runtime-acceptance phase; missing,
      stale, or altered evidence is a hard stop. It must be no more than one
      hour old (with at most five minutes of forward clock skew) at each
      downstream gate.
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
- [ ] Protected `audit-replay` proves the completed synthetic ticket timeline
      is Box-scoped, ordered, linked to its operation, denied from an alternate
      Box, and exported without identifiers or content; retention purge is also
      demonstrated.
- [ ] Backup and restore are demonstrated to an isolated, exact-manifest-bound
      target with the protected `pitr-freeze` → `pitr-manifest` → `pitr-start`
      → `pitr-complete`/`pitr-cleanup` → `pitr-resume` sequence. Retain only
      self-hashed sanitized evidence, the distinct owner's manifest approval,
      and writer-freeze/resume evidence; never retain the database URL, raw Box
      identifier, source/target server IDs, or database contents outside the
      protected runner. The terminal completion artifact must include the
      bound freeze, restore-point, restore-start, and restore-ready timestamps
      plus measured RTO/RPO seconds.
- [ ] Run protected `release-rollback` followed immediately by
      `release-forward` against two distinct staged, scan-clean, locked releases.
      Release B must be a descendant of A with a different Git tree, and all
      four A/B API/web digests must be pairwise distinct.
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
| Workload verification JSON hash and exact source/release/state binding | **BLOCKED / REQUIRED** |
| `/health` status and non-sensitive body | **BLOCKED / REQUIRED** |
| API `/ready` status and non-sensitive body | **BLOCKED / REQUIRED** |
| Worker private `:8001/ready` status and latency | **BLOCKED / REQUIRED** |
| Box-scoped, content-free audit replay evidence hash | **BLOCKED / REQUIRED** |
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
| D3 infrastructure ready | **REQUIRED before testers; currently NO — bootstrap/runner only** | **NO — application foundation and workloads absent** |
| Dedicated Organization and Box bound | **REQUIRED before testers; currently NO** | **NO — BLOCKED** |
| Clerk Org and authority proven | **REQUIRED before testers; currently NO** | **NO — BLOCKED** |
| Human deployment evidenced | **REQUIRED before testers; currently NO** | **NO — BLOCKED** |
| Named clinic and clinic approval | **N/A — lab is non-clinical** | **NO — BLOCKED** |
| BAA prerequisites accepted | **N/A — PHI PROHIBITED** | **NO — BLOCKED** |
| PHI authorized | **NO — NOT AUTHORIZED** | **NO — NOT AUTHORIZED** |

Stop immediately on any credential/PHI exposure, shared Track A dependency,
unreviewed destructive action, credits-only economics, or inability to prove
tenant and human-authority boundaries.
