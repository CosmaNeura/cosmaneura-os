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
| 1 | Key Vault secret pastes (**names only** — §4): temporary public-access window from Johns own `/32`, set via `--file`. **John only, §4.1:** paste Step A fence → **pause** → rotate/load fence → **pause** → Step B fence (names/tags only) **inside this window**. Then restore `publicNetworkAccess=Disabled` and empty `ipRules`. **If interrupted:** restore Disabled + empty `ipRules` first, then verify by printing the whole `ipRules` list (§4.3). Agents never rotate or load. | 25 | **"yes, KV secrets loaded and public access disabled"** |
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

**Shell rule (N1):** `set -e` is inert inside a function/subshell invoked as
`if ! fn`. Every check must be chained with `|| return 1` (or run the whole
block as `bash -c 'set -euo pipefail; …'` / a script file where `-e` is live).
Do not rely on bare `test` / `[[` mid-body. Do not use bare `exit` (keeps the
interactive shell open).

**Mac paste rule (H-A / N2):** default macOS zsh has `interactivecomments`
off, so `#` is not a comment at the prompt. Every pasteable fence below has
**no `#` lines and no apostrophes inside the fence**. Paste into bash 3.2+ or
default zsh. Instructions live outside the fences. Split Step A, load, and
Step B into three fences with an explicit pause between them so Step B does
not run before the load.

**Operator smoke (before trusting):** for each function below, feed one
deliberately wrong input (wrong path, empty `ACCOUNT_ID`, Enabled vault, wrong
origin) and confirm it STOPs before using it on real artifacts.

#### Sitting 2 (John) — Step A, pause, load, pause, Step B (never `secret show`)

John only. Inside the temporary public-access window, **before** restoring
`Disabled`. **Shell:** bash 3.2+ or default macOS zsh (no `mapfile`). Agents
never run the write. Set `PROD_KV_NAME` / `RG` to the applied prod names first
(`PROD_KV_NAME` must match `^kv-cbot-prd-`).

**Fence 1 — Step A** (resolve exactly one prod OpenAI account; print the
account resource id — not a secret):

```bash
PROD_KV_NAME='kv-cbot-prd-REPLACE'
RG='rg-cosmabot-prod-eus2-01'
cosmabot_llm_kv_step_a_resolve_account() {
  command -v az >/dev/null || return 1
  command -v jq >/dev/null || return 1
  printf '%s' "$PROD_KV_NAME" | grep -Eq '^kv-cbot-prd-' || return 1
  OAI_COUNT=$(az cognitiveservices account list \
    --resource-group "$RG" \
    --query "length([?kind=='OpenAI'])" -o tsv) || return 1
  test "$OAI_COUNT" = "1" || return 1
  OAI_NAME=$(az cognitiveservices account list \
    --resource-group "$RG" \
    --query "[?kind=='OpenAI'].name | [0]" -o tsv) || return 1
  printf '%s' "$OAI_NAME" | grep -Eq '^oai-cbot-prd-[a-z0-9]{6,10}$' || return 1
  ACCOUNT_ID=$(az cognitiveservices account show \
    --resource-group "$RG" \
    --name "$OAI_NAME" \
    --query id -o tsv) || return 1
  test -n "$ACCOUNT_ID" || return 1
  printf '%s\n' "$ACCOUNT_ID"
}
ACCOUNT_ID=$(cosmabot_llm_kv_step_a_resolve_account) || {
  echo "STOP: Step A failed - no usable oai-cbot-prd account id"
  false
}
echo "source-account tag value (account resource id, not a secret): $ACCOUNT_ID"
```

**Pause here.** Do not paste Fence 3 yet. Rotate the provider key on that
OpenAI account. Put the new key in a local file on the operator Mac (never
paste the secret value into chat). Then paste Fence 2 only.

**Fence 2 — load** (John only; replace the file path):

```bash
az keyvault secret set \
  --vault-name "$PROD_KV_NAME" \
  --name WORKSPACE-LLM-API-KEY \
  --file /path/to/rotated-key-file \
  --tags "source-account=${ACCOUNT_ID}"
```

**Pause here.** Confirm the set command exited 0. Then paste Fence 3.

**Fence 3 — Step B** (metadata only; never `az keyvault secret show`):

```bash
cosmabot_llm_kv_step_b_verify_tag() {
  command -v az >/dev/null || return 1
  command -v jq >/dev/null || return 1
  test -n "${ACCOUNT_ID:-}" || return 1
  META_JSON=$(az keyvault secret list \
    --vault-name "$PROD_KV_NAME" \
    --query "[?name=='WORKSPACE-LLM-API-KEY'].{name:name,id:id,tags:tags}" -o json) || return 1
  test "$(printf '%s' "$META_JSON" | jq -er 'length')" = "1" || return 1
  test "$(printf '%s' "$META_JSON" | jq -er '.[0].name')" = "WORKSPACE-LLM-API-KEY" || return 1
  TAGGED=$(printf '%s' "$META_JSON" | jq -er '.[0].tags["source-account"] // empty') || return 1
  test -n "$TAGGED" || return 1
  test "$TAGGED" = "$ACCOUNT_ID" || return 1
}
cosmabot_llm_kv_step_b_verify_tag || {
  echo "STOP: Step B failed - source-account tag missing or not equal to Step A id; close vault per section 4.3"
  false
}
```

Then restore `publicNetworkAccess=Disabled` and empty `ipRules` (Sitting 2
gate). If the session is interrupted, jump to §4.3 first.

#### After host install (when secrets-transport ticket/PR exists) — file name/mode only

**Shell:** bash on the Linux VM (`stat -c`). Chain every check with `|| return 1`.

```bash
cosmabot_stop_llm_host_files() {
  test -n "${RELEASE_ID:-}" || return 1
  for role in api worker; do
    f="/etc/cosmabot/runtime/${RELEASE_ID}/${role}/WORKSPACE_LLM_API_KEY"
    test -f "$f" || return 1
    test "$(stat -c '%a' "$f")" = "400" || return 1
  done
}
cosmabot_stop_llm_host_files || {
  echo "STOP: host WORKSPACE_LLM_API_KEY missing or not mode 0400"
  false
}
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
Feed the auth header from a **file**, never argv / process list.

```bash
cosmabot_stop_llm_http_status() {
  command -v curl >/dev/null || return 1
  test -n "${WORKSPACE_LLM_ENDPOINT:-}" || return 1
  test -n "${RELEASE_ID:-}" || return 1
  KEYFILE="/etc/cosmabot/runtime/${RELEASE_ID}/api/WORKSPACE_LLM_API_KEY"
  test -f "$KEYFILE" || return 1
  ENDPOINT=$WORKSPACE_LLM_ENDPOINT
  printf '%s' "$ENDPOINT" | grep -Eq '^https://oai-cbot-prd-[a-z0-9]{6,10}\.openai\.azure\.com/openai/v1$' || return 1
  HDR=$(mktemp) || return 1
  trap 'rm -f "$HDR"' EXIT INT
  { printf 'api-key: '; cat "$KEYFILE"; printf '\n'; } >"$HDR" || return 1
  set +x
  STATUS=$(curl -sS -o /dev/null -w '%{http_code}' \
    --connect-timeout 10 --max-time 60 \
    -H 'Content-Type: application/json' \
    -H @"$HDR" \
    -d '{"model":"gpt-4.1-dzus","messages":[{"role":"user","content":"ping"}],"max_tokens":1}' \
    "${ENDPOINT}/chat/completions") || return 1
  rm -f "$HDR"
  trap - EXIT INT
  test "$STATUS" = "200" || return 1
}
cosmabot_stop_llm_http_status || {
  echo "STOP: prod OpenAI HTTP status proof failed (want 200; 401 means foreign key) — roll back AI-on"
  false
}
```

### 4.2 Deploy-time STOP — production bundles embed `https://api.beta.cosmas.ai`

**When:** before admitting the production-review iPhone / web build (and before
AI-on first start).

**Primary proof (exact equality):**

- iPhone `Info.plist`: `CosmasNativeIdentity.apiOrigin` =
  `https://api.beta.cosmas.ai`
- iPhone `Info.plist`: `CosmasNativeIdentity.frontendOrigin` (Clerk issuer) =
  `https://clerk.beta.cosmas.ai`
- iPhone `Info.plist`: `CosmasNativeIdentity.publishableKey` equals the Sitting
  1 public publishable key (`pk_live_…` only; never a secret)
- `web-build-arguments.json`: `VITE_WORKSPACE_HOSTED_API_ORIGIN` and
  `VITE_CLERK_PUBLISHABLE_KEY`
- `web-build-env.json`: both `VITE_API_BASE` and
  `VITE_WORKSPACE_HOSTED_API_ORIGIN`, plus `VITE_CLERK_PUBLISHABLE_KEY`

**Secondary scan (configured staging API origins only):** refuse
`https://api.staging.`, `https://enrollment-api.staging.`, and
`https://api.<x>.staging.` under the scanned roots. Do **not** substring-match
`staging.cosmas.ai` or `accounts.dev` (Swift/Clerk source literals would
false-stop a real `CosmaBot.app`).

**iPhone scan scope (H-B):** scan **only** `Info.plist` (via `plutil` exact
extracts) and the embedded web assets directory `$APP/public` (Capacitor
`webDir`). Do **not** scan the whole `.app` tree or Mach-O binaries.

Confirmed in-repo artifact names (`scripts/prepare-workspace-identity.mjs`,
`docs/beta/WEB_RELEASE.md`, `apps/capture/ios/App/App/capacitor.config.json`):

| File | Path | Keys checked |
| --- | --- | --- |
| `Info.plist` | inside reviewed `.app` | `CosmasNativeIdentity.apiOrigin`, `.frontendOrigin`, `.publishableKey` |
| `$APP/public` | Capacitor web assets only | staging API origin forms (scan) |
| `web-build-arguments.json` | prepare output / `/protected/ephemeral/…` | `VITE_WORKSPACE_HOSTED_API_ORIGIN`, `VITE_CLERK_PUBLISHABLE_KEY` |
| `web-build-env.json` | same prepare output | `VITE_API_BASE`, `VITE_WORKSPACE_HOSTED_API_ORIGIN`, `VITE_CLERK_PUBLISHABLE_KEY` |

**Shell:** bash 3.2+ or default macOS zsh; chain every check with `|| return 1`.
Pasteable fence has no `#` comments and no apostrophes. Set
`EXPECTED_CLERK_PUBLISHABLE_KEY` from Sitting 1 public values first (no
secrets).

```bash
WANT='https://api.beta.cosmas.ai'
EXPECTED_CLERK_ISSUER='https://clerk.beta.cosmas.ai'
test -n "${EXPECTED_CLERK_PUBLISHABLE_KEY:-}" || {
  echo "STOP: set EXPECTED_CLERK_PUBLISHABLE_KEY from Sitting 1 public values"
  false
}
printf '%s' "$EXPECTED_CLERK_PUBLISHABLE_KEY" | grep -Eq '^pk_live_' || {
  echo "STOP: publishable key must be pk_live_ public value"
  false
}
cosmabot_scan_forbidden_origins() {
  root=$1
  test -d "$root" || return 1
  if ! command -v rg >/dev/null 2>&1 && ! command -v /usr/bin/grep >/dev/null 2>&1; then
    echo "STOP: need rg or /usr/bin/grep"; return 1
  fi
  _hit() {
    if command -v rg >/dev/null 2>&1; then
      rg -a --no-ignore --hidden -q "$1" "$root"
    else
      /usr/bin/grep -rE "$1" "$root" >/dev/null
    fi
  }
  if _hit 'https://api\.staging\.'; then
    echo "STOP: https://api.staging. under $root"; return 1
  fi
  if _hit 'https://enrollment-api\.staging\.'; then
    echo "STOP: https://enrollment-api.staging. under $root"; return 1
  fi
  if _hit 'https://api\.[^/[:space:]]+\.staging\.'; then
    echo "STOP: https://api.<x>.staging. under $root"; return 1
  fi
  return 0
}
cosmabot_stop_iphone_api_origin() {
  APP=$1
  command -v /usr/bin/plutil >/dev/null || return 1
  test -d "$APP" || return 1
  test -f "$APP/Info.plist" || return 1
  WEB_ASSETS="$APP/public"
  test -d "$WEB_ASSETS" || return 1
  ORIGIN=$(/usr/bin/plutil -extract CosmasNativeIdentity.apiOrigin raw -o - "$APP/Info.plist") || return 1
  test "$ORIGIN" = "$WANT" || return 1
  ISSUER=$(/usr/bin/plutil -extract CosmasNativeIdentity.frontendOrigin raw -o - "$APP/Info.plist") || return 1
  test "$ISSUER" = "$EXPECTED_CLERK_ISSUER" || return 1
  PK=$(/usr/bin/plutil -extract CosmasNativeIdentity.publishableKey raw -o - "$APP/Info.plist") || return 1
  test "$PK" = "$EXPECTED_CLERK_PUBLISHABLE_KEY" || return 1
  cosmabot_scan_forbidden_origins "$WEB_ASSETS" || return 1
}
cosmabot_stop_web_api_origin() {
  WEB_ROOT=$1
  ARGS=${2:-"$WEB_ROOT/../web-build-arguments.json"}
  ENVJSON=${3:-"$WEB_ROOT/../web-build-env.json"}
  command -v jq >/dev/null || return 1
  test -d "$WEB_ROOT" || return 1
  if command -v rg >/dev/null 2>&1; then
    rg -aF --no-ignore --hidden -q "$WANT" "$WEB_ROOT" || return 1
  else
    command -v /usr/bin/grep >/dev/null || return 1
    /usr/bin/grep -rF "$WANT" "$WEB_ROOT" >/dev/null || return 1
  fi
  cosmabot_scan_forbidden_origins "$WEB_ROOT" || return 1
  test -f "$ARGS" || return 1
  test "$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ARGS")" = "$WANT" || return 1
  test "$(jq -er '.VITE_CLERK_PUBLISHABLE_KEY' "$ARGS")" = "$EXPECTED_CLERK_PUBLISHABLE_KEY" || return 1
  test -f "$ENVJSON" || return 1
  jq -e --arg want "$WANT" --arg pk "$EXPECTED_CLERK_PUBLISHABLE_KEY" '
    (.VITE_API_BASE | type == "string" and length > 0 and . == $want)
    and (.VITE_WORKSPACE_HOSTED_API_ORIGIN | type == "string" and length > 0 and . == $want)
    and (.VITE_CLERK_PUBLISHABLE_KEY | type == "string" and length > 0 and . == $pk)
  ' "$ENVJSON" >/dev/null || return 1
}
```

After defining the functions, run one wrong-path smoke, then the real
artifacts (paths outside the fence so zsh paste stays clean):

1. `cosmabot_stop_iphone_api_origin /path/to/wrong.app` must STOP
2. `cosmabot_stop_iphone_api_origin /path/to/CosmaBot.app` must pass
3. `cosmabot_stop_web_api_origin /path/to/reviewed-web-dist` must pass

#### Baseline from a known-good production build (N3)

Before trusting candidates, record a baseline from one known-good
production-review build (public values only). Store it outside the repo
(example path `/protected/ephemeral/prod-bundle-baseline.json`):

```bash
cosmabot_record_bundle_baseline() {
  APP=$1
  WEB_ROOT=$2
  OUT=$3
  ARGS=${4:-"$WEB_ROOT/../web-build-arguments.json"}
  ENVJSON=${5:-"$WEB_ROOT/../web-build-env.json"}
  command -v jq >/dev/null || return 1
  command -v /usr/bin/plutil >/dev/null || return 1
  test -f "$APP/Info.plist" || return 1
  test -d "$APP/public" || return 1
  test -f "$ARGS" || return 1
  test -f "$ENVJSON" || return 1
  jq -n \
    --arg api "$(/usr/bin/plutil -extract CosmasNativeIdentity.apiOrigin raw -o - "$APP/Info.plist")" \
    --arg issuer "$(/usr/bin/plutil -extract CosmasNativeIdentity.frontendOrigin raw -o - "$APP/Info.plist")" \
    --arg pk "$(/usr/bin/plutil -extract CosmasNativeIdentity.publishableKey raw -o - "$APP/Info.plist")" \
    --arg wapi "$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ARGS")" \
    --arg wpk "$(jq -er '.VITE_CLERK_PUBLISHABLE_KEY' "$ARGS")" \
    --arg eapi "$(jq -er '.VITE_API_BASE' "$ENVJSON")" \
    --arg eorigin "$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ENVJSON")" \
    --arg epk "$(jq -er '.VITE_CLERK_PUBLISHABLE_KEY' "$ENVJSON")" \
    '{apiOrigin:$api,clerkIssuer:$issuer,publishableKey:$pk,webBuildArguments:{VITE_WORKSPACE_HOSTED_API_ORIGIN:$wapi,VITE_CLERK_PUBLISHABLE_KEY:$wpk},webBuildEnv:{VITE_API_BASE:$eapi,VITE_WORKSPACE_HOSTED_API_ORIGIN:$eorigin,VITE_CLERK_PUBLISHABLE_KEY:$epk}}' >"$OUT" || return 1
  test "$(jq -er '.apiOrigin' "$OUT")" = "https://api.beta.cosmas.ai" || return 1
  test "$(jq -er '.clerkIssuer' "$OUT")" = "https://clerk.beta.cosmas.ai" || return 1
}
cosmabot_compare_bundle_to_baseline() {
  APP=$1
  WEB_ROOT=$2
  BASELINE=$3
  ARGS=${4:-"$WEB_ROOT/../web-build-arguments.json"}
  ENVJSON=${5:-"$WEB_ROOT/../web-build-env.json"}
  test -f "$BASELINE" || return 1
  cosmabot_stop_iphone_api_origin "$APP" || return 1
  cosmabot_stop_web_api_origin "$WEB_ROOT" "$ARGS" "$ENVJSON" || return 1
  test "$(/usr/bin/plutil -extract CosmasNativeIdentity.apiOrigin raw -o - "$APP/Info.plist")" = "$(jq -er '.apiOrigin' "$BASELINE")" || return 1
  test "$(/usr/bin/plutil -extract CosmasNativeIdentity.frontendOrigin raw -o - "$APP/Info.plist")" = "$(jq -er '.clerkIssuer' "$BASELINE")" || return 1
  test "$(/usr/bin/plutil -extract CosmasNativeIdentity.publishableKey raw -o - "$APP/Info.plist")" = "$(jq -er '.publishableKey' "$BASELINE")" || return 1
  test "$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ARGS")" = "$(jq -er '.webBuildArguments.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$BASELINE")" || return 1
  test "$(jq -er '.VITE_CLERK_PUBLISHABLE_KEY' "$ARGS")" = "$(jq -er '.webBuildArguments.VITE_CLERK_PUBLISHABLE_KEY' "$BASELINE")" || return 1
  test "$(jq -er '.VITE_API_BASE' "$ENVJSON")" = "$(jq -er '.webBuildEnv.VITE_API_BASE' "$BASELINE")" || return 1
  test "$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ENVJSON")" = "$(jq -er '.webBuildEnv.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$BASELINE")" || return 1
  test "$(jq -er '.VITE_CLERK_PUBLISHABLE_KEY' "$ENVJSON")" = "$(jq -er '.webBuildEnv.VITE_CLERK_PUBLISHABLE_KEY' "$BASELINE")" || return 1
}
```

Do not ship or admit a candidate that fails the STOP checks or the baseline
compare. Re-record the baseline only when John accepts a new known-good build.

### 4.3 Interrupted Key Vault access window

If Sitting 2 is interrupted while the vault is open to the operator `/32`:

1. **First:** restore `publicNetworkAccess=Disabled` and empty `ipRules`
   (John only; use the `#356` README restore commands for the prod vault).
2. **Then verify** by printing the **whole** `ipRules` list (and access flag).

**Shell:** bash 3.2+ or default macOS zsh. Fence has no `#` comments.

```bash
cosmabot_verify_kv_closed() {
  command -v az >/dev/null || return 1
  test -n "${PROD_KV_NAME:-}" || return 1
  az keyvault show --name "$PROD_KV_NAME" \
    --query "{publicNetworkAccess:properties.publicNetworkAccess,ipRules:properties.networkAcls.ipRules}" \
    -o json || return 1
  ACCESS=$(az keyvault show --name "$PROD_KV_NAME" \
    --query properties.publicNetworkAccess -o tsv) || return 1
  test "$ACCESS" = "Disabled" || return 1
  COUNT=$(az keyvault show --name "$PROD_KV_NAME" \
    --query "length(properties.networkAcls.ipRules)" -o tsv) || return 1
  test "$COUNT" = "0" || return 1
}
cosmabot_verify_kv_closed || {
  echo "STOP: vault still open or ipRules not empty - fix before continuing"
  false
}
```

Do not continue Sitting 2 secret work until that verify passes.

### 4.4 Mac-side fence syntax proof (H-A)

Every pasteable Mac-side fence in §4.1–§4.3 must parse under both `bash -n`
and `zsh -n` (and under zsh with `interactivecomments` unset). Proof commands
and results are recorded when this runbook revision is authored; re-run after
editing those fences:

```text
bash -n fence1-step-a.sh
bash -n fence2-load.sh
bash -n fence3-step-b.sh
bash -n fence-bundle-checks.sh
bash -n fence-kv-closed.sh
zsh -f -c 'unsetopt interactivecomments; zsh -n fence1-step-a.sh'
zsh -f -c 'unsetopt interactivecomments; zsh -n fence2-load.sh'
zsh -f -c 'unsetopt interactivecomments; zsh -n fence3-step-b.sh'
zsh -f -c 'unsetopt interactivecomments; zsh -n fence-bundle-checks.sh'
zsh -f -c 'unsetopt interactivecomments; zsh -n fence-kv-closed.sh'
```

Author proof results for this revision (all exit 0): listed in the PR body and
agent report for the commit that added §4.4.

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

**Order for first `/ready` (path 1) — same clock as §1 (Sitting 2 before
After-14:30 host work):**

1. Merge `#381` (§9 (a) decided) **and** `#377` (VM-runtime delete host-key
   mapping + production-review name allowance).
2. Sitting 1: apply `#356` (RG, VM, OpenAI `gpt-4.1-dzus`).
3. Sitting 2: John sets mode-600 passwords; pastes KV names including vault
   `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET`
   (#356 README line 191); §4.1 Step A print account id → rotate/load vault
   `WORKSPACE-LLM-API-KEY` with `source-account=<id>` → Step B list/compare
   before closing the vault.
4. Host prep (agents after Sitting 2 yes) — prod bootstrap retarget **BLOCKED**
   until a named ticket/PR exists. Matches §1 After 14:30 step 1.
5. **Install** mode-0400 secret files — **BLOCKED** until a named
   secrets-transport ticket/PR exists (do not invent a transport). Matches §1
   After 14:30 step 2.
6. **STOP checks** before AI-on: §4.1 (host files) and §4.2 (exact
   `https://api.beta.cosmas.ai` + Clerk issuer/publishable key on Info.plist /
   JSON; scan `$APP/public` only; refuse configured staging API origin forms;
   compare to known-good baseline). On failure: roll back; do not flip AI-on.
7. **Flag flip:** `WORKSPACE_LLM_BACKEND=azure_gpt41`;
   `WORKSPACE_LLM_USDZ_ENABLED=true` (required for `gpt-4.1-dzus` per `#356`
   README later LLM cutover item 3 / `config.py` reviewed-deployment set);
   `WORKSPACE_LLM_ENDPOINT` matching `#381` pattern
   `https://oai-cbot-prd-<suffix>.openai.azure.com/openai/v1`;
   `secret_names` includes `WORKSPACE_LLM_API_KEY`; synthetic + eight switches
   false.
8. **Render/start:** `data` → `prepare` → `run`.
9. §4.1 post-start HTTP status proof (200 only; auth header from file). Then
   `/ready` after DB prepare, secrets loaded, BASE satisfied, `#381`
   availability true for the configured prod host, DNS or local checks OK;
   `/version.json` shows reviewed commit.

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
- [ ] Sitting 2: §4.1 Fence 1 Step A → pause → Fence 2 load → pause → Fence 3 Step B → restore Disabled → mode-600 passwords → disk-format yes → DNS proxy off → continue-prep yes
- [ ] §4.3 if interrupted: restore Disabled + empty `ipRules`, print whole list, verify
- [ ] After 14:30 (= §9 (b) steps 4–9): install (BLOCKED) → checks → flag flip → render/start
- [ ] §4.1: split fences; no `#`/apostrophes in Mac fences; bash -n + zsh -n proof; HTTP 200 with header file
- [ ] §4.2: Info.plist + `$APP/public` only; exact Clerk issuer/pk; staging API forms only; baseline compare
- [ ] `#377` **and** `#381` merged before AI-on first start (`#377` for VM-runtime delete host-key mapping)
- [ ] Account-delete vault `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET` (#356 README line 191)
- [ ] Flags: `WORKSPACE_LLM_BACKEND=azure_gpt41`, `WORKSPACE_LLM_USDZ_ENABLED=true` → `/ready` + `version.json`
- [ ] Eight switches false; synthetic only; staging untouched; no CosmasCode key in prod
