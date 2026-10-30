# D3 Cosmas Beta Lab capability manifest

Manifest status: **LOCAL SOURCE GATES COMPLETE / RELEASE SHA AND CI BINDING REQUIRED / LIVE EVIDENCE INCOMPLETE**
Environment status: **NOT DEPLOYED**
Deployment mode: **`synthetic_lab`**
Data classification: **`synthetic-only`**
PHI authorization: **NOT AUTHORIZED**
Non-auth external connectors: **ALL DARK**

This is the concrete source-controlled capability decision for the first D3
Cosmas Beta Lab. It records what the lab may do and what remains blocked. It is
not a Terraform approval, a live-evidence record, or permission to invite a
tester. Deployment-derived values stay `PENDING` until a human records them;
none may be replaced with an invented identifier or evidence reference.

The final workload approval must identify this file at the reviewed full Git
commit and record its SHA-256 outside the repository. Editing the file after
that review invalidates the prior manifest reference.

## 1. Accepted scope

| Decision | Recorded state | Authority / evidence |
|---|---|---|
| D3 isolated environment | **APPROVED** | `DL-20260903-03`; never promote D2 in place |
| First cohort | **Cosmas Beta Lab; owner and later invited outside testers** | `DL-20260903-04` |
| Data | **Invented data only** | `synthetic_lab`; PHI, real clinic data, and production exports prohibited |
| Identity topology | **Shared Cosmaneura Clerk application; separate CosmaBot permissions, organization binding, and one Box** | `DL-20260927-01`, which supersedes the separate Clerk application requirement in `DL-20260903-04` and `DL-20260903-05`. Platform membership does not grant CosmaBot access |
| Development Clerk state | **HISTORICAL DEVELOPMENT STRUCTURE / NOT PRODUCTION AUTHORITY** | A separate development app and zero-member Beta Lab Org were configured earlier. Production sign-in reuses the Cosmaneura identity instance |
| Production Clerk state | **SHARED IDENTITY ACCEPTED / ROLLOUT NOT AUTHORIZED** | `DL-20260927-01`. Reuse the existing Cosmaneura identity. Keep CosmaBot grants, Box, principals, and organization binding independent. Qualify the account transition before changing live sign-in. See `docs/validation/shared-identity-flight-plan.md` |
| MyCatholicDoctor users | **NO TRANSFER / NO SHARED SESSION** | Direct re-invitation may be reviewed later; bulk migration remains separately gated |
| Mobile | **SCHEDULED AFTER BROWSER D3, BEFORE D4; NOT AUTHORIZED TO BUILD/UPLOAD HERE** | `DL-20260903-06` |
| Track A | **OUT OF SCOPE / UNTOUCHED** | No shared state, identity, database, storage, credential, or direct call |

## 2. Environment binding

| Field | Current value |
|---|---|
| Organization display name | `Cosmas Beta Lab` |
| Dedicated logical `box_id` | **PENDING — generate a UUID and obtain owner review before bootstrap apply** |
| Production Clerk Organization ID | **PENDING — create after the exact web origin exists** |
| Production Clerk issuer/JWKS | **PENDING — exact production values only** |
| Accepted Clerk audience | `cosmas-os-beta-api` |
| Azure subscription display name | `Microsoft Azure Sponsorship` (identifiers omitted from this repository record) |
| Bootstrap/state resource group | **PENDING — exact source-derived name in reviewed bootstrap plan** |
| Workload resource group | **PENDING — exact source-derived name in reviewed bootstrap/environment plans** |
| Region | `centralus` **PROVISIONAL; human approval and refreshed quota/price evidence pending** |
| Registry posture | `private` **RECOMMENDED TARGET; exact selection plus Premium/Private Link cost and routing approval pending** |
| Deployable source revision | **REQUIRED PER RELEASE — exact committed SHA with green GitHub CI and external protected-record binding** |
| API/worker image digest | **PENDING PROTECTED-RUNNER BUILD, SCAN, PUSH, AND READBACK** |
| Web image digest | **PENDING EXACT-ORIGIN/PRODUCTION-CLERK BUILD, SCAN, PUSH, AND READBACK** |
| Dedicated production web hostname | **PENDING EXACT OWNER DECISION — `beta.cosmaneura.com` RECOMMENDED** |
| API and web origins | **PENDING FOUNDATION OUTPUTS; production web origin must use the accepted dedicated hostname** |
| Named human deployer | **PENDING HUMAN RECORD** |
| Capability manifest binding | **REQUIRED PER DEPLOYABLE RELEASE — exact committed SHA plus external SHA-256 evidence record** |

## 3. Permitted product surface

The live D3 lab may expose only this surface after all workload and acceptance
evidence passes:

- invited, verified human sign-in through the one production Cosmas Beta Lab
  Clerk Organization;
- the fixed repository-owned invented ArtifactChase queue;
- review, edit, and human approve/deny actions on that invented queue;
- owner-only identity roster, bind, deactivate, reactivate, and ownership
  transfer, with opaque evidence references and separate Clerk membership or
  session revocation where required;
- F-8 as the only work queue and approval substrate; and
- audit/replay, retention/purge, restore, rollback, readiness, and monitoring
  exercises using invented data only.

The following entry paths remain **BLOCKED** in `synthetic_lab`: schedule or
CSV import, PatientLink creation, new chase creation, artifact upload, clinic
data entry, production exports, and any PHI. A UI element or backend route must
not be treated as permission to widen this list.

## 4. Capability state

| Capability | D3 synthetic-lab state | Activation boundary / fail-closed result |
|---|---|---|
| Clerk AuthPort | **SOURCE IMPLEMENTED; SHARED IDENTITY ACCEPTED; PRODUCTION ROLLOUT OFF** | `DL-20260927-01`. Production exact-origin, organization, Box, and separate CosmaBot grant evidence required; otherwise reject and make zero API calls |
| Fixed synthetic F-8 queue | **SOURCE IMPLEMENTED; LIVE OFF** | May turn on only with the digest-pinned workloads and completed acceptance evidence |
| Human decision actions | **SOURCE IMPLEMENTED; LIVE OFF** | Immutable revision/payload binding and authenticated human authority required |
| Identity administration | **SOURCE IMPLEMENTED; LIVE OFF** | Box owner only; no deployer impersonation or agent approval |
| Synthetic seed CLI | **SOURCE IMPLEMENTED; HUMAN-ONLY LIVE STEP** | Fixed invented dataset only; refuses `authorized_beta` |
| Azure Blob adapter | **SOURCE IMPLEMENTED; CLOUD VALIDATION PENDING** | Managed identity and exact Box prefix required; delete fails unless exact-name enumeration finds no current, version, snapshot, or deleted representation recoverable through Azure APIs |
| Schedule/Athena/Acuity | **DARK** | Separate D5 gate; no external read or write |
| EHR/record system | **DARK** | Separate D5 gate; no external read or write |
| Email/SMS/A2P/Teams | **DARK** | Separate D5 gate; no send or delivery |
| External model/LLM | **DARK** | Separate data/service review and activation gate |
| Track A Scribe | **DARK** | D6 gate and versioned contract; no shared database, identity, or state |
| Payment/PAN | **FORBIDDEN** | Reject payment-card handling |
| `AUTO_TEMPLATE` / `AUTO_DRAFT` send | **DARK** | Human approval remains mandatory; no automatic send |

`enabled_connectors` must remain the empty set in every D3 plan. Clerk is the
approved authentication boundary, not a general D5 connector activation.

## 5. Source evidence and open verification

Current component evidence is recorded in `BUILD_REPORT.md`. The complete
`./scripts/d3-self-test.sh` gate passed on 2026-09-03 with **209 Python** and
**32 web** tests, bootstrap OpenTofu **6/6**, environment OpenTofu **32/32**,
and clean deployment-guard, Bash-syntax, and ShellCheck results. Focused
PITR/recovery/offboarding tests passed **31/31**, and the protected-runner
payload measured **61,132 / 65,536 bytes**. Final local Linux/amd64 API and web
builds succeeded; current-database Trivy scans found **0 fixable HIGH/CRITICAL
findings**; and the final source audit found no code blocker.

Local source gates are complete, but that result alone does **not** make a
deployable release or complete D3. Every deployable release must use a committed
SHA with green GitHub CI and bind that exact SHA in its external protected
release record. Live Azure, exact-plan/apply, production Clerk, and tester
acceptance evidence do not exist.

## 6. Required live controls

- [ ] Bootstrap and workload boundaries use two new D3 resource groups and no
      D2/Track A dependency.
- [ ] Protected runner has no public IP or inbound path; exact UAMI, private
      state path, source SHA, toolchain, and network boundary are verified.
- [ ] Public access is disabled for PostgreSQL, Redis, Blob, Key Vault, and the
      selected private ACR posture; private DNS and endpoint reachability are
      demonstrated from the exact protected runner.
- [ ] Runtime identity has only ACR pull, secret read, and Box-container Blob
      rights; web identity has ACR pull only; database-job identity has ACR
      pull only.
- [ ] The exact owner decision binds the dedicated production hostname and
      authentication policy before the foundation; the recommended package is
      `beta.cosmaneura.com`, verified email + TOTP + recovery codes, SMS
      disabled, and no wildcard/shared `azurecontainerapps.io` origin.
- [ ] Production Clerk issuer, JWKS, audience, authorized party, Organization,
      Box, and human-principal mapping pass positive and negative live tests.
- [ ] The unscheduled database job emits a successful structured
      `database_preparation_attestation` binding image digest, schema revision,
      evidence hash, execution ID, Box ID, and exact database-server ID.
- [ ] `runner_live_network_evidence_reference` independently binds live DNS
      and endpoint probes to the exact runner/environment/release.
- [ ] API/worker and web run only their scanned immutable digests; rollback
      digests remain available.
- [ ] Audit replay and exact-key recoverable-absence purge, isolated restore,
      rollback and forward recovery, post-apply drift, alert delivery, and
      offboarding pass. Purge evidence is an Azure API recoverability claim,
      not physical-media erasure.
- [ ] No tester is invited until the accountable human accepts all results.

The isolated D3 artifact account deliberately disables Blob versioning and
Blob/container soft delete. That makes the synthetic purge invariant testable
but gives up accidental-deletion recovery. PHI remains prohibited. An
`authorized_beta` release requires a separate durability, recovery, legal-
retention, and purge design; it must not inherit this setting implicitly.

## 7. Cost and operating decision

| Item | Current record |
|---|---|
| Low-traffic infrastructure envelope | **Approximately $170–260/month** across bootstrap/state and workload resource groups; planning range only, no credits |
| Exclusions | Founder support, Clerk paid-plan charges, taxes, and unusual egress/log volume |
| Proposed aggregate alert | **$350/month across both D3 resource groups — OWNER APPROVAL PENDING** |
| Alert semantics | Notification only; **not a spending cap or automatic shutdown** |
| Alert recipient | **PENDING HUMAN-OWNED ADDRESS; do not record the address in this public manifest** |
| Support owner/escalation | **PENDING** |

The exact plan must refresh Azure calculator/contract pricing and prove the
alert covers both D3 groups. A workload-resource-group budget by itself does
not satisfy the combined requirement.

## 8. Plan-bound approval record

| Approval/evidence | Current state |
|---|---|
| Release SHA, green CI, and external manifest binding | **REQUIRED PER DEPLOYABLE RELEASE** |
| Bootstrap saved-plan hash and named-human approval | **PENDING** |
| Foundation saved-plan hash and named-human approval | **PENDING** |
| Production Clerk/Org/Box and web-release evidence | **PENDING** |
| Database-stage saved-plan approval and live attestation | **PENDING** |
| Workload saved-plan hash, lineage/serial, and named-human approval | **PENDING** |
| Live acceptance and tester-admission decision | **PENDING** |

Final disposition: **BLOCKED — D3 IS NOT COMPLETE OR DEPLOYED; PHI IS NOT
AUTHORIZED; ALL NON-AUTH EXTERNAL CONNECTORS REMAIN DARK.**
