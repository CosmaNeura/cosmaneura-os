# CosmaBot production post-apply runbook (prep only)

**Tonight for existing live users: nothing. Docs only, nothing applied.**

Status: **PREP ONLY — clock for Fri 13 Nov 2026 (ET).** This runbook does not
authorize OpenTofu apply, Azure writes, DNS changes, Clerk console work, secret
pastes, or a deploy. Coding agents must not run those steps from this document.
John asked to start production server work today; the schedule below compresses
owner sittings onto **today's** clock. Agents prepare between sittings. Staging
stays untouched. Synthetic data only.

**Audience:** John (owner gates) and agents/release lead after John applies
`#356` (`grok/cosmabot-prod-hosting`, unapplied).

**Target host:** `rg-cosmabot-prod-eus2-01`, `beta.cosmas.ai` /
`api.beta.cosmas.ai`.

---

## Pending prerequisites (app fixes — not this PR, not `#356`)

| PR / branch | What it does | Status |
| --- | --- | --- |
| [`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377) `grok/appstore-1-review-delete-key` | Production-review accepts the secret **name** `ACCOUNT_DELETE_CLERK_SECRET_KEY` (delete-key name mapping from KV/`CLERK_ACCOUNT_DELETION_SECRET` custody toward the App Store delete mount name). No Key Vault write, no deploy. | **Pending** (draft) |
| New small app PR on **`grok/prod-openai-endpoint-allow`** | Allow the configured **production** Azure OpenAI endpoint in hosted `workspace_llm_available` (today pinned to CosmasCode only — §9 (a)). No model change. | **Pending** (must be opened/merged before AI-on first start) |

Do not merge or apply those from this docs ticket. Agents may open/land them on
their own branches while John is in a sitting or between sittings.

---

## 0. Hard stops

| Forbidden in this prep ticket | Why |
| --- | --- |
| Merge `#356` or this PR | Owner only |
| `tofu` / `terraform` plan or apply | John's Mac / separate apply |
| `az` write, Key Vault writes, DNS edits, Clerk changes | Owner / later tickets |
| Secret values in chat, git, run-command, or this doc | Names only |
| Touch staging or run5 | Plan invariant |
| Model change | Same model: `gpt-4.1` / `gpt-4.1-dzus` |
| Real patient data | Synthetic until a separate compliance yes |

---

## 1. Today's clock (Fri 13 Nov 2026, ET)

Two John sittings. Everything else is agent prep or a typed **yes** gate.
Times are planning envelopes; slip only if John is filming.

### Before Sitting 1 — agents (now → ~11:15 ET)

| Who | Work | ~Duration |
| --- | --- | --- |
| Agents | Keep this runbook draft green (`ci:full`); watch `#377`; open/drive **`grok/prod-openai-endpoint-allow`** (decision §9 (a)) | ongoing |
| Agents | Prep `#356` review packet on John's Mac path (hashes, opt-in inputs with `enable_azure_openai: true`) — **do not apply** | 30–45 min |
| Agents | List secret **names** and Clerk public fields John will need (below) | 10 min |

### Sitting 1 — John (~11:15–12:30 ET, ~75 min)

Hands-on only. Exact order:

| # | John does | ~Min | Gate |
| --- | --- | --- | ---: |
| 1 | Sign in to Azure as `john@cosmaneura.com`; confirm subscription is the one that already has staging | 5 | — |
| 2 | Review `#356` plan + cost on his Mac; type **yes** on the exact plan/summary hashes | 15 | **"yes" on plan hash** |
| 3 | Apply foundation (John only; `enable_azure_openai: true` in reviewed inputs) | 20 | Apply exits 0 |
| 4 | Confirm RG `rg-cosmabot-prod-eus2-01`, VM up, record public IP, OpenAI + `gpt-4.1-dzus` present | 10 | **"yes, apply looks complete"** |
| 5 | Create/finish **production Clerk** (not Cosmas, not staging): domain `clerk.beta.cosmas.ai`; origins `https://beta.cosmas.ai` + `capacitor://localhost`; JWT audience per 30 Oct list; one synthetic org + fake reviewer | 20 | — |
| 6 | Send agents **public** Clerk values only (issuer, JWKS URL, audience, authorized parties, org ID, publishable key) | 5 | — |

**John does not paste secrets in Sitting 1.** Stop after public Clerk values.

### Between sittings — agents (~12:30–13:30 ET)

| Who | Work |
| --- | --- |
| Agents | Read-only verify RG/VM/IP/OpenAI names; draft DNS record text (do not publish) |
| Agents | Retarget host-bootstrap receipt fields to prod VM/disk IDs (staging names refused) |
| Agents | Advance `#377` and `grok/prod-openai-endpoint-allow` toward green; do not merge without John |
| Agents | Prepare Key Vault **names** checklist and mode-600 password-file instructions for Sitting 2 |
| Agents | No Run Command with secrets; no staging changes |

### Sitting 2 — John (~13:30–14:30 ET, ~60 min)

| # | John does | ~Min | Gate |
| --- | --- | --- | ---: |
| 1 | Key Vault secret pastes (**names only** — §4): temporary public-access window from John's own `/32`, set via `--file`, then restore `publicNetworkAccess=Disabled` and empty `ipRules` | 25 | **"yes, KV secrets loaded and public access disabled"** |
| 2 | On the new VM as root: create distinct DB/Postgres/Redis passwords in a **mode-600** file he owns. **Never** via Azure Run Command | 10 | **"yes, mode-600 password file is on the host"** |
| 3 | Type **yes** to format the new empty data disk (prod IDs only) | 5 | **"yes, format the new empty data disk"** |
| 4 | Publish Cloudflare DNS (proxy **off**): `beta.cosmas.ai` A, `api.beta.cosmas.ai` A → public IP; `clerk.beta.cosmas.ai` CNAME from Clerk | 10 | — |
| 5 | Decide §9 (b) path (recommended: AI-on first start after endpoint-allow PR) and type **yes** for agents to continue host prep / data services after this sitting | 5 | **"yes, continue host prep"** |
| 6 | Optional: merge `#377` and/or `grok/prod-openai-endpoint-allow` when green | 5 | Owner merge only |

### After 14:30 ET — agents (same day if John said yes)

Not John's hands-on. Still synthetic; still no staging:

1. Host bootstrap → Docker/IMDS guard → Postgres 16 + Redis on the VM (§3).
2. Install mode-0400 secret files from the names John pasted (§4); Run Command
   still must not carry secret values.
3. When `#377` + endpoint-allow are merged and John chose AI-on: flip runnable
   profile flags per §9 (b); include `WORKSPACE_LLM_API_KEY` (**prod** account
   key name only).
4. Render + `start.sh data` → `prepare` → `run`.
5. Verify `/ready`, `/version.json`, smoke, eight backend switches `'false'`
   (§8). Admit smoke only after John's separate yes.

External TestFlight still needs **Alfred's go + John's direct yes** (not today).

---

## 2. What `#356` leaves behind (after Sitting 1 apply)

| Item | Expected name / note |
| --- | --- |
| Resource group | `rg-cosmabot-prod-eus2-01` (East US 2) |
| VM | `vm-cosmabot-prod-eus2-01` (`Standard_D2s_v5`) |
| Key Vault | `kv-cbot-prd-*` (public access Disabled until Sitting 2) |
| ACR / storage / PE / DNS zones / Log Analytics | As planned; private |
| Azure OpenAI | Classic `kind = "OpenAI"` + deployment `gpt-4.1-dzus` (capacity 1) |
| Runtime LLM in foundation profile | `WORKSPACE_LLM_BACKEND=disabled`; `routes_runtime_traffic=false`. Runnable start: §9 (b) |
| Secrets on the VM | **None** until Sitting 2 / secrets install |
| DNS | Unchanged until Sitting 2 |

Postgres 16 and Redis run **on the VM** (not Azure Database / Azure Cache).

---

## 3. Postgres and Redis on the production VM

Mirror staging host/runtime:

1. Bootstrap formats the 128 GiB data disk with a reviewed creation receipt;
   mount `/var/lib/cosmabot`; empty `postgres`/`redis` (UID 999).
2. Runtime render brings Postgres **16** and Redis on reserved bridges; only
   proxy 80/443 published.
3. Distinct URL-safe passwords for `DATABASE_PASSWORD`, `POSTGRES_PASSWORD`,
   `REDIS_PASSWORD`. Entrypoint builds URLs; never supply those URLs as secrets.
4. `start.sh`: `data` → `prepare` → `run`.

**Prod retarget:** never run staging-hardwired scripts
(`rg-cosmas-os-vm-staging-eus2-lab01`, `staging.cosmas.ai`, …) against prod.

---

## 4. Synthetic deploy on `beta.cosmas.ai` + secret names

### Profile invariants

- `DATA_MODE=synthetic`, `AUTH_MODE=clerk_jwt`, `COSMAS_ENV=early_adopter_beta`
- `#356` first-setup: `WORKSPACE_LLM_BACKEND=disabled` — see §9 (b) before API start
- `REAL_PATIENT_RECORDING_ENABLED=false`
- Eight backend switches `'false'`: `WORKSPACE_CAPTURE_PROXY_ENABLED`,
  `GOOGLE_CONNECTION_BROKER_ENABLED`, `WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED`,
  `WORKSPACE_ENROLLMENT_MANAGED`, `COSMAS_EHR_REAL_DATA_ENABLED`,
  `WORKSPACE_RX_SANDBOX_ENABLED`, `REAL_PATIENT_RECORDING_ENABLED`,
  `WORKSPACE_EFAX_SANDBOX_ENABLED`

### Account deletion name mapping (depends on `#377`)

- KV / custody name: `CLERK-ACCOUNT-DELETION-SECRET` → host
  `CLERK_ACCOUNT_DELETION_SECRET`
- App Store delete mount name required by the API:
  `ACCOUNT_DELETE_CLERK_SECRET_KEY`
- `#377` allows that **name** on production-review (`beta.cosmas.ai`). Pending.
  Do not mount until `#377` is merged and John pastes the value himself.

### Key Vault → host file names only

| Key Vault secret name | Host file name |
| --- | --- |
| `CLERK-SECRET-KEY` | `CLERK_SECRET_KEY` |
| `CLERK-ACCOUNT-DELETION-SECRET` | `CLERK_ACCOUNT_DELETION_SECRET` |
| `DATABASE-PASSWORD` | `DATABASE_PASSWORD` |
| `POSTGRES-PASSWORD` | `POSTGRES_PASSWORD` |
| `REDIS-PASSWORD` | `REDIS_PASSWORD` |
| `HUMAN-DEPLOY-EVIDENCE-REF` | `HUMAN_DEPLOY_EVIDENCE_REF` |

Also for AI-on first start (§9 (b)): host/KV name `WORKSPACE_LLM_API_KEY`
(prod account only — never CosmasCode). Optional after `#377`:
`ACCOUNT_DELETE_CLERK_SECRET_KEY`.

### Clerk public values (Sitting 1)

Issuer, JWKS URL, audience, authorized parties, organization ID, publishable
key. Secrets: Sitting 2 Key Vault only.

---

## 5. Azure OpenAI + `gpt-4.1-dzus`

Created in Sitting 1 apply when `enable_azure_openai: true`:

- `kind = "OpenAI"`, SKU `S0`, PE + `privatelink.openai.azure.com`
- Deployment `gpt-4.1-dzus`, model `gpt-4.1` / `2025-04-14`, DataZoneStandard
  capacity **1**
- Rotate provider-generated keys before loading `WORKSPACE_LLM_API_KEY`
- Shared CosmasCode / staging keys must never enter prod

Runnable traffic needs §9 (a) endpoint-allow PR + §9 (b) flag flips.

---

## 6. DNS (Sitting 2; proxy off)

| Name | Type | Target | Proxy |
| --- | --- | --- | --- |
| `beta.cosmas.ai` | A | prod public IP | DNS-only |
| `api.beta.cosmas.ai` | A | same IP | DNS-only |
| `clerk.beta.cosmas.ai` | CNAME | Clerk value | CosmaBot app proxy **off** |

`#356` does not touch DNS.

---

## 7. OpenAI endpoint kind vs app pin

**Verdict:** `#356` creates classic Azure OpenAI (`*.openai.azure.com`). App
default pin is CosmasCode `*.services.ai.azure.com/openai/v1`. Standalone
client/validators accept both hosts with `/openai/v1`. Hosted
`workspace_llm_available` does **not** — see §9 (a). Prefer classic
`https://<prod>.openai.azure.com/openai/v1` at cutover; do not change the model.

### Evidence (`#356` branch `grok/cosmabot-prod-hosting`)

- `infra/beta/vm/prod/foundation/modules/azure_openai/main.tf` lines 8–22:
  `kind = "OpenAI"`
- Same file lines 25–39: deployment `gpt-4.1-dzus`
- Same file lines 42–44: `privatelink.openai.azure.com`
- `infra/beta/vm/prod/profile/runtime-public.json` lines 11–13, 29, 34–40:
  AI disabled in foundation profile; module base URL ≠ app endpoint form

### Evidence (`main`)

| Location | Expectation |
| --- | --- |
| `src/cosmas_os/config.py` 238 | Default CosmasCode `services.ai` endpoint |
| `src/cosmas_os/config.py` 449 | Hosted availability **equals** CosmasCode only |
| `src/cosmas_os/config.py` 912 | Standalone accepts either host + `/openai/v1` |
| `src/cosmas_os/adapters/gpt41.py` 31, 170 | Default CosmasCode; constructor accepts either |
| `scripts/prepare-operational-startup.py` 258–259 | Both host forms in binding allow-list |

API surface: Azure OpenAI **v1** path (`/openai/v1/...`), not `?api-version=`.

---

## 8. Verification and rollback

### Verification (after agents finish post-14:30 work; John's admit yes)

1. `GET …/ready` (API + local) — DB up; no secrets in body
2. `GET …/version.json` — reviewed commit
3. Sign-in page + Clerk public config
4. Worker `:8001/ready`
5. Eight backend switches `'false'`
6. `DATA_MODE=synthetic`, `REAL_PATIENT_RECORDING_ENABLED=false`; LLM flags per §9 (b)
7. Synthetic smoke only after John yes
8. Health probe application ok

### Rollback

| Phase | Action |
| --- | --- |
| Before apply | Delete local plan folder; $0 |
| After apply, before traffic | Keep state; destroy only with a new John yes |
| After pointer switch | Point `active-release` at prior release; run that `start.sh` |
| DNS | Remove/grey-cloud records John added; staging untouched |
| LLM | Never load CosmasCode key into prod |

---

## 9. Decisions for John

Do **not** fix these in `#356`. Do **not** change app/runtime code in this
docs PR. No model change.

### (a) Hosted AI availability is pinned to CosmasCode

**Confirm:**

| File | Lines | Behavior |
| --- | --- | --- |
| `src/cosmas_os/config.py` | 237–238 | Default backend `disabled`; endpoint CosmasCode |
| `src/cosmas_os/config.py` | 444–451 | Non-standalone `workspace_llm_available` requires **exact** CosmasCode endpoint + `azure_gpt41` + reviewed deployment + key |
| `src/cosmas_os/config.py` | 658–659 | Backend on but unavailable → runtime refuse |
| `src/cosmas_os/adapters/gpt41.py` | 31, 170 | Default CosmasCode; constructor accepts either host |
| `src/cosmas_os/config.py` | 912 | Standalone already accepts either host |

**Contradiction:** `#356` creates a separate prod OpenAI account. Hosted path
still refuses any non-CosmasCode endpoint when AI is on.

**Smallest fix:** new small app PR on **`grok/prod-openai-endpoint-allow`** —
widen lines 448–451 to accept a configured prod endpoint matching the line 912
regex (keep CosmasCode for live users; keep deployment + key checks; no model
change). Optional tighter one-origin allowlist if John wants it.

**Tests (mutation-killing):** prod `*.openai.azure.com/openai/v1` → available
true; CosmasCode still true; invented host false; backend disabled still off;
line 658 guard; model pins unchanged. CI: hosted/LLM unit shards + new matrix
module.

### (b) VM runtime refuses start unless AI is on with its key; `#356` profile is AI-off

**Confirm:**

| File | Lines | Behavior |
| --- | --- | --- |
| `infra/beta/vm/runtime/entrypoint.py` | 20–35 | `BASE` requires `WORKSPACE_LLM_BACKEND=azure_gpt41` |
| `infra/beta/vm/runtime/entrypoint.py` | 118–119 | Diff from `BASE` → `hosted_synthetic_profile_required` |
| `infra/beta/vm/runtime/entrypoint.py` | 158–159 | Missing `WORKSPACE_LLM_API_KEY` in `secret_names` → `model_credential_required` |
| `#356` profile `runtime-public.json` | 11–13, 16–22 | `disabled`; no `WORKSPACE_LLM_API_KEY` |

**Fork:**

1. **Recommended today:** AI-on first start after `grok/prod-openai-endpoint-allow`
   merges; treat `#356` disabled profile as foundation-only.
2. **Alternative:** separate runtime PR allowing AI-off first start (not `#356`).

**Order for first `/ready` (path 1):**

1. Merge `grok/prod-openai-endpoint-allow` (§9 (a)).
2. Sitting 1: apply `#356` (RG, VM, OpenAI `gpt-4.1-dzus`).
3. Host prep (agents after Sitting 2 yes).
4. Sitting 2: John sets mode-600 passwords; pastes KV names:
   `DATABASE_PASSWORD`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
   `CLERK_SECRET_KEY`, `CLERK_ACCOUNT_DELETION_SECRET`,
   `HUMAN_DEPLOY_EVIDENCE_REF`, then `WORKSPACE_LLM_API_KEY` (prod only).
   After `#377`: optional `ACCOUNT_DELETE_CLERK_SECRET_KEY`.
5. Flags flip: backend `azure_gpt41`; endpoint
   `https://<prod>.openai.azure.com/openai/v1`; USDZ/deployment `gpt-4.1-dzus`;
   `secret_names` includes `WORKSPACE_LLM_API_KEY`; synthetic + eight switches
   false.
6. Install 0400 files; `data` → `prepare` → `run`.
7. `/ready` after DB prepare, secrets loaded, BASE satisfied, (a) available
   true, DNS or local checks OK; `/version.json` shows reviewed commit.

### Other gaps

1. Secrets ticket owns runnable KV load/verify/cleanup + host 0400 transport.
2. Endpoint kind: classic vs Foundry recreate — §7.
3. Password-name acceptance on prod entrypoint still unverified per `#356`
   guard-hardening notes — prove before admitting testers.
4. `#356` OpenAI is first-apply-only if omitted from Sitting 1 inputs.
5. TestFlight blocked until Alfred + John.
6. Staging ticket files named in the original ask were not in this checkout;
   this doc mirrors `release-r7` pointer-switch + in-repo host/runtime READMEs.

---

## 10. Today's checklist (Fri 13 Nov)

- [ ] Agents: runbook PR green; `#377` watched; `grok/prod-openai-endpoint-allow` opened
- [ ] Sitting 1: plan-hash yes → `#356` apply → IP recorded → Clerk public values sent
- [ ] Between: agent prep only (no secrets, no staging)
- [ ] Sitting 2: KV names pasted → mode-600 passwords → disk-format yes → DNS proxy off → continue-prep yes
- [ ] After 14:30: host Postgres/Redis → secrets install → flags per §9 (b) → `/ready` + `version.json`
- [ ] `#377` merged before delete-key mount
- [ ] Endpoint-allow merged before AI-on against prod endpoint
- [ ] Eight switches false; synthetic only; staging untouched; no CosmasCode key in prod
