# East US 2 staging cost review — September 25, 2026

For the selected one-replica API profile, the public retail scenarios below are
**about $278–329/month with private Premium ACR**, or **$224–275/month with the
separately reviewed synthetic-only public Basic ACR exception**, before additional
usage charges. These totals include the retained Central US runner/state network.
The corresponding new workload cost is approximately **$195–246** or **$141–192**.
The earlier $170–260 combined estimate is not a reliable current envelope.

This is a source-based planning estimate, not an Azure invoice, offer quote,
deployment approval or upper spending bound. No branch is selected by this review.
Private ACR remains required unless the existing explicit synthetic-public
exception is approved. Public prices do not prove subscription/SKU eligibility.

## Basis and recurring resources

Resource source: `f0561ba4f4855344542330320d82c91195f5069c`. Workloads are in
`eastus2`; the existing bootstrap/state/runner remain in `centralus`. Use 730 hours
and 730/24 days per month, USD on-demand prices, and no assumed credits, reservations,
free grants, tax or account discount. The runner is assumed allocated all month.

| Component | Public unit rate and quantity | Monthly estimate |
| --- | --- | ---: |
| Existing Linux B2s runner | $0.0499/hour × 730 | $36.43 |
| Existing 32 GiB Standard SSD LRS OS disk | E4 disk, excluding operations | $2.40 |
| Existing Standard NAT Gateway | $0.045/hour × 730 | $32.85 |
| Existing NAT static Standard public IP | $0.005/hour × 730 | $3.65 |
| Existing state private endpoint and DNS zone | $0.01/hour + $0.50/zone-month | $7.80 |
| **Existing fixed subtotal** | Excludes state storage/transactions and transfer | **$83.13** |
| New PostgreSQL 16 B1ms and 32 GiB storage | $0.017/hour + 32 × $0.115/month | $16.09 |
| New Managed Redis Balanced B0, HA enabled | Official **two-node HA** price $0.032/hour | $23.36 |
| New private endpoints | Premium branch: 4; Basic branch: 3; $0.01/hour each | $29.20 / $21.90 |
| New private DNS zones | Premium branch: 4; Basic branch: 3; $0.50/month each | $2.00 / $1.50 |
| Registry | Premium $1.6666/day; Basic $0.1666/day | $50.69 / $5.07 |
| Two metric alert time series | $0.10 each/month, before any free allowance | $0.20 |
| Azure-managed Container Apps network | One Standard load balancer plus 1–2 Standard public IPs | $21.90–25.55 |

Counts include the retained state endpoint/zone only in the existing subtotal.
Total endpoint/zone counts are five/five with Premium or four/four with Basic.
PostgreSQL uses a delegated subnet, so it is not an extra private endpoint.
DNS VNet links are not extra DNS zones. Registry geo-replication and shared disk
mounts are not configured. Blob storage and operations remain usage-based.

Container Apps creates additional resources in its own managed resource group.
Microsoft documents one load balancer and one egress public IP for an external
consumption-only environment; a workload-profile external environment also has
an ingress public IP. The source declares no dedicated workload profile. The
range retains both documented network cases until the actual provider-created
resources are confirmed. It uses $0.025/hour for the first five Standard load
balancer rules and $0.005/hour per Standard public IP. Extra rules, extra IPs and
processed bytes are additional. Do not count these resources as absent merely
because they are not declared separately in Terraform.

No Dedicated-plan, Container Apps environment private-endpoint, or planned-
maintenance fee is included: those features are not requested in this source.
The service's newer $0.10/hour feature-management meters are not the ordinary
$0.01/hour private endpoints for Key Vault, Redis, Blob and ACR. Re-price if the
approved plan enables those additional environment features.

## Application scenarios

The API and worker each allocate 0.5 vCPU/1 GiB with minimum one replica. The web
allocates 0.25 vCPU/0.5 GiB and may scale to zero. Active CPU is $0.000024/vCPU-second,
idle CPU $0.000003/vCPU-second, and memory $0.000003/GiB-second at either rate.
Idle billing is conditional on Microsoft's actual idle criteria; it is not
assumed for the worker or guaranteed for the API.

| Full-month scenario | Containers only | Combined with existing infrastructure: Premium | Combined: reviewed Basic exception |
| --- | ---: | ---: | ---: |
| API qualifies as idle; worker active; web zero | $51.25 | $277.82–281.47 | $224.39–228.04 |
| API and worker active; web zero | $78.84 | $305.41–309.06 | $251.98–255.63 |
| API, worker and web all active | $98.55 | $325.12–328.77 | $271.69–275.34 |

These are scenarios, not a promised minimum or maximum. Old/new revision overlap,
manual jobs and retries add usage. One 900-second 0.25-vCPU/0.5-GiB job is about
$0.00675 before grants. Requesting three quota cores instead of four does not
reserve or directly bill three cores; the exact API cap limits possible scale.

## Usage and budget limits

- Log Analytics ingestion above available allowance is $2.76/GB. A modeled
  1 GB/day for 730/24 days adds **$83.95 gross**; the daily ingestion setting is
  not a financial hard cap. This alone can put the Premium scenarios above $350.
  Source retention is 30 days; longer retention requires a separate calculation.
- NAT processing is $0.045/GB; private-endpoint ingress/egress processing starts
  at $0.01/GB. Global VNet peering between Central US and East US 2 lists
  $0.035/GB at each endpoint, or $0.07 per GB traversing that peering, before
  overlapping applicable service meters. Internet egress is additional.
- Example Hot LRS Blob storage is $0.0184/GB-month, writes $0.05/10,000 and reads
  $0.004/10,000. The source does not explicitly pin account kind/access tier;
  verify the resolved defaults before applying these rates. State versions and
  30-day soft-deleted state data also consume storage. PostgreSQL backup overage,
  IOPS/storage changes, ACR storage overage and temporary PITR servers are extra.
- Key Vault standard operations are $0.03/10,000; DNS private queries $0.40/million;
  runner disk operations $0.002/10,000. Notification volume also affects charges.
- The existing **$350 notification budget is filtered to only the named state
  and workload resource groups**. It does not automatically include the
  Container Apps managed resource group and is not a spending cap. Include that
  group in the reviewed cost-control scope once its exact identity is available.
- Clerk, Core/Scribe/platform hosting, models, connected services, Apple release
  accounts, the domain registrar, and other subscription resources are outside
  this CosmaBot infrastructure calculation. Do not present this as the whole
  business or subscription bill.

## Evidence and outstanding decisions

The public retail API and official billing pages were read September 25 without
authentication or resource changes. Exact query URLs, raw response hashes,
selected meter IDs, Decimal calculations and the source inventory are retained
in local task evidence `staging-cost-refresh-r1/`. The Redis page explicitly
provides the two-node HA rate; multiplying an unidentified cache-instance meter
was not used as proof of HA pricing.

Official references:

- [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
- [Container Apps billing](https://learn.microsoft.com/en-us/azure/container-apps/billing)
- [Container Apps custom VNet managed resources](https://learn.microsoft.com/en-us/azure/container-apps/custom-virtual-networks#managed-resources)
- [Container Apps pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/)
- [Managed Redis pricing](https://azure.microsoft.com/en-us/pricing/details/managed-redis/)
- [Azure DNS pricing](https://azure.microsoft.com/en-us/pricing/details/dns/)

The subscription still needs sufficient East US 2 SandboxCores, resolution of
PostgreSQL OfferRestricted, and confirmation that Balanced_B0 supports the exact
HA/private-network/AOF configuration there. Retail pricing is not proof of any
of these. Final approval must bind the current resolved plan, ACR posture,
resource-group cost scope, identity and domain settings. No deployment or billing
change was performed by this review.
