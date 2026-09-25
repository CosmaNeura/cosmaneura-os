# Optional East US 2 VM staging path

Prepared September 25, 2026 against published application/infra source
`88ce82998ed14fd80608c9d282380b6d3fee8237`. This is a proposed alternative,
not a selected architecture, deployment approval, allocated server, or beta
acceptance. No cloud resource, account, secret or DNS settings were changed.
This assessment uses public prices and authorized Azure quota/SKU metadata.

**Recommendation: one dedicated `Standard_D2s_v5` Linux VM (2 vCPU, 8 GiB) in
East US 2, with PostgreSQL and Redis private on the host, while keeping the
managed-service requests open.** It avoids the current Container Apps,
PostgreSQL and Managed Redis eligibility blockers. It preserves CosmaBot as its
own application, datastore and deployment, connecting to Cosmaneura by approved
HTTPS APIs. The protected Central US runner/state remains separate and retained.
Scribe work remains paused here.

## Sizing and feasibility

Azure currently advertises the exact D2s_v5 East US 2 SKU with no subscription
restrictions. Its `standardDSv5Family` quota and total regional quota are both
65 vCPU, with zero used. These reads prove neither allocation nor performance.
The prior B2s_v2 SKU observation remains useful, but a later exact-family quota
query returned no `standardBSv2Family` row; the BS-family quota is not proof for
Bsv2. Do not assume Bsv2 eligibility from a similarly named family.

Existing source allocates API 0.5 CPU/1 GiB, Celery worker 0.5 CPU/1 GiB with
concurrency 1, and static web 0.25 CPU/0.5 GiB. That is **2.5 GiB before the
host, PostgreSQL, Redis, proxy, backup and deployment overhead**. The 4 GiB B2s
is therefore not the recommended host. A provisional 8 GiB envelope can retain
those app limits and reserve roughly 1.5 GiB for PostgreSQL, 0.75 GiB for Redis
process overhead, 1.25 GiB for host/proxy/monitoring and 2 GiB for headroom.
These are planning allocations, not measured RSS or safe hard limits. Redis
`maxmemory` must leave room for AOF rewriting; database connections/work memory
also need bounded settings. No model inference or image compilation on this VM.

D2s_v5 costs only **$9.34/month more** than the 8 GiB burstable B2s_v2 at public
retail. Prefer sustained CPU while sizing remains unmeasured. Two CPU are a
starting point for limited synthetic staging, not a full-beta concurrency
promise. Use one API process/one existing Celery worker initially, bounded
backup/migration activity and controlled maintenance deployment; do not promise
blue/green overlap or zero downtime on this host. Measure actual workflow
latency, memory peak and disk I/O before deciding whether to resize.

## Proposed resource inventory and cost

New workload-only resource group: proposed `rg-cosmas-os-vm-staging-eus2-lab01`.
Names below are candidates; global availability and exact IDs belong in the
reviewed plan. Existing protected state/bootstrap must never be recreated.

| Resource | Proposed quantity / setting | Monthly fixed estimate |
|---|---|---:|
| Linux VM `vm-cosmabot-staging-eus2-lab01` | D2s_v5, 2 CPU/8 GiB, no Spot | $70.08 |
| Managed disks | 64 GiB Standard SSD LRS OS + 128 GiB persistent data | $14.40 |
| Standard static public IPv4 | One, attached to VM NIC | $3.65 |
| Container registry | One Premium, private, admin user disabled | $50.69 |
| Ordinary private endpoints | Four: registry, Key Vault, application Blob, backup Blob | $29.20 |
| Private DNS zones | Three: ACR, Key Vault, shared Blob zone | $1.50 |
| Metric alerts | Three single-resource time series, gross before free allowance | $0.30 |
| **New fixed subtotal** | | **$169.82** |
| Retained Central US runner/state/network | Existing fixed-cost baseline | $83.13 |
| **Combined fixed subtotal** | | **$252.95** |

Also proposed: one VNet, workload and private-endpoint subnets, one NIC, NSG,
managed runtime identity, container-scoped role assignments, Standard Key Vault,
two separate StorageV2 Hot LRS accounts/containers (application objects and
backup repository), Log Analytics, and alert action group. VNet/NSG/NIC/identity
have no separate meter included here; data, operations and logs are variable.
No new NAT gateway, load balancer, Container Apps environment, managed PostgreSQL,
managed Redis or Azure Backup protected-instance service is included. Explicit
outbound uses the VM's static IP. If access from the retained runner needs VNet
peering and extra DNS links, those must appear in the plan; peering transfer is
additional. This is not permission to alter its bootstrap or current state.

All estimates use 730 hours/month, USD on-demand retail, without discounts,
credits, free grants or tax. An illustrative **10 GB application objects +
100 GB retained database/WAL backups + 0.1 GB/day logs + 10,000 Key Vault
operations** adds $10.45, giving **$180.27 incremental / $263.40 combined**.
The retained backup byte count is an assumption, not a retention guarantee.
Traffic, disk/blob/DNS operations, snapshots, extra backup growth, additional
metrics/security products and external identity/model/email/domain/Apple costs
remain extra. This is not the full subscription bill or a spending cap.
The existing $350 notification budget does not automatically cover this new RG;
its final scope and alert recipients must be reviewed explicitly.

An authenticated public **Basic ACR exception**, if separately selected, removes
one private endpoint/zone and lowers the fixed estimates to **$116.40 incremental
/ $199.52 combined**, or **$126.85 / $209.97** with the same illustrative usage.
It changes registry network posture; the private profile above is recommended.
B2s_v2 saves $9.34 under either profile, with burst/quota uncertainties. No
registry-posture change or alternative SKU is preapproved by this proposal.

## Required deployment shape

- **Endpoints:** approved web name `staging.cosmas.ai`; proposed separate API
  name `api.staging.cosmas.ai`. The API name is not known to exist or be selected.
  Both would target the new static IP, with distinct TLS virtual hosts. An
  authenticated API remains necessary even if the final review chooses one
  origin. Reserve `bot.cosmas.ai` as previously directed.
- **Network:** only HTTPS and narrowly handled ACME HTTP challenge/redirect
  ingress; no public PostgreSQL, Redis, health, Docker or management ports.
  SSH, if needed, restricted to the approved administrative source, never the
  Internet. Private data containers publish no host ports. Apply container-aware
  firewall rules; Docker must not bypass the intended NSG/host policy.
- **TLS:** automated public certificate renewal with failure alerts. PostgreSQL
  retains `verify-full` plus `sslrootcert=system`; Redis retains authenticated
  `rediss` with required certificate verification. For private container names,
  use dedicated CA-signed certificates with exact SANs and an installed public
  trust bundle in client containers. CA signing/server keys stay protected.
  Prove wrong-host and untrusted-chain refusal; never weaken existing guards.
- **Identity/secrets:** Clerk JWT issuer/JWKS/audience/organization and exact
  web/native authorized origins remain mandatory. Assign only the narrow runtime
  identity to the VM: application Blob scope and separately approved Core API
  access, with no broad Key Vault/deployment/backup permissions. Only API/worker
  may reach IMDS, through explicitly isolated container networks/firewall rules;
  web, proxy, database, broker and other containers must be denied. Do not attach
  stronger host identities to IMDS and assume a container cannot select them.
  A separate, authorized deployment identity installs exact versioned Key Vault
  secrets into per-service, least-readable runtime files; credentials are absent
  from images, user data, source and logs. Registry pull and backup credentials
  must likewise remain host-only and narrowly scoped, not extra VM identities
  available to the app. This isolation/rotation/install mechanism is a required
  implementation, not a claim that ordinary Compose provides it.
- **Release:** reuse production Dockerfiles and immutable image digests, pinned
  base images, non-root processes and restricted mounts/capabilities. Keep
  single-worker semantics and runtime flags/Box checks. Disable dev servers,
  source mounts, default credentials, live-data mode and unapproved connectors.
  Existing development Compose is not deployable. Use a new reviewed deployment
  profile/state namespace; current protected managed-service apply scripts do
  not accept a VM plan. Retain exact image/config/schema/plan hashes and a
  maintenance rollback package. Migrations require a backup and explicit schema
  compatibility; do not promise an automatic destructive downgrade.

## Persistence, recovery and the acceptance milestone

Store PostgreSQL and Redis data/AOF on the managed data disk, never ephemeral
container storage. Redis needs authentication, TLS, `noeviction` and one-second
AOF; a disk is not high availability. Propose encrypted off-host PostgreSQL
base backups plus continuous WAL to the separate private Blob account, seven-day
retention, monitored backup freshness and a restore identity separate from the
host writer. Keep backup deletion protection/lifecycle consistent with the
retention policy. Proposed targets are RPO ≤5 minutes and RTO ≤2 hours for this
synthetic stage; neither is proven. Validate recovery into an isolated restored
database before admitting the candidate. Keep side-effect execution disabled
while reconciling restored state. Snapshotting alone is not PostgreSQL PITR.

The **modern workspace handoff/routine workers poll PostgreSQL from the API
lifespan**. Their durable admission and ambiguous-outcome policies, not just a
Celery queue replay, determine user-visible recovery. Keep the current
Celery/Redis component for the legacy operation path, but do not invent a generic
scanner that blindly reruns pending/uncertain actions. Reserved work can expire
to abandoned; uncertain dispatched work must show unknown and require explicit
retry. Legacy fake-notification durability is not modern workspace acceptance.

One bounded connected acceptance sequence should establish:

1. Real sign-in at the actual staging host, authorized synthetic workspace, and
   an actual non-Scribe handoff through its normal worker/provider path.
2. A handoff queued before a graceful restart resumes while its reservation is
   still valid; completed work and its saved result reopen after restart.
3. An interrupted/ambiguous dispatch stays unknown and needs explicit retry,
   without a duplicate external effect; expired reservations stay abandoned.
4. A protected backup restores successfully, with matching durable work/audit
   evidence and a recorded measured recovery interval.

Use existing applicable local checks plus these deployment-specific exercises,
not a repeat of every unchanged suite. Actual service activation remains
separately bounded. Then rebuild/configure the Mac and iPhone candidates for
this verified endpoint and perform their still-required signing, device and
connected acceptance. Scribe acceptance remains with its owner.

**One host is one failure domain.** Host maintenance/failure interrupts the app,
database and broker together. Backups reduce loss and recovery time; they do
not equal the prepared managed Redis HA design or remove full-beta availability
requirements. Passing this stage is an unblock, not the full operational beta.

## Remaining public inputs and decisions

Resolve these into one concrete deployment review, without asking for raw
credentials in chat:

- Exact subscription/tenant and new resource/state identities, accepted VM and
  registry posture, cost/budget scope, availability tradeoff and recovery targets.
- DNS control/delegation for the approved web host and the proposed API host,
  administrative access source/method, and certificate renewal owner.
- The actual production Clerk public key/frontend, issuer/JWKS, organization,
  audience, authorized web/native origins and callbacks matching the candidate.
- Verified Cosmaneura staging API origin and API contract, expected audience,
  runtime identity grant/tenant mapping and the permitted synthetic test scope.
  `staging.cosmaneura.com` alone is not proof of its separate API address or grant.
- Protected Key Vault secret names/versions and custody/provisioning mechanism,
  scoped image-pull/backup credentials, storage names and approved operator
  identity. These are access/configuration dependencies, not values to invent.

Estimate **16–32 focused engineering hours (2–4 days)** for a secured deployment
profile, appropriate local validation, first apply and bounded synthetic recovery
acceptance, assuming configuration/access and allocation work. This is conditional
on no substantial new runtime defect and on the still-unimplemented identity,
TLS, backup and release mechanics. DNS/Clerk/Core access or allocation waits can
extend elapsed time. Device signing/distribution, Scribe, real connector and full
beta acceptance are excluded; no whole-beta completion percentage is claimed.

## Evidence

Local task evidence in `vm-staging-proposal-r1/EVIDENCE.json` contains the source
hashes, exact retail rows, Decimal calculation, reused price-page hashes and
current SKU/quota receipts. Its `calculate.py` recomputes figures from retained
public pages without new cloud calls. VM/disk prices were refreshed for this
proposal; unchanged Key Vault/network/ACR/Blob/log prices reuse the evidence for
the [September 25 managed-staging cost review](STAGING_COST_REVIEW_20260925.md).
These local receipts are not deployment or GitHub Actions evidence.

Read-only Azure commands were `az vm list-skus --location eastus2
--resource-type virtualMachines --size Standard_D2s_v5 --all` and `az vm
list-usage --location eastus2`, filtered to SKU capabilities, restrictions and
relevant quota rows. Both exited 0. Their results are
`d2s-v5-sku.json` and `family-quotas.json`. No allocation test was performed.
