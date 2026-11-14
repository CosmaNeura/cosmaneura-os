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
`#356` (merged to `main`; foundation may still need Sitting 1 apply or
[`#383`](https://github.com/CosmaNeura/cosmaneura-os/pull/383) `--recover`).

**Target host:** `rg-cosmabot-prod-eus2-01`, `beta.cosmas.ai` /
`api.beta.cosmas.ai`.

---

## Pending prerequisites (app / recover — not this PR)

`#377` and `#381` are **Merged** on `main` (required for AI-on first start in
§9 (b)). `#383` is still required **before** any Sitting 1 recover apply of a
partial foundation (not an AI-on gate).

| PR | What it does | Status |
| --- | --- | --- |
| [`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377) | **Account-delete on prod.** Production on the `#356` VM runs `infra/beta/vm/runtime/entrypoint.py` (`runtime.secret_names` + host-file contract). `#377` adds the `CLERK_ACCOUNT_DELETION_SECRET` host-key mapping for that contract (vault `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET` → app `ACCOUNT_DELETE_CLERK_SECRET_KEY`). Also allows the process env name on production-review. | **Merged** |
| [`#381`](https://github.com/CosmaNeura/cosmaneura-os/pull/381) | **Decision (a) decided (CTO, 13 Nov).** Allows the exact production host pattern `https://oai-cbot-prd-[a-z0-9]{6,10}.openai.azure.com/openai/v1` and wires hosted chat (text and tools, including streaming) to the configured endpoint. Unusable configured endpoint → fail closed, never silent CosmasCode fallback. No endpoint set (staging) → unchanged. Model, deployment, and API version unchanged. | **Merged** |
| [`#383`](https://github.com/CosmaNeura/cosmaneura-os/pull/383) | **Prod foundation `--recover` mode.** CTO-approved recovery path when Sitting 1 first apply is partial (existing encrypted state / passphrase reused in place; ADD-ONLY; only `rg-cosmabot-prod-eus2-01` may pre-exist). Without `--recover`, first-apply refusals stay unchanged. Merge and use before a recover plan/apply; not a substitute for `#377` / `#381`. | **Pending** (draft; required before Sitting 1 recover apply) |

Do not merge or apply `#383` from this docs ticket. Agents may drive it to
green while John is in a sitting or between sittings; John merges.

---

## 0. Hard stops

| Forbidden in this prep ticket | Why |
| --- | --- |
| Merge this docs PR; re-apply foundation without a reviewed plan hash | Owner only; `#356` is already on `main` |
| Recover apply without [`#383`](https://github.com/CosmaNeura/cosmaneura-os/pull/383) `--recover` | Partial first apply needs the recover path |
| `tofu` / `terraform` plan or apply from this ticket | John's Mac / separate apply / `#383` recover |
| `az` write, Key Vault writes, DNS edits, Clerk changes | Owner / later tickets |
| Secret values in chat, git, run-command, terminal, or this doc | Names / ids / HTTP status only — never print a secret value |
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
| Agents | Keep this runbook draft green (`ci:full`); watch [`#383`](https://github.com/CosmaNeura/cosmaneura-os/pull/383) (`#377` / `#381` already Merged) | ongoing |
| Agents | Prep `#356` / `#383` review packet on John's Mac path (hashes, opt-in inputs with `enable_azure_openai: true`; recover plan if partial) — **do not apply** | 30–45 min |
| Agents | List secret **names** and Clerk public fields John will need (below) | 10 min |

### Sitting 1 — John (~11:15–12:30 ET, ~75 min)

Hands-on only. Exact order:

| # | John does | ~Min | Gate |
| --- | --- | --- | ---: |
| 1 | Sign in to Azure as `john@cosmaneura.com`; confirm subscription is the one that already has staging | 5 | — |
| 2 | Review `#356` first-apply plan **or** [`#383`](https://github.com/CosmaNeura/cosmaneura-os/pull/383) recover plan + cost on his Mac; type **yes** on the exact plan/summary hashes | 15 | **"yes" on plan hash** |
| 3 | Apply foundation (John only; `enable_azure_openai: true`). Fresh RG: first-apply path. Partial first apply: **only** via `#383` `--recover` (reuse encrypted state/passphrase; never regenerate) | 20 | Apply exits 0 |
| 4 | Confirm RG `rg-cosmabot-prod-eus2-01`, VM up, record public IP, OpenAI + `gpt-4.1-dzus` present | 10 | **"yes, apply looks complete"** |
| 5 | Create/finish **production Clerk** (not Cosmas, not staging): domain `clerk.beta.cosmas.ai`; origins `https://beta.cosmas.ai` + `capacitor://localhost`; JWT audience per 30 Oct list; one synthetic org + fake reviewer | 20 | — |
| 6 | Send agents **public** Clerk values only (issuer, JWKS URL, audience, authorized parties, org ID, publishable key) | 5 | — |

**John does not paste secrets in Sitting 1.** Stop after public Clerk values.

### Between sittings — agents (~12:30–13:30 ET)

| Who | Work |
| --- | --- |
| Agents | Read-only verify RG/VM/IP/OpenAI names; draft DNS record text (do not publish) |
| Agents | **BLOCKED** — prod host-bootstrap retarget (staging unit is `infra/beta/vm/runtime/cosmabot-staging.service`). Do not invent a transport or rename in place. Wait for a **named** ticket/PR that owns the prod unit/receipt retarget. |
| Agents | Advance [`#383`](https://github.com/CosmaNeura/cosmaneura-os/pull/383) toward green; do not merge without John (`#377` / `#381` already Merged) |
| Agents | Prepare Key Vault **names** checklist and mode-600 password-file instructions for Sitting 2 (John loads; agents never rotate or load vault secrets) |
| Agents | No Run Command with secrets; no staging changes |

### Sitting 2 — John (~13:30–14:30 ET, ~60 min)

| # | John does | ~Min | Gate |
| --- | --- | --- | ---: |
| 1 | Key Vault secret pastes (**names only** — §4): temporary public-access window from John's own `/32`. **John only, §4.1:** export `KEYFILE` once → paste Step A → **pause** → rotate wrapper (umask 077 + `pipefail` + `test -s`; **key1 only**) → Fence 2 load (`--output none`, `test -s`) → **pause** → Step B (tag proof; removes `$KEYFILE` on PASS and on STOP fail-safe) **inside this window**. Never print the key. Then restore `publicNetworkAccess=Disabled` and empty `ipRules`. **If interrupted/abandoned:** restore Disabled + empty `ipRules` first, then remove `$KEYFILE` (§4.3). Agents never rotate or load. | 25 | **"yes, KV secrets loaded and public access disabled"** |
| 2 | On the new VM as root: create distinct DB/Postgres/Redis passwords in a **mode-600** file he owns. **Never** via Azure Run Command | 10 | **"yes, mode-600 password file is on the host"** |
| 3 | Type **yes** to format the new empty data disk (prod IDs only) | 5 | **"yes, format the new empty data disk"** |
| 4 | Publish Cloudflare DNS (proxy **off**): `beta.cosmas.ai` A, `api.beta.cosmas.ai` A → public IP; `clerk.beta.cosmas.ai` CNAME from Clerk | 10 | — |
| 5 | Decide §9 (b) path (recommended: AI-on first start after endpoint-allow PR) and type **yes** for agents to continue host prep / data services after this sitting | 5 | **"yes, continue host prep"** |
| 6 | Optional: merge `#383` when green (recover path only; `#377` / `#381` already Merged) | 5 | Owner merge only |

### After 14:30 ET — agents (same day if John said yes)

Not John's hands-on. Still synthetic; still no staging. **One order** (same as §9 (b)):

1. Host bootstrap / Postgres 16 + Redis on the VM (§3) — only after the named
   prod bootstrap retarget ticket/PR exists (**BLOCKED** until then).
2. Install mode-0400 secret files from the names John pasted (§4) with
   `infra/beta/vm/host/secrets_transport.py` (T-PROD-3-SECRETS): workstation
   stage under `/32`, then §4.5 temporary SSH `/32` open → ssh-stdin install
   (no VM value staging) → close-and-verify (John, 14 Nov 2026 9:45am ET).
   Run Command must not carry secret values (host-key public fetch only).
3. Deploy-time STOP checks: §4.1 (remaining host/post-start proofs) and §4.2
   (bundle API origins). On any mismatch: **STOP and roll back** — do not flip
   AI-on flags, do not start API/worker with model traffic.
4. When checks pass and John chose AI-on (`#377` + `#381` already Merged): flip
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

Per `#356` `infra/beta/vm/prod/README.md` on `main` (merged)
(**lines 188–191** of that file; table row at **line 191**):

| Key Vault secret name | Host file name | Services |
| --- | --- | --- |
| `CLERK-ACCOUNT-DELETION-SECRET` | `CLERK_ACCOUNT_DELETION_SECRET` | `api`, `worker` |

**Production entrypoint:** the `#356` prod profile runs
`infra/beta/vm/runtime/entrypoint.py` (`runtime.secret_names` + host-file
contract). [`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377) is
**Merged** and adds the `CLERK_ACCOUNT_DELETION_SECRET` host-key mapping for
that contract (vault → host → app `ACCOUNT_DELETE_CLERK_SECRET_KEY`). Do
**not** invent a different vault object name. Mount only after John pastes the
value himself. No Clerk secret values in this runbook.

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
`WORKSPACE_LLM_API_KEY` file (and the other §4 name-mapped secrets) uses
`infra/beta/vm/host/secrets_transport.py` (T-PROD-3-SECRETS): workstation
`--stage-from-vault` under John's vault `/32` window → §4.5 temporary SSH
`/32` open → ssh-stdin install (no VM value staging) → close-and-verify →
mode-0400 service-UID host files; Run Command refused for values (host-key
public fetch only); no Secrets Officer `az login` on the VM; no Bastion;
values never printed. Restore vault per §4.3; SSH close-and-verify per §4.5
(mandatory before any Terraform plan/apply).

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
**no `#` comment lines** (single-quoted strings and `${var#prefix}` expansions
are fine). Paste into bash 3.2+ or default zsh. Instructions live outside the
fences. Split Step A, rotate, load, and Step B into separate fences with an
explicit pause between them so Step B does not run before the load.

**Operator smoke (before trusting):** for each function below, feed one
deliberately wrong input (wrong path, empty `ACCOUNT_ID`, Enabled vault, wrong
origin) and confirm it STOPs before using it on real artifacts.

#### Sitting 2 (John) — Step A, pause, rotate, load, pause, Step B (never `secret show`)

John only. Inside the temporary public-access window, **before** restoring
`Disabled`. **Shell:** bash 3.2+ or default macOS zsh (no `mapfile`). Agents
never run the write. **Before any fence**, export these once in the shell (do
**not** put placeholder assignments or a second `KEYFILE=` inside fences):

- `PROD_KV_NAME` must match `^kv-cbot-prd-[a-z0-9]+$`
- `RG=rg-cosmabot-prod-eus2-01`
- `KEYFILE` = one private local path for the rotated key file (mode 0600 via
  `umask 077`; **no trailing newline**). Define it **once** here; fences only
  read `"$KEYFILE"`.

**Hard rule:** no step may print the production AI key or put it in shell
history. Never assign the key to a shell variable. Never use `printf` /
`echo` with the key. Every `az keyvault secret set` must use `--output none`.
Step A STOP reasons go to **stderr** so they are not captured into
`ACCOUNT_ID`. On any Step A failure, clear `ACCOUNT_ID`.

`ACCOUNT_ID` must match this full resource-id regex (anchored with `^` and
`$`) in Fence 1, rotate, Fence 2, and Step B:

`^/subscriptions/[^/]+/resourceGroups/rg-cosmabot-prod-eus2-01/providers/Microsoft\.CognitiveServices/accounts/oai-cbot-prd-[a-z0-9]{6,10}$`

**Fence 1 — Step A** (resolve exactly one prod OpenAI account; print the
account resource id on stdout only — not a secret). Capture, shape check, and
PASS all live inside a wrapper so a STOP never prints PASS:

```bash
cosmabot_llm_kv_step_a_resolve_account() {
  command -v az >/dev/null || {
    echo "STOP: Step A needs az" >&2
    return 1
  }
  command -v jq >/dev/null || {
    echo "STOP: Step A needs jq" >&2
    return 1
  }
  test -n "${PROD_KV_NAME:-}" || {
    echo "STOP: Step A PROD_KV_NAME unset - export applied vault name first" >&2
    return 1
  }
  test -n "${RG:-}" || {
    echo "STOP: Step A RG unset - export rg-cosmabot-prod-eus2-01 first" >&2
    return 1
  }
  printf '%s' "$PROD_KV_NAME" | grep -Eq '^kv-cbot-prd-[a-z0-9]+$' || {
    echo "STOP: Step A PROD_KV_NAME must match kv-cbot-prd-<suffix>" >&2
    return 1
  }
  OAI_COUNT=$(az cognitiveservices account list \
    --resource-group "$RG" \
    --query "length([?kind=='OpenAI'])" -o tsv) || {
    echo "STOP: Step A cognitiveservices list failed" >&2
    return 1
  }
  test "$OAI_COUNT" = "1" || {
    echo "STOP: Step A expected exactly one OpenAI account in RG" >&2
    return 1
  }
  OAI_NAME=$(az cognitiveservices account list \
    --resource-group "$RG" \
    --query "[?kind=='OpenAI'].name | [0]" -o tsv) || {
    echo "STOP: Step A OpenAI name query failed" >&2
    return 1
  }
  printf '%s' "$OAI_NAME" | grep -Eq '^oai-cbot-prd-[a-z0-9]{6,10}$' || {
    echo "STOP: Step A OpenAI name is not oai-cbot-prd-<suffix>" >&2
    return 1
  }
  RID=$(az cognitiveservices account show \
    --resource-group "$RG" \
    --name "$OAI_NAME" \
    --query id -o tsv) || {
    echo "STOP: Step A account id query failed" >&2
    return 1
  }
  printf '%s' "$RID" | grep -Eq '^/subscriptions/[^/]+/resourceGroups/rg-cosmabot-prod-eus2-01/providers/Microsoft\.CognitiveServices/accounts/oai-cbot-prd-[a-z0-9]{6,10}$' || {
    echo "STOP: Step A ACCOUNT_ID shape invalid" >&2
    return 1
  }
  printf '%s\n' "$RID"
}
cosmabot_llm_kv_step_a_run() {
  ACCOUNT_ID=$(cosmabot_llm_kv_step_a_resolve_account) || {
    echo "STOP: Step A failed - no usable oai-cbot-prd account id" >&2
    ACCOUNT_ID=
    return 1
  }
  printf '%s' "${ACCOUNT_ID:-}" | grep -Eq '^/subscriptions/[^/]+/resourceGroups/rg-cosmabot-prod-eus2-01/providers/Microsoft\.CognitiveServices/accounts/oai-cbot-prd-[a-z0-9]{6,10}$' || {
    echo "STOP: Step A ACCOUNT_ID shape invalid after capture" >&2
    ACCOUNT_ID=
    return 1
  }
  echo "PASS: Step A resolved account resource id"
  echo "source-account tag value (account resource id, not a secret): $ACCOUNT_ID"
  return 0
}
cosmabot_llm_kv_step_a_run || {
  echo "STOP: Step A failed" >&2
  ACCOUNT_ID=
  false
}
```

**Pause here.** Do not paste Fence 3 yet. Rotate with the wrapper below (uses
the already-exported `KEYFILE`; never reassigns it). Never `cat` / `echo` /
`printf` the file contents. Then paste Fence 2 only.

**key1 only (L-3):** this rotate regenerates and loads **`key1` only**. Azure
OpenAI keeps two account keys; Sitting 2 uses `key1` as the active value for
vault `WORKSPACE-LLM-API-KEY`. Leave **`key2` untouched** in this sitting so it
remains the prior/backup key for rollback if the new `key1` load fails. Rotate
and load `key2` only in a later sitting after the new `key1` is proven in use
(host HTTP proof / AI-on) and John schedules a second dual-key cutover — do not
regenerate both keys in the same sitting.

```bash
cosmabot_llm_kv_rotate_key() {
  test -n "${KEYFILE:-}" || {
    echo "STOP: rotate KEYFILE unset - export once before fences" >&2
    return 1
  }
  test -n "${RG:-}" || {
    echo "STOP: rotate RG unset" >&2
    return 1
  }
  test -n "${ACCOUNT_ID:-}" || {
    echo "STOP: rotate ACCOUNT_ID empty - run Fence 1 first" >&2
    return 1
  }
  printf '%s' "$ACCOUNT_ID" | grep -Eq '^/subscriptions/[^/]+/resourceGroups/rg-cosmabot-prod-eus2-01/providers/Microsoft\.CognitiveServices/accounts/oai-cbot-prd-[a-z0-9]{6,10}$' || {
    echo "STOP: rotate ACCOUNT_ID shape invalid" >&2
    return 1
  }
  (
    umask 077
    set -o pipefail
    mkdir -p "$(dirname "$KEYFILE")" || exit 1
    rm -f "$KEYFILE" || exit 1
    az cognitiveservices account keys regenerate \
      --resource-group "$RG" \
      --name "${ACCOUNT_ID##*/}" \
      --key-name key1 \
      --query key1 -o tsv | tr -d '\n' > "$KEYFILE" || exit 1
  ) || {
    echo "STOP: rotate regenerate failed" >&2
    rm -f "${KEYFILE:-}"
    return 1
  }
  test -s "$KEYFILE" || {
    echo "STOP: rotate KEYFILE empty or missing" >&2
    rm -f "${KEYFILE:-}"
    return 1
  }
  echo "PASS: rotate wrote KEYFILE (value not printed)"
  return 0
}
cosmabot_llm_kv_rotate_key || {
  echo "STOP: rotate failed" >&2
  false
}
```

**Fence 2 — load** (John only; uses `$KEYFILE`). Wrapped in a function so
every guard uses `|| return 1` and PASS cannot print after a STOP. Requires a
non-empty key file (`test -s`). `--output none` so the secret value is never
printed:

```bash
cosmabot_llm_kv_fence2_load() {
  test -n "${ACCOUNT_ID:-}" || {
    echo "STOP: Fence 2 ACCOUNT_ID empty - run Fence 1 first" >&2
    return 1
  }
  printf '%s' "$ACCOUNT_ID" | grep -Eq '^/subscriptions/[^/]+/resourceGroups/rg-cosmabot-prod-eus2-01/providers/Microsoft\.CognitiveServices/accounts/oai-cbot-prd-[a-z0-9]{6,10}$' || {
    echo "STOP: Fence 2 ACCOUNT_ID shape invalid" >&2
    return 1
  }
  test -n "${PROD_KV_NAME:-}" || {
    echo "STOP: Fence 2 PROD_KV_NAME unset" >&2
    return 1
  }
  printf '%s' "$PROD_KV_NAME" | grep -Eq '^kv-cbot-prd-[a-z0-9]+$' || {
    echo "STOP: Fence 2 PROD_KV_NAME must match kv-cbot-prd-<suffix>" >&2
    return 1
  }
  test -n "${KEYFILE:-}" || {
    echo "STOP: Fence 2 KEYFILE unset" >&2
    return 1
  }
  test -s "$KEYFILE" || {
    echo "STOP: Fence 2 KEYFILE missing or empty" >&2
    return 1
  }
  az keyvault secret set \
    --vault-name "$PROD_KV_NAME" \
    --name WORKSPACE-LLM-API-KEY \
    --file "$KEYFILE" \
    --tags "source-account=${ACCOUNT_ID}" \
    --output none || {
    echo "STOP: Fence 2 secret set failed" >&2
    return 1
  }
  echo "PASS: Fence 2 WORKSPACE-LLM-API-KEY set (value not printed)"
  return 0
}
cosmabot_llm_kv_fence2_load || {
  echo "STOP: Fence 2 failed" >&2
  false
}
```

**Pause here.** Confirm Fence 2 printed PASS. Then paste Fence 3.

**Fence 3 — Step B** (metadata only; never `az keyvault secret show`).

**What Step B proves / does not prove (L-2):** Step B lists vault secret
**metadata** and checks that the `source-account` **tag** equals the Step A
account resource id. It does **not** read or compare the secret **value**, and
it does **not** prove that the bytes in `$KEYFILE` match what Fence 2 wrote.
Never use `az keyvault secret show` to “fix” the key (that would print or
expose the production AI key). Key-value proof is later: the §4.1 host HTTP
status check (auth header from the host key **file**, status `200` only). If
you re-run **rotate**, you must also re-run **Fence 2** before Step B — a new
`$KEYFILE` is useless until it is loaded again.

**`$KEYFILE` keep vs remove (L-1):** do not leave a key file on disk after a
failed or abandoned sitting.

| Outcome | `$KEYFILE` |
| --- | --- |
| Step B **PASS** | **Remove** (`rm -f` + clear `KEYFILE` inside the function). |
| Step B **STOP**, will **not** immediately retry Fence 2 / Step B in this sitting | **Remove** (fail-safe on the STOP path below). Then close the vault (§4.3). |
| Step B **STOP**, will **immediately** retry Fence 2 / Step B **without** re-rotating | **Keep** for that retry only: skip the STOP-path `rm` lines for that attempt, retry, then remove on PASS or when abandoning. |
| Re-run **rotate** to retry | **Remove** any old `$KEYFILE` first (rotate does). Must also re-run **Fence 2**, then Step B. |
| **Abandon sitting** / interrupt / will not retry | **Remove** via §4.3 abandon cleanup after closing the vault. |

```bash
cosmabot_llm_kv_step_b_verify_tag() {
  command -v az >/dev/null || {
    echo "STOP: Step B needs az" >&2
    return 1
  }
  command -v jq >/dev/null || {
    echo "STOP: Step B needs jq" >&2
    return 1
  }
  test -n "${ACCOUNT_ID:-}" || {
    echo "STOP: Step B ACCOUNT_ID empty" >&2
    return 1
  }
  printf '%s' "$ACCOUNT_ID" | grep -Eq '^/subscriptions/[^/]+/resourceGroups/rg-cosmabot-prod-eus2-01/providers/Microsoft\.CognitiveServices/accounts/oai-cbot-prd-[a-z0-9]{6,10}$' || {
    echo "STOP: Step B ACCOUNT_ID shape invalid" >&2
    return 1
  }
  test -n "${PROD_KV_NAME:-}" || {
    echo "STOP: Step B PROD_KV_NAME unset" >&2
    return 1
  }
  META_JSON=$(az keyvault secret list \
    --vault-name "$PROD_KV_NAME" \
    --query "[?name=='WORKSPACE-LLM-API-KEY'].{name:name,id:id,tags:tags}" -o json) || {
    echo "STOP: Step B secret list failed" >&2
    return 1
  }
  test "$(printf '%s' "$META_JSON" | jq -er 'length')" = "1" || {
    echo "STOP: Step B expected exactly one WORKSPACE-LLM-API-KEY" >&2
    return 1
  }
  test "$(printf '%s' "$META_JSON" | jq -er '.[0].name')" = "WORKSPACE-LLM-API-KEY" || {
    echo "STOP: Step B secret name mismatch" >&2
    return 1
  }
  TAGGED=$(printf '%s' "$META_JSON" | jq -er '.[0].tags["source-account"] // empty') || {
    echo "STOP: Step B source-account tag read failed" >&2
    return 1
  }
  test -n "$TAGGED" || {
    echo "STOP: Step B source-account tag empty" >&2
    return 1
  }
  test "$TAGGED" = "$ACCOUNT_ID" || {
    echo "STOP: Step B source-account tag does not match Step A id" >&2
    return 1
  }
  echo "PASS: Step B source-account tag matches Step A"
  rm -f "${KEYFILE:-}"
  KEYFILE=
  return 0
}
cosmabot_llm_kv_step_b_verify_tag || {
  echo "STOP: Step B failed - close vault per section 4.3; fail-safe removing KEYFILE (skip next two lines only for immediate Fence 2 retry)" >&2
  rm -f "${KEYFILE:-}"
  KEYFILE=
  false
}
```

Then restore `publicNetworkAccess=Disabled` and empty `ipRules` (Sitting 2
gate). If the session is interrupted or abandoned, jump to §4.3 first
(including the abandon `$KEYFILE` cleanup).

#### After host install (`infra/beta/vm/host/secrets_transport.py`) — file name/mode only

**Shell:** bash on the Linux VM (`stat -c`). Chain every check with `|| return 1`.

```bash
cosmabot_stop_llm_host_files() {
  test -n "${RELEASE_ID:-}" || {
    echo "STOP: host files RELEASE_ID unset"
    return 1
  }
  for role in api worker; do
    f="/etc/cosmabot/runtime/${RELEASE_ID}/${role}/WORKSPACE_LLM_API_KEY"
    test -f "$f" || {
      echo "STOP: host WORKSPACE_LLM_API_KEY missing for $role"
      return 1
    }
    test "$(stat -c '%a' "$f")" = "400" || {
      echo "STOP: host WORKSPACE_LLM_API_KEY not mode 0400 for $role"
      return 1
    }
  done
  echo "PASS: host WORKSPACE_LLM_API_KEY present mode 0400 for api and worker"
  return 0
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
  command -v curl >/dev/null || {
    echo "STOP: HTTP proof needs curl"
    return 1
  }
  test -n "${WORKSPACE_LLM_ENDPOINT:-}" || {
    echo "STOP: HTTP proof WORKSPACE_LLM_ENDPOINT unset"
    return 1
  }
  test -n "${RELEASE_ID:-}" || {
    echo "STOP: HTTP proof RELEASE_ID unset"
    return 1
  }
  HOST_LLM_KEYFILE="/etc/cosmabot/runtime/${RELEASE_ID}/api/WORKSPACE_LLM_API_KEY"
  test -f "$HOST_LLM_KEYFILE" || {
    echo "STOP: HTTP proof HOST_LLM_KEYFILE missing"
    return 1
  }
  ENDPOINT=$WORKSPACE_LLM_ENDPOINT
  printf '%s' "$ENDPOINT" | grep -Eq '^https://oai-cbot-prd-[a-z0-9]{6,10}\.openai\.azure\.com/openai/v1$' || {
    echo "STOP: HTTP proof endpoint is not the PR 381 prod pattern"
    return 1
  }
  HDR=$(mktemp) || {
    echo "STOP: HTTP proof mktemp failed"
    return 1
  }
  _prev_exit=$(trap -p EXIT)
  _prev_int=$(trap -p INT)
  _prev_term=$(trap -p TERM)
  trap 'rm -f "$HDR"' EXIT INT TERM
  set +x
  { printf 'api-key: '; cat "$HOST_LLM_KEYFILE"; printf '\n'; } >"$HDR" || {
    echo "STOP: HTTP proof header file write failed"
    rm -f "$HDR"
    eval "${_prev_exit:-trap - EXIT}"
    eval "${_prev_int:-trap - INT}"
    eval "${_prev_term:-trap - TERM}"
    return 1
  }
  STATUS=$(curl -sS -o /dev/null -w '%{http_code}' \
    --connect-timeout 10 --max-time 60 \
    -H 'Content-Type: application/json' \
    -H @"$HDR" \
    -d '{"model":"gpt-4.1-dzus","messages":[{"role":"user","content":"ping"}],"max_tokens":1}' \
    "${ENDPOINT}/chat/completions") || {
    echo "STOP: HTTP proof curl failed"
    rm -f "$HDR"
    eval "${_prev_exit:-trap - EXIT}"
    eval "${_prev_int:-trap - INT}"
    eval "${_prev_term:-trap - TERM}"
    return 1
  }
  rm -f "$HDR"
  eval "${_prev_exit:-trap - EXIT}"
  eval "${_prev_int:-trap - INT}"
  eval "${_prev_term:-trap - TERM}"
  test "$STATUS" = "200" || {
    echo "STOP: HTTP proof status was $STATUS (want 200; 401 means foreign key) - roll back AI-on"
    return 1
  }
  echo "PASS: HTTP proof status 200 (body and key value not printed)"
  return 0
}
cosmabot_stop_llm_http_status || {
  echo "STOP: prod OpenAI HTTP status proof failed - roll back AI-on"
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
`webDir`). Do **not** scan the whole `.app` tree or Mach-O binaries. The
`$APP/public` Clerk publishable-key check is **presence-only** (fixed-string
for the expected Sitting 1 `pk_live_…`): it proves the expected key is present
and does **not** refuse a second different `pk_` elsewhere in that tree. Exact
equality for the shipped key remains on `Info.plist` via `plutil`.

Confirmed in-repo artifact names (`scripts/prepare-workspace-identity.mjs`,
`docs/beta/WEB_RELEASE.md`, `apps/capture/ios/App/App/capacitor.config.json`):

| File | Path | Keys checked |
| --- | --- | --- |
| `Info.plist` | inside reviewed `.app` | `CosmasNativeIdentity.apiOrigin`, `.frontendOrigin`, `.publishableKey` |
| `$APP/public` | Capacitor web assets only | staging API origin forms + expected `pk_live_` (**presence-only** fixed-string) |
| `web-build-arguments.json` | prepare output / `/protected/ephemeral/…` | `VITE_WORKSPACE_HOSTED_API_ORIGIN`, `VITE_CLERK_PUBLISHABLE_KEY` |
| `web-build-env.json` | same prepare output | `VITE_API_BASE`, `VITE_WORKSPACE_HOSTED_API_ORIGIN`, `VITE_CLERK_PUBLISHABLE_KEY` |

**Shell:** bash 3.2+ or default macOS zsh; chain every check with an explicit
STOP echo. Pasteable fence has no `#` comment lines. Set
`EXPECTED_CLERK_PUBLISHABLE_KEY` from Sitting 1 public values first (public
`pk_live_…` only; no secrets). The stop functions themselves refuse an empty
or unset expected key, decode the key (base64 after `pk_live_`), and require
the embedded host to equal `clerk.beta.cosmas.ai` (parity with
`scripts/native_iphone_auth_profile.py`).

```bash
WANT='https://api.beta.cosmas.ai'
EXPECTED_CLERK_ISSUER='https://clerk.beta.cosmas.ai'
EXPECTED_CLERK_HOST='clerk.beta.cosmas.ai'
cosmabot_clerk_pk_host() {
  key=$1
  test -n "$key" || return 1
  case "$key" in
    pk_live_*) ;;
    *) return 1 ;;
  esac
  enc=${key#pk_live_}
  enc=$(printf '%s' "$enc" | tr '_-' '/+') || return 1
  rem=$(( ${#enc} % 4 ))
  case "$rem" in
    0) ;;
    2) enc="${enc}==" ;;
    3) enc="${enc}=" ;;
    *) return 1 ;;
  esac
  decoded=$(printf '%s' "$enc" | /usr/bin/base64 -D 2>/dev/null || printf '%s' "$enc" | base64 -d 2>/dev/null) || return 1
  case "$decoded" in
    *\$) host=${decoded%\$} ;;
    *) return 1 ;;
  esac
  test -n "$host" || return 1
  printf '%s\n' "$host"
}
cosmabot_require_prod_clerk_pk() {
  key=$1
  test -n "$key" || {
    echo "STOP: publishable key empty or unset"
    return 1
  }
  host=$(cosmabot_clerk_pk_host "$key") || {
    echo "STOP: publishable key is not a decodable pk_live_ value"
    return 1
  }
  test "$host" = "$EXPECTED_CLERK_HOST" || {
    echo "STOP: publishable key host is not clerk.beta.cosmas.ai"
    return 1
  }
  return 0
}
cosmabot_scan_forbidden_origins() {
  root=$1
  test -d "$root" || {
    echo "STOP: scan root missing: $root"
    return 1
  }
  if ! command -v rg >/dev/null 2>&1 && ! command -v /usr/bin/grep >/dev/null 2>&1; then
    echo "STOP: need rg or /usr/bin/grep"
    return 1
  fi
  _hit() {
    if command -v rg >/dev/null 2>&1; then
      rg -a --no-ignore --hidden -q "$1" "$root"
    else
      /usr/bin/grep -rE "$1" "$root" >/dev/null
    fi
  }
  if _hit 'https://api\.staging\.'; then
    echo "STOP: https://api.staging. under $root"
    return 1
  fi
  if _hit 'https://enrollment-api\.staging\.'; then
    echo "STOP: https://enrollment-api.staging. under $root"
    return 1
  fi
  if _hit 'https://api\.[a-z0-9.-]+\.staging\.'; then
    echo "STOP: https://api.<x>.staging. under $root"
    return 1
  fi
  return 0
}
cosmabot_stop_iphone_api_origin() {
  APP=$1
  test -n "${EXPECTED_CLERK_PUBLISHABLE_KEY:-}" || {
    echo "STOP: iPhone EXPECTED_CLERK_PUBLISHABLE_KEY unset"
    return 1
  }
  cosmabot_require_prod_clerk_pk "$EXPECTED_CLERK_PUBLISHABLE_KEY" || return 1
  command -v /usr/bin/plutil >/dev/null || {
    echo "STOP: iPhone needs /usr/bin/plutil"
    return 1
  }
  test -d "$APP" || {
    echo "STOP: iPhone app path missing"
    return 1
  }
  test -f "$APP/Info.plist" || {
    echo "STOP: iPhone Info.plist missing"
    return 1
  }
  WEB_ASSETS="$APP/public"
  test -d "$WEB_ASSETS" || {
    echo "STOP: iPhone public web assets missing"
    return 1
  }
  ORIGIN=$(/usr/bin/plutil -extract CosmasNativeIdentity.apiOrigin raw -o - "$APP/Info.plist") || {
    echo "STOP: iPhone apiOrigin extract failed"
    return 1
  }
  test "$ORIGIN" = "$WANT" || {
    echo "STOP: iPhone apiOrigin mismatch"
    return 1
  }
  ISSUER=$(/usr/bin/plutil -extract CosmasNativeIdentity.frontendOrigin raw -o - "$APP/Info.plist") || {
    echo "STOP: iPhone frontendOrigin extract failed"
    return 1
  }
  test "$ISSUER" = "$EXPECTED_CLERK_ISSUER" || {
    echo "STOP: iPhone frontendOrigin mismatch"
    return 1
  }
  PK=$(/usr/bin/plutil -extract CosmasNativeIdentity.publishableKey raw -o - "$APP/Info.plist") || {
    echo "STOP: iPhone publishableKey extract failed"
    return 1
  }
  test -n "$PK" || {
    echo "STOP: iPhone publishableKey empty"
    return 1
  }
  cosmabot_require_prod_clerk_pk "$PK" || return 1
  test "$PK" = "$EXPECTED_CLERK_PUBLISHABLE_KEY" || {
    echo "STOP: iPhone publishableKey does not match Sitting 1 public value"
    return 1
  }
  cosmabot_scan_forbidden_origins "$WEB_ASSETS" || return 1
  if command -v rg >/dev/null 2>&1; then
    rg -aF --no-ignore --hidden -q "$EXPECTED_CLERK_PUBLISHABLE_KEY" "$WEB_ASSETS" || {
      echo "STOP: iPhone public web assets missing expected publishable key (presence-only)"
      return 1
    }
  else
    /usr/bin/grep -rF "$EXPECTED_CLERK_PUBLISHABLE_KEY" "$WEB_ASSETS" >/dev/null || {
      echo "STOP: iPhone public web assets missing expected publishable key (presence-only)"
      return 1
    }
  fi
  echo "PASS: iPhone Info.plist + public web assets OK (Clerk key presence-only under public)"
  return 0
}
cosmabot_stop_web_api_origin() {
  WEB_ROOT=$1
  ARGS=${2:-"$WEB_ROOT/../web-build-arguments.json"}
  ENVJSON=${3:-"$WEB_ROOT/../web-build-env.json"}
  test -n "${EXPECTED_CLERK_PUBLISHABLE_KEY:-}" || {
    echo "STOP: web EXPECTED_CLERK_PUBLISHABLE_KEY unset"
    return 1
  }
  cosmabot_require_prod_clerk_pk "$EXPECTED_CLERK_PUBLISHABLE_KEY" || return 1
  command -v jq >/dev/null || {
    echo "STOP: web needs jq"
    return 1
  }
  test -d "$WEB_ROOT" || {
    echo "STOP: web root missing"
    return 1
  }
  if command -v rg >/dev/null 2>&1; then
    rg -aF --no-ignore --hidden -q "$WANT" "$WEB_ROOT" || {
      echo "STOP: web dist missing api.beta.cosmas.ai"
      return 1
    }
    rg -aF --no-ignore --hidden -q "$EXPECTED_CLERK_PUBLISHABLE_KEY" "$WEB_ROOT" || {
      echo "STOP: web dist missing expected publishable key (fixed-string)"
      return 1
    }
  else
    command -v /usr/bin/grep >/dev/null || {
      echo "STOP: web needs rg or /usr/bin/grep"
      return 1
    }
    /usr/bin/grep -rF "$WANT" "$WEB_ROOT" >/dev/null || {
      echo "STOP: web dist missing api.beta.cosmas.ai"
      return 1
    }
    /usr/bin/grep -rF "$EXPECTED_CLERK_PUBLISHABLE_KEY" "$WEB_ROOT" >/dev/null || {
      echo "STOP: web dist missing expected publishable key (fixed-string)"
      return 1
    }
  fi
  cosmabot_scan_forbidden_origins "$WEB_ROOT" || return 1
  test -f "$ARGS" || {
    echo "STOP: web-build-arguments.json missing"
    return 1
  }
  test "$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ARGS")" = "$WANT" || {
    echo "STOP: web-build-arguments API origin mismatch"
    return 1
  }
  test "$(jq -er '.VITE_CLERK_PUBLISHABLE_KEY' "$ARGS")" = "$EXPECTED_CLERK_PUBLISHABLE_KEY" || {
    echo "STOP: web-build-arguments publishable key mismatch"
    return 1
  }
  test -f "$ENVJSON" || {
    echo "STOP: web-build-env.json missing"
    return 1
  }
  jq -e --arg want "$WANT" --arg pk "$EXPECTED_CLERK_PUBLISHABLE_KEY" '
    (.VITE_API_BASE | type == "string" and length > 0 and . == $want)
    and (.VITE_WORKSPACE_HOSTED_API_ORIGIN | type == "string" and length > 0 and . == $want)
    and (.VITE_CLERK_PUBLISHABLE_KEY | type == "string" and length > 0 and . == $pk)
  ' "$ENVJSON" >/dev/null || {
    echo "STOP: web-build-env.json origin or key mismatch"
    return 1
  }
  echo "PASS: web dist + sidecars OK"
  return 0
}
```

After defining the functions, run one wrong-path smoke, then the real
artifacts (paths outside the fence so zsh paste stays clean). Each call must
print STOP or PASS — never silence:

1. `cosmabot_stop_iphone_api_origin /path/to/wrong.app` must print STOP
2. `cosmabot_stop_iphone_api_origin /path/to/CosmaBot.app` must print PASS
3. `cosmabot_stop_web_api_origin /path/to/reviewed-web-dist` must print PASS

#### Baseline from a known-good production build (N3) — **Pending**

**Status: Pending** (not closed). The original N3 ask (prove the scan passes a
real known-good production build) cannot be closed until such a build exists
and John accepts it. The helpers below are ready; do not treat baseline work
as done.

Before trusting candidates, record a baseline from one known-good
production-review build (public values only). Store it outside the repo
(example path `/protected/ephemeral/prod-bundle-baseline.json`). Record runs
the STOP functions first:

```bash
cosmabot_record_bundle_baseline() {
  APP=$1
  WEB_ROOT=$2
  OUT=$3
  ARGS=${4:-"$WEB_ROOT/../web-build-arguments.json"}
  ENVJSON=${5:-"$WEB_ROOT/../web-build-env.json"}
  test -n "${EXPECTED_CLERK_PUBLISHABLE_KEY:-}" || {
    echo "STOP: baseline EXPECTED_CLERK_PUBLISHABLE_KEY unset"
    return 1
  }
  cosmabot_stop_iphone_api_origin "$APP" || {
    echo "STOP: baseline record refused - iPhone STOP failed"
    return 1
  }
  cosmabot_stop_web_api_origin "$WEB_ROOT" "$ARGS" "$ENVJSON" || {
    echo "STOP: baseline record refused - web STOP failed"
    return 1
  }
  command -v jq >/dev/null || {
    echo "STOP: baseline needs jq"
    return 1
  }
  command -v /usr/bin/plutil >/dev/null || {
    echo "STOP: baseline needs plutil"
    return 1
  }
  api=$(/usr/bin/plutil -extract CosmasNativeIdentity.apiOrigin raw -o - "$APP/Info.plist") || {
    echo "STOP: baseline apiOrigin extract failed"
    return 1
  }
  issuer=$(/usr/bin/plutil -extract CosmasNativeIdentity.frontendOrigin raw -o - "$APP/Info.plist") || {
    echo "STOP: baseline frontendOrigin extract failed"
    return 1
  }
  pk=$(/usr/bin/plutil -extract CosmasNativeIdentity.publishableKey raw -o - "$APP/Info.plist") || {
    echo "STOP: baseline publishableKey extract failed"
    return 1
  }
  wapi=$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ARGS") || {
    echo "STOP: baseline args API origin read failed"
    return 1
  }
  wpk=$(jq -er '.VITE_CLERK_PUBLISHABLE_KEY' "$ARGS") || {
    echo "STOP: baseline args key read failed"
    return 1
  }
  eapi=$(jq -er '.VITE_API_BASE' "$ENVJSON") || {
    echo "STOP: baseline env API base read failed"
    return 1
  }
  eorigin=$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ENVJSON") || {
    echo "STOP: baseline env API origin read failed"
    return 1
  }
  epk=$(jq -er '.VITE_CLERK_PUBLISHABLE_KEY' "$ENVJSON") || {
    echo "STOP: baseline env key read failed"
    return 1
  }
  jq -n \
    --arg api "$api" \
    --arg issuer "$issuer" \
    --arg pk "$pk" \
    --arg wapi "$wapi" \
    --arg wpk "$wpk" \
    --arg eapi "$eapi" \
    --arg eorigin "$eorigin" \
    --arg epk "$epk" \
    '{apiOrigin:$api,clerkIssuer:$issuer,publishableKey:$pk,webBuildArguments:{VITE_WORKSPACE_HOSTED_API_ORIGIN:$wapi,VITE_CLERK_PUBLISHABLE_KEY:$wpk},webBuildEnv:{VITE_API_BASE:$eapi,VITE_WORKSPACE_HOSTED_API_ORIGIN:$eorigin,VITE_CLERK_PUBLISHABLE_KEY:$epk}}' >"$OUT" || {
    echo "STOP: baseline write failed"
    return 1
  }
  test "$(jq -er '.apiOrigin' "$OUT")" = "https://api.beta.cosmas.ai" || {
    echo "STOP: baseline apiOrigin pin failed"
    return 1
  }
  test "$(jq -er '.clerkIssuer' "$OUT")" = "https://clerk.beta.cosmas.ai" || {
    echo "STOP: baseline clerkIssuer pin failed"
    return 1
  }
  echo "PASS: baseline recorded (public values only; N3 still pending until John accepts a known-good build)"
  return 0
}
cosmabot_compare_bundle_to_baseline() {
  APP=$1
  WEB_ROOT=$2
  BASELINE=$3
  ARGS=${4:-"$WEB_ROOT/../web-build-arguments.json"}
  ENVJSON=${5:-"$WEB_ROOT/../web-build-env.json"}
  test -f "$BASELINE" || {
    echo "STOP: baseline file missing"
    return 1
  }
  cosmabot_stop_iphone_api_origin "$APP" || {
    echo "STOP: baseline compare iPhone STOP failed"
    return 1
  }
  cosmabot_stop_web_api_origin "$WEB_ROOT" "$ARGS" "$ENVJSON" || {
    echo "STOP: baseline compare web STOP failed"
    return 1
  }
  test "$(/usr/bin/plutil -extract CosmasNativeIdentity.apiOrigin raw -o - "$APP/Info.plist")" = "$(jq -er '.apiOrigin' "$BASELINE")" || {
    echo "STOP: baseline compare apiOrigin drift"
    return 1
  }
  test "$(/usr/bin/plutil -extract CosmasNativeIdentity.frontendOrigin raw -o - "$APP/Info.plist")" = "$(jq -er '.clerkIssuer' "$BASELINE")" || {
    echo "STOP: baseline compare frontendOrigin drift"
    return 1
  }
  test "$(/usr/bin/plutil -extract CosmasNativeIdentity.publishableKey raw -o - "$APP/Info.plist")" = "$(jq -er '.publishableKey' "$BASELINE")" || {
    echo "STOP: baseline compare publishableKey drift"
    return 1
  }
  test "$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ARGS")" = "$(jq -er '.webBuildArguments.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$BASELINE")" || {
    echo "STOP: baseline compare web-build-arguments API origin drift"
    return 1
  }
  test "$(jq -er '.VITE_CLERK_PUBLISHABLE_KEY' "$ARGS")" = "$(jq -er '.webBuildArguments.VITE_CLERK_PUBLISHABLE_KEY' "$BASELINE")" || {
    echo "STOP: baseline compare web-build-arguments key drift"
    return 1
  }
  test "$(jq -er '.VITE_API_BASE' "$ENVJSON")" = "$(jq -er '.webBuildEnv.VITE_API_BASE' "$BASELINE")" || {
    echo "STOP: baseline compare web-build-env API base drift"
    return 1
  }
  test "$(jq -er '.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$ENVJSON")" = "$(jq -er '.webBuildEnv.VITE_WORKSPACE_HOSTED_API_ORIGIN' "$BASELINE")" || {
    echo "STOP: baseline compare web-build-env API origin drift"
    return 1
  }
  test "$(jq -er '.VITE_CLERK_PUBLISHABLE_KEY' "$ENVJSON")" = "$(jq -er '.webBuildEnv.VITE_CLERK_PUBLISHABLE_KEY' "$BASELINE")" || {
    echo "STOP: baseline compare web-build-env key drift"
    return 1
  }
  echo "PASS: candidate matches baseline (N3 still pending until a known-good build is accepted)"
  return 0
}
```

Do not ship or admit a candidate that fails the STOP checks or the baseline
compare. Re-record the baseline only when John accepts a new known-good build.
Keep N3 marked **Pending** until that acceptance exists.

### 4.3 Interrupted Key Vault access window

If Sitting 2 is interrupted while the vault is open to the operator `/32`:

1. **First:** restore `publicNetworkAccess=Disabled` and empty `ipRules`
   (John only; use the `#356` README restore commands for the prod vault).
2. **Then verify** by printing the **whole** `ipRules` list (and access flag).
3. **Abandon sitting / will not retry (L-1):** after the vault is closed (or
   immediately if the vault was never opened), remove any local rotated key
   file so a failed or abandoned sitting does not leave `$KEYFILE` on disk.
   Keep `$KEYFILE` only when you will **immediately** retry Fence 2 / Step B
   in this same sitting without re-rotating (see §4.1 keep-vs-remove table).
   Never leave `$KEYFILE` overnight or across sittings.

**Shell:** bash 3.2+ or default macOS zsh. Fence has no `#` comments.

```bash
cosmabot_verify_kv_closed() {
  command -v az >/dev/null || {
    echo "STOP: kv-closed needs az"
    return 1
  }
  test -n "${PROD_KV_NAME:-}" || {
    echo "STOP: kv-closed PROD_KV_NAME unset"
    return 1
  }
  az keyvault show --name "$PROD_KV_NAME" \
    --query "{publicNetworkAccess:properties.publicNetworkAccess,ipRules:properties.networkAcls.ipRules}" \
    -o json || {
    echo "STOP: kv-closed show failed"
    return 1
  }
  ACCESS=$(az keyvault show --name "$PROD_KV_NAME" \
    --query properties.publicNetworkAccess -o tsv) || {
    echo "STOP: kv-closed access query failed"
    return 1
  }
  test "$ACCESS" = "Disabled" || {
    echo "STOP: kv-closed publicNetworkAccess is not Disabled"
    return 1
  }
  COUNT=$(az keyvault show --name "$PROD_KV_NAME" \
    --query "length(properties.networkAcls.ipRules)" -o tsv) || {
    echo "STOP: kv-closed ipRules length query failed"
    return 1
  }
  test "$COUNT" = "0" || {
    echo "STOP: kv-closed ipRules not empty"
    return 1
  }
  echo "PASS: vault public access Disabled and ipRules empty"
  return 0
}
cosmabot_verify_kv_closed || {
  echo "STOP: vault still open or ipRules not empty - fix before continuing"
  false
}
```

**Abandon-sitting `$KEYFILE` cleanup** (paste after vault closed, or when the
sitting will not retry Fence 2 / Step B). Fail-safe; never prints file
contents. `KEYFILE` must already be the same once-exported path from §4.1:

```bash
cosmabot_abandon_sitting_keyfile_cleanup() {
  test -n "${KEYFILE:-}" || {
    echo "PASS: abandon sitting KEYFILE already unset"
    return 0
  }
  rm -f "$KEYFILE"
  KEYFILE=
  echo "PASS: abandon sitting removed KEYFILE (value not printed)"
  return 0
}
cosmabot_abandon_sitting_keyfile_cleanup || {
  echo "STOP: abandon sitting KEYFILE cleanup failed" >&2
  false
}
```

Do not continue Sitting 2 secret work until the vault-closed verify passes.
If abandoning, run the `$KEYFILE` cleanup before leaving the machine.

### 4.5 Temporary SSH `/32` for secrets install (John, 14 Nov 2026 9:45am ET)

John: "Yes, open sign-in to my address for the install, then close it."

No Bastion. No Secrets Officer `az login` on the VM. No permanent NSG/Terraform
change. Fixed rule name `TEMP-JOHN-SSH-SECRETS-INSTALL`, priority `200`
(before `deny-all-other-ingress` at `4000`), NSG `nsg-cosmabot-prod-eus2-01`,
RG `rg-cosmabot-prod-eus2-01`. Detect John's IP with
`curl -fsS https://api.ipify.org` (prints IP only). Create uses `--output none`.

**No secret values on the prod disk outside final mode-0400 destinations.**
Workstation stages under a local mode-700 dir; install pipes each value over
`ssh` stdin into `secrets_transport.py --install-from-stdin` as root (umask
077). Do not `scp` secret values. Do not stage under `/tmp` or `/root` on the
VM. Ship the module only; verify `sha256` against
`infra/beta/vm/host/secrets_transport.sha256` before running. Pin the VM
ed25519 host key via `az vm run-command` (public key only) into a per-session
`known_hosts`; `ssh` uses `StrictHostKeyChecking=yes`.

**Close-and-verify is MANDATORY after every outcome**, including STOP mid-way
and SIGINT. An out-of-band NSG rule shows as drift on the next Terraform plan —
finish close-and-verify before any plan or apply. Close requires deny-all at
priority `4000`, Python `--check-ssh-closed`, and an SSH probe that PASSes only
on connection refused or timeout (auth failure = still reachable = FAIL).

Define-only fence files (no `#` comment lines; sourcing has zero side effects)
live in `infra/beta/vm/host/fences/`:

| Step | Fence file |
| --- | --- |
| OPEN | `fence-ssh-nsg-open.sh` → `cosmabot_ssh_nsg_open` |
| INSTALL | `fence-ssh-secrets-install.sh` → `cosmabot_ssh_secrets_install` |
| CLOSE AND VERIFY | `fence-ssh-nsg-close-verify.sh` → `cosmabot_ssh_nsg_close_and_verify` |
| Session (always closes) | `fence-ssh-secrets-session.sh` → `cosmabot_ssh_secrets_session` |
| Terminal closed partway | `fence-ssh-nsg-recovery.sh` → `cosmabot_ssh_nsg_recovery_if_stranded` |

**Order:** source the open/install/close fences, then invoke the session
wrapper (it traps EXIT/INT/TERM/ERR so close-and-verify always runs):

```text
export RG=rg-cosmabot-prod-eus2-01 VM_PUBLIC_IP=… RELEASE_ID=… LOCAL_STAGING=… PROD_KV_NAME=… SECRETS_TRANSPORT_PY=…/secrets_transport.py
source infra/beta/vm/host/fences/fence-ssh-nsg-open.sh
source infra/beta/vm/host/fences/fence-ssh-secrets-install.sh
source infra/beta/vm/host/fences/fence-ssh-nsg-close-verify.sh
source infra/beta/vm/host/fences/fence-ssh-secrets-session.sh
cosmabot_ssh_secrets_session
```

Sourcing alone must never open or close the NSG rule. Secrets stay with John;
fences print names / rule metadata / pass-fail only.

#### Terminal closed partway — recovery

If the session dies while `TEMP-JOHN-SSH-SECRETS-INSTALL` may still exist, source
and invoke `cosmabot_ssh_nsg_recovery_if_stranded` (deletes the rule by fixed
name, verifies absence + deny-all at 4000, removes stranded local staging).
Then do not plan/apply until that PASS prints.

### 4.4 Mac-side fence syntax proof

Every pasteable bash fence in §4.1–§4.3 (ten fences: Step A, rotate,
Fence 2 load, Step B, host-files, HTTP status, bundle-checks, baseline,
kv-closed, abandon-sitting `$KEYFILE` cleanup) must parse under `bash -n`
and `zsh -n`. Real evidence that a pasted interactive zsh prompt will not
treat `#` as a comment is that the fences contain **no `#` comment lines**
(parameter expansions like `${var#prefix}` are fine). Do **not** claim that
`zsh -n` honours a parent `unsetopt interactivecomments` — `zsh -n` always
treats `#` as a comment inside a file. Proof commands (re-run after editing
fences):

```text
bash -n fence1-step-a.sh
bash -n fence-rotate.sh
bash -n fence2-load.sh
bash -n fence3-step-b.sh
bash -n fence-host-files.sh
bash -n fence-http-status.sh
bash -n fence-bundle-checks.sh
bash -n fence-baseline.sh
bash -n fence-kv-closed.sh
bash -n fence-abandon-keyfile.sh
zsh -n fence1-step-a.sh
zsh -n fence-rotate.sh
zsh -n fence2-load.sh
zsh -n fence3-step-b.sh
zsh -n fence-host-files.sh
zsh -n fence-http-status.sh
zsh -n fence-bundle-checks.sh
zsh -n fence-baseline.sh
zsh -n fence-kv-closed.sh
zsh -n fence-abandon-keyfile.sh
```

Author proof results for this revision (all exit 0): listed in the PR body /
agent artifact for issue `#385` (follow-up Lows to `#379`).

---

## 5. Azure OpenAI + `gpt-4.1-dzus`

Created in Sitting 1 apply when `enable_azure_openai: true`:

- `kind = "OpenAI"`, SKU `S0`, PE + `privatelink.openai.azure.com`
- Deployment `gpt-4.1-dzus`, model `gpt-4.1` / `2025-04-14`, DataZoneStandard
  capacity **1**
- John rotates provider-generated keys before loading vault
  `WORKSPACE-LLM-API-KEY` with `source-account=<account id>` (Sitting 2 / §4.1)
- Shared CosmasCode / staging keys must never enter prod

Runnable traffic needs §9 (b) flag flips including
`WORKSPACE_LLM_USDZ_ENABLED=true` (`#381` and `#377` already Merged).

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

### Evidence (`#356` on `main`)

- `infra/beta/vm/prod/foundation/modules/azure_openai/main.tf` lines 8–22:
  `kind = "OpenAI"`
- Same file lines 25–39: deployment `gpt-4.1-dzus`
- Same file lines 42–44: `privatelink.openai.azure.com`
- `infra/beta/vm/prod/profile/runtime-public.json` lines 11–13, 29, 34–40:
  AI disabled in foundation profile; module base URL ≠ app endpoint form
- Partial first apply: use [`#383`](https://github.com/CosmaNeura/cosmaneura-os/pull/383)
  `--recover` (not a fresh first-apply) before continuing Sitting 1

### Evidence (`main`, post-`#381` / `#377`)

| Location | Expectation |
| --- | --- |
| `src/cosmas_os/config.py` 310–311 | Default backend `disabled`; endpoint CosmasCode |
| `src/cosmas_os/config.py` 517–536 | `workspace_llm_available`: production-review requires `#381` prod pattern; other hosted profiles stay CosmasCode-only |
| `src/cosmas_os/config.py` 743–765 | Backend on but unavailable / wrong profile → runtime refuse (incl. line 765) |
| `src/cosmas_os/config.py` 1017–1022 | Standalone accepts either host + `/openai/v1` |
| `src/cosmas_os/adapters/gpt41.py` 31, 171 | Default CosmasCode; constructor accepts either |
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

**Evidence on `main` after `#381` Merged:**

| File | Lines | Behavior |
| --- | --- | --- |
| `src/cosmas_os/config.py` | 310–311 | Default backend `disabled`; endpoint CosmasCode |
| `src/cosmas_os/config.py` | 517–536 | Production-review requires the `#381` prod endpoint; other hosted profiles stay CosmasCode-only |
| `src/cosmas_os/config.py` | 743–765 | Backend on but unavailable / wrong profile → runtime refuse (incl. line 765) |
| `src/cosmas_os/adapters/gpt41.py` | 31, 171 | Default CosmasCode; constructor accepts either host |
| `src/cosmas_os/config.py` | 1017–1022 | Standalone accepts either host |

**Decision (Merged):** [`#381`](https://github.com/CosmaNeura/cosmaneura-os/pull/381)

1. Allows the exact production host pattern
   `https://oai-cbot-prd-[a-z0-9]{6,10}.openai.azure.com/openai/v1` (and keeps
   CosmasCode for existing live / unset-staging paths).
2. Wires hosted chat — text and tools, including streaming — to the configured
   endpoint.
3. If that endpoint is set but unusable → fail closed with a clear error; **never**
   silently fall back to CosmasCode.
4. With no endpoint set (staging) → nothing changes.
5. Model, deployment name, and API version unchanged.

With `#381` Merged and the production endpoint configured, production chat uses
production's own AI account. Do **not** recreate the `#356` OpenAI resource for
this.

### (b) VM runtime refuses start unless AI is on with its key; `#356` profile is AI-off

**Confirm:**

| File | Lines | Behavior |
| --- | --- | --- |
| `infra/beta/vm/runtime/entrypoint.py` | 20–35 | `BASE` requires `WORKSPACE_LLM_BACKEND=azure_gpt41` |
| `infra/beta/vm/runtime/entrypoint.py` | 164–165 | Diff from `BASE` → `hosted_synthetic_profile_required` |
| `infra/beta/vm/runtime/entrypoint.py` | 210–211 | Missing `WORKSPACE_LLM_API_KEY` in `secret_names` → `model_credential_required` |
| `#356` profile `runtime-public.json` | 11–13, 16–22 | `disabled`; no `WORKSPACE_LLM_API_KEY` |

**Prerequisites before AI-on first start:** [`#381`](https://github.com/CosmaNeura/cosmaneura-os/pull/381)
and [`#377`](https://github.com/CosmaNeura/cosmaneura-os/pull/377) are
**Merged** (`CLERK_ACCOUNT_DELETION_SECRET` mapping for
`infra/beta/vm/runtime/entrypoint.py` host-file contract).

**Fork:**

1. **Recommended today:** AI-on first start with `#381` + `#377` Merged;
   treat `#356` disabled profile as foundation-only.
2. **Alternative:** separate runtime PR allowing AI-off first start (not `#356`).

**Order for first `/ready` (path 1) — same clock as §1 (Sitting 2 before
After-14:30 host work):**

1. `#381` (§9 (a) decided) **and** `#377` (VM-runtime delete host-key mapping
   + production-review name allowance) are already **Merged**.
2. Sitting 1: apply `#356` (RG, VM, OpenAI `gpt-4.1-dzus`).
3. Sitting 2: John sets mode-600 passwords; pastes KV names including vault
   `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET`
   (#356 README line 191); §4.1 Step A wrapper → rotate wrapper (`key1` only)
   → Fence 2 load (`--output none`, `test -s`) → Step B tag proof → remove
   `$KEYFILE` on Step B PASS (and on STOP fail-safe / abandon per §4.3)
   before closing the vault.
4. Host prep (agents after Sitting 2 yes) — prod bootstrap retarget **BLOCKED**
   until a named ticket/PR exists. Matches §1 After 14:30 step 1.
5. **Install** mode-0400 secret files with
   `infra/beta/vm/host/secrets_transport.py` (T-PROD-3-SECRETS): names from
   §4; workstation stage under John's vault `/32` window (not the runtime
   UAMI); §4.5 temporary SSH `/32` open → ssh-stdin install (sha256-pinned
   module; no VM `/tmp`/`/root` value staging) → close-and-verify;
   service-UID ownership; mode 0400; Run Command refused for values. Matches
   §1 After 14:30 step 2.
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

1. Host 0400 install: use `infra/beta/vm/host/secrets_transport.py`
   (T-PROD-3-SECRETS). Vault is closed after Sitting 2; workstation
   `--stage-from-vault` uses a temporary vault `/32` window then §4.3
   restore. SSH install uses §4.5 temporary NSG `/32` rule then
   close-and-verify (mandatory before any plan/apply). Do not `az login`
   as Secrets Officer on the VM. No Bastion. Run Command must not carry
   values.
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

- [ ] Agents: runbook PR green; `#383` watched (`#377` / `#381` Merged)
- [ ] Sitting 1: plan-hash yes → `#356` apply **or** `#383` `--recover` → IP recorded → Clerk public values sent
- [ ] Between: agent prep only (no secrets, no staging); bootstrap retarget **BLOCKED** until named ticket/PR
- [ ] Sitting 2: export `KEYFILE` once → Fence 1 Step A wrapper → pause → rotate wrapper (`pipefail` + `test -s`; `key1` only) → Fence 2 (`test -s`, `--output none`) → pause → Step B (tag proof; rm `$KEYFILE` on PASS and STOP fail-safe) → restore Disabled → mode-600 passwords → disk-format yes → DNS proxy off → continue-prep yes
- [ ] §4.3 if interrupted/abandoned: restore Disabled + empty `ipRules`, print whole list, verify, then abandon `$KEYFILE` cleanup
- [ ] After 14:30 (= §9 (b) steps 4–9): install via `secrets_transport.py` + §4.5 SSH open/install/close-and-verify → checks → flag flip → render/start
- [ ] §4.1: Fence 1 wrapper (no PASS after STOP); fail-closed rotate (`key1` only; `key2` later); `test -s`; anchored ACCOUNT_ID `^…$`; `--output none`; Step B tag-only; no key on screen/history
- [ ] §4.2: Info.plist + `$APP/public` only; pk_live decode; `$APP/public` Clerk key **presence-only**; web `-F` key; staging host class `[a-z0-9.-]+`; baseline **Pending**
- [ ] `#377` / `#381` Merged; `#383` merged before any recover apply
- [ ] Account-delete vault `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET` (#356 README line 191)
- [ ] Flags: `WORKSPACE_LLM_BACKEND=azure_gpt41`, `WORKSPACE_LLM_USDZ_ENABLED=true` → `/ready` + `version.json`
- [ ] Eight switches false; synthetic only; staging untouched; no CosmasCode key in prod; never print secret values
