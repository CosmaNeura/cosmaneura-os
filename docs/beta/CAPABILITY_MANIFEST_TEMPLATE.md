# D3 capability and prerequisite manifest template

Manifest status: **BLOCKED / REQUIRED — SELECT ONE DEPLOYMENT MODE**
Environment status: **NOT DEPLOYED**
PHI authorization: **NOT AUTHORIZED**
Live connectors: **ALL DARK**

Copy this template to an approval-specific, non-secret record only after the
owner supplies the required inputs. Do not insert credentials, patient data,
production identifiers, connection strings, tokens, or secret values.

The current D3 source-review record is
[SYNTHETIC_LAB_CAPABILITY_MANIFEST.md](SYNTHETIC_LAB_CAPABILITY_MANIFEST.md).
It deliberately leaves deployment-derived values and human approval evidence
pending rather than inventing them.

Choose exactly one mode. Do not combine their prerequisites or use evidence
placeholders:

| `deployment_mode` | Permitted data | Required legal evidence |
|---|---|---|
| `synthetic_lab` | Invented data only; real clinic/patient data prohibited | No named clinic, BAA, or PHI authorization required |
| `authorized_beta` | PHI only after the recorded release gate | Named clinic + clinic approval + applicable BAA + separate PHI authorization, all human-reviewed |

The Clerk Organization, dedicated Box, human deployment evidence, isolation,
private data paths, and dark external connectors are required in both modes.

## 1. Environment identity

| Field | Required entry |
|---|---|
| Deployment mode | **REQUIRED — `synthetic_lab` or `authorized_beta`; current approved path is `synthetic_lab`** |
| Data classification | `synthetic-only` for `synthetic_lab`; `phi-authorized` only after all `authorized_beta` evidence passes |
| Organization identity | **REQUIRED — Cosmas Beta Lab for `synthetic_lab`; named legal clinic for `authorized_beta`** |
| Legal clinic / covered entity | **NOT APPLICABLE for `synthetic_lab`; BLOCKED / REQUIRED for `authorized_beta`** |
| Approved clinic slug | **NOT APPLICABLE for `synthetic_lab`; BLOCKED / REQUIRED for `authorized_beta`** |
| Dedicated logical `box_id` | **BLOCKED / REQUIRED IN BOTH MODES** |
| Exact Clerk Organization ID | **BLOCKED / REQUIRED IN BOTH MODES — one Org maps to this one Box** |
| Azure subscription display name | **REQUIRED** |
| D3 state and workload resource groups | **BLOCKED / REQUIRED — two new OS beta RGs; neither may be `cosmaneura-os-synth`** |
| Environment tag | `early_adopter_beta` |
| Provisional region | `centralus` based only on 2026-09-03 capacity evidence |
| Final region / residency approval | **BLOCKED / REQUIRED** |
| Source commit | **REQUIRED — full commit SHA** |
| Immutable API/worker and web images | **REQUIRED — distinct ACR paths pinned by `sha256` digests** |
| Exact beta web/API origins | **REQUIRED — foundation outputs, production Clerk configuration, browser build, and workload plan must agree** |

## 2. Human and legal prerequisites

| Prerequisite | `synthetic_lab` | `authorized_beta` | Non-secret evidence reference |
|---|---|---|---|
| Owner-approved named clinic | **NOT REQUIRED — MUST REMAIN NON-CLINICAL** | **BLOCKED / REQUIRED** | |
| Clinic authority to enter beta | **NOT REQUIRED** | **BLOCKED / REQUIRED** | |
| Applicable BAA executed and scope reviewed | **NOT REQUIRED — PHI PROHIBITED** | **BLOCKED / REQUIRED** | |
| Separate PHI release authorization | **NOT AUTHORIZED / NOT REQUIRED** | **BLOCKED / REQUIRED** | |
| Azure service eligibility under applicable agreement reviewed | **BLOCKED / REQUIRED** | **BLOCKED / REQUIRED** | |
| Clerk plan/application eligibility reviewed | **BLOCKED / REQUIRED** | **BLOCKED / REQUIRED, including any BAA eligibility** | |
| Exact Clerk Organization created by a human | **BLOCKED / REQUIRED** | **BLOCKED / REQUIRED** | |
| Human owner/approver role mapping accepted | **BLOCKED / REQUIRED** | **BLOCKED / REQUIRED** | |
| Named human deployer and dedicated deploy identity | **BLOCKED / REQUIRED** | **BLOCKED / REQUIRED** | |
| No coding-agent access to live credentials or PHI demonstrated | **BLOCKED / REQUIRED** | **BLOCKED / REQUIRED** | |
| RTO/RPO, retention, purge, and support ownership accepted | **BLOCKED / REQUIRED** | **BLOCKED / REQUIRED** | |
| Non-credit budget approved | **BLOCKED / REQUIRED** | **BLOCKED / REQUIRED** | |

Evidence references must identify an approved system of record, date, owner,
and immutable record ID without copying confidential agreement text here.

## 3. Isolation requirements

All entries are **REQUIRED in both modes** unless an item explicitly says it is
an additional `authorized_beta` requirement.

- [ ] New D3 state and workload resource groups; no in-place promotion of D2.
- [ ] Dedicated Box and database/storage/workload boundary for the selected
      Organization; one Organization maps to exactly one Box.
- [ ] Dedicated beta deployment identity with least-privilege scope.
- [ ] No Track A service principal, database, Key Vault, registry, Terraform
      state, or production credential reuse.
- [ ] PostgreSQL has no public access; approved private connectivity and DNS
      are tested from workloads and the human-operated migration/restore path.
- [ ] Blob, Key Vault, Redis (if retained), registry, logs, backups, and support
      tools follow the approved network and `box_id` boundary.
- [ ] Storage disallows public blob containers and uses approved redundancy,
      retention, lifecycle, and purge controls.
- [ ] Key Vault uses RBAC, purge protection, approved retention, and private
      access where required.
- [ ] Logs exclude PHI, credentials, raw payloads, and patient identifiers;
      alerts and access retention are approved.
- [ ] Ingress, egress, private DNS, operator access, and break-glass behavior
      are documented and tested fail closed.

## 4. Capability states

No row may become `ON` from this template. Activation requires its own reviewed
manifest evidence and, where applicable, the exact D5 gate.

| Capability / port | Current state | Prerequisites to change state | Fail-closed behavior |
|---|---|---|---|
| AuthPort — Clerk | **BACKEND + WEB RELEASE SOURCE IMPLEMENTED / LIVE LOGIN BLOCKED** | Production Cosmas OS Clerk app + exact Org/origin, role mapping, reviewed web digest, and real session validation; BAA review additionally required for `authorized_beta` | Reject unauthenticated callers; never trust caller identity headers; frontend makes zero API calls without complete configuration/session/Org/token |
| SchedulePort L0 manual/CSV | **LOCAL/FAKE ONLY** | Synthetic validation; D4 approval for clinic use | No external schedule access |
| SchedulePort — Athena/Acuity | **DARK** | Separate D5 rung, vendor access/BAA, least scopes, reconciliation tests | No external read/write |
| RecordPort / EHR | **DARK** | Separate D5 rung, BAA, scopes, human approver, UNKNOWN reconciliation | No EHR read or write |
| NotifyPort — email | **DARK** | Separate D5 rung, approved channel, consent/opt-out, neutral body + secure link | In-app/fake only |
| NotifyPort — SMS/A2P | **DARK** | Separate D5 rung, A2P registration, consent/opt-out, delivery reconciliation | No SMS send |
| Track A Scribe integration | **DARK** | D6 approval plus Track A IAM and versioned contract | No shared DB/SP/state or direct call |
| Azure Blob adapter | **IMPLEMENTED / CLOUD VALIDATION BLOCKED** | Managed-identity and Box-key tests pass offline; private access, recovery, and retention/purge evidence remain required | No live uploads; local synthetic adapter remains the test path |
| External model / LLM | **DARK** | Separate approval, agreement, data-boundary and no-training evidence | Deterministic/local behavior only |
| Teams | **DARK** | Separate reviewed connector rung | No delivery |
| Payment / PAN | **FORBIDDEN** | New product decision would be required | Reject PAN/payment handling |
| `AUTO_TEMPLATE` send | **DARK / REJECTED** | New accepted decision required | Human approval remains mandatory |
| `AUTO_DRAFT` send | **DARK** | Human-reviewed activation | Staff surface only; never auto-send |

## 5. Authority and safety acceptance

- [ ] The selected Clerk Organization maps to exactly one logical Box; a clinic
      deployment also binds that Organization to the approved legal entity.
- [ ] Human and agent principals remain distinct.
- [ ] Agents cannot self-approve, impersonate, sign, or submit as a human.
- [ ] F-8 is the only queue and approval surface.
- [ ] Approval is bound to an immutable action revision and exact payload hash.
- [ ] Postgres is authoritative; Redis/Celery is transport only.
- [ ] Retry and ambiguous external outcomes use `UNKNOWN` reconciliation, not
      blind replay.
- [ ] Disabled connectors fail closed and the L0 workflow remains usable.
- [ ] Audit replay and retention purge pass with non-production or explicitly
      authorized beta data.
- [ ] Backup/restore and digest rollback are demonstrated.

## 6. Cost and operations acceptance

Record a non-credit scenario and the assumptions behind it.

| Variable | Required choice / evidence |
|---|---|
| Web/API/worker resources and replica floors | **REQUIRED** |
| PostgreSQL SKU/storage/HA/backup | **REQUIRED** |
| Redis tier or alternative | **REQUIRED** |
| Registry tier/network posture | **REQUIRED** |
| Private networking and controlled egress | **REQUIRED** |
| Blob redundancy/capacity/transactions | **REQUIRED** |
| Monitoring ingestion/retention | **REQUIRED** |
| Clerk plan | **BLOCKED / REQUIRED** |
| Human support staffing and escalation | **BLOCKED / REQUIRED** |
| Current low-traffic planning envelope | **Approximately $170–260/month across both D3 resource groups; refresh against the exact plan and do not present as a quote** |
| Aggregate Cost Management alert | **Proposed $350/month across both D3 resource groups; owner decision and human-owned recipient REQUIRED** |
| Spending cap | **NONE — an Azure budget alert notifies; it does not stop resources or cap charges** |
| Estimated monthly total without credits | **REQUIRED — include bootstrap/state and workload groups** |

Kill the deployment if economics require credits, setup/approval burden is not
lower than saved staff time, or ordinary retries require manual intervention.
Do not describe a workload-resource-group alert as aggregate unless separate
evidence proves the bootstrap/state resource group is covered too.

## 7. Approval record

| Role | Human name | Decision | UTC timestamp | Evidence ID |
|---|---|---|---|---|
| Clinic authority | **NOT APPLICABLE for `synthetic_lab`; REQUIRED for `authorized_beta`** | | | |
| Security/legal reviewer | **NOT REQUIRED for clinic/BAA release in `synthetic_lab`; REQUIRED for `authorized_beta`** | | | |
| Product owner | **BLOCKED / REQUIRED** | | | |
| Human deployer | **BLOCKED / REQUIRED** | | | |

Final manifest disposition: **BLOCKED — D3 NOT COMPLETE OR DEPLOYED; current
approved mode is `synthetic_lab`; PHI NOT AUTHORIZED**.
