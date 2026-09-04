# D3 isolated early-adopter beta readiness

Status as of 2026-09-04: **SYNTHETIC LAB PATH APPROVED / ISOLATED
BOOTSTRAP AND PROTECTED RUNNER PRESENT / CURRENT WORKTREE GATES PASS / RELEASE
SHA AND CI BINDING REQUIRED / APPLICATION NOT DEPLOYED / D3 NOT COMPLETE**.

The owner authorized D3 planning and implementation with the exact gate
`APPROVE D3 ISOLATED EARLY-ADOPTER BETA`. `DL-20260903-04` then selected the
first D3 slice: a strictly non-PHI **Cosmas Beta Lab** for the owner and invited
outside testers. That decision removes the named-clinic and BAA prerequisites
only from this synthetic path; it does not authorize PHI or a clinic deployment.

**PHI is NOT AUTHORIZED. All live connectors are DARK.** The isolated D3
bootstrap/state boundary and protected runner exist. The application
foundation, database-preparation job, workloads, custom-domain binding, and
production Clerk instance do not. `cosmaneura-os-synth` must not be promoted in
place or used as a D3 dependency.

The complete local `./scripts/d3-self-test.sh` gate passed on 2026-09-04 with
**447 Python** and **32 web** tests, bootstrap OpenTofu **6/6**, environment
OpenTofu **35/35**, clean deployment guards, and successful local Linux/amd64
API and web builds. Ruff, Pyright, Bash syntax, ShellCheck, formatting, and diff
integrity also pass. The latest current-database Trivy scans found **0 fixable
HIGH/CRITICAL findings**, and independent adversarial reviews found no open
P0-P2 source defect. These are worktree-local results only. Any deployable
release must use a committed SHA with green GitHub CI and bind that exact SHA
in its external protected release record. Live bootstrap/runner evidence
exists; application-foundation, production Clerk, workload, and acceptance
evidence remains pending.

Every deployment record must select exactly one Terraform `deployment_mode`:

| Mode | Data classification | Runtime `DATA_MODE` | Clinic / BAA / PHI evidence |
|---|---|---|---|
| `synthetic_lab` | `synthetic-only` | `synthetic` | Not required; real clinic or patient data remains prohibited |
| `authorized_beta` | `phi-authorized` | `authorized_beta` | Named clinic approval, applicable BAA evidence, and a separate PHI authorization reference are all mandatory |

`synthetic_lab` is the safe default. Selecting `authorized_beta` does not itself
grant authority: Terraform refuses the plan unless all three protected evidence
references are present, and the application still fails closed without its PHI
authorization reference. The bootstrap output binds the selected mode into the
first environment plan so the two Terraform roots cannot silently disagree.
After entering `authorized_beta`, a `prevent_destroy` mode lock blocks an
ordinary plan from relabeling retained PHI as synthetic.

## Required owner and human inputs

| Input | State | Evidence required before deployment |
|---|---|---|
| Deployment mode | **`synthetic_lab` APPROVED** | Record `synthetic_lab`; any later `authorized_beta` plan requires a new reviewed evidence set |
| Legal name of first early-adopter clinic | **NOT REQUIRED FOR `synthetic_lab`; BLOCKED FOR `authorized_beta`** | Human-confirmed legal organization name, kept out of public resource names |
| Dedicated Box identity | **ASSIGNED IN PROTECTED BOOTSTRAP EVIDENCE** | Exact UUID remains private; live production Clerk Organization-to-Box binding proof is still required |
| BAA and PHI authorization prerequisites | **NOT REQUIRED FOR `synthetic_lab`; BLOCKED FOR `authorized_beta`** | Human/legal BAA confirmation plus a separate PHI release authorization for the PHI-capable mode |
| Clerk application and Organization | **DEVELOPMENT STRUCTURE CREATED / PRODUCTION POLICY CHOSEN, EXECUTION PENDING** | The dedicated hostname and strict production auth/Org policy are accepted inputs. After foundation-derived API/default-host evidence, create the empty production app/Org and use its publishable key for the initial web build; verify final custom-origin/redirect configuration before the DNS-ready workload promotion and any tester admission |
| Beta web host and exact origin | **`beta.cosmaneura.com` ACCEPTED / FOUNDATION OUTPUT PENDING** | Foundation-derived API/default-host evidence, production Clerk configuration, reviewed web digest, DNS/certificate proof, and human release evidence |
| Human deployer | **PENDING HUMAN RECORD** | Named accountable human, exact deployment identity, plan-bound approval records, and execution evidence |
| Region and data residency | **CENTRAL US ACCEPTED / LIVE CAPACITY BLOCKED** | The synthetic-lab operating choice is accepted; fresh evidence still shows Container Apps quota below requirement and Managed Redis `Balanced_B0` unavailable until the named capacity requests resolve |
| Celery broker | **SOURCE SELECTED / DEPLOYMENT EVIDENCE REQUIRED** | Private Azure Managed Redis `Balanced_B0`, two-node HA, TLS, `NoCluster`, `NoEviction`, one-second AOF; refresh Central US availability, quota, and price before plan |
| Network and operator access | **BOOTSTRAP RUNNER PRESENT / FOUNDATION NETWORK PROOF PENDING** | The protected runner boundary exists; refresh its preflight before every operation, then prove exact private DNS and endpoint reachability after the foundation |
| Database preparation | **SOURCE IMPLEMENTED / LIVE ATTESTATION PENDING** | Run the manual digest-pinned in-network job and keep workloads disabled until its structured `database_preparation_attestation` and the separate `runner_live_network_evidence_reference` are recorded |
| RTO, RPO, retention, and purge | **BEST-EFFORT SYNTHETIC POLICY ACCEPTED / LIVE EXERCISES PENDING** | No quantified SLA; exact backup, PITR, purge, rollback, and forward-recovery acceptance remains mandatory before testers |
| Monthly cost and alert posture | **OPERATING CHOICE ACCEPTED / EXACT-PLAN REFRESH AND RECIPIENT PENDING** | Approximately $170–260/month at low traffic without credits and a $350 aggregate notification alert across both D3 resource groups; the alert is not a spending cap |
| Support envelope | **BEST-EFFORT POLICY ACCEPTED / PRIVATE OWNER AND ROUTE PENDING** | Record the accountable human and private escalation route before tester admission |

The bootstrap already ran under its consumed exact-plan approval. Until each
remaining stage's inputs and exact authority are recorded, no capacity request,
foundation, production Clerk, DNS, database, workload, or tester-admission
mutation may proceed. Source work, synthetic tests, and read-only
reconnaissance may continue. A `synthetic_lab` deployment does not require
invented clinic or BAA evidence, but its fixtures and user-entered content must
never contain real clinic identifiers, patient data, or production exports.
Credentials and vendor tokens remain outside the repository and
human-controlled.

## Remaining staged approvals

The D3 phase and `synthetic_lab` mode are already authorized. The exact
bootstrap plan was separately approved and applied; its one-use approval is
consumed, and the isolated state/runner boundary is present. Those completed
steps do not replace the human review that binds each remaining irreversible
cloud step to its exact saved plan or release evidence:

1. **Release eligibility:** select a committed SHA from the locally verified
   source, require green GitHub CI, and bind that exact SHA in the external
   protected release record. This step does not create D3 cloud resources.
2. **Azure capacity:** approve and submit only the two named support requests,
   then wait for fresh proof of at least four Container Apps sandbox cores and
   stable Managed Redis `Balanced_B0` availability in Central US.
3. **Foundation apply:** after capacity and refreshed cost evidence, separately
   approve the exact create-only environment
   plan. It must leave the database-preparation job and all workloads disabled.
4. **Identity and release preparation:** use the selected dedicated hostname
   and foundation-derived API/default-host evidence to configure the
   preliminary production Cosmas OS Clerk instance and empty Beta Lab Org;
   build, scan, push, and record the immutable API/worker and web digests.
5. **Database preparation:** approve the exact subsequent plan, run the
   unscheduled job once, and review the structured
   `database_preparation_attestation` plus protected-runner live-network
   evidence.
6. **Workload and domain progression:** approve the exact initial workload
   plan and its current state lineage/serial, image digests, web release
   evidence, capability-manifest hash, database attestation, and live-network
   evidence. After that web revision yields exact domain-verification material,
   verify DNS and Clerk origin/redirect configuration, then separately approve
   the DNS-ready workload generation.
7. **Tester admission:** invite nobody until synthetic login/authority,
   readiness, audit/purge, restore, rollback, drift, monitoring, and
   offboarding evidence has been reviewed by the accountable human.

Placeholders are never acceptable: each deployment must carry its exact
committed manifest binding and exact plan hashes. See
[SYNTHETIC_LAB_CAPABILITY_MANIFEST.md](SYNTHETIC_LAB_CAPABILITY_MANIFEST.md) for
the current source-controlled capability decision and unresolved live fields.

## Sanitized Azure evidence

Sanitized inventory and provider/capacity evidence was collected on 2026-09-03
from the enabled default subscription named `Microsoft Azure Sponsorship`.
Subscription and tenant IDs are intentionally omitted here.

### Naming and collision check

- No resources were tagged `env=beta` or `env=early_adopter_beta`.
- The only resources tagged `product=cosmas-os` belong to the D2 synthetic
  resource group `cosmaneura-os-synth` and carry `phi=false`.
- `cosmaneura-os-beta` did not exist at query time.
- Neutral placeholders `cosmasosbetaacr`, `cosmasosbetast`, and
  `kvcosmasosbeta` passed global name-availability checks at query time. These
  are not approved final names and availability can change.
- Final names must derive from a human-approved opaque `beta_id` that does not
  encode a clinic name or other sensitive context, and must be rechecked
  immediately before deployment. The private evidence record maps that token
  to the approved Beta Lab Organization and Box; an `authorized_beta` record
  additionally maps it to the approved clinic. Do not reuse or modify similarly
  named non-OS resources elsewhere in the subscription.

### Accepted region and unresolved capacity

**Central US is the accepted single-region choice for this synthetic lab.** It
is a resource-placement decision, not a legal-residency determination or a
capacity guarantee. The refreshed 2026-09-04 monitor is fail-closed:

- Container Apps `SandboxCores` is **1**, below the required **4**;
- stable and preview catalogs do not advertise Managed Redis `Balanced_B0` in
  Central US; and
- neither of the two exact named capacity requests has been submitted.

The observations below are earlier selection evidence, not proof that the
current capacity gate is satisfied:

- East US currently advertises Container Apps, Redis, ACR, Key Vault, Storage,
  and Log Analytics, but PostgreSQL Flexible Server reports provisioning
  restricted for this subscription with no available versions or editions.
- Central US currently advertises all of those service families, including
  the `Microsoft.Cache/redisEnterprise` resource type used by Azure Managed
  Redis. PostgreSQL
  reports versions 11–18; Burstable, General Purpose, and Memory Optimized
  editions; zone-redundant HA and geo-backup capability; and
  `Standard_B1ms` in zones 1–3.
- Container Apps reports Consumption and Flex workload profiles in both East
  US and Central US.
- Reported network quota usage is 3/1000 VNets and 6/65536 private endpoints
  in East US, and 1/1000 VNets and 0/65536 private endpoints in Central US.
- Current subscription inventory includes 3 East US Container Apps
  environments, 14 Container Apps, 9 registries, 9 Key Vaults, 20 Log
  Analytics workspaces, and 18 user-assigned identities. These counts indicate
  room for one small stack but do not guarantee capacity.
- Required resource providers are registered. Central US advertised the
  protected runner's `Standard_B2s` shape, and the applicable BS-family quota
  had room for its two vCPUs when checked. Availability and quota are still
  point-in-time evidence and must be refreshed in the exact-plan review.

### Network capability evidence

Read-only private-link discovery exposed these service subresources:

| Service | Private-link group | Private DNS zone |
|---|---|---|
| PostgreSQL Flexible Server | `postgresqlServer` | `privatelink.postgres.database.azure.com` |
| Azure Managed Redis | `redisEnterprise` | `privatelink.redis.azure.net` |
| Key Vault | `vault` | `privatelink.vaultcore.azure.net` |
| Storage | `blob` and other account services | `privatelink.blob.core.windows.net` for Blob |

The current D2 Basic ACR exposed no private-link resource. The accepted D3
posture is Premium/private ACR with Private Link. The source also supports a
lower-cost Basic/public exception only for a separately reviewed
`synthetic_lab` choice; it is not selected for this deployment. Live routing
and refreshed exact-plan cost evidence remain **REQUIRED** before foundation
approval.

## D3 cost posture and D2 shaping reference

These are current configurations, not price quotes and not a D3 recommendation:

| Component | D2 shape |
|---|---|
| Container Apps | Consumption; no VNet or zone redundancy |
| API | 0.25 vCPU / 0.5 GiB; scale-to-zero; max 1 |
| Worker | 0.25 vCPU / 0.5 GiB; min 1 / max 2 |
| PostgreSQL | Central US Burstable `Standard_B1ms`; 32 GiB P4; 7-day backup; no HA or geo backup |
| Redis | Basic C0; no replicas/zones; TLS 1.2; non-TLS disabled |
| ACR | Basic; public network; no zone redundancy; admin disabled |
| Storage | Standard_LRS Hot; public network; public-container capability currently allowed |
| Key Vault | Standard/RBAC; public network; 7-day soft delete; purge protection not enabled |
| Log Analytics | PerGB2018; 30-day retention; public ingestion and query |

D3 must not copy the D2 public-network posture merely because it is cheaper.
For the source-declared private, low-traffic D3 shape, the current planning
envelope is approximately **$170–260/month** across the bootstrap/state and
workload resource groups, excluding founder support, Clerk paid-plan charges,
taxes, and unusual egress or log volume, and without relying on Azure credits.
This is planning evidence, not a quote or approval; refresh the calculator and
contract prices against the exact plan.

The proposed first-deployment guardrail is a **$350/month aggregate Cost
Management alert across both D3 resource groups**. It is a notification
threshold, not a spending cap: Azure will not stop resources at that amount.
The final evidence must prove that the combined scope is covered and record a
human-owned recipient. A workload-resource-group alert alone must not be
described as covering the bootstrap/state group.

The D3 broker is no longer an open design choice. It uses private Azure
Managed Redis `Balanced_B0` with two-node HA, encrypted `NoCluster` access,
`NoEviction`, and one-second AOF persistence. Read-only Central US retail
evidence on 2026-09-03 was $0.018 per node-hour, or approximately $26.28/month
for the selected HA pair, plus the private endpoint and data processing. The
retiring D2 Basic C0 shape was about $16.06/month. A one-replica internal Redis
Container App was rejected because it would not provide managed failover or
durable TLS broker state, and the current application has no PostgreSQL scanner
to restore messages lost with the broker.

Cost variables that must be priced explicitly include:

- API and always-on worker vCPU/GiB-seconds, replica floors, and egress;
- PostgreSQL SKU, storage/IOPS, backup retention, HA, and geo-backup;
- the selected Managed Redis B0 HA service, private endpoint, and current
  contract-specific price;
- ACR tier, especially if private access requires Premium;
- private endpoints, private DNS, NAT/firewall or other controlled egress;
- Blob redundancy/capacity/transactions and immutable/audit storage needs;
- Key Vault operations and retention/purge posture;
- PHI-safe monitoring ingestion and retention;
- Clerk plan and support/operations labor.

## Required artifacts and exit boundary

The current source provides offline-tested Clerk token/Org/Box enforcement,
reviewed identity bootstrap, managed-identity Blob access with Box-prefixed
keys, exact-origin/TLS startup checks, current-schema readiness, and separate
guarded infrastructure roots. The local React queue remains synthetic-only and
the beta build renders a blocked screen rather than contacting an API until a
real login provider is configured. The synthetic lab permits review, edit, and
decision actions only on the fixed invented queue; schedule import, PatientLink
creation, new chase creation, and uploads remain blocked until an
`authorized_beta` deployment. The source now declares a dedicated HTTPS-only
static web Container App and digest-gated release contract; neither has been
deployed. The runtime database role and migration path are implemented as a
separate manual, digest-pinned job; its live evidence has not been produced.
Follow [WEB_RELEASE.md](WEB_RELEASE.md).

- Review the concrete
  [SYNTHETIC_LAB_CAPABILITY_MANIFEST.md](SYNTHETIC_LAB_CAPABILITY_MANIFEST.md),
  bind its final committed version/hash to the workload approval, and retain
  [CAPABILITY_MANIFEST_TEMPLATE.md](CAPABILITY_MANIFEST_TEMPLATE.md) for later
  modes/releases.
- Follow [HUMAN_DEPLOYMENT_EVIDENCE.md](HUMAN_DEPLOYMENT_EVIDENCE.md).
- Follow [DATABASE_PREPARATION.md](DATABASE_PREPARATION.md) after the
  foundation and reviewed API/worker image exist.
- Choose and follow the separate-app enrollment path in
  [CLERK_SETUP_AND_MIGRATION.md](CLERK_SETUP_AND_MIGRATION.md).
- Demonstrate login and authority mapping, audit replay, purge,
  backup/restore, and digest rollback. For `synthetic_lab`, use invented data
  only. `authorized_beta` remains blocked until its separate evidence set is
  complete.
- Keep `box_id` at every shared boundary and keep coding agents unable to reach
  live PHI or live credentials.

D3 remains **NOT COMPLETE** until every required item is evidenced and a human
has performed or explicitly confirmed the approved deployment. D4 and all D5
connector activations remain separately gated.
