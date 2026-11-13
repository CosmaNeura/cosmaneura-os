# CosmaBot production post-apply runbook (prep only)

**Tonight for existing live users: nothing. Docs only, nothing applied.**

Status: **PREP ONLY.** This runbook is written before `#356` is applied. It
does not authorize OpenTofu apply, Azure writes, DNS changes, Clerk console
work, secret pastes, or a deploy. Coding agents must not run those steps from
this document.

**Audience:** John (owner gates) and the release lead after John applies the
production foundation in `#356` (`grok/cosmabot-prod-hosting`, unapplied).

**Target:** new resource group `rg-cosmabot-prod-eus2-01`, hostnames
`beta.cosmas.ai` / `api.beta.cosmas.ai`, synthetic data only. Staging
(`rg-cosmas-os-vm-staging-eus2-lab01`, `staging.cosmas.ai`) stays untouched.

**Sources (evidence, not executable instructions):**

- CosmaBot production hosting plan, Wed 11 Nov 2026 (owner plan; cost and
  Sat 14–Sun 15 ET order)
- `#356` guard-hardening / Key Vault–secrets and app-cutover notes (deferred
  ticket text)
- PR `#356` (`grok/cosmabot-prod-hosting`): production foundation IaC and
  `infra/beta/vm/prod/README.md` on that branch (unapplied)
- Staging host/runtime docs on `main`: `infra/beta/vm/host/README.md`,
  `infra/beta/vm/runtime/README.md`, `infra/standalone/README.md`
- Staging release pointer pattern (plan §§11–12 style): CosmaBot staging
  `release-r7` step list (precheck → stage/trial → pointer switch →
  `/version.json` + `/ready` → rollback script)

---

## 0. Hard stops

| Forbidden in this prep ticket | Why |
| --- | --- |
| Merge `#356` or this PR | Owner only |
| `tofu` / `terraform` plan or apply | Separate apply ticket / John's Mac |
| `az` write commands, Key Vault writes, DNS edits, Clerk changes | Owner / later release tickets |
| Secret values in chat, git, run-command, or this doc | Names only |
| Touch staging or run5 | Plan invariant |
| Model change | Same model: `gpt-4.1` / deployment `gpt-4.1-dzus` |
| Real patient data | Synthetic until a separate compliance yes |

---

## 1. What `#356` leaves behind (after John's apply)

After a successful first apply of `#356` with reviewed inputs that set
`enable_azure_openai: true` (see `inputs.optin.example.json` on that branch):

| Item | Expected name / note |
| --- | --- |
| Resource group | `rg-cosmabot-prod-eus2-01` (East US 2) |
| VM | `vm-cosmabot-prod-eus2-01` (`Standard_D2s_v5`) |
| Key Vault | `kv-cbot-prd-*` (public network access Disabled until the secrets path) |
| ACR / storage / PE / DNS zones / Log Analytics | As planned; private |
| Azure OpenAI account | Classic Cognitive Services `kind = "OpenAI"` (see §7) |
| Deployment | `gpt-4.1-dzus` (DataZoneStandard capacity **1**) |
| Runtime LLM | **Off.** Profile `WORKSPACE_LLM_BACKEND=disabled`; `routes_runtime_traffic=false` |
| Secrets on the VM | **None** until a separate secrets / release ticket |
| DNS | **Unchanged.** Hostnames in the profile are placeholders only |

Postgres 16 and Redis are **on the VM**, same as staging — not Azure Database
for PostgreSQL and not Azure Cache for Redis. Host install of those services
is post-apply work (§3), not part of the foundation module itself.

---

## 2. John's ordered steps (ET), Sat 14 – Sun 15 Nov 2026

Rough durations are planning envelopes from the 11 Nov hosting plan. Slip if
John is filming. Every **yes** gate is typed by John; agents do not apply.

### Day A — Saturday 14 Nov (after foundation apply is green)

| Slot (ET) | Step | Who | ~Duration | Gate |
| --- | --- | --- | --- | --- |
| 09:00–09:15 | Confirm `#356` apply finished: RG exists, VM running, public IP recorded, OpenAI account present if opt-in was in the plan | John + release lead (read-only) | 15 min | John: **"yes, apply looks complete"** |
| 09:15–10:00 | Create / finish **production Clerk** app (not Cosmas, not staging): custom domain `clerk.beta.cosmas.ai`; sign-in origins `https://beta.cosmas.ai` and `capacitor://localhost`; JWT audience per 30 Oct list; one synthetic org + fake reviewer user | John | 45 min | — |
| 10:00–10:15 | Send **public** Clerk values only (issuer, JWKS URL, audience, authorized parties, organization ID, publishable key) | John | 15 min | — |
| 10:15–11:00 | Key Vault secret pastes (**names only** below) via the later secrets ticket path: temporary public-access window from John's own `/32`, `az keyvault secret set --file`, then restore `publicNetworkAccess=Disabled` and empty `ipRules` | John | 45 min | John: **"yes, KV secrets loaded and public access disabled"** |
| 11:00–11:20 | On the new VM as root: create distinct DB / Postgres / Redis passwords himself in a **mode-600** file he owns. **Never** via Azure Run Command. Agents never generate, read, or transmit these values | John | 20 min | John: **"yes, mode-600 password file is on the host"** |
| 11:20–12:00 | Host prep start: reviewed `bootstrap_host.py` path mirrored from staging host README, retargeted to prod VM/disk IDs (data disk format/mount, Docker packages masked until reviewed) | Release lead after John's yes | 40 min | John: **"yes, format the new empty data disk"** (same shape as staging `--format-new-empty-disk`) |

Suggested Saturday window: **09:00–12:00 ET**. If apply slips to Saturday afternoon, slide the same block to **14:00–17:00 ET**.

### Day B — Sunday 15 Nov

| Slot (ET) | Step | Who | ~Duration | Gate |
| --- | --- | --- | --- | --- |
| 10:00–10:30 | Install secret **names** onto host files as mode-0400 under `/etc/cosmabot/runtime/<release_id>/…` per `infra/beta/vm/runtime/README.md` (transport is the secrets ticket; Run Command still must not carry secret values) | John / release lead | 30 min | John: **"yes, host secret files installed"** |
| 10:30–12:00 | Continue machine prep (unmask Docker only after review, DOCKER-USER / IMDS guard, empty `postgres`/`redis` dirs UID 999) | Release lead | 90 min | John: **"yes, continue host prep"** |
| Optional afternoon | Dry-run DNS record drafts (do not publish until public IP is final and Mon/Tue deploy window) | John | 15 min | — |

Suggested Sunday window: **10:00–12:00 ET**.

### Mon 16 – Tue 17 Nov (follow-on; still synthetic)

| Order | Step | Gate |
| --- | --- | --- |
| 1 | Install Postgres 16 + Redis on the VM (compose/runtime path mirroring staging) | John: **"yes, start data services"** |
| 2 | Render + deploy app in **synthetic** mode for `https://beta.cosmas.ai` / `https://api.beta.cosmas.ai` | John: **"yes, deploy synthetic beta"** |
| 3 | Confirm Azure OpenAI resource + `gpt-4.1-dzus` exist (created in first apply if opt-in; otherwise a separate reviewed day-2 tool — not this doc) | John: **"yes, OpenAI resources match the plan"** (no model change) |
| 4 | Cloudflare DNS (§5), proxy **off** | John publishes records |
| 5 | Verification + smoke (§6) | John: **"yes, admit synthetic beta smoke"** |

Fri 20 Nov external TestFlight still needs **Alfred's go plus John's direct yes** (out of scope here).

---

## 3. (a) Postgres and Redis on the production VM

Mirror staging:

1. Foundation leaves a D2s_v5 Ubuntu 22.04 VM with a 128 GiB data disk.
2. Host bootstrap formats that disk only with a reviewed creation receipt and
   mounts it at `/var/lib/cosmabot` (`nodev,nosuid,noexec`), creating empty
   `postgres` / `redis` (UID/GID 999) and `caddy-*` (10001) directories.
3. Runtime render (`infra/beta/vm/runtime/`) brings Postgres **16** and Redis
   (7.2/7.4 bookworm digests from the reviewed manifest) on reserved bridges
   (`172.30.240.0/24` backend, etc.). Only proxy 80/443 are published.
4. Passwords: distinct URL-safe values for `DATABASE_PASSWORD`,
   `POSTGRES_PASSWORD`, and `REDIS_PASSWORD` (see §4 names). Entrypoint builds
   `DATABASE_URL` / `REDIS_URL`; those URLs are never supplied as secrets.
5. `start.sh` order (same as staging): `data` → `prepare` (forward-only schema)
   → `run`. Do not bypass host preflight with raw Compose.

**Prod retarget:** every staging-hardwired name
(`rg-cosmas-os-vm-staging-eus2-lab01`, `vm-cosmabot-staging-eus2-lab01`,
`staging.cosmas.ai`) must be replaced with the production RG/VM/hostnames
before any script runs. Do not run the staging scripts against prod.

---

## 4. (b) Deploy app in synthetic mode on `beta.cosmas.ai`

### Profile invariants

From `#356` `infra/beta/vm/prod/profile/runtime-public.json`:

- `DATA_MODE=synthetic`
- `AUTH_MODE=clerk_jwt`
- `COSMAS_ENV=early_adopter_beta`
- `WORKSPACE_LLM_BACKEND=disabled` (no LLM traffic until a later cutover)
- `REAL_PATIENT_RECORDING_ENABLED=false`
- Eight standalone backend switches stay explicit `'false'`
  (`infra/standalone/README.md`):  
  `WORKSPACE_CAPTURE_PROXY_ENABLED`, `GOOGLE_CONNECTION_BROKER_ENABLED`,
  `WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED`, `WORKSPACE_ENROLLMENT_MANAGED`,
  `COSMAS_EHR_REAL_DATA_ENABLED`, `WORKSPACE_RX_SANDBOX_ENABLED`,
  `REAL_PATIENT_RECORDING_ENABLED`, `WORKSPACE_EFAX_SANDBOX_ENABLED`

### Account deletion (App Store) — pending name allowance

Hosted delete on production-review (`beta.cosmas.ai`) needs the private env
**name** `ACCOUNT_DELETE_CLERK_SECRET_KEY` accepted by the standalone
review profile.

- **Pending, not merged:** [PR `#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377)
  — *T-APPSTORE-FIXES 1/4: production-review ACCOUNT_DELETE_CLERK_SECRET_KEY
  name allowance* (`grok/appstore-1-review-delete-key`).
- That PR only allows the **name**; it does not mount a key, write Key Vault,
  or change staging's deletion-off state.
- Operator later pastes the account-deletion Clerk secret into Key Vault under
  the names in the table below. `CLERK_SECRET_KEY` stays refused for CosmaBot
  sign-in (JWKS-only).

Do not deploy production-review account-delete until `#377` is merged **and**
John pastes the secret himself.

### Key Vault secret names only (no values)

From `#356` prod README names table (Key Vault name → host file):

| Key Vault secret name | Host file name | Used by |
| --- | --- | --- |
| `CLERK-SECRET-KEY` | `CLERK_SECRET_KEY` | api, worker (custody; standalone sign-in still JWKS-only) |
| `CLERK-ACCOUNT-DELETION-SECRET` | `CLERK_ACCOUNT_DELETION_SECRET` | api, worker |
| `DATABASE-PASSWORD` | `DATABASE_PASSWORD` | api, worker, prepare |
| `POSTGRES-PASSWORD` | `POSTGRES_PASSWORD` | prepare, postgres |
| `REDIS-PASSWORD` | `REDIS_PASSWORD` | api, worker, redis |
| `HUMAN-DEPLOY-EVIDENCE-REF` | `HUMAN_DEPLOY_EVIDENCE_REF` | api, worker |

Also plan for the optional App Store delete mount name
`ACCOUNT_DELETE_CLERK_SECRET_KEY` (host file same name) once `#377` lands —
still **name only** in tickets and chat.

`WORKSPACE_LLM_API_KEY` is **not** in the first-apply profile. It belongs only
to the later LLM cutover.

### Clerk public values John sends (non-secret)

Issuer, JWKS URL, audience, authorized parties, organization ID, publishable
key. Secret key and account-deletion secret: John pastes into Key Vault only.

---

## 5. (c) Azure OpenAI + `gpt-4.1-dzus`

With first-apply `enable_azure_openai: true`:

- Account: `azurerm_cognitive_account` `kind = "OpenAI"`, SKU `S0`, public
  network disabled, private endpoint + `privatelink.openai.azure.com`
- Deployment name: `gpt-4.1-dzus`
- Model: `gpt-4.1` version `2025-04-14`, DataZoneStandard capacity **1**
- Runtime: **no traffic** until cutover (`WORKSPACE_LLM_BACKEND=disabled`,
  `routes_runtime_traffic=false`)
- Shared / staging / CosmasCode model account keys must **never** be loaded
  into prod

John gate: **"yes"** to creating that resource and deployment (same model,
Data Zone US) — already expressed as opt-in inputs for first apply; confirm
again if a day-2 tool is used instead.

After apply, John should rotate the provider-generated OpenAI account keys
before any cutover that loads a key into Key Vault (`#356` README).

---

## 6. (d) DNS records (John publishes; proxy off)

Once the production static public IP is known (from apply outputs):

| Name | Type | Target | Proxy |
| --- | --- | --- | --- |
| `beta.cosmas.ai` | A | production public IP | **DNS-only** (grey cloud) |
| `api.beta.cosmas.ai` | A | same public IP | **DNS-only** |
| `clerk.beta.cosmas.ai` | CNAME | value Clerk gives John | per Clerk; CosmaBot app proxy stays **off** |

Proxying the CosmaBot host would decrypt traffic in transit; default is off
(30 Oct / 11 Nov plan). `#356` does not touch DNS. Do not publish until John
is ready for Mon/Tue cutover checks.

---

## 7. Open question — production OpenAI endpoint kind vs app pin

### Verdict

**They do not match the app's default pin host, but they do match the app's
accepted Azure OpenAI v1 client shape when configured for standalone/synthetic
beta. Prefer configuring the classic `*.openai.azure.com/openai/v1` endpoint
at LLM cutover; do not change the model. Recreate as AI Foundry only if John
requires a `*.services.ai.azure.com` host.**

### Evidence from `#356` IaC (branch `grok/cosmabot-prod-hosting`)

In `infra/beta/vm/prod/foundation/modules/azure_openai/main.tf` on that branch:

- Lines 8–22: `azurerm_cognitive_account.openai` sets `kind = "OpenAI"` (classic
  Azure OpenAI Cognitive Services account), SKU `S0`, public network disabled.
- Lines 25–39: `azurerm_cognitive_deployment.gpt41_dzus` name `gpt-4.1-dzus`,
  model `gpt-4.1` version `2025-04-14`, `DataZoneStandard` capacity `1`.
- Lines 42–44: private DNS zone `privatelink.openai.azure.com` (classic OpenAI
  privatelink, not `privatelink.services.ai.azure.com`).

Also on that branch, `infra/beta/vm/prod/profile/runtime-public.json`:

- Lines 11–13: `WORKSPACE_LLM_BACKEND=disabled`, deployment still named
  `gpt-4.1`, `WORKSPACE_LLM_USDZ_ENABLED=false`.
- Lines 29, 34–40: notes that module output `azure_openai_endpoint` is the
  Cognitive account base URL (not yet the app `WORKSPACE_LLM_ENDPOINT` form);
  `routes_runtime_traffic` is false; deployment created when enabled is
  `gpt-4.1-dzus`.

Provider endpoint for `kind = "OpenAI"` is the classic base URL
(`https://<name>.openai.azure.com/`). That is **not** an AI Foundry /
`*.services.ai.azure.com` project endpoint.

### Evidence from app pin on `main`

| Location | What it expects |
| --- | --- |
| `src/cosmas_os/config.py` line 238 | Default `workspace_llm_endpoint = "https://cosmascode.services.ai.azure.com/openai/v1"` (**AI Foundry-style** host) |
| `src/cosmas_os/config.py` line 449 | Non-standalone `workspace_llm_available` requires that **exact** cosmascode `services.ai` endpoint |
| `src/cosmas_os/config.py` line 912 | Standalone validator accepts **either** `*.openai.azure.com` **or** `*.services.ai.azure.com` with path `/openai/v1` |
| `src/cosmas_os/adapters/gpt41.py` line 31 | Hardcoded default chat URL on `services.ai.azure.com` |
| `src/cosmas_os/adapters/gpt41.py` line 170 | Connector accepts **either** host kind with `/openai/v1/chat/completions` |
| `scripts/prepare-operational-startup.py` lines 258–259 | Binding allow-list includes both `https://{name}.openai.azure.com/openai/v1` and `https://{name}.services.ai.azure.com/openai/v1` |

**API surface:** the pinned client uses the Azure OpenAI **v1** HTTP path
(`/openai/v1/...`), not the older deployment URL with `?api-version=...`.
Classic `kind=OpenAI` accounts expose that v1 path. No separate api-version
query string is required by `GPT41Connector`.

### Guard-hardening note (deferred ticket)

`356-guard-hardening.md` already flagged: *prod account is kind OpenAI
(`*.openai.azure.com`) vs app pin `*.services.ai.azure.com/openai/v1`; confirm
or recreate.* This runbook confirms that mismatch for the **default pin** and
for non-standalone `workspace_llm_available`.

### What must change (later cutover ticket — not this PR, no model change)

1. Keep the `#356` classic OpenAI account (recommended) **or** John decides to
   recreate as a Foundry/`services.ai` resource (extra cost / new plan).
2. App / profile cutover must set:
   - `WORKSPACE_LLM_ENDPOINT=https://<prod-account-subdomain>.openai.azure.com/openai/v1`
     (append `/openai/v1`; bare cognitive base URL is invalid for the app)
   - `WORKSPACE_LLM_BACKEND=azure_gpt41`
   - `WORKSPACE_LLM_USDZ_ENABLED=true` and deployment `gpt-4.1-dzus` (or remove
     an overriding pin)
   - `standalone_model_origin_allowlist` to the matching origin
   - Prod account key only (never the shared cosmascode key)
3. If production ever uses the non-standalone `workspace_llm_available` path,
   that property's hardcoded cosmascode `services.ai` equality
   (`src/cosmas_os/config.py` line 449) must be widened or replaced in an
   **app** ticket — still without changing the model.
4. Until that cutover, leave `WORKSPACE_LLM_BACKEND=disabled`.

---

## 8. (e) Rollback and (f) verification

### Verification (admit only after John's yes)

Mirror the staging pointer-switch post-checks (`release-r7` step 15 shape):

1. `GET https://api.beta.cosmas.ai/ready` (and local/container `/ready`) returns
   ready and proves DB connectivity — no secrets in the body.
2. `GET https://beta.cosmas.ai/version.json` shows the reviewed source commit.
3. Sign-in page serves the expected synthetic bundle (not a stale hashed
   asset); Clerk production-review public config matches John's values.
4. Worker private `:8001/ready` only while its dependencies are up
   (`docs/beta/HUMAN_DEPLOYMENT_EVIDENCE.md`).
5. Confirm the **eight** backend switches are `'false'` in the rendered public
   environment (`infra/standalone/README.md` list in §4).
6. Confirm `DATA_MODE=synthetic`, `REAL_PATIENT_RECORDING_ENABLED=false`,
   `WORKSPACE_LLM_BACKEND=disabled`.
7. Optional synthetic smoke: fake reviewer user, no real patients.
8. Health unit / probe reports application ok (staging used `cosmabot-health`).

### Rollback

| Phase | Action |
| --- | --- |
| Before `#356` apply | Delete local plan folder; **$0**. Do not apply. |
| After apply, before DNS/public traffic | Keep state; destroy only with a **new** yes from John (vault/disks/storage delete-protection). |
| After a release pointer switch (staging pattern) | Point `/etc/cosmabot/active-release` back at the previous release directory and run that release's `start.sh`. Do not delete the new release dir until John says so. |
| DNS | Remove or grey-cloud the A/CNAME records John added; staging DNS stays untouched. |
| LLM | Leave backend `disabled`; do not load `WORKSPACE_LLM_API_KEY`. |

Trial ports / side-by-side release directories (staging used 54120/54122) must
not take public traffic until the pointer switch. Public traffic moves only
when the active-release pointer changes.

---

## 9. Gaps and decisions for John

1. **Merge `#377` before** mounting `ACCOUNT_DELETE_CLERK_SECRET_KEY` on beta;
   until then account delete fails closed (`account deletion is not configured`).
2. **Secrets ticket** still owns the runnable Key Vault load/verify/cleanup
   script and host 0400 install (`#356` explicitly split this out).
3. **Endpoint kind:** confirm classic `*.openai.azure.com` at cutover (this
   runbook's recommendation) vs recreate as `services.ai` Foundry — cost and
   a new plan if recreating.
4. **Non-standalone pin** at `src/cosmas_os/config.py` line 449 blocks using
   the prod classic endpoint on that code path until an app ticket changes it.
5. **Runtime acceptance** of `DATABASE_PASSWORD` / `POSTGRES_PASSWORD` /
   `REDIS_PASSWORD` on the prod entrypoint is still called out as unverified
   in `356-guard-hardening.md` — prove on the prod VM before admitting
   testers.
6. **OpenAI in first apply vs day-2:** `#356` first-apply-only tooling expects
   opt-in in the same apply; a false first apply cannot add OpenAI without a
   separately reviewed day-2 tool.
7. **TestFlight / App Store upload** remain blocked until Alfred's go + John's
   direct yes (Fri 20 target is readiness only).
8. Staging runbook sources named in the ticket
   (`tickets/2026-11-10-staging-release-facts.md`,
   `cosmabot-staging-deploy-plan` §§11–12, `t-r7/POINTER_SWITCH_STEP_LIST.md`)
   were not in this repository checkout; this doc mirrors the staging
   `release-r7` pointer-switch list and in-repo host/runtime READMEs instead.

---

## 10. Checklist (copy for the apply weekend)

- [ ] `#356` applied; RG/VM/IP recorded
- [ ] John typed yes on plan/summary hashes before apply (already done that day)
- [ ] Production Clerk public values received; secrets pasted by name into KV
- [ ] Mode-600 password file on VM (John); not via Run Command
- [ ] Host bootstrap + Docker/IMDS guard reviewed
- [ ] Postgres 16 + Redis up on data disk
- [ ] Synthetic app render/deploy for beta hostnames
- [ ] `#377` merged before delete-key mount (pending)
- [ ] DNS A/CNAME published, proxy off
- [ ] `/ready`, `/version.json`, smoke, eight switches false
- [ ] LLM still disabled; no shared model key in prod
- [ ] Staging untouched
