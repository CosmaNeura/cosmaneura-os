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
| [`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377) | **Prerequisite for account-delete on prod.** Production on the `#356` VM runs `infra/beta/vm/runtime/entrypoint.py` (`runtime.secret_names` + host-file contract). `#377` adds the `CLERK_ACCOUNT_DELETION_SECRET` host-key mapping for that contract (vault `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET` → app `ACCOUNT_DELETE_CLERK_SECRET_KEY`). Also allows the process env name on production-review. No Key Vault write, no deploy from this docs ticket. | **Pending** (draft; merge before delete-secret mount / AI-on first start) |
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
| Agents | **BLOCKED** — prod host-bootstrap retarget (staging unit is `infra/beta/vm/runtime/cosmabot-staging.service`). Do not invent a transport or rename in place. Wait for a **named** ticket/PR that owns the prod unit/receipt retarget. |
| Agents | Advance [`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377) and [`#381`](https://github.com/CosmaNeura/cosmaneura-os/pull/381) toward green; do not merge without John |
| Agents | Prepare Key Vault **names** checklist and mode-600 password-file instructions for Sitting 2 (John loads; agents never rotate or load vault secrets) |
| Agents | No Run Command with secrets; no staging changes |

### Sitting 2 — John (~13:30–14:30 ET, ~60 min)

| # | John does | ~Min | Gate |
| --- | --- | --- | ---: |
| 1 | Key Vault secret pastes (**names only** — §4): temporary public-access window from John's own `/32`, set via `--file`. **John only:** rotate the prod OpenAI account key, then load vault object `WORKSPACE-LLM-API-KEY` with tag `source-account=<oai-cbot-prd account resource id>` (§4.1). Run the §4.1 Sitting-2 `az keyvault secret list` check **inside this window**. Then restore `publicNetworkAccess=Disabled` and empty `ipRules`. **If interrupted:** restore Disabled + empty `ipRules` first, then verify by printing the whole `ipRules` list (§4.3). Agents never rotate or load. | 25 | **"yes, KV secrets loaded and public access disabled"** |
| 2 | On the new VM as root: create distinct DB/Postgres/Redis passwords in a **mode-600** file he owns. **Never** via Azure Run Command | 10 | **"yes, mode-600 password file is on the host"** |
| 3 | Type **yes** to format the new empty data disk (prod IDs only) | 5 | **"yes, format the new empty data disk"** |
| 4 | Publish Cloudflare DNS (proxy **off**): `beta.cosmas.ai` A, `api.beta.cosmas.ai` A → public IP; `clerk.beta.cosmas.ai` CNAME from Clerk | 10 | — |
| 5 | Decide §9 (b) path (recommended: AI-on first start after endpoint-allow PR) and type **yes** for agents to continue host prep / data services after this sitting | 5 | **"yes, continue host prep"** |
| 6 | Optional: merge `#377` and/or `#381` when green (both required before AI-on first start) | 5 | Owner merge only |

### After 14:30 ET — agents (same day if John said yes)

Not John's hands-on. Still synthetic; still no staging. **One order** (same as §9 (b)):

1. Host bootstrap / Postgres 16 + Redis on the VM (§3) — only after the named
   prod bootstrap retarget ticket/PR exists (**BLOCKED** until then).
2. Install mode-0400 secret files from the names John pasted (§4) — **BLOCKED**
   until a **named** secrets-transport ticket/PR exists. Do not invent a
   transport. Run Command still must not carry secret values.
3. Deploy-time STOP checks: §4.1 (remaining host/post-start proofs) and §4.2
   (bundle API origins). On any mismatch: **STOP and roll back** — do not flip
   AI-on flags, do not start API/worker with model traffic.
4. When `#377` + `#381` are merged, checks pass, and John chose AI-on: flip
   runnable profile flags per §9 (b), including
   `WORKSPACE_LLM_BACKEND=azure_gpt41`, `WORKSPACE_LLM_USDZ_ENABLED=true`,
   and `WORKSPACE_LLM_API_KEY` in `secret_names` (**prod** account only).
5. Render + `start.sh data` → `prepare` → `run`.
6. §4.1 post-start value-free HTTP status proof against the prod OpenAI
   endpoint (status code only). Then `/ready`, `/version.json`, smoke, eight
   backend switches `'false'` (§8). Admit smoke only after John's separate yes.

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

**Production entrypoint:** the `#356` prod profile runs
`infra/beta/vm/runtime/entrypoint.py` (`runtime.secret_names` + host-file
contract). [`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377) is a
**prerequisite**: it adds the `CLERK_ACCOUNT_DELETION_SECRET` host-key mapping
for that contract (vault → host → app `ACCOUNT_DELETE_CLERK_SECRET_KEY`). Do
**not** invent a different vault object name. Do not mount until `#377` is
merged and John pastes the value himself. No Clerk secret values in this
runbook.

### Key Vault → host file names only

| Key Vault secret name | Host file name |
| --- | --- |
| `CLERK-SECRET-KEY` | `CLERK_SECRET_KEY` |
| `CLERK-ACCOUNT-DELETION-SECRET` | `CLERK_ACCOUNT_DELETION_SECRET` |
| `DATABASE-PASSWORD` | `DATABASE_PASSWORD` |
| `POSTGRES-PASSWORD` | `POSTGRES_PASSWORD` |
| `REDIS-PASSWORD` | `REDIS_PASSWORD` |
| `HUMAN-DEPLOY-EVIDENCE-REF` | `HUMAN_DEPLOY_EVIDENCE_REF` |
| `WORKSPACE-LLM-API-KEY` | `WORKSPACE_LLM_API_KEY` |

`WORKSPACE-LLM-API-KEY` is **John-only** in Sitting 2 (rotate + load with
`source-account` tag). Agents never rotate or load. Host install of the
`WORKSPACE_LLM_API_KEY` file waits on the named secrets-transport ticket/PR.

### Clerk public values (Sitting 1)

Issuer, JWKS URL, audience, authorized parties, organization ID, publishable
key. Secrets: Sitting 2 Key Vault only. (No Clerk values in this docs push.)

### 4.1 Deploy-time STOP — `WORKSPACE_LLM_API_KEY` is production OpenAI only

**Rule:** prove the key **came from** the production Azure OpenAI account
`oai-cbot-prd-*`, not CosmasCode and not staging. Check **names, resource ids,
tags, and HTTP status only**. Never print, log, or copy a secret **value**. On
mismatch: **STOP and roll back**.

Every STOP below is a real shell comparison that returns non-zero. Run the
functions/subshells as written so John's interactive shell is not closed by
`set -e` / `exit`.

#### Sitting 2 (John) — rotate, load with provenance tag, list (never `secret show`)

John only. Inside the temporary public-access window, **before** restoring
`Disabled`:

```bash
# Adjust names to the applied prod vault / RG. Agents never run these writes.
PROD_KV_NAME='kv-cbot-prd-REPLACE'   # must match ^kv-cbot-prd-
RG='rg-cosmabot-prod-eus2-01'

cosmabot_stop_llm_kv_provenance() (
  set -euo pipefail
  command -v az >/dev/null
  [[ "$PROD_KV_NAME" =~ ^kv-cbot-prd- ]]

  mapfile -t OAI_NAMES < <(
    az cognitiveservices account list \
      --resource-group "$RG" \
      --query "[?kind=='OpenAI'].name" -o tsv
  )
  test "${#OAI_NAMES[@]}" -eq 1
  [[ "${OAI_NAMES[0]}" =~ ^oai-cbot-prd-[a-z0-9]{6,10}$ ]]

  ACCOUNT_ID=$(az cognitiveservices account show \
    --resource-group "$RG" \
    --name "${OAI_NAMES[0]}" \
    --query id -o tsv)
  test -n "$ACCOUNT_ID"

  # John: rotate the provider key on that account first, then load via --file
  # with the provenance tag (path is on John's machine; never paste the value):
  #   az keyvault secret set \
  #     --vault-name "$PROD_KV_NAME" \
  #     --name WORKSPACE-LLM-API-KEY \
  #     --file /path/to/rotated-key-file \
  #     --tags "source-account=${ACCOUNT_ID}"
  #
  # Metadata only — never `az keyvault secret show` (that fetches the value).
  META_JSON=$(az keyvault secret list \
    --vault-name "$PROD_KV_NAME" \
    --query "[?name=='WORKSPACE-LLM-API-KEY'].{name:name,id:id,tags:tags}" -o json)
  test "$(jq -er 'length' <<<"$META_JSON")" -eq 1
  test "$(jq -er '.[0].name' <<<"$META_JSON")" = 'WORKSPACE-LLM-API-KEY'
  TAGGED=$(jq -er '.[0].tags["source-account"] // empty' <<<"$META_JSON")
  test -n "$TAGGED"
  test "$TAGGED" = "$ACCOUNT_ID"
)

if ! cosmabot_stop_llm_kv_provenance; then
  echo "STOP: WORKSPACE-LLM-API-KEY provenance failed — roll back; close vault per §4.3 before leaving"
  false
fi
```

Then restore `publicNetworkAccess=Disabled` and empty `ipRules` (Sitting 2
gate). If the session is interrupted, jump to §4.3 first.

#### After host install (when secrets-transport ticket/PR exists) — file name/mode only

```bash
cosmabot_stop_llm_host_files() (
  set -euo pipefail
  for role in api worker; do
    f="/etc/cosmabot/runtime/${RELEASE_ID}/${role}/WORKSPACE_LLM_API_KEY"
    test -f "$f"
    test "$(stat -c '%a' "$f")" = '400'
  done
)
if ! cosmabot_stop_llm_host_files; then
  echo "STOP: host WORKSPACE_LLM_API_KEY missing or not mode 0400"
  false
fi
```

Also confirm runnable public env (when AI-on is prepared) sets
`WORKSPACE_LLM_ENDPOINT` to the `#381` pattern
`https://oai-cbot-prd-[a-z0-9]{6,10}.openai.azure.com/openai/v1` and
`WORKSPACE_LLM_USDZ_ENABLED=true` — still no secret values.

#### After AI-on first start — value-free HTTP status proof from the VM

Record the **HTTP status code only** (never body, headers dump, or key value).
`200` continues; `401` or any other status is STOP (foreign / wrong key).
Operator supplies `WORKSPACE_LLM_ENDPOINT` from the reviewed **public** AI-on
profile (same string as `#381`); do not invent it from module base URL alone.

```bash
cosmabot_stop_llm_http_status() (
  set -euo pipefail
  command -v curl >/dev/null
  test -n "${WORKSPACE_LLM_ENDPOINT:-}"
  test -n "${RELEASE_ID:-}"
  KEYFILE="/etc/cosmabot/runtime/${RELEASE_ID}/api/WORKSPACE_LLM_API_KEY"
  test -f "$KEYFILE"
  ENDPOINT=$WORKSPACE_LLM_ENDPOINT
  [[ "$ENDPOINT" =~ ^https://oai-cbot-prd-[a-z0-9]{6,10}\.openai\.azure\.com/openai/v1$ ]]
  # Status code only; curl -o /dev/null discards the body. Do not enable -v/--trace.
  set +x
  STATUS=$(curl -sS -o /dev/null -w '%{http_code}' \
    --connect-timeout 10 --max-time 60 \
    -H 'Content-Type: application/json' \
    -H "api-key: $(cat "$KEYFILE")" \
    -d '{"model":"gpt-4.1-dzus","messages":[{"role":"user","content":"ping"}],"max_tokens":1}' \
    "${ENDPOINT}/chat/completions")
  test "$STATUS" = '200'
)
if ! cosmabot_stop_llm_http_status; then
  echo "STOP: prod OpenAI HTTP status proof failed (want 200; 401 means foreign key) — roll back AI-on"
  false
fi
```

### 4.2 Deploy-time STOP — production bundles embed `https://api.beta.cosmas.ai`

**When:** before admitting the production-review iPhone / web build (and before
AI-on first start). **STOP** if the embedded API origin is not exactly
`https://api.beta.cosmas.ai`, or if `staging.cosmas.ai` / `accounts.dev` appear.

Confirmed in-repo artifact names (`scripts/prepare-workspace-identity.mjs`,
`docs/beta/WEB_RELEASE.md`):

| File | Path (prepare output / protected builder) | API-origin keys |
| --- | --- | --- |
| `web-build-arguments.json` | prepare output root; protected example `/protected/ephemeral/web-build-arguments.json` | `VITE_WORKSPACE_HOSTED_API_ORIGIN` (this file does **not** carry `VITE_API_BASE`) |
| `web-build-env.json` | same prepare output (`web` client env) | **both** `VITE_API_BASE` and `VITE_WORKSPACE_HOSTED_API_ORIGIN` must be present and equal |

Run inside a function/subshell so John's interactive shell never exits:

```bash
WANT='https://api.beta.cosmas.ai'

cosmabot_scan_forbidden_origins() (
  set -euo pipefail
  root=$1
  test -d "$root"
  if command -v rg >/dev/null 2>&1; then
    if rg -aF --no-ignore --hidden -q 'staging.cosmas.ai' "$root"; then
      echo "STOP: staging.cosmas.ai under $root"; return 1
    fi
    if rg -aF --no-ignore --hidden -q 'accounts.dev' "$root"; then
      echo "STOP: accounts.dev under $root"; return 1
    fi
  else
    command -v /usr/bin/grep >/dev/null
    if /usr/bin/grep -rF 'staging.cosmas.ai' "$root" >/dev/null; then
      echo "STOP: staging.cosmas.ai under $root"; return 1
    fi
    if /usr/bin/grep -rF 'accounts.dev' "$root" >/dev/null; then
      echo "STOP: accounts.dev under $root"; return 1
    fi
  fi
)

cosmabot_stop_iphone_api_origin() (
  set -euo pipefail
  APP=$1
  command -v /usr/bin/plutil >/dev/null
  test -d "$APP"
  test -f "$APP/Info.plist"
  ORIGIN=$(/usr/bin/plutil -extract CosmasNativeIdentity.apiOrigin raw -o - "$APP/Info.plist")
  test "$ORIGIN" = "$WANT"
  # Whole .app tree includes Info.plist and embedded web assets (www/public/…).
  cosmabot_scan_forbidden_origins "$APP"
)

cosmabot_stop_web_api_origin() (
  set -euo pipefail
  WEB_ROOT=$1
  ARGS=${2:-"$WEB_ROOT/../web-build-arguments.json"}
  ENVJSON=${3:-"$WEB_ROOT/../web-build-env.json"}
  command -v jq >/dev/null
  test -d "$WEB_ROOT"
  if command -v rg >/dev/null 2>&1; then
    rg -aF --no-ignore --hidden -q "$WANT" "$WEB_ROOT"
  else
    command -v /usr/bin/grep >/dev/null
    /usr/bin/grep -rF "$WANT" "$WEB_ROOT" >/dev/null
  fi
  cosmabot_scan_forbidden_origins "$WEB_ROOT"

  test -f "$ARGS"
  test "$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ARGS")" = "$WANT"

  # Both keys required present and equal (companion env from prepare-workspace-identity).
  test -f "$ENVJSON"
  jq -e --arg want "$WANT" '
    (.VITE_API_BASE | type == "string" and length > 0 and . == $want)
    and (.VITE_WORKSPACE_HOSTED_API_ORIGIN | type == "string" and length > 0 and . == $want)
  ' "$ENVJSON" >/dev/null
)

# Examples (reviewed artifacts only):
# if ! cosmabot_stop_iphone_api_origin /path/to/CosmaBot.app; then
#   echo "STOP: iPhone API origin check failed"; false
# fi
# if ! cosmabot_stop_web_api_origin /path/to/reviewed-web-dist; then
#   echo "STOP: web API origin check failed"; false
# fi
```

Do not ship or admit a candidate that fails either check.

### 4.3 Interrupted Key Vault access window

If Sitting 2 is interrupted while the vault is open to John's `/32`:

1. **First:** restore `publicNetworkAccess=Disabled` and empty `ipRules`
   (John only; use the `#356` README restore commands for the prod vault).
2. **Then verify** by printing the **whole** `ipRules` list (and access flag):

```bash
cosmabot_verify_kv_closed() (
  set -euo pipefail
  command -v az >/dev/null
  az keyvault show --name "$PROD_KV_NAME" \
    --query "{publicNetworkAccess:properties.publicNetworkAccess,ipRules:properties.networkAcls.ipRules}" \
    -o json
  ACCESS=$(az keyvault show --name "$PROD_KV_NAME" \
    --query properties.publicNetworkAccess -o tsv)
  test "$ACCESS" = 'Disabled'
  COUNT=$(az keyvault show --name "$PROD_KV_NAME" \
    --query 'length(properties.networkAcls.ipRules)' -o tsv)
  test "$COUNT" = '0'
)
if ! cosmabot_verify_kv_closed; then
  echo "STOP: vault still open or ipRules not empty — fix before continuing"
  false
fi
```

Do not continue Sitting 2 secret work until that verify passes.

---

## 5. Azure OpenAI + `gpt-4.1-dzus`

Created in Sitting 1 apply when `enable_azure_openai: true`:

- `kind = "OpenAI"`, SKU `S0`, PE + `privatelink.openai.azure.com`
- Deployment `gpt-4.1-dzus`, model `gpt-4.1` / `2025-04-14`, DataZoneStandard
  capacity **1**
- John rotates provider-generated keys before loading vault
  `WORKSPACE-LLM-API-KEY` with `source-account=<account id>` (Sitting 2 / §4.1)
- Shared CosmasCode / staging keys must never enter prod

Runnable traffic needs `#381` merged + §9 (b) flag flips including
`WORKSPACE_LLM_USDZ_ENABLED=true` (and `#377` before delete-key mount / AI-on
first start prerequisites).

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
[`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377)
(`CLERK_ACCOUNT_DELETION_SECRET` mapping for
`infra/beta/vm/runtime/entrypoint.py` host-file contract).

**Fork:**

1. **Recommended today:** AI-on first start only after `#381` + `#377` merge;
   treat `#356` disabled profile as foundation-only.
2. **Alternative:** separate runtime PR allowing AI-off first start (not `#356`).

**Order for first `/ready` (path 1) — same as §1 After 14:30:**

1. Merge `#381` (§9 (a) decided) **and** `#377` (VM-runtime delete host-key
   mapping + production-review name allowance).
2. Sitting 1: apply `#356` (RG, VM, OpenAI `gpt-4.1-dzus`).
3. Host prep (agents after Sitting 2 yes) — prod bootstrap retarget **BLOCKED**
   until a named ticket/PR exists.
4. Sitting 2: John sets mode-600 passwords; pastes KV names including vault
   `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET`
   (#356 README line 191) and vault `WORKSPACE-LLM-API-KEY` with
   `source-account=<oai-cbot-prd account id>` (§4.1 list check before closing
   the vault).
5. **Install** mode-0400 secret files — **BLOCKED** until a named
   secrets-transport ticket/PR exists (do not invent a transport).
6. **STOP checks** before AI-on: §4.1 (provenance + host files) and §4.2
   (iPhone + web embed exactly `https://api.beta.cosmas.ai`; refuse
   `staging.cosmas.ai` / `accounts.dev`). On failure: roll back; do not flip
   AI-on.
7. **Flag flip:** `WORKSPACE_LLM_BACKEND=azure_gpt41`;
   `WORKSPACE_LLM_USDZ_ENABLED=true` (required for `gpt-4.1-dzus` per `#356`
   README later LLM cutover item 3 / `config.py` reviewed-deployment set);
   `WORKSPACE_LLM_ENDPOINT` matching `#381` pattern
   `https://oai-cbot-prd-<suffix>.openai.azure.com/openai/v1`;
   `secret_names` includes `WORKSPACE_LLM_API_KEY`; synthetic + eight switches
   false.
8. **Render/start:** `data` → `prepare` → `run`.
9. §4.1 post-start HTTP status proof (200 only). Then `/ready` after DB
   prepare, secrets loaded, BASE satisfied, `#381` availability true for the
   configured prod host, DNS or local checks OK; `/version.json` shows
   reviewed commit.

### Other gaps

1. **BLOCKED:** named secrets-transport ticket/PR owns host 0400 install
   (vault is closed after Sitting 2; Run Command must not carry values). Do
   not invent a transport in this runbook.
2. **BLOCKED:** named prod host-bootstrap retarget ticket/PR (staging unit is
   `cosmabot-staging.service`). Do not invent a rename here.
3. Endpoint kind: classic vs Foundry recreate — §7.
4. Password-name acceptance on prod entrypoint still unverified per `#356`
   guard-hardening notes — prove before admitting testers.
5. `#356` OpenAI is first-apply-only if omitted from Sitting 1 inputs.
6. TestFlight blocked until Alfred + John.
7. Staging ticket files named in the original ask were not in this checkout;
   this doc mirrors `release-r7` pointer-switch + in-repo host/runtime READMEs.

---

## 10. Today's checklist (Fri 13 Nov)

- [ ] Agents: runbook PR green; `#377` and `#381` watched
- [ ] Sitting 1: plan-hash yes → `#356` apply → IP recorded → Clerk public values sent
- [ ] Between: agent prep only (no secrets, no staging); bootstrap retarget **BLOCKED** until named ticket/PR
- [ ] Sitting 2: KV names pasted (incl. `WORKSPACE-LLM-API-KEY` + `source-account` tag) → §4.1 list check → restore Disabled → mode-600 passwords → disk-format yes → DNS proxy off → continue-prep yes
- [ ] §4.3 if interrupted: restore Disabled + empty `ipRules`, print whole list, verify
- [ ] After 14:30 order: install (BLOCKED until named secrets-transport ticket/PR) → §4.1/§4.2 checks → flag flip → render/start
- [ ] §4.1: exactly one `oai-cbot-prd-*` account; tag equals account id; post-start HTTP 200 only
- [ ] §4.2: iPhone + web + `.app` assets; `web-build-arguments.json` + both keys in `web-build-env.json`
- [ ] `#377` **and** `#381` merged before AI-on first start (`#377` for VM-runtime delete host-key mapping)
- [ ] Account-delete vault `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET` (#356 README line 191)
- [ ] Flags: `WORKSPACE_LLM_BACKEND=azure_gpt41`, `WORKSPACE_LLM_USDZ_ENABLED=true` → `/ready` + `version.json`
- [ ] Eight switches false; synthetic only; staging untouched; no CosmasCode key in prod
