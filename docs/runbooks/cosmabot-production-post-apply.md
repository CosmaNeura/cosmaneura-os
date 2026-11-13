# CosmaBot production post-apply runbook (prep only)

**Tonight for existing live users: nothing. Docs only, nothing applied.**

Status: **PREP ONLY — clock for Fri 13 Nov 2026 (ET).** Times below are
**targets** and shift later if a sitting starts late. This runbook does not
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

Both must be merged **before** the AI-on first start in decision §9 (b).

| PR | What it does | Status |
| --- | --- | --- |
| [`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377) | Production-review accepts process env name `ACCOUNT_DELETE_CLERK_SECRET_KEY`. Custody mapping stays vault `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET` (#356 README line 191). No Key Vault write, no deploy. | **Pending** (draft) |
| [`#381`](https://github.com/CosmaNeura/cosmaneura-os/pull/381) | **Decision (a) decided (CTO, 13 Nov).** Allows the exact production host pattern `https://oai-cbot-prd-[a-z0-9]{6,10}.openai.azure.com/openai/v1` and wires hosted chat (text and tools, including streaming) to the configured endpoint. Unusable configured endpoint → fail closed, never silent CosmasCode fallback. No endpoint set (staging) → unchanged. Model, deployment, and API version unchanged. | **Pending** (open; merge before AI-on first start) |

Do not merge or apply those from this docs ticket. Agents may drive them to
green while John is in a sitting or between sittings; John merges.

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
| Agents | Keep this runbook draft green (`ci:full`); watch [`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377) and [`#381`](https://github.com/CosmaNeura/cosmaneura-os/pull/381) | ongoing |
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
| Agents | Advance [`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377) and [`#381`](https://github.com/CosmaNeura/cosmaneura-os/pull/381) toward green; do not merge without John |
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
| 6 | Optional: merge `#377` and/or `#381` when green (both required before AI-on first start) | 5 | Owner merge only |

### After 14:30 ET — agents (same day if John said yes)

Not John's hands-on. Still synthetic; still no staging:

1. Host bootstrap → Docker/IMDS guard → Postgres 16 + Redis on the VM (§3).
2. Install mode-0400 secret files from the names John pasted (§4); Run Command
   still must not carry secret values.
3. **Before AI-on first start:** run the deploy-time STOP checks in §4.1
   (prod `WORKSPACE_LLM_API_KEY` reference) and §4.2 (bundle API origins).
   On any mismatch: **STOP and roll back** — do not flip AI-on flags, do not
   start API/worker with model traffic.
4. When `#377` + `#381` are merged, checks pass, and John chose AI-on: flip
   runnable profile flags per §9 (b); include `WORKSPACE_LLM_API_KEY` (**prod**
   account key name only).
5. Render + `start.sh data` → `prepare` → `run`.
6. Verify `/ready`, `/version.json`, smoke, eight backend switches `'false'`
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

### Account deletion name mapping (matches `#356` README)

Per `#356` `infra/beta/vm/prod/README.md` on branch `grok/cosmabot-prod-hosting`
(**lines 188–191** of that file; table row at **line 191**):

| Key Vault secret name | Host file name | Services |
| --- | --- | --- |
| `CLERK-ACCOUNT-DELETION-SECRET` | `CLERK_ACCOUNT_DELETION_SECRET` | `api`, `worker` |

That is the custody mapping for the account-delete step. Do **not** invent a
different vault object name. `#377` separately allows the production-review
process env **name** `ACCOUNT_DELETE_CLERK_SECRET_KEY` (App Store delete path);
install still starts from vault object `CLERK-ACCOUNT-DELETION-SECRET` → host
`CLERK_ACCOUNT_DELETION_SECRET`. Do not mount until `#377` is merged and John
pastes the value himself. No Clerk secret values in this runbook.

### Key Vault → host file names only

| Key Vault secret name | Host file name |
| --- | --- |
| `CLERK-SECRET-KEY` | `CLERK_SECRET_KEY` |
| `CLERK-ACCOUNT-DELETION-SECRET` | `CLERK_ACCOUNT_DELETION_SECRET` |
| `DATABASE-PASSWORD` | `DATABASE_PASSWORD` |
| `POSTGRES-PASSWORD` | `POSTGRES_PASSWORD` |
| `REDIS-PASSWORD` | `REDIS_PASSWORD` |
| `HUMAN-DEPLOY-EVIDENCE-REF` | `HUMAN_DEPLOY_EVIDENCE_REF` |

Also for AI-on first start (§9 (b) / §4.1): host file `WORKSPACE_LLM_API_KEY`
from the **production** OpenAI account only — never CosmasCode or staging.

### Clerk public values (Sitting 1)

Issuer, JWKS URL, audience, authorized parties, organization ID, publishable
key. Secrets: Sitting 2 Key Vault only. (No Clerk values in this docs push.)

### 4.1 Deploy-time STOP — `WORKSPACE_LLM_API_KEY` is production OpenAI only

**When:** after secrets are named in KV/host files, **before** AI-on first start
(§9 (b) step that flips `WORKSPACE_LLM_BACKEND=azure_gpt41`).

**Rule:** the vault **reference** (name / id / tags / linked account name) for
`WORKSPACE_LLM_API_KEY` must belong to the production Azure OpenAI account
`oai-cbot-prd-*`, not CosmasCode and not staging. Check **names and references
only**. Never print, log, or copy a secret **value**. On mismatch: **STOP and
roll back** (do not start AI-on; leave backend disabled / prior release).

Read-only checks (names only; adjust vault/RG to the applied prod names):

```bash
# 1) Production OpenAI account name must match oai-cbot-prd-<6-10 alnum>
az cognitiveservices account list \
  --resource-group rg-cosmabot-prod-eus2-01 \
  --query "[?kind=='OpenAI'].name" -o tsv
# Expect exactly one name matching: ^oai-cbot-prd-[a-z0-9]{6,10}$
# STOP if missing, or if any name contains cosmascode / staging.

# 2) Vault secret *metadata* only — never query value / never --output that prints value
az keyvault secret show \
  --vault-name "$PROD_KV_NAME" \
  --name WORKSPACE-LLM-API-KEY \
  --query "{name:name, id:id, contentType:contentType, tags:tags}" -o json
# STOP if vault name is not the prod kv-cbot-prd-* vault.
# STOP if id/name/tags reference cosmascode, staging, or a non oai-cbot-prd-* account.

# 3) Host install lists the file name only (no cat / no od of the secret file)
ls -l /etc/cosmabot/runtime/"$RELEASE_ID"/api/WORKSPACE_LLM_API_KEY \
      /etc/cosmabot/runtime/"$RELEASE_ID"/worker/WORKSPACE_LLM_API_KEY
# Expect mode 0400; STOP if the path is missing or if a CosmasCode/staging
# reference file was installed instead.
```

Also confirm runnable public env (when AI-on is prepared) sets
`WORKSPACE_LLM_ENDPOINT` to the `#381` pattern
`https://oai-cbot-prd-[a-z0-9]{6,10}.openai.azure.com/openai/v1` — still no
secret values.

### 4.2 Deploy-time STOP — production bundles embed `https://api.beta.cosmas.ai`

**When:** before admitting the production-review iPhone / web build that talks
to this host (and before AI-on first start that serves that API). **STOP** if
the embedded API origin is not exactly `https://api.beta.cosmas.ai`, or if any
staging API origin is present.

**iPhone (composed/production `.app` or unpacked IPA `Payload/*.app`) — read-only:**

```bash
APP="/path/to/CosmaBot.app"   # reviewed production-review artifact only
/usr/bin/plutil -extract CosmasNativeIdentity.apiOrigin raw -o - "$APP/Info.plist"
# Expect exactly one line:
# https://api.beta.cosmas.ai
# STOP on any other value (including empty or api.staging.cosmas.ai).

# Refuse staging origin anywhere in the stamped Info:
if /usr/bin/plutil -convert json -o - "$APP/Info.plist" \
  | rg -F 'api.staging.cosmas.ai' -q; then
  echo "STOP: staging API origin in iPhone Info.plist"; exit 1
fi
```

**Web (unpacked production web archive / release web root) — read-only:**

```bash
WEB_ROOT="/path/to/reviewed-web-dist"   # production-review archive only

# Must embed the exact production API origin:
rg -aF 'https://api.beta.cosmas.ai' "$WEB_ROOT" -q \
  || { echo "STOP: missing https://api.beta.cosmas.ai in web bundle"; exit 1; }

# Must not embed staging API origin:
if rg -aF 'https://api.staging.cosmas.ai' "$WEB_ROOT" -q; then
  echo "STOP: staging API origin in web bundle"; exit 1
fi

# If the release retained web-build-env.json beside the archive, pin both keys:
if test -f "$WEB_ROOT/../web-build-env.json"; then
  jq -er '
    (.VITE_API_BASE // empty),
    (.VITE_WORKSPACE_HOSTED_API_ORIGIN // empty)
    | select(length > 0)
    | select(. != "https://api.beta.cosmas.ai")
    | "STOP: " + .
  ' "$WEB_ROOT/../web-build-env.json"
  # Any printed STOP line means rollback; empty output means pass.
fi
```

Do not ship or admit a candidate that fails either check.

---

## 5. Azure OpenAI + `gpt-4.1-dzus`

Created in Sitting 1 apply when `enable_azure_openai: true`:

- `kind = "OpenAI"`, SKU `S0`, PE + `privatelink.openai.azure.com`
- Deployment `gpt-4.1-dzus`, model `gpt-4.1` / `2025-04-14`, DataZoneStandard
  capacity **1**
- Rotate provider-generated keys before loading `WORKSPACE_LLM_API_KEY`
- Shared CosmasCode / staging keys must never enter prod

Runnable traffic needs `#381` merged + §9 (b) flag flips (and `#377` before
delete-key mount / AI-on first start prerequisites).

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
default pin is CosmasCode `*.services.ai.azure.com/openai/v1`. **Decision (a)
is decided (CTO, 13 Nov):** [`#381`](https://github.com/CosmaNeura/cosmaneura-os/pull/381)
allows the exact production pattern
`https://oai-cbot-prd-[a-z0-9]{6,10}.openai.azure.com/openai/v1` and wires
hosted chat to that configured endpoint (fail closed if set but unusable; staging
with no endpoint unchanged). Model/deployment/API version unchanged.

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

### (a) Hosted production endpoint — **decided (CTO, 13 Nov)**

**Pre-decision evidence on `main` (why `#381` exists):**

| File | Lines | Behavior |
| --- | --- | --- |
| `src/cosmas_os/config.py` | 237–238 | Default backend `disabled`; endpoint CosmasCode |
| `src/cosmas_os/config.py` | 444–451 (pre-`#381`) | Non-standalone `workspace_llm_available` required **exact** CosmasCode endpoint |
| `src/cosmas_os/config.py` | 658–659 | Backend on but unavailable → runtime refuse |
| `src/cosmas_os/adapters/gpt41.py` | 31, 170 | Default CosmasCode; constructor accepts either host |
| `src/cosmas_os/config.py` | 912 | Standalone already accepts either host |

**Decision:** [`#381`](https://github.com/CosmaNeura/cosmaneura-os/pull/381)
(`grok/prod-openai-endpoint-allow`):

1. Allows the exact production host pattern
   `https://oai-cbot-prd-[a-z0-9]{6,10}.openai.azure.com/openai/v1` (and keeps
   CosmasCode for existing live / unset-staging paths).
2. Wires hosted chat — text and tools, including streaming — to the configured
   endpoint.
3. If that endpoint is set but unusable → fail closed with a clear error; **never**
   silently fall back to CosmasCode.
4. With no endpoint set (staging) → nothing changes.
5. Model, deployment name, and API version unchanged.

Once `#381` is merged and the production endpoint is configured, production
chat uses production's own AI account. Do **not** recreate the `#356` OpenAI
resource for this.

### (b) VM runtime refuses start unless AI is on with its key; `#356` profile is AI-off

**Confirm:**

| File | Lines | Behavior |
| --- | --- | --- |
| `infra/beta/vm/runtime/entrypoint.py` | 20–35 | `BASE` requires `WORKSPACE_LLM_BACKEND=azure_gpt41` |
| `infra/beta/vm/runtime/entrypoint.py` | 118–119 | Diff from `BASE` → `hosted_synthetic_profile_required` |
| `infra/beta/vm/runtime/entrypoint.py` | 158–159 | Missing `WORKSPACE_LLM_API_KEY` in `secret_names` → `model_credential_required` |
| `#356` profile `runtime-public.json` | 11–13, 16–22 | `disabled`; no `WORKSPACE_LLM_API_KEY` |

**Prerequisites before AI-on first start:** merge
[`#381`](https://github.com/CosmaNeura/cosmaneura-os/pull/381) **and**
[`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377).

**Fork:**

1. **Recommended today:** AI-on first start only after `#381` + `#377` merge;
   treat `#356` disabled profile as foundation-only.
2. **Alternative:** separate runtime PR allowing AI-off first start (not `#356`).

**Order for first `/ready` (path 1):**

1. Merge `#381` (§9 (a) decided) **and** `#377` (delete-key name allowance).
2. Sitting 1: apply `#356` (RG, VM, OpenAI `gpt-4.1-dzus`).
3. Host prep (agents after Sitting 2 yes).
4. Sitting 2: John sets mode-600 passwords; pastes KV names:
   `DATABASE_PASSWORD`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
   `CLERK_SECRET_KEY`, vault `CLERK-ACCOUNT-DELETION-SECRET` → host
   `CLERK_ACCOUNT_DELETION_SECRET` (#356 README line 191),
   `HUMAN_DEPLOY_EVIDENCE_REF`, then `WORKSPACE_LLM_API_KEY` (prod only).
5. **STOP checks before AI-on:** §4.1 (prod OpenAI key reference) and §4.2
   (iPhone + web embed exactly `https://api.beta.cosmas.ai`, no staging). On
   failure: roll back; do not flip AI-on.
6. Flags flip: backend `azure_gpt41`; endpoint matching `#381` pattern
   `https://oai-cbot-prd-<suffix>.openai.azure.com/openai/v1`;
   USDZ/deployment `gpt-4.1-dzus`; `secret_names` includes
   `WORKSPACE_LLM_API_KEY`; synthetic + eight switches false.
7. Install 0400 files; `data` → `prepare` → `run`.
8. `/ready` after DB prepare, secrets loaded, BASE satisfied, `#381`
   availability true for the configured prod host, DNS or local checks OK;
   `/version.json` shows reviewed commit.

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

- [ ] Agents: runbook PR green; `#377` and `#381` watched
- [ ] Sitting 1: plan-hash yes → `#356` apply → IP recorded → Clerk public values sent
- [ ] Between: agent prep only (no secrets, no staging)
- [ ] Sitting 2: KV names pasted → mode-600 passwords → disk-format yes → DNS proxy off → continue-prep yes
- [ ] After 14:30: host Postgres/Redis → secrets install
- [ ] §4.1 STOP check: `WORKSPACE_LLM_API_KEY` reference is `oai-cbot-prd-*` only (no CosmasCode/staging); else rollback
- [ ] §4.2 STOP check: iPhone + web embed exactly `https://api.beta.cosmas.ai` (no staging); else rollback
- [ ] `#377` **and** `#381` merged before AI-on first start
- [ ] Account-delete vault `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET` (#356 README line 191)
- [ ] Flags per §9 (b) → `/ready` + `version.json`
- [ ] Eight switches false; synthetic only; staging untouched; no CosmasCode key in prod
