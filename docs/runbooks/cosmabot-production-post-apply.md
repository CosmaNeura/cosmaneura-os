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
| Agents | Prod host bootstrap tooling and unit **file** exist (T-PROD-2 / `#389`). Do not run staging-hardwired names against prod. Do not install the unit yet (after secrets + acceptance; see after-secrets-closed agents). |
| Agents | Advance [`#383`](https://github.com/CosmaNeura/cosmaneura-os/pull/383) toward green; do not merge without John (`#377` / `#381` already Merged) |
| Agents | Prepare Key Vault **names** checklist and mode-600 password-file instructions for Sitting 2 (John loads; agents never rotate or load vault secrets) |
| Agents | No Run Command with secrets; no staging changes |

### Sitting 2 — John (~13:30–14:30 ET, ~60 min)

| # | John does | ~Min | Gate |
| --- | --- | --- | ---: |
| 1 | Key Vault secret pastes (**names only** — §4): temporary public-access window from John's own `/32` (vault is RBAC; `publicNetworkAccess` starts Disabled — every vault write sits inside this window). **John only, §4.1:** export `KEYFILE=$HOME/.cosmabot-sitting2/llm-key1` once → open vault `/32` → Step A → **pause** → rotate **key1** → Fence 2 → **pause** → Step B → generate mode-600 password file (CSPRNG; never printed) → load the other six vault secrets (`--file` / no-echo prompt; `--output none`) → **then** close vault + verify. Close-and-verify is mandatory even after a STOP. **If interrupted/abandoned:** close vault first, then abandon `$KEYFILE` cleanup (§4.3). Agents never rotate or load. | 30 | **"yes, KV secrets loaded and public access disabled"** |
| 2 | Type **yes** to format the new empty data disk (prod IDs only) | 5 | **"yes, format the new empty data disk"** |
| 3 | Publish Cloudflare DNS (proxy **off**): `beta.cosmas.ai` A, `api.beta.cosmas.ai` A → public IP; `clerk.beta.cosmas.ai` CNAME from Clerk | 10 | — |
| 4 | Decide §9 (b) path (recommended: AI-on first start after endpoint-allow PR) and type **yes** for agents to continue host prep / data services after this sitting | 5 | **"yes, continue host prep"** |
| 5 | **John's hands-on — one order** (same as §9 (b) / host README / checklist; needs John's `/32`, vault window, and SSH key): `#389` host bootstrap (`bootstrap_host.py --profile cosmabot-vm-prod-v1`, prod receipt; unit file not enabled yet) → **second vault window** (row 1 already closed the vault) re-open §4.1 → workstation `--stage-from-vault` (all expected names present and non-empty, or STOP before SSH) → `TEMP-JOHN-SSH-SECRETS-INSTALL` (John `/32`) → ssh-stdin install (`#388`) → close-and-verify vault (§4.1) and NSG (**§4.5**). SSH host / user / `-i` identity from tofu `foundation.public_ip`, reviewed `admin_username`, and the private key that matches `admin_ssh_public_key` (placeholders only). Never via Azure Run Command for values. Close-and-verify before any tofu plan/apply. | 10 | **"yes, host secrets path closed; vault Disabled; no port-22 allow"** |
| 6 | Optional: merge `#383` when green (recover path only; `#377` / `#381` already Merged) | 5 | Owner merge only |

### After continue-prep yes — John's hands-on (bootstrap + secrets)

Same day as Sitting 2 row 5. **John's hands-on** — needs John's `/32`, second
vault window, and SSH identity. Still synthetic; still no staging names.
**One order** (Sitting 2 row 5 / §9 (b) / host README / checklist):

1. `#389` host bootstrap on the VM (§3) — run
   `infra/beta/vm/host/bootstrap_host.py --profile cosmabot-vm-prod-v1` with the
   receipt built by `build_creation_receipt.py` and placed on the VM at
   `/root/cosmabot-creation-receipt.json` (T-PROD-2-BOOTSTRAP). Bootstrap is
   what creates `/etc/cosmabot` (including `host-bootstrap.json`); do not create
   that directory or place the receipt under it beforehand. The
   `cosmabot-prod.service` **file** exists; do not install or enable the unit
   yet. Do not run staging-hardwired names against prod.
2. Install mode-0400 secret files from the names John pasted (§4) with
   `infra/beta/vm/host/secrets_transport.py` (T-PROD-3-SECRETS / `#388`):
   **second vault window** + `TEMP-JOHN-SSH-SECRETS-INSTALL` — re-open with
   §4.1 `cosmabot_kv_open_john_32` → workstation `--stage-from-vault` →
   `--check-staging-complete` (empty/partial → STOP; SSH not opened; no PASS) →
   §4.5 temporary SSH `/32` open → ssh-stdin install (no VM value staging;
   pre-check `/etc/cosmabot` exists, then `install -d -o root -g root -m 0700`
   for release root) → close-and-verify vault (§4.1) and NSG (§4.5)
   (John, 14 Nov 2026 9:45am ET). Run Command must not carry secret values
   (host-key public fetch only).

### After secrets closed — agents (not John's hands-on)

Agents continue only after Sitting 2 row 5 gate
(**"yes, host secrets path closed; vault Disabled; no port-22 allow"**).
No John `/32`, vault window, or SSH key required for these steps:

1. Deploy-time STOP checks: §4.1 (remaining host/post-start proofs) and §4.2
   (bundle API origins). On any mismatch: **STOP and roll back** — do not flip
   AI-on flags, do not start API/worker with model traffic.
2. When checks pass and John chose AI-on (`#377` + `#381` already Merged): flip
   runnable profile flags per §9 (b), including
   `WORKSPACE_LLM_BACKEND=azure_gpt41`, `WORKSPACE_LLM_USDZ_ENABLED=true`,
   and `WORKSPACE_LLM_API_KEY` in `secret_names` (**prod** account only).
3. Render + `start.sh data` → `prepare` → `run`.
4. §4.1 post-start value-free HTTP status proof against the prod OpenAI
   endpoint (status code only). Then `/ready`, `/version.json`, smoke, eight
   backend switches `'false'` (§8). Admit smoke only after John's separate yes.
5. After secrets are on the host and acceptance above passes: the
   `cosmabot-prod.service` **file** may be placed with a root-owned
   `/etc/cosmabot/active-release` (matches host/runtime READMEs). **Do NOT
   enable** `cosmabot-prod.service` until **T-PROD-5** (backup units) and
   **T-PROD-6** (probe) retarget are merged. Leave staging hardwires in render /
   `start.sh` for the other named follow-ups in §9 Other gaps. Once enabling is
   allowed: `systemctl start cosmabot-prod.service`, then
   `systemctl restart cosmabot-prod.service`, then reboot, then confirm
   `systemctl is-active cosmabot-prod.service` and that `/run/cosmabot` exists.
   Note: `host-preflight.py`'s `mountpoint -q /var/lib/cosmabot` is not
   trustworthy under the unit's `ReadWritePaths` (bind-mount visibility); the
   operator runs `findmnt /var/lib/cosmabot` **outside** the unit to prove the
   data disk mount.

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
`infra/beta/vm/host/secrets_transport.py` (T-PROD-3-SECRETS / `#388`): after
Sitting 2 closes the vault, open a **second vault window** (§4.1) →
`--stage-from-vault` → §4.5 temporary SSH `/32` open → ssh-stdin install (no
VM value staging) → close-and-verify vault (§4.1) and NSG (§4.5) → mode-0400
service-UID host files; Run Command refused for values (host-key public fetch
only); no Secrets Officer `az login` on the VM; no Bastion; values never
printed. Close-and-verify is mandatory before any Terraform plan/apply.

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

#### Sitting 2 (John) — vault `/32` window, Step A, rotate key1, load all secrets, close (never `secret show`)

John only. The prod vault (`kv-cbot-prd-*`) uses **RBAC** and starts with
`publicNetworkAccess=Disabled`. Every vault **write** in this sitting (LLM key
and the other six secrets, including generated passwords) must sit inside the
temporary public-access window from John's own `/32`, **before** restoring
`Disabled`. **Shell:** bash 3.2+ or default macOS zsh (no `mapfile`). Agents
never run the write.

**Sitting 2 start — paste once** (logs in, prints account **name** and **id**
only, then exports `RG`, `PROD_KV_NAME`, and `KEYFILE`). Every later Sitting 2
paste box uses these exact names. `PROD_KV_NAME` must match
`^kv-cbot-prd-[a-z0-9]+$` and come from exactly one vault whose name starts with
`kv-cbot-prd-` in the prod RG. `KEYFILE=$HOME/.cosmabot-sitting2/llm-key1` —
**this exact path** everywhere in Sitting 2 (mkdir the dir with mode `700`;
file mode `600` via `umask 077`; **no trailing newline**). If `KEYFILE` is
unset mid-sitting, STOP and re-paste this box (never print PASS for an unset
`KEYFILE`). You should see account name/id JSON, then
`PASS: Sitting 2 start exports set` (no secret values):

```bash
az login
az account show --query "{name:name, id:id}" -o json
export RG=rg-cosmabot-prod-eus2-01
if ! _kv_matches=$(az keyvault list --resource-group "$RG" --query "[?starts_with(name, 'kv-cbot-prd-')].name" -o tsv); then
  echo "STOP: Sitting 2 start az keyvault list failed" >&2
elif
  _kv_count=$(printf '%s\n' "$_kv_matches" | sed '/^$/d' | wc -l | tr -d '[:space:]')
  ! test "$_kv_count" = "1"
then
  echo "STOP: Sitting 2 start expected exactly one kv-cbot-prd-* vault in $RG (found ${_kv_count})" >&2
  unset _kv_matches _kv_count PROD_KV_NAME
elif ! printf '%s' "$_kv_matches" | grep -Eq '^kv-cbot-prd-[a-z0-9]+$'; then
  echo "STOP: Sitting 2 start PROD_KV_NAME must match kv-cbot-prd-<suffix>" >&2
  unset _kv_matches _kv_count PROD_KV_NAME
else
  export PROD_KV_NAME="$_kv_matches"
  export KEYFILE=$HOME/.cosmabot-sitting2/llm-key1
  unset _kv_matches _kv_count
  echo "PASS: Sitting 2 start exports set (RG PROD_KV_NAME KEYFILE; values not printed beyond account name/id)"
fi
```

**SSH reach (host install only; not vault):** derive `VM_PUBLIC_IP` in the
§4.5 session box from `pip-cosmabot-prod-eus2-01`. Set `ADMIN_USERNAME` to the
reviewed prod `admin_username`, and `SSH_IDENTITY_PATH` to the private key that
matches `admin_ssh_public_key`. Temporary NSG rule name
**`TEMP-JOHN-SSH-SECRETS-INSTALL`** — see §4.1 “Server access for secrets
install” and [`#388`](https://github.com/CosmaNeura/cosmaneura-os/pull/388).

**Hard rule:** no step may **print** a secret value or put it in shell history /
process **argv**. Never `echo` a secret value. Never `az keyvault secret show`.
Every `az keyvault secret set` must use `--file … --encoding utf-8 --output none`
(never a value in argv). **Allowed:** `printf '%s' "$val" >mode-600-file`
(and the no-echo `read -rs` → printf-to-file path) because `printf` is a shell
builtin and the value is **not** placed in process argv. Never assign a secret
value to a lasting shell variable for display. Step A STOP reasons go to
**stderr** so they are not captured into `ACCOUNT_ID`. On any Step A failure,
clear `ACCOUNT_ID`.

`ACCOUNT_ID` must match this full resource-id regex (anchored with `^` and
`$`) in Fence 1, rotate, Fence 2, and Step B:

`^/subscriptions/[^/]+/resourceGroups/rg-cosmabot-prod-eus2-01/providers/Microsoft\.CognitiveServices/accounts/oai-cbot-prd-[a-z0-9]{6,10}$`

**Fence 0 — open vault public access for John's `/32` only** (detect IP with a
command that prints **only** the IP; then enable + add rule). Saves the `/32`
to `$HOME/.cosmabot-sitting2/john-32.ip` (mode `600`) so close can work without
relying on the current shell. All `az` writes use `--output none` except the
read-only verify (access flag + rule count only). Paste this **before** any
`secret set`:

```bash
cosmabot_kv_open_john_32() {
  command -v az >/dev/null || {
    echo "STOP: kv-open needs az" >&2
    return 1
  }
  command -v curl >/dev/null || {
    echo "STOP: kv-open needs curl" >&2
    return 1
  }
  test -n "${PROD_KV_NAME:-}" || {
    echo "STOP: kv-open PROD_KV_NAME unset" >&2
    return 1
  }
  test -n "${RG:-}" || {
    echo "STOP: kv-open RG unset" >&2
    return 1
  }
  printf '%s' "$PROD_KV_NAME" | grep -Eq '^kv-cbot-prd-[a-z0-9]+$' || {
    echo "STOP: kv-open PROD_KV_NAME must match kv-cbot-prd-<suffix>" >&2
    return 1
  }
  SITDIR="$HOME/.cosmabot-sitting2"
  IPFILE="$SITDIR/john-32.ip"
  (
    umask 077
    mkdir -m 700 -p "$SITDIR" || exit 1
  ) || {
    echo "STOP: kv-open sitting2 dir failed" >&2
    return 1
  }
  MY_IP=$(curl -4 -fsS --max-time 15 https://api.ipify.org) || {
    echo "STOP: kv-open IP detect failed" >&2
    return 1
  }
  MY_IP=$(printf '%s' "$MY_IP" | tr -d '[:space:]')
  printf '%s' "$MY_IP" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || {
    echo "STOP: kv-open MY_IP is not a dotted IPv4" >&2
    return 1
  }
  (
    umask 077
    printf '%s\n' "${MY_IP}/32" >"$IPFILE" || exit 1
    chmod 600 "$IPFILE" || exit 1
  ) || {
    echo "STOP: kv-open save john-32.ip failed" >&2
    return 1
  }
  az keyvault update \
    --name "$PROD_KV_NAME" \
    --resource-group "$RG" \
    --public-network-access Enabled \
    --default-action Deny \
    --output none || {
    echo "STOP: kv-open update Enabled failed - run kv-close before leaving" >&2
    return 1
  }
  az keyvault network-rule add \
    --name "$PROD_KV_NAME" \
    --resource-group "$RG" \
    --ip-address "${MY_IP}/32" \
    --output none || {
    echo "STOP: kv-open network-rule add failed - run kv-close before leaving" >&2
    return 1
  }
  ACCESS=$(az keyvault show --name "$PROD_KV_NAME" --resource-group "$RG" \
    --query properties.publicNetworkAccess -o tsv) || {
    echo "STOP: kv-open verify access failed" >&2
    return 1
  }
  COUNT=$(az keyvault show --name "$PROD_KV_NAME" --resource-group "$RG" \
    --query "length(properties.networkAcls.ipRules)" -o tsv) || {
    echo "STOP: kv-open verify rule count failed" >&2
    return 1
  }
  test "$ACCESS" = "Enabled" || {
    echo "STOP: kv-open publicNetworkAccess is not Enabled" >&2
    return 1
  }
  test "$COUNT" = "1" || {
    echo "STOP: kv-open expected exactly one ipRules entry" >&2
    return 1
  }
  echo "PASS: vault public access Enabled with one /32 rule (IP value not repeated)"
  return 0
}
cosmabot_kv_open_john_32 || {
  echo "STOP: kv-open failed - do not load secrets; close-and-verify if partially open" >&2
  false
}
```

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
    mkdir -m 700 -p "$(dirname "$KEYFILE")" || exit 1
    rm -f "$KEYFILE" || exit 1
    az cognitiveservices account keys regenerate \
      --resource-group "$RG" \
      --name "${ACCOUNT_ID##*/}" \
      --key-name key1 \
      --query key1 -o tsv | tr -d '\n' > "$KEYFILE" || exit 1
    chmod 600 "$KEYFILE" || exit 1
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
    --encoding utf-8 \
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

**`$KEYFILE` keep vs remove (L-1 / residual Lows):** do not leave a key file on
disk after a failed or abandoned sitting. There is **no** “skip the STOP-path
`rm`” keep path.

| Outcome | `$KEYFILE` |
| --- | --- |
| Step B **PASS** | **Remove** (`rm -f`, verify `! -e`, clear `KEYFILE` inside the function). |
| Step B **STOP** | **Remove** (fail-safe on the STOP path below). Then close the vault (§4.3). A retry after STOP means: **re-export** `KEYFILE=$HOME/.cosmabot-sitting2/llm-key1`, **re-rotate**, then Fence 2, then Step B. |
| Re-run **rotate** to retry | **Remove** any old `$KEYFILE` first (rotate does). Must also re-run **Fence 2**, then Step B. |
| **Abandon sitting** / interrupt / will not retry | Close vault first (§4.3), then **Remove** via §4.3 abandon cleanup. |

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
  test -n "${KEYFILE:-}" || {
    echo "STOP: Step B PASS path KEYFILE unset" >&2
    return 1
  }
  rm -f "$KEYFILE" || {
    echo "STOP: Step B PASS path KEYFILE rm failed" >&2
    return 1
  }
  test ! -e "$KEYFILE" || {
    echo "STOP: Step B PASS path KEYFILE still exists after rm" >&2
    return 1
  }
  KEYFILE=
  echo "PASS: Step B source-account tag matches Step A"
  return 0
}
cosmabot_llm_kv_step_b_verify_tag || {
  echo "STOP: Step B failed - close vault per section 4.3; fail-safe removing sitting2 secret files; retry means re-export KEYFILE, re-rotate, then Fence 2" >&2
  rm -f "${KEYFILE:-}" \
    "$HOME/.cosmabot-sitting2/DATABASE-PASSWORD.value" \
    "$HOME/.cosmabot-sitting2/POSTGRES-PASSWORD.value" \
    "$HOME/.cosmabot-sitting2/REDIS-PASSWORD.value" \
    "$HOME/.cosmabot-sitting2/prompt-CLERK-SECRET-KEY.tmp" \
    "$HOME/.cosmabot-sitting2/prompt-CLERK-ACCOUNT-DELETION-SECRET.tmp" \
    "$HOME/.cosmabot-sitting2/prompt-HUMAN-DEPLOY-EVIDENCE-REF.tmp"
  KEYFILE=
  false
}
```

**Do not close the vault yet.** Generate passwords and load the other six
secrets first (ordering: every secret load, including generated passwords,
happens **before** public network access is disabled again).

**Fence — generate mode-600 password files** (workstation; CSPRNG; never print
values). Writes three distinct URL-safe password files under the mode-`700`
dir `$HOME/.cosmabot-sitting2/` (password value files stay out of the default
tmp dir; file mode `600`) named for vault secrets `DATABASE-PASSWORD`,
`POSTGRES-PASSWORD`, and `REDIS-PASSWORD`. Trap on `EXIT`/`INT`/`TERM`/`HUP`
removes those files on interrupt. Trap save is shell-portable (bash: `trap -p`;
zsh: `trap` listing — never `trap -p` in zsh, which sets a trap to the command
`-p`). In zsh the short-lived trap-listing scratch file uses `mktemp` under
`${TMPDIR:-/tmp}` (mode `600`) and is removed before return, or by a cleanup
trap armed before the parse loop if that loop is interrupted. Restore only
reinstalls what was saved, or clears the signal when save showed none; it never
clears a trap it did not capture. In zsh, `EXIT` traps set inside a function are
function-local, so restore runs via `eval` in that same function. If zsh
`TRAPxxx` function traps are already set, STOP and run this fence in a **fresh
terminal**:

```bash
cosmabot_sitting2_writer_save_traps() {
  if test -n "${ZSH_VERSION:-}"; then
    if typeset -f TRAPINT >/dev/null 2>&1 \
      || typeset -f TRAPTERM >/dev/null 2>&1 \
      || typeset -f TRAPHUP >/dev/null 2>&1 \
      || typeset -f TRAPEXIT >/dev/null 2>&1; then
      echo "STOP: zsh TRAPxxx function traps present - run this fence in a fresh terminal" >&2
      return 1
    fi
    _writer_trap_tmp=$(umask 077; mktemp "${TMPDIR:-/tmp}/cosmabot-wtraps.XXXXXX") || {
      echo "STOP: zsh trap-save mktemp failed - run this fence in a fresh terminal" >&2
      return 1
    }
    chmod 600 "$_writer_trap_tmp" || {
      rm -f "$_writer_trap_tmp"
      echo "STOP: zsh trap-save chmod failed - run this fence in a fresh terminal" >&2
      return 1
    }
    trap >"$_writer_trap_tmp" || {
      rm -f "$_writer_trap_tmp"
      echo "STOP: zsh trap save failed - run this fence in a fresh terminal" >&2
      return 1
    }
    _writer_prev_exit=
    _writer_prev_int=
    _writer_prev_term=
    _writer_prev_hup=
    trap 'rm -f "${_writer_trap_tmp:-}"' EXIT INT TERM HUP
    while IFS= read -r _trap_line || test -n "${_trap_line:-}"; do
      case "$_trap_line" in
        *" EXIT") _writer_prev_exit=$_trap_line ;;
        *" INT"|*" SIGINT") _writer_prev_int=$_trap_line ;;
        *" TERM"|*" SIGTERM") _writer_prev_term=$_trap_line ;;
        *" HUP"|*" SIGHUP") _writer_prev_hup=$_trap_line ;;
      esac
    done <"$_writer_trap_tmp"
    rm -f "$_writer_trap_tmp" || {
      rm -f "$_writer_trap_tmp"
      if test -n "${_writer_prev_exit:-}"; then eval "${_writer_prev_exit}"; else trap - EXIT; fi
      if test -n "${_writer_prev_int:-}"; then eval "${_writer_prev_int}"; else trap - INT; fi
      if test -n "${_writer_prev_term:-}"; then eval "${_writer_prev_term}"; else trap - TERM; fi
      if test -n "${_writer_prev_hup:-}"; then eval "${_writer_prev_hup}"; else trap - HUP; fi
      unset _writer_trap_tmp
      echo "STOP: zsh trap-save temp rm failed - run this fence in a fresh terminal" >&2
      return 1
    }
    test ! -e "$_writer_trap_tmp" || {
      rm -f "$_writer_trap_tmp"
      if test -n "${_writer_prev_exit:-}"; then eval "${_writer_prev_exit}"; else trap - EXIT; fi
      if test -n "${_writer_prev_int:-}"; then eval "${_writer_prev_int}"; else trap - INT; fi
      if test -n "${_writer_prev_term:-}"; then eval "${_writer_prev_term}"; else trap - TERM; fi
      if test -n "${_writer_prev_hup:-}"; then eval "${_writer_prev_hup}"; else trap - HUP; fi
      unset _writer_trap_tmp
      echo "STOP: zsh trap-save temp still exists - run this fence in a fresh terminal" >&2
      return 1
    }
    if test -n "${_writer_prev_exit:-}"; then eval "${_writer_prev_exit}"; else trap - EXIT; fi
    if test -n "${_writer_prev_int:-}"; then eval "${_writer_prev_int}"; else trap - INT; fi
    if test -n "${_writer_prev_term:-}"; then eval "${_writer_prev_term}"; else trap - TERM; fi
    if test -n "${_writer_prev_hup:-}"; then eval "${_writer_prev_hup}"; else trap - HUP; fi
    unset _writer_trap_tmp
  else
    _writer_prev_exit=$(trap -p EXIT)
    _writer_prev_int=$(trap -p INT)
    _writer_prev_term=$(trap -p TERM)
    _writer_prev_hup=$(trap -p HUP)
  fi
  return 0
}
cosmabot_sitting2_writer_restore_traps() {
  if test -n "${_writer_prev_exit:-}"; then
    printf '%s\n' 'eval "${_writer_prev_exit}"'
  else
    printf '%s\n' 'trap - EXIT'
  fi
  if test -n "${_writer_prev_int:-}"; then
    printf '%s\n' 'eval "${_writer_prev_int}"'
  else
    printf '%s\n' 'trap - INT'
  fi
  if test -n "${_writer_prev_term:-}"; then
    printf '%s\n' 'eval "${_writer_prev_term}"'
  else
    printf '%s\n' 'trap - TERM'
  fi
  if test -n "${_writer_prev_hup:-}"; then
    printf '%s\n' 'eval "${_writer_prev_hup}"'
  else
    printf '%s\n' 'trap - HUP'
  fi
  printf '%s\n' 'unset _writer_prev_exit _writer_prev_int _writer_prev_term _writer_prev_hup'
}
cosmabot_sitting2_write_password_file() {
  command -v openssl >/dev/null || {
    echo "STOP: password file needs openssl" >&2
    return 1
  }
  set +x
  SITDIR="$HOME/.cosmabot-sitting2"
  DBF="$SITDIR/DATABASE-PASSWORD.value"
  PGF="$SITDIR/POSTGRES-PASSWORD.value"
  RDF="$SITDIR/REDIS-PASSWORD.value"
  cosmabot_sitting2_writer_save_traps || return 1
  trap 'rm -f "$DBF" "$PGF" "$RDF"' EXIT INT TERM HUP
  (
    umask 077
    mkdir -m 700 -p "$SITDIR" || exit 1
    rm -f "$DBF" "$PGF" "$RDF" || exit 1
    openssl rand -base64 32 | tr -d '\n=+/ ' >"$DBF" || exit 1
    openssl rand -base64 32 | tr -d '\n=+/ ' >"$PGF" || exit 1
    openssl rand -base64 32 | tr -d '\n=+/ ' >"$RDF" || exit 1
    chmod 600 "$DBF" "$PGF" "$RDF" || exit 1
    test -s "$DBF" && test -s "$PGF" && test -s "$RDF" || exit 1
  ) || {
    echo "STOP: password file write failed" >&2
    rm -f "$DBF" "$PGF" "$RDF"
    eval "$(cosmabot_sitting2_writer_restore_traps)"
    return 1
  }
  for _pf in "$DBF" "$PGF" "$RDF"; do
    _mode=$(stat -c '%a' "$_pf" 2>/dev/null || stat -f '%Lp' "$_pf") || {
      echo "STOP: password file stat failed" >&2
      rm -f "$DBF" "$PGF" "$RDF"
      eval "$(cosmabot_sitting2_writer_restore_traps)"
      return 1
    }
    test "$_mode" = "600" || {
      echo "STOP: password file not mode 600" >&2
      rm -f "$DBF" "$PGF" "$RDF"
      eval "$(cosmabot_sitting2_writer_restore_traps)"
      return 1
    }
  done
  eval "$(cosmabot_sitting2_writer_restore_traps)"
  echo "PASS: mode-600 password files written (values not printed)"
  return 0
}
cosmabot_sitting2_write_password_file || {
  echo "STOP: password file failed - close vault per section 4.3" >&2
  false
}
```

**Fence — load the other six vault secrets** (still inside the `/32` window;
`--file` + `--encoding utf-8` + `--output none`; never a value in argv; never
`echo` a value). Password files come from the fence above. For Clerk / evidence
values John already holds in local mode-600 files, point the `*_FILE` exports
at those paths. For a no-echo prompt path, the helper writes a mode-600 file
under `$HOME/.cosmabot-sitting2/` (**never** default tmp), loads it, then
`rm` + `test ! -e`, with trap cleanup on `EXIT`/`INT`/`TERM`/`HUP`.
The prompt helper and this load fence use **separate** saved-trap variables
(`_prompt_prev_*` vs `_load_prev_*`) and each restores/clears every signal it
set (including `HUP`), so no `rm` trap is left in John's interactive shell and
nothing lingers into kv-close or a second vault window. Trap save is
shell-portable (bash: `trap -p`; zsh: `trap` listing — never `trap -p` in zsh).
Restore only reinstalls what was saved, or clears the signal when save showed
none; it never clears a trap it did not capture. Restore is `eval "$(…_restore_traps)"`
in the same function that set the traps (zsh `EXIT` is function-local). If zsh `TRAPxxx` function
traps are already set, STOP and run this fence in a **fresh terminal**.
On **any** STOP — including when `PROD_KV_NAME` is unset — this fence sets the
three password-file paths first, then calls `cosmabot_sitting2_rm_password_files`
(`rm` + `test ! -e` each) before returning (do not leave that to abandon).
After any load STOP the password files are **gone**, so a retry must re-run the
password-file fence first.
`printf '%s' "$_val" >file` is the allowed write path (builtin; not argv):

```bash
cosmabot_kv_set_from_file() {
  _name=$1
  _file=$2
  set +x
  test -n "$_name" && test -n "$_file" || {
    echo "STOP: kv-set name or file missing" >&2
    return 1
  }
  test -s "$_file" || {
    echo "STOP: kv-set file missing or empty for $_name" >&2
    return 1
  }
  az keyvault secret set \
    --vault-name "$PROD_KV_NAME" \
    --name "$_name" \
    --file "$_file" \
    --encoding utf-8 \
    --output none || {
    echo "STOP: kv-set failed for $_name" >&2
    return 1
  }
  echo "PASS: loaded $_name (value not printed)"
  return 0
}
cosmabot_sitting2_prompt_save_traps() {
  if test -n "${ZSH_VERSION:-}"; then
    if typeset -f TRAPINT >/dev/null 2>&1 \
      || typeset -f TRAPTERM >/dev/null 2>&1 \
      || typeset -f TRAPHUP >/dev/null 2>&1 \
      || typeset -f TRAPEXIT >/dev/null 2>&1; then
      echo "STOP: zsh TRAPxxx function traps present - run this fence in a fresh terminal" >&2
      return 1
    fi
    _prompt_trap_tmp=$(umask 077; mktemp "${TMPDIR:-/tmp}/cosmabot-ptraps.XXXXXX") || {
      echo "STOP: zsh trap-save mktemp failed - run this fence in a fresh terminal" >&2
      return 1
    }
    chmod 600 "$_prompt_trap_tmp" || {
      rm -f "$_prompt_trap_tmp"
      echo "STOP: zsh trap-save chmod failed - run this fence in a fresh terminal" >&2
      return 1
    }
    trap >"$_prompt_trap_tmp" || {
      rm -f "$_prompt_trap_tmp"
      echo "STOP: zsh trap save failed - run this fence in a fresh terminal" >&2
      return 1
    }
    _prompt_prev_exit=
    _prompt_prev_int=
    _prompt_prev_term=
    _prompt_prev_hup=
    trap 'rm -f "${_prompt_trap_tmp:-}"' EXIT INT TERM HUP
    while IFS= read -r _trap_line || test -n "${_trap_line:-}"; do
      case "$_trap_line" in
        *" EXIT") _prompt_prev_exit=$_trap_line ;;
        *" INT"|*" SIGINT") _prompt_prev_int=$_trap_line ;;
        *" TERM"|*" SIGTERM") _prompt_prev_term=$_trap_line ;;
        *" HUP"|*" SIGHUP") _prompt_prev_hup=$_trap_line ;;
      esac
    done <"$_prompt_trap_tmp"
    rm -f "$_prompt_trap_tmp" || {
      rm -f "$_prompt_trap_tmp"
      if test -n "${_prompt_prev_exit:-}"; then eval "${_prompt_prev_exit}"; else trap - EXIT; fi
      if test -n "${_prompt_prev_int:-}"; then eval "${_prompt_prev_int}"; else trap - INT; fi
      if test -n "${_prompt_prev_term:-}"; then eval "${_prompt_prev_term}"; else trap - TERM; fi
      if test -n "${_prompt_prev_hup:-}"; then eval "${_prompt_prev_hup}"; else trap - HUP; fi
      unset _prompt_trap_tmp
      echo "STOP: zsh trap-save temp rm failed - run this fence in a fresh terminal" >&2
      return 1
    }
    test ! -e "$_prompt_trap_tmp" || {
      rm -f "$_prompt_trap_tmp"
      if test -n "${_prompt_prev_exit:-}"; then eval "${_prompt_prev_exit}"; else trap - EXIT; fi
      if test -n "${_prompt_prev_int:-}"; then eval "${_prompt_prev_int}"; else trap - INT; fi
      if test -n "${_prompt_prev_term:-}"; then eval "${_prompt_prev_term}"; else trap - TERM; fi
      if test -n "${_prompt_prev_hup:-}"; then eval "${_prompt_prev_hup}"; else trap - HUP; fi
      unset _prompt_trap_tmp
      echo "STOP: zsh trap-save temp still exists - run this fence in a fresh terminal" >&2
      return 1
    }
    if test -n "${_prompt_prev_exit:-}"; then eval "${_prompt_prev_exit}"; else trap - EXIT; fi
    if test -n "${_prompt_prev_int:-}"; then eval "${_prompt_prev_int}"; else trap - INT; fi
    if test -n "${_prompt_prev_term:-}"; then eval "${_prompt_prev_term}"; else trap - TERM; fi
    if test -n "${_prompt_prev_hup:-}"; then eval "${_prompt_prev_hup}"; else trap - HUP; fi
    unset _prompt_trap_tmp
  else
    _prompt_prev_exit=$(trap -p EXIT)
    _prompt_prev_int=$(trap -p INT)
    _prompt_prev_term=$(trap -p TERM)
    _prompt_prev_hup=$(trap -p HUP)
  fi
  return 0
}
cosmabot_sitting2_prompt_restore_traps() {
  if test -n "${_prompt_prev_exit:-}"; then
    printf '%s\n' 'eval "${_prompt_prev_exit}"'
  else
    printf '%s\n' 'trap - EXIT'
  fi
  if test -n "${_prompt_prev_int:-}"; then
    printf '%s\n' 'eval "${_prompt_prev_int}"'
  else
    printf '%s\n' 'trap - INT'
  fi
  if test -n "${_prompt_prev_term:-}"; then
    printf '%s\n' 'eval "${_prompt_prev_term}"'
  else
    printf '%s\n' 'trap - TERM'
  fi
  if test -n "${_prompt_prev_hup:-}"; then
    printf '%s\n' 'eval "${_prompt_prev_hup}"'
  else
    printf '%s\n' 'trap - HUP'
  fi
  printf '%s\n' 'unset _prompt_prev_exit _prompt_prev_int _prompt_prev_term _prompt_prev_hup'
}
cosmabot_kv_set_from_prompt_file() {
  _name=$1
  set +x
  SITDIR="$HOME/.cosmabot-sitting2"
  (
    umask 077
    mkdir -m 700 -p "$SITDIR" || exit 1
  ) || {
    echo "STOP: kv-set prompt sitting2 dir failed for $_name" >&2
    return 1
  }
  _tmp="$SITDIR/prompt-${_name}.tmp"
  cosmabot_sitting2_prompt_save_traps || return 1
  trap 'rm -f "$_tmp"' EXIT INT TERM HUP
  rm -f "$_tmp" || {
    echo "STOP: kv-set prompt pre-rm failed for $_name" >&2
    eval "$(cosmabot_sitting2_prompt_restore_traps)"
    return 1
  }
  (
    umask 077
    : >"$_tmp" || exit 1
    chmod 600 "$_tmp" || exit 1
  ) || {
    rm -f "$_tmp"
    echo "STOP: kv-set prompt chmod failed for $_name" >&2
    eval "$(cosmabot_sitting2_prompt_restore_traps)"
    return 1
  }
  printf 'Paste value for %s (no echo), then Enter: ' "$_name" >&2
  read -rs _val || {
    rm -f "$_tmp"
    echo "STOP: kv-set prompt read failed for $_name" >&2
    eval "$(cosmabot_sitting2_prompt_restore_traps)"
    return 1
  }
  printf '\n' >&2
  printf '%s' "$_val" >"$_tmp" || {
    unset _val
    rm -f "$_tmp"
    echo "STOP: kv-set prompt write failed for $_name" >&2
    eval "$(cosmabot_sitting2_prompt_restore_traps)"
    return 1
  }
  unset _val
  cosmabot_kv_set_from_file "$_name" "$_tmp" || {
    rm -f "$_tmp"
    eval "$(cosmabot_sitting2_prompt_restore_traps)"
    return 1
  }
  rm -f "$_tmp" || {
    echo "STOP: kv-set prompt temp rm failed for $_name" >&2
    eval "$(cosmabot_sitting2_prompt_restore_traps)"
    return 1
  }
  test ! -e "$_tmp" || {
    echo "STOP: kv-set prompt temp still exists for $_name" >&2
    eval "$(cosmabot_sitting2_prompt_restore_traps)"
    return 1
  }
  eval "$(cosmabot_sitting2_prompt_restore_traps)"
  return 0
}
cosmabot_sitting2_rm_password_files() {
  rm -f "$DBF" "$PGF" "$RDF" || {
    echo "STOP: other-secrets password file rm failed" >&2
    return 1
  }
  test ! -e "$DBF" || {
    echo "STOP: other-secrets DATABASE-PASSWORD.value still exists" >&2
    return 1
  }
  test ! -e "$PGF" || {
    echo "STOP: other-secrets POSTGRES-PASSWORD.value still exists" >&2
    return 1
  }
  test ! -e "$RDF" || {
    echo "STOP: other-secrets REDIS-PASSWORD.value still exists" >&2
    return 1
  }
  return 0
}
cosmabot_sitting2_load_save_traps() {
  if test -n "${ZSH_VERSION:-}"; then
    if typeset -f TRAPINT >/dev/null 2>&1 \
      || typeset -f TRAPTERM >/dev/null 2>&1 \
      || typeset -f TRAPHUP >/dev/null 2>&1 \
      || typeset -f TRAPEXIT >/dev/null 2>&1; then
      echo "STOP: zsh TRAPxxx function traps present - run this fence in a fresh terminal" >&2
      return 1
    fi
    _load_trap_tmp=$(umask 077; mktemp "${TMPDIR:-/tmp}/cosmabot-ltraps.XXXXXX") || {
      echo "STOP: zsh trap-save mktemp failed - run this fence in a fresh terminal" >&2
      return 1
    }
    chmod 600 "$_load_trap_tmp" || {
      rm -f "$_load_trap_tmp"
      echo "STOP: zsh trap-save chmod failed - run this fence in a fresh terminal" >&2
      return 1
    }
    trap >"$_load_trap_tmp" || {
      rm -f "$_load_trap_tmp"
      echo "STOP: zsh trap save failed - run this fence in a fresh terminal" >&2
      return 1
    }
    _load_prev_exit=
    _load_prev_int=
    _load_prev_term=
    _load_prev_hup=
    trap 'rm -f "${_load_trap_tmp:-}"' EXIT INT TERM HUP
    while IFS= read -r _trap_line || test -n "${_trap_line:-}"; do
      case "$_trap_line" in
        *" EXIT") _load_prev_exit=$_trap_line ;;
        *" INT"|*" SIGINT") _load_prev_int=$_trap_line ;;
        *" TERM"|*" SIGTERM") _load_prev_term=$_trap_line ;;
        *" HUP"|*" SIGHUP") _load_prev_hup=$_trap_line ;;
      esac
    done <"$_load_trap_tmp"
    rm -f "$_load_trap_tmp" || {
      rm -f "$_load_trap_tmp"
      if test -n "${_load_prev_exit:-}"; then eval "${_load_prev_exit}"; else trap - EXIT; fi
      if test -n "${_load_prev_int:-}"; then eval "${_load_prev_int}"; else trap - INT; fi
      if test -n "${_load_prev_term:-}"; then eval "${_load_prev_term}"; else trap - TERM; fi
      if test -n "${_load_prev_hup:-}"; then eval "${_load_prev_hup}"; else trap - HUP; fi
      unset _load_trap_tmp
      echo "STOP: zsh trap-save temp rm failed - run this fence in a fresh terminal" >&2
      return 1
    }
    test ! -e "$_load_trap_tmp" || {
      rm -f "$_load_trap_tmp"
      if test -n "${_load_prev_exit:-}"; then eval "${_load_prev_exit}"; else trap - EXIT; fi
      if test -n "${_load_prev_int:-}"; then eval "${_load_prev_int}"; else trap - INT; fi
      if test -n "${_load_prev_term:-}"; then eval "${_load_prev_term}"; else trap - TERM; fi
      if test -n "${_load_prev_hup:-}"; then eval "${_load_prev_hup}"; else trap - HUP; fi
      unset _load_trap_tmp
      echo "STOP: zsh trap-save temp still exists - run this fence in a fresh terminal" >&2
      return 1
    }
    if test -n "${_load_prev_exit:-}"; then eval "${_load_prev_exit}"; else trap - EXIT; fi
    if test -n "${_load_prev_int:-}"; then eval "${_load_prev_int}"; else trap - INT; fi
    if test -n "${_load_prev_term:-}"; then eval "${_load_prev_term}"; else trap - TERM; fi
    if test -n "${_load_prev_hup:-}"; then eval "${_load_prev_hup}"; else trap - HUP; fi
    unset _load_trap_tmp
  else
    _load_prev_exit=$(trap -p EXIT)
    _load_prev_int=$(trap -p INT)
    _load_prev_term=$(trap -p TERM)
    _load_prev_hup=$(trap -p HUP)
  fi
  return 0
}
cosmabot_sitting2_load_restore_traps() {
  if test -n "${_load_prev_exit:-}"; then
    printf '%s\n' 'eval "${_load_prev_exit}"'
  else
    printf '%s\n' 'trap - EXIT'
  fi
  if test -n "${_load_prev_int:-}"; then
    printf '%s\n' 'eval "${_load_prev_int}"'
  else
    printf '%s\n' 'trap - INT'
  fi
  if test -n "${_load_prev_term:-}"; then
    printf '%s\n' 'eval "${_load_prev_term}"'
  else
    printf '%s\n' 'trap - TERM'
  fi
  if test -n "${_load_prev_hup:-}"; then
    printf '%s\n' 'eval "${_load_prev_hup}"'
  else
    printf '%s\n' 'trap - HUP'
  fi
  printf '%s\n' 'unset _load_prev_exit _load_prev_int _load_prev_term _load_prev_hup'
}
cosmabot_sitting2_load_other_secrets() {
  set +x
  SITDIR="$HOME/.cosmabot-sitting2"
  DBF="$SITDIR/DATABASE-PASSWORD.value"
  PGF="$SITDIR/POSTGRES-PASSWORD.value"
  RDF="$SITDIR/REDIS-PASSWORD.value"
  test -n "${PROD_KV_NAME:-}" || {
    echo "STOP: other-secrets PROD_KV_NAME unset" >&2
    cosmabot_sitting2_rm_password_files
    return 1
  }
  cosmabot_sitting2_load_save_traps || {
    cosmabot_sitting2_rm_password_files
    return 1
  }
  trap 'rm -f "$DBF" "$PGF" "$RDF" "$SITDIR/prompt-CLERK-SECRET-KEY.tmp" "$SITDIR/prompt-CLERK-ACCOUNT-DELETION-SECRET.tmp" "$SITDIR/prompt-HUMAN-DEPLOY-EVIDENCE-REF.tmp"' EXIT INT TERM HUP
  cosmabot_kv_set_from_file DATABASE-PASSWORD "$DBF" || {
    cosmabot_sitting2_rm_password_files
    eval "$(cosmabot_sitting2_load_restore_traps)"
    return 1
  }
  cosmabot_kv_set_from_file POSTGRES-PASSWORD "$PGF" || {
    cosmabot_sitting2_rm_password_files
    eval "$(cosmabot_sitting2_load_restore_traps)"
    return 1
  }
  cosmabot_kv_set_from_file REDIS-PASSWORD "$RDF" || {
    cosmabot_sitting2_rm_password_files
    eval "$(cosmabot_sitting2_load_restore_traps)"
    return 1
  }
  cosmabot_sitting2_rm_password_files || {
    eval "$(cosmabot_sitting2_load_restore_traps)"
    return 1
  }
  if test -n "${CLERK_SECRET_KEY_FILE:-}" && test -s "${CLERK_SECRET_KEY_FILE}"; then
    cosmabot_kv_set_from_file CLERK-SECRET-KEY "$CLERK_SECRET_KEY_FILE" || {
      cosmabot_sitting2_rm_password_files
      eval "$(cosmabot_sitting2_load_restore_traps)"
      return 1
    }
  else
    cosmabot_kv_set_from_prompt_file CLERK-SECRET-KEY || {
      cosmabot_sitting2_rm_password_files
      eval "$(cosmabot_sitting2_load_restore_traps)"
      return 1
    }
  fi
  if test -n "${CLERK_ACCOUNT_DELETION_SECRET_FILE:-}" && test -s "${CLERK_ACCOUNT_DELETION_SECRET_FILE}"; then
    cosmabot_kv_set_from_file CLERK-ACCOUNT-DELETION-SECRET "$CLERK_ACCOUNT_DELETION_SECRET_FILE" || {
      cosmabot_sitting2_rm_password_files
      eval "$(cosmabot_sitting2_load_restore_traps)"
      return 1
    }
  else
    cosmabot_kv_set_from_prompt_file CLERK-ACCOUNT-DELETION-SECRET || {
      cosmabot_sitting2_rm_password_files
      eval "$(cosmabot_sitting2_load_restore_traps)"
      return 1
    }
  fi
  if test -n "${HUMAN_DEPLOY_EVIDENCE_REF_FILE:-}" && test -s "${HUMAN_DEPLOY_EVIDENCE_REF_FILE}"; then
    cosmabot_kv_set_from_file HUMAN-DEPLOY-EVIDENCE-REF "$HUMAN_DEPLOY_EVIDENCE_REF_FILE" || {
      cosmabot_sitting2_rm_password_files
      eval "$(cosmabot_sitting2_load_restore_traps)"
      return 1
    }
  else
    cosmabot_kv_set_from_prompt_file HUMAN-DEPLOY-EVIDENCE-REF || {
      cosmabot_sitting2_rm_password_files
      eval "$(cosmabot_sitting2_load_restore_traps)"
      return 1
    }
  fi
  eval "$(cosmabot_sitting2_load_restore_traps)"
  echo "PASS: other six vault secrets loaded (values not printed)"
  return 0
}
cosmabot_sitting2_load_other_secrets || {
  echo "STOP: other-secrets load failed - close vault per section 4.3 before leaving" >&2
  false
}
```

**Fence — close vault `/32` and verify** (Sitting 2 gate). **Mandatory even
after a STOP partway through** this sitting, including from a **new shell**.
Order is fixed: (1) set `publicNetworkAccess=Disabled` **first**, (2) remove
**every** IP rule from `az keyvault network-rule list` (and the `/32` saved in
`$HOME/.cosmabot-sitting2/john-32.ip` if present; at most 32 successful
removes, then STOP only if a rule still remains), (3) verify **last** that
access is Disabled **and** rule count is 0, then `rm` + `test ! -e` the
saved `john-32.ip` on the success path. Close must **not** depend on
`MY_IP`, ipify, or the current shell. A failed lookup or dead terminal must
never leave the vault Enabled:

```bash
cosmabot_kv_close_john_32() {
  command -v az >/dev/null || {
    echo "STOP: kv-close needs az" >&2
    return 1
  }
  test -n "${PROD_KV_NAME:-}" || {
    echo "STOP: kv-close PROD_KV_NAME unset" >&2
    return 1
  }
  test -n "${RG:-}" || {
    echo "STOP: kv-close RG unset" >&2
    return 1
  }
  az keyvault update \
    --name "$PROD_KV_NAME" \
    --resource-group "$RG" \
    --public-network-access Disabled \
    --output none || {
    echo "STOP: kv-close update Disabled failed" >&2
    return 1
  }
  IPFILE="$HOME/.cosmabot-sitting2/john-32.ip"
  if test -s "$IPFILE"; then
    _saved=$(tr -d '[:space:]' <"$IPFILE") || _saved=
    if printf '%s' "$_saved" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/32$'; then
      az keyvault network-rule remove \
        --name "$PROD_KV_NAME" \
        --resource-group "$RG" \
        --ip-address "$_saved" \
        --output none 2>/dev/null || true
    fi
  fi
  _n=0
  while test "$_n" -lt 32; do
    _ip=$(az keyvault network-rule list \
      --name "$PROD_KV_NAME" \
      --resource-group "$RG" \
      --query "ipRules[0].value" -o tsv 2>/dev/null) || _ip=
    test -n "$_ip" || break
    az keyvault network-rule remove \
      --name "$PROD_KV_NAME" \
      --resource-group "$RG" \
      --ip-address "$_ip" \
      --output none || {
      echo "STOP: kv-close network-rule remove failed" >&2
      return 1
    }
    _n=$((_n + 1))
  done
  _ip=$(az keyvault network-rule list \
    --name "$PROD_KV_NAME" \
    --resource-group "$RG" \
    --query "ipRules[0].value" -o tsv 2>/dev/null) || _ip=
  if test -n "$_ip"; then
    echo "STOP: kv-close rule remove loop bound exceeded" >&2
    return 1
  fi
  ACCESS=$(az keyvault show --name "$PROD_KV_NAME" --resource-group "$RG" \
    --query properties.publicNetworkAccess -o tsv) || {
    echo "STOP: kv-close verify access failed" >&2
    return 1
  }
  COUNT=$(az keyvault show --name "$PROD_KV_NAME" --resource-group "$RG" \
    --query "length(properties.networkAcls.ipRules)" -o tsv) || {
    echo "STOP: kv-close verify rule count failed" >&2
    return 1
  }
  printf 'publicNetworkAccess=%s ipRules_count=%s\n' "$ACCESS" "$COUNT"
  test "$ACCESS" = "Disabled" || {
    echo "STOP: kv-close publicNetworkAccess is not Disabled" >&2
    return 1
  }
  test "$COUNT" = "0" || {
    echo "STOP: kv-close ipRules not empty" >&2
    return 1
  }
  rm -f "$IPFILE" || {
    echo "STOP: kv-close john-32.ip rm failed" >&2
    return 1
  }
  test ! -e "$IPFILE" || {
    echo "STOP: kv-close john-32.ip still exists" >&2
    return 1
  }
  echo "PASS: vault public access Disabled and ipRules empty"
  return 0
}
cosmabot_kv_close_john_32 || {
  echo "STOP: vault still open or ipRules not empty - fix before continuing" >&2
  false
}
```

If the session is interrupted or abandoned, jump to §4.3 first (close-and-verify,
then abandon sitting2 cleanup / dead-terminal dir recovery).

#### Server access for secrets install (temporary SSH `/32` + second vault window)

John (9:45am ET): open sign-in to his address for the install, then close it.
Full pasteable fences and ssh-stdin install live in **§4.5**
(`infra/beta/vm/host/fences/`, `secrets_transport.py`). Do not invent a second
transport here.

**One order** (Sitting 2 row 5 / after format-disk yes + continue-prep yes /
host README / checklist): `#389` bootstrap → **second vault window** +
`TEMP-JOHN-SSH-SECRETS-INSTALL` → install → close-and-verify → **§4.5**.
Sitting 2 row 1 already closed the vault and deleted local sitting2 files.
For host install (`#388`):

0. `#389` host bootstrap so `/etc/cosmabot` exists (paste boxes below; before any
   SSH secrets install). Build the creation receipt on the workstation with
   `build_creation_receipt.py` (receipt-tool paste), open a temporary SSH `/32`
   with the existing §4.5 open fence, copy the reviewed `host/` + sibling
   `logging/` tree onto the VM, place the receipt as a root-owned mode-0600
   file at `/root/cosmabot-creation-receipt.json` (receipt-place paste; outside
   `/etc/cosmabot`), then run bootstrap from a root shell. Do not create
   `/etc/cosmabot` and do not place the receipt under it before bootstrap.
   Close-and-verify that SSH rule (and confirm
   `/etc/cosmabot/host-bootstrap.json` exists) before the second vault window
   or secrets session. After a successful bootstrap, remote secrets install
   pre-checks `/etc/cosmabot`, then `install -d -o root -g root -m 0700` for
   the release root (does not invent `/etc/cosmabot`; bootstrap must have
   created it).
1. Re-open the vault with the **same** §4.1 open fence
   (`cosmabot_kv_open_john_32`) only after bootstrap-close PASSes (including
   the `host-bootstrap.json` guard).
2. Workstation stage-from-vault paste box below (`LOCAL_STAGING` + full catalog;
   values never printed). Path shape + session `--check-staging-complete`:
   every expected catalog host name must be present and non-empty — bad path,
   empty, or partial staging is STOP before SSH open (nothing opened; no PASS).
3. §4.5: open `TEMP-JOHN-SSH-SECRETS-INSTALL` (John `/32`, priority 200) →
   ssh-stdin install to final mode-0400 destinations (no VM `/tmp` or `/root`
   value staging; no `scp` of values; `ADMIN_USERNAME` + `-i` identity from the
   §4.5 session box) → close-and-verify NSG.
4. Close the vault with the **same** §4.1 close-first fence
   (`cosmabot_kv_close_john_32`) and the read-only verify — Disabled first,
   remove every listed rule, verify last.
5. If the terminal closed partway: §4.5 recovery **always** deletes
   `TEMP-JOHN-SSH-SECRETS-INSTALL`, verifies NSG closed, and prints the result.
   Wrong-shape `LOCAL_STAGING` is a STOP before recovery runs. Unset
   `LOCAL_STAGING` prints a NOTE (check and remove any leftover staging folder
   by hand) and still runs recovery so the SSH `/32` rule is deleted. Valid
   shape runs as now; also close the vault.

**Before the bootstrap SSH boxes:** export `ADMIN_USERNAME` to the reviewed
prod `admin_username` and `SSH_IDENTITY_PATH` to the private key path that
matches `admin_ssh_public_key`. You should see both already set (`test -n`
succeeds) before you paste. `RG` comes from the Sitting 2 start box.
`VM_PUBLIC_IP` and `SECRETS_TRANSPORT_PY` are derived in the open box.
`bootstrap_host.py` reads `../logging/retention.py` and
`../logging/retention.json` relative to the script file, so the copy box places
the whole `infra/beta/vm/host` tree beside `infra/beta/vm/logging` under
`/opt/cosmabot/vm/` on the VM. Build the creation receipt first with the
receipt-tool paste below (`build_creation_receipt.py`, same flags as
`infra/beta/vm/host/README.md`). That paste exports the local workstation path
and sha256 under `$HOME/.cosmabot-sitting2/`. After SSH is open, the
receipt-place paste pipes that local JSON over the same ssh target used by the
host/logging copy box into a root-owned mode-0600 regular file at the fixed VM
path `/root/cosmabot-creation-receipt.json` (outside `/etc/cosmabot`; do not
create `/etc/cosmabot` yet). It verifies `sha256sum` on the VM against the
local `.sha256` sidecar and prints the two `export` lines to paste into the VM
root shell (`BOOTSTRAP_CREATION_RECEIPT` and
`BOOTSTRAP_CREATION_RECEIPT_SHA256`). Do not run the receipt tool's printed
`sudo install` lines for Sitting 2. Before the bootstrap paste, also set
`FORMAT_APPROVAL_DISK_ID` by hand to the exact data-disk ARM ID you read from
the receipt tool's printed `disk_id=` line (or the portal); the bootstrap paste
STOPs unless that value exactly equals the receipt `disk_id`, and only that
hand-set value is passed to `--format-new-empty-disk`. The receipt field
`apply_started_utc` must be less than 24 hours old; the bootstrap paste STOPs
before any host change when that window has passed (stop and tell the CTO; do
not invent a re-apply step here).

**Paste — build creation receipt** (workstation; after Sitting 2 start / `az
login`). Calls `build_creation_receipt.py` exactly as
`infra/beta/vm/host/README.md` documents (`--profile cosmabot-vm-prod-v1`,
`--out-dir "$HOME/.cosmabot-sitting2"`). Read-only `az vm show` / `az disk
show` only; no Azure writes. You should see the tool `PASS:` lines plus
`PASS: creation receipt built` with exports set (sha256 value not re-printed
by this wrapper):

```bash
if ! test -f infra/beta/vm/host/build_creation_receipt.py; then
  echo "STOP: build-creation-receipt build_creation_receipt.py missing - run from the repo root" >&2
elif ! mkdir -p "$HOME/.cosmabot-sitting2"; then
  echo "STOP: build-creation-receipt mkdir out-dir failed" >&2
elif ! chmod 700 "$HOME/.cosmabot-sitting2"; then
  echo "STOP: build-creation-receipt chmod 700 out-dir failed" >&2
elif ! python3 infra/beta/vm/host/build_creation_receipt.py --profile cosmabot-vm-prod-v1 --out-dir "$HOME/.cosmabot-sitting2"; then
  echo "STOP: build-creation-receipt tool failed" >&2
elif ! test -f "$HOME/.cosmabot-sitting2/creation-receipt.json"; then
  echo "STOP: build-creation-receipt creation-receipt.json missing after tool" >&2
elif ! test -f "$HOME/.cosmabot-sitting2/creation-receipt.sha256"; then
  echo "STOP: build-creation-receipt creation-receipt.sha256 missing after tool" >&2
elif ! BOOTSTRAP_CREATION_RECEIPT_SHA256=$(tr -d '[:space:]' < "$HOME/.cosmabot-sitting2/creation-receipt.sha256"); then
  echo "STOP: build-creation-receipt could not read creation-receipt.sha256" >&2
elif ! test -n "$BOOTSTRAP_CREATION_RECEIPT_SHA256"; then
  echo "STOP: build-creation-receipt sha256 empty" >&2
else
  export BOOTSTRAP_CREATION_RECEIPT="$HOME/.cosmabot-sitting2/creation-receipt.json"
  export BOOTSTRAP_CREATION_RECEIPT_SHA256
  echo "PASS: creation receipt built; BOOTSTRAP_CREATION_RECEIPT and BOOTSTRAP_CREATION_RECEIPT_SHA256 exported"
fi
```

**Paste — open SSH `/32` and root shell for `#389` bootstrap** (workstation;
uses the existing §4.5 open fence and the same SSH variables the session box
uses). After the NSG open, pins the VM ed25519 host key the same way
`fence-ssh-secrets-install.sh` does (`az vm run-command` + temporary
`UserKnownHostsFile`), exports `SSH_KNOWN_HOSTS_FILE` for later bootstrap ssh
and for the close-verify probe, then opens an interactive root shell with
`StrictHostKeyChecking=yes`. You should see
`PASS: bootstrap-ssh TEMP-JOHN-SSH-SECRETS-INSTALL open`, then the root prompt.
Exit that shell when ready for the copy paste; the `/32` rule stays open until
bootstrap-close. If this interactive `ssh -t ... sudo -i` fails, or if any of
the five host-key pin steps after `cosmabot_ssh_nsg_open` STOPs (mktemp,
run-command, parse, shape, write), go straight to the bootstrap-close paste or
paste the Terminal closed partway recovery box so the temporary SSH rule is
closed and verified:

```bash
if ! test -n "${RG:-}"; then
  echo "STOP: bootstrap-ssh RG unset - paste Sitting 2 start box first" >&2
elif ! test -n "${ADMIN_USERNAME:-}"; then
  echo "STOP: bootstrap-ssh ADMIN_USERNAME unset - export the reviewed admin_username first" >&2
elif ! test -n "${SSH_IDENTITY_PATH:-}"; then
  echo "STOP: bootstrap-ssh SSH_IDENTITY_PATH unset - export the private key path matching admin_ssh_public_key first" >&2
elif ! test -f "$SSH_IDENTITY_PATH"; then
  echo "STOP: bootstrap-ssh SSH_IDENTITY_PATH missing" >&2
elif ! test -f infra/beta/vm/host/secrets_transport.py; then
  echo "STOP: bootstrap-ssh secrets_transport.py missing - run from the repo root" >&2
elif ! test -f infra/beta/vm/host/fences/fence-ssh-nsg-open.sh; then
  echo "STOP: bootstrap-ssh fence-ssh-nsg-open.sh missing - run from the repo root" >&2
elif ! VM_PUBLIC_IP=$(az network public-ip show --resource-group "$RG" --name pip-cosmabot-prod-eus2-01 --query ipAddress -o tsv); then
  echo "STOP: bootstrap-ssh could not read pip-cosmabot-prod-eus2-01" >&2
elif ! test -n "$VM_PUBLIC_IP"; then
  echo "STOP: bootstrap-ssh VM_PUBLIC_IP empty" >&2
else
  export RG ADMIN_USERNAME SSH_IDENTITY_PATH VM_PUBLIC_IP
  export SECRETS_TRANSPORT_PY="$PWD/infra/beta/vm/host/secrets_transport.py"
  source infra/beta/vm/host/fences/fence-ssh-nsg-open.sh
  if ! cosmabot_ssh_nsg_open; then
    echo "STOP: bootstrap-ssh cosmabot_ssh_nsg_open failed" >&2
  elif ! SSH_KNOWN_HOSTS_FILE=$(mktemp "${TMPDIR:-/tmp}/cosmabot-known-hosts.XXXXXX"); then
    echo "STOP: bootstrap-ssh known_hosts mktemp failed - paste the Terminal closed partway recovery box" >&2
  else
    export SSH_KNOWN_HOSTS_FILE
    if ! HOSTKEY_JSON=$(az vm run-command invoke --resource-group "$RG" --name vm-cosmabot-prod-eus2-01 --command-id RunShellScript --scripts "cat /etc/ssh/ssh_host_ed25519_key.pub" -o json); then
      echo "STOP: bootstrap-ssh host-key run-command failed - paste the Terminal closed partway recovery box" >&2
      rm -f "$SSH_KNOWN_HOSTS_FILE"
    elif ! HOSTKEY_LINE=$(printf '%s' "$HOSTKEY_JSON" | jq -r '.value[0].message | split("\n") | map(select(test("^ssh-ed25519 "))) | .[0] // empty'); then
      echo "STOP: bootstrap-ssh host-key parse failed - paste the Terminal closed partway recovery box" >&2
      rm -f "$SSH_KNOWN_HOSTS_FILE"
    elif ! printf '%s' "$HOSTKEY_LINE" | grep -Eq '^ssh-ed25519 [A-Za-z0-9+/=]+'; then
      echo "STOP: bootstrap-ssh host-key shape invalid - paste the Terminal closed partway recovery box" >&2
      rm -f "$SSH_KNOWN_HOSTS_FILE"
    else
      HOSTKEY_BODY=$(printf '%s' "$HOSTKEY_LINE" | awk '{print $1" "$2}')
      if ! printf '%s %s\n' "$VM_PUBLIC_IP" "$HOSTKEY_BODY" >"$SSH_KNOWN_HOSTS_FILE"; then
        echo "STOP: bootstrap-ssh known_hosts write failed - paste the Terminal closed partway recovery box" >&2
        rm -f "$SSH_KNOWN_HOSTS_FILE"
      else
        echo "PASS: bootstrap-ssh TEMP-JOHN-SSH-SECRETS-INSTALL open; host key pinned"
        echo "NOTE: if this interactive ssh fails, or if a host-key pin STOP printed above, paste bootstrap-close or the Terminal closed partway recovery box to close the TEMP SSH rule"
        ssh -i "$SSH_IDENTITY_PATH" -t -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=${SSH_KNOWN_HOSTS_FILE}" "${ADMIN_USERNAME}@${VM_PUBLIC_IP}" 'sudo -i'
      fi
    fi
  fi
fi
```

**Paste — copy host + logging bootstrap folders to the VM** (workstation; SSH
`/32` still open from the box above). Places `host/` and sibling `logging/`
under `/opt/cosmabot/vm/` so `../logging/retention.py` and
`../logging/retention.json` resolve next to `bootstrap_host.py`. Uses the
pinned `SSH_KNOWN_HOSTS_FILE` from the open box on every ssh. You should see
`PASS: bootstrap folders on VM under /opt/cosmabot/vm`:

```bash
if ! test -n "${ADMIN_USERNAME:-}"; then
  echo "STOP: bootstrap-copy ADMIN_USERNAME unset - export the reviewed admin_username first" >&2
elif ! test -n "${SSH_IDENTITY_PATH:-}"; then
  echo "STOP: bootstrap-copy SSH_IDENTITY_PATH unset - export the private key path matching admin_ssh_public_key first" >&2
elif ! test -f "$SSH_IDENTITY_PATH"; then
  echo "STOP: bootstrap-copy SSH_IDENTITY_PATH missing" >&2
elif ! test -n "${VM_PUBLIC_IP:-}"; then
  echo "STOP: bootstrap-copy VM_PUBLIC_IP unset - paste the bootstrap-ssh open box first" >&2
elif ! test -n "${SSH_KNOWN_HOSTS_FILE:-}"; then
  echo "STOP: bootstrap-copy SSH_KNOWN_HOSTS_FILE unset - paste the bootstrap-ssh open box first" >&2
elif ! test -f "$SSH_KNOWN_HOSTS_FILE"; then
  echo "STOP: bootstrap-copy SSH_KNOWN_HOSTS_FILE missing" >&2
elif ! test -d infra/beta/vm/host; then
  echo "STOP: bootstrap-copy infra/beta/vm/host missing - run from the repo root" >&2
elif ! test -d infra/beta/vm/logging; then
  echo "STOP: bootstrap-copy infra/beta/vm/logging missing - run from the repo root" >&2
elif ! test -f infra/beta/vm/logging/retention.py; then
  echo "STOP: bootstrap-copy infra/beta/vm/logging/retention.py missing" >&2
elif ! test -f infra/beta/vm/logging/retention.json; then
  echo "STOP: bootstrap-copy infra/beta/vm/logging/retention.json missing" >&2
else
  if ! tar -C infra/beta/vm -cf - host logging | ssh -i "$SSH_IDENTITY_PATH" -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=${SSH_KNOWN_HOSTS_FILE}" "${ADMIN_USERNAME}@${VM_PUBLIC_IP}" 'sudo mkdir -p /opt/cosmabot/vm && sudo tar -C /opt/cosmabot/vm -xf - && sudo chown -R root:root /opt/cosmabot/vm'; then
    echo "STOP: bootstrap-copy could not place host and logging under /opt/cosmabot/vm" >&2
  else
    if ! ssh -i "$SSH_IDENTITY_PATH" -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=${SSH_KNOWN_HOSTS_FILE}" "${ADMIN_USERNAME}@${VM_PUBLIC_IP}" 'test -f /opt/cosmabot/vm/host/bootstrap_host.py && test -f /opt/cosmabot/vm/logging/retention.py && test -f /opt/cosmabot/vm/logging/retention.json'; then
      echo "STOP: bootstrap-copy remote retention or bootstrap_host.py missing after transfer" >&2
    else
      echo "PASS: bootstrap folders on VM under /opt/cosmabot/vm"
    fi
  fi
fi
```

**Paste — place creation receipt on the VM** (workstation; SSH `/32` still
open; same ssh target, `-i` identity, and pinned `SSH_KNOWN_HOSTS_FILE` as the
host/logging copy box). Pipes `$HOME/.cosmabot-sitting2/creation-receipt.json`
into a root-owned mode-0600 regular file at the fixed path
`/root/cosmabot-creation-receipt.json` (outside `/etc/cosmabot`; do not create
`/etc/cosmabot` here). Verifies remote `sudo sha256sum` against the local
`.sha256` sidecar (ssh exit status checked before parsing the hash) and STOPs
on missing file or mismatch. On PASS it prints the two `export` lines to paste
into the VM root shell before the bootstrap box
(`BOOTSTRAP_CREATION_RECEIPT` fixed path and the 64-hex
`BOOTSTRAP_CREATION_RECEIPT_SHA256`):

```bash
if ! test -n "${ADMIN_USERNAME:-}"; then
  echo "STOP: receipt-place ADMIN_USERNAME unset - export the reviewed admin_username first" >&2
elif ! test -n "${SSH_IDENTITY_PATH:-}"; then
  echo "STOP: receipt-place SSH_IDENTITY_PATH unset - export the private key path matching admin_ssh_public_key first" >&2
elif ! test -f "$SSH_IDENTITY_PATH"; then
  echo "STOP: receipt-place SSH_IDENTITY_PATH missing" >&2
elif ! test -n "${VM_PUBLIC_IP:-}"; then
  echo "STOP: receipt-place VM_PUBLIC_IP unset - paste the bootstrap-ssh open box first" >&2
elif ! test -n "${SSH_KNOWN_HOSTS_FILE:-}"; then
  echo "STOP: receipt-place SSH_KNOWN_HOSTS_FILE unset - paste the bootstrap-ssh open box first" >&2
elif ! test -f "$SSH_KNOWN_HOSTS_FILE"; then
  echo "STOP: receipt-place SSH_KNOWN_HOSTS_FILE missing" >&2
elif ! test -f "$HOME/.cosmabot-sitting2/creation-receipt.json"; then
  echo "STOP: receipt-place local creation-receipt.json missing - paste the build-creation-receipt box first" >&2
elif ! test -f "$HOME/.cosmabot-sitting2/creation-receipt.sha256"; then
  echo "STOP: receipt-place local creation-receipt.sha256 missing - paste the build-creation-receipt box first" >&2
elif ! LOCAL_RECEIPT_SHA256=$(tr -d '[:space:]' < "$HOME/.cosmabot-sitting2/creation-receipt.sha256"); then
  echo "STOP: receipt-place could not read local creation-receipt.sha256" >&2
elif ! test -n "$LOCAL_RECEIPT_SHA256"; then
  echo "STOP: receipt-place local sha256 empty" >&2
elif ! printf '%s' "$LOCAL_RECEIPT_SHA256" | grep -Eq '^[0-9a-f]{64}$'; then
  echo "STOP: receipt-place local sha256 must be 64 lowercase hex chars" >&2
else
  if ! ssh -i "$SSH_IDENTITY_PATH" -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=${SSH_KNOWN_HOSTS_FILE}" "${ADMIN_USERNAME}@${VM_PUBLIC_IP}" "sudo sh -c 'cat > /root/cosmabot-creation-receipt.json && chown root:root /root/cosmabot-creation-receipt.json && chmod 0600 /root/cosmabot-creation-receipt.json'" < "$HOME/.cosmabot-sitting2/creation-receipt.json"; then
    echo "STOP: receipt-place could not write /root/cosmabot-creation-receipt.json on the VM" >&2
  else
    if ! REMOTE_SHA_RAW=$(ssh -n -i "$SSH_IDENTITY_PATH" -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=${SSH_KNOWN_HOSTS_FILE}" "${ADMIN_USERNAME}@${VM_PUBLIC_IP}" 'sudo sha256sum /root/cosmabot-creation-receipt.json'); then
      echo "STOP: receipt-place remote sudo sha256sum failed" >&2
    else
      REMOTE_RECEIPT_SHA256=${REMOTE_SHA_RAW%% *}
      if ! test -n "$REMOTE_RECEIPT_SHA256"; then
        echo "STOP: receipt-place remote sha256 empty" >&2
      elif ! test "$REMOTE_RECEIPT_SHA256" = "$LOCAL_RECEIPT_SHA256"; then
        echo "STOP: receipt-place remote sha256 does not match local creation-receipt.sha256" >&2
      else
        echo "PASS: receipt placed at /root/cosmabot-creation-receipt.json (sha256 matched)"
        echo "Paste these two lines into the VM root shell before the bootstrap box:"
        echo "export BOOTSTRAP_CREATION_RECEIPT=/root/cosmabot-creation-receipt.json"
        echo "export BOOTSTRAP_CREATION_RECEIPT_SHA256=${LOCAL_RECEIPT_SHA256}"
      fi
    fi
  fi
fi
```

**Paste — `#389` host bootstrap** (run as root in the prod VM root shell;
creates `/etc/cosmabot`). Exact command shape from
`infra/beta/vm/host/README.md`
(`python3 bootstrap_host.py --profile cosmabot-vm-prod-v1 ...`). After the
receipt-place paste, open a root shell again if needed with the pinned host
key (`ssh -i "$SSH_IDENTITY_PATH" -t -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=${SSH_KNOWN_HOSTS_FILE}" "${ADMIN_USERNAME}@${VM_PUBLIC_IP}" 'sudo -i'`),
paste the two `export` lines that box printed, then `cd /opt/cosmabot/vm/host`
so `bootstrap_host.py` and `../logging/retention.py` /
`../logging/retention.json` are present. This box runs as root, sets
`BOOTSTRAP_CREATION_RECEIPT` to the fixed VM path
`/root/cosmabot-creation-receipt.json`, and STOPs unless that file exists and
its `sha256sum` equals the pasted `BOOTSTRAP_CREATION_RECEIPT_SHA256`. Set
`FORMAT_APPROVAL_DISK_ID` by hand first to the exact data-disk ARM ID from the
receipt tool's printed `disk_id=` line or the portal; this paste STOPs if that
export is unset or does not exactly equal the receipt `disk_id`, and passes
only `FORMAT_APPROVAL_DISK_ID` to `--format-new-empty-disk` (so the format
approval is not a circular re-read of the same receipt field). The 24-hour
window is the receipt field `apply_started_utc`: this paste reads that field
and STOPs before any host change when the receipt is older than 24 hours or in
the future (stop and tell the CTO; no re-apply step here). Retention files are
checked before `bootstrap_host.py` runs so package install cannot start with a
missing sibling. You should see the receipt exports and
`FORMAT_APPROVAL_DISK_ID` already set, then the bootstrap JSON receipt print
(no secret values). Do **not** enable `cosmabot-prod.service` yet:

```bash
BOOTSTRAP_CREATION_RECEIPT=/root/cosmabot-creation-receipt.json
if ! test -f bootstrap_host.py; then
  echo "STOP: bootstrap_host.py missing - cd to /opt/cosmabot/vm/host first" >&2
elif ! test -f ../logging/retention.py; then
  echo "STOP: bootstrap ../logging/retention.py missing - paste the bootstrap-copy box first" >&2
elif ! test -f ../logging/retention.json; then
  echo "STOP: bootstrap ../logging/retention.json missing - paste the bootstrap-copy box first" >&2
elif ! test -n "${BOOTSTRAP_CREATION_RECEIPT_SHA256:-}"; then
  echo "STOP: bootstrap BOOTSTRAP_CREATION_RECEIPT_SHA256 unset - paste the two export lines from the receipt-place box first" >&2
elif ! test -f "$BOOTSTRAP_CREATION_RECEIPT"; then
  echo "STOP: bootstrap /root/cosmabot-creation-receipt.json missing - paste the receipt-place box first" >&2
elif ! BOOTSTRAP_REMOTE_SHA256=$(sha256sum "$BOOTSTRAP_CREATION_RECEIPT" | awk '{print $1}'); then
  echo "STOP: bootstrap could not sha256sum /root/cosmabot-creation-receipt.json" >&2
elif ! test "$BOOTSTRAP_REMOTE_SHA256" = "$BOOTSTRAP_CREATION_RECEIPT_SHA256"; then
  echo "STOP: bootstrap receipt sha256sum does not equal BOOTSTRAP_CREATION_RECEIPT_SHA256" >&2
elif ! python3 -c 'import datetime as dt, json, sys
receipt = json.load(open(sys.argv[1], encoding="utf-8"))
started = dt.datetime.fromisoformat(str(receipt["apply_started_utc"]).replace("Z", "+00:00"))
now = dt.datetime.now(dt.timezone.utc)
age = now - started
if age < dt.timedelta(0) or age > dt.timedelta(hours=24):
    raise SystemExit(1)
' "$BOOTSTRAP_CREATION_RECEIPT"; then
  echo "STOP: bootstrap apply_started_utc older than 24 hours or in the future - stop and tell the CTO" >&2
elif ! BOOTSTRAP_EXPECTED_DEVICE=$(readlink -f /dev/disk/azure/scsi1/lun0); then
  echo "STOP: bootstrap could not resolve /dev/disk/azure/scsi1/lun0" >&2
elif ! printf '%s' "$BOOTSTRAP_EXPECTED_DEVICE" | grep -Eq '^/dev/sd[a-z]+$'; then
  echo "STOP: bootstrap expected device must be /dev/sdX from lun0" >&2
elif ! BOOTSTRAP_VM_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["vm_id"])' "$BOOTSTRAP_CREATION_RECEIPT"); then
  echo "STOP: bootstrap could not read vm_id from receipt" >&2
elif ! BOOTSTRAP_DISK_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["disk_id"])' "$BOOTSTRAP_CREATION_RECEIPT"); then
  echo "STOP: bootstrap could not read disk_id from receipt" >&2
elif ! test -n "${FORMAT_APPROVAL_DISK_ID:-}"; then
  echo "STOP: bootstrap FORMAT_APPROVAL_DISK_ID unset - set it by hand to the disk_id from the receipt tool print or the portal" >&2
elif ! test "$FORMAT_APPROVAL_DISK_ID" = "$BOOTSTRAP_DISK_ID"; then
  echo "STOP: bootstrap FORMAT_APPROVAL_DISK_ID must exactly equal the receipt disk_id" >&2
else
  python3 bootstrap_host.py \
    --profile cosmabot-vm-prod-v1 \
    --vm-id "$BOOTSTRAP_VM_ID" \
    --disk-id "$BOOTSTRAP_DISK_ID" \
    --expected-device "$BOOTSTRAP_EXPECTED_DEVICE" \
    --creation-receipt "$BOOTSTRAP_CREATION_RECEIPT" \
    --creation-receipt-sha256 "$BOOTSTRAP_CREATION_RECEIPT_SHA256" \
    --format-new-empty-disk "$FORMAT_APPROVAL_DISK_ID"
fi
```

**Paste — close SSH `/32` after `#389` bootstrap** (workstation; same open
rule name the secrets session will reuse). Design: when prerequisites are
present, `cosmabot_ssh_nsg_close_and_verify` **always** runs so the temporary
SSH `/32` rule is closed and verified no matter what the host-file check
returns. The host check must use SSH, so it runs first with
`sudo test -f /etc/cosmabot/host-bootstrap.json` when `SSH_KNOWN_HOSTS_FILE` is
set (`/etc/cosmabot` is root-owned mode 0700 after bootstrap). If that file is
unset or missing, skip the host check, leave `BOOTSTRAP_HOST_OK=0`, and still
run close-and-verify (the close fence falls back to `/dev/null` for
`UserKnownHostsFile`). Then close runs on both the present and missing
branches. If the host file is missing after a successful close, print STOP
(secrets window blocked; rule already closed) and name the Terminal closed
partway recovery box if the rule may still exist from another session. Exports
`SSH_KNOWN_HOSTS_FILE` for the close-verify SSH probe when present. You should
see the close PASS (and host-bootstrap present) before any second vault window
or §4.5 secrets session:

```bash
if ! test -n "${RG:-}"; then
  echo "STOP: bootstrap-close RG unset - paste Sitting 2 start box first" >&2
elif ! test -n "${SECRETS_TRANSPORT_PY:-}"; then
  echo "STOP: bootstrap-close SECRETS_TRANSPORT_PY unset - paste the bootstrap-ssh open box first" >&2
elif ! test -f "$SECRETS_TRANSPORT_PY"; then
  echo "STOP: bootstrap-close SECRETS_TRANSPORT_PY missing" >&2
elif ! test -n "${VM_PUBLIC_IP:-}"; then
  echo "STOP: bootstrap-close VM_PUBLIC_IP unset - paste the bootstrap-ssh open box first" >&2
elif ! test -n "${ADMIN_USERNAME:-}"; then
  echo "STOP: bootstrap-close ADMIN_USERNAME unset - export the reviewed admin_username first" >&2
elif ! test -n "${SSH_IDENTITY_PATH:-}"; then
  echo "STOP: bootstrap-close SSH_IDENTITY_PATH unset - export the private key path matching admin_ssh_public_key first" >&2
elif ! test -f "$SSH_IDENTITY_PATH"; then
  echo "STOP: bootstrap-close SSH_IDENTITY_PATH missing" >&2
elif ! test -f infra/beta/vm/host/fences/fence-ssh-nsg-close-verify.sh; then
  echo "STOP: bootstrap-close fence-ssh-nsg-close-verify.sh missing - run from the repo root" >&2
else
  export RG SECRETS_TRANSPORT_PY VM_PUBLIC_IP ADMIN_USERNAME SSH_IDENTITY_PATH
  if test -n "${SSH_KNOWN_HOSTS_FILE:-}"; then
    export SSH_KNOWN_HOSTS_FILE
  fi
  source infra/beta/vm/host/fences/fence-ssh-nsg-close-verify.sh
  BOOTSTRAP_HOST_OK=0
  if test -n "${SSH_KNOWN_HOSTS_FILE:-}" && test -f "$SSH_KNOWN_HOSTS_FILE"; then
    if ssh -n -i "$SSH_IDENTITY_PATH" -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=${SSH_KNOWN_HOSTS_FILE}" "${ADMIN_USERNAME}@${VM_PUBLIC_IP}" 'sudo test -f /etc/cosmabot/host-bootstrap.json'; then
      BOOTSTRAP_HOST_OK=1
    fi
  fi
  if ! cosmabot_ssh_nsg_close_and_verify; then
    echo "STOP: bootstrap-close cosmabot_ssh_nsg_close_and_verify failed" >&2
  elif ! test "$BOOTSTRAP_HOST_OK" = "1"; then
    echo "STOP: bootstrap-close /etc/cosmabot/host-bootstrap.json missing - TEMP SSH rule already closed and verified; secrets window blocked; if a TEMP rule may still exist use the Terminal closed partway recovery box" >&2
  else
    echo "PASS: TEMP SSH rule closed and verified; /etc/cosmabot/host-bootstrap.json present"
  fi
fi
```

**Paste — workstation `--stage-from-vault` (full secret set)** (after the
second vault window is open with `cosmabot_kv_open_john_32`; uses Sitting 2
start exports `RG` / `PROD_KV_NAME`). Omitting `--secret-name` stages the full
catalog so `--check-staging-complete` / the §4.5 session gate can PASS. STOPs
if `LOCAL_STAGING` is already set and that directory exists (use guarded rm or
the Terminal closed partway recovery box first) instead of re-running
`mktemp`. Keep the same `$LOCAL_STAGING` for §4.5 after a successful stage.
You should see `PASS: workstation stage complete` (names / pass-fail only;
values not printed):

```bash
if ! test -n "${RG:-}"; then
  echo "STOP: stage-from-vault RG unset - paste Sitting 2 start box first" >&2
elif ! test -n "${PROD_KV_NAME:-}"; then
  echo "STOP: stage-from-vault PROD_KV_NAME unset - paste Sitting 2 start box first" >&2
elif ! test -f infra/beta/vm/host/secrets_transport.py; then
  echo "STOP: stage-from-vault secrets_transport.py missing - run from the repo root" >&2
elif test -n "${LOCAL_STAGING:-}" && test -d "${LOCAL_STAGING}"; then
  echo "STOP: stage-from-vault LOCAL_STAGING already set and exists - use guarded rm or the Terminal closed partway recovery box first" >&2
elif ! LOCAL_STAGING=$(mktemp -d /tmp/cosmabot-staging.XXXXXX); then
  echo "STOP: stage-from-vault mktemp failed" >&2
elif ! chmod 700 "$LOCAL_STAGING"; then
  echo "STOP: stage-from-vault chmod 700 failed" >&2
elif ! python3 infra/beta/vm/host/secrets_transport.py \
  --profile cosmabot-vm-prod-v1 \
  --resource-group "$RG" \
  --vault-name "$PROD_KV_NAME" \
  --stage-from-vault \
  --staging-dir "$LOCAL_STAGING"; then
  echo "STOP: stage-from-vault tool failed" >&2
else
  export LOCAL_STAGING
  echo "PASS: workstation stage complete"
fi
```

**Close-and-verify (vault + NSG) is MANDATORY before any tofu plan or apply** —
otherwise the temporary NSG rule shows as drift and/or the vault stays open.
No Bastion, no `az login` on the VM, no IaC change for this path.

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

Run on the Linux VM under bash.

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
  test -s "$HOST_LLM_KEYFILE" || {
    echo "STOP: HTTP proof HOST_LLM_KEYFILE empty"
    return 1
  }
  test "$(stat -c '%a' "$HOST_LLM_KEYFILE")" = "400" || {
    echo "STOP: HTTP proof HOST_LLM_KEYFILE not mode 0400"
    return 1
  }
  test "$(stat -c '%u' "$HOST_LLM_KEYFILE")" -gt 0 || {
    echo "STOP: HTTP proof HOST_LLM_KEYFILE owner uid missing"
    return 1
  }
  echo "PASS: HTTP proof keyfile present mode=$(stat -c '%a' "$HOST_LLM_KEYFILE") owner_uid=$(stat -c '%u' "$HOST_LLM_KEYFILE") size_gt0=yes (value not printed)"
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
  umask 077
  {
    printf 'api-key: '
    tr -d '\n\r' <"$HOST_LLM_KEYFILE"
    printf '\n'
  } >"$HDR" || {
    echo "STOP: HTTP proof header file write failed"
    rm -f "$HDR"
    eval "${_prev_exit:-trap - EXIT}"
    eval "${_prev_int:-trap - INT}"
    eval "${_prev_term:-trap - TERM}"
    return 1
  }
  grep -Eq '^api-key: .+' "$HDR" || {
    echo "STOP: HTTP proof header name missing or empty"
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

If Sitting 2 is interrupted while the vault is open to the operator `/32`
(or any STOP leaves the window open):

1. **First (mandatory):** paste the §4.1 **kv-close** fence
   (`cosmabot_kv_close_john_32`) — **Disabled first**, then remove every listed
   IP rule (works from a new shell; does not need `MY_IP` / ipify), then verify
   last. Close-and-verify must run even after a STOP partway through.
2. **Then verify** again with the read-only fence below (prints only
   `publicNetworkAccess` and `ipRules` count — not secret values).
3. **Abandon sitting / STOP leftover secrets:** after the vault is closed,
   remove Sitting 2 local secret files under `$HOME/.cosmabot-sitting2/`
   (password/`prompt-`/`john-32.ip` paths plus `$KEYFILE`). Verify each with
   `! -e`. **If `KEYFILE` is unset:** the abandon fence prints **STOP**, tells
   John to re-export the §4.1 path (`$HOME/.cosmabot-sitting2/llm-key1`),
   returns 1, and **never** prints PASS. If the shell died mid-sitting, use the
   dead-terminal dir recovery fence (removes the whole dir). A retry after
   STOP means: re-export `KEYFILE=$HOME/.cosmabot-sitting2/llm-key1`,
   re-rotate, then Fence 2. Never leave secret files overnight.

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
  ACCESS=$(az keyvault show --name "$PROD_KV_NAME" \
    --query properties.publicNetworkAccess -o tsv) || {
    echo "STOP: kv-closed access query failed"
    return 1
  }
  COUNT=$(az keyvault show --name "$PROD_KV_NAME" \
    --query "length(properties.networkAcls.ipRules)" -o tsv) || {
    echo "STOP: kv-closed ipRules length query failed"
    return 1
  }
  printf 'publicNetworkAccess=%s ipRules_count=%s\n' "$ACCESS" "$COUNT"
  test "$ACCESS" = "Disabled" || {
    echo "STOP: kv-closed publicNetworkAccess is not Disabled"
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

**Abandon-sitting secret-file cleanup** (paste after vault closed). Never prints
file contents. **If `KEYFILE` is unset:** print **STOP**, tell John to
re-export the §4.1 path (`$HOME/.cosmabot-sitting2/llm-key1`), return 1, and
**never** print PASS. When `KEYFILE` is set: remove known sitting2 secret files
(including `$KEYFILE`) and `test ! -e` each. For a dead terminal / unknown
leftovers, use the dir recovery fence below instead.

```bash
cosmabot_abandon_sitting_keyfile_cleanup() {
  test -n "${KEYFILE:-}" || {
    echo "STOP: abandon sitting KEYFILE unset - re-export the section 4.1 path \$HOME/.cosmabot-sitting2/llm-key1" >&2
    return 1
  }
  SITDIR="$HOME/.cosmabot-sitting2"
  DBF="$SITDIR/DATABASE-PASSWORD.value"
  PGF="$SITDIR/POSTGRES-PASSWORD.value"
  RDF="$SITDIR/REDIS-PASSWORD.value"
  IPFILE="$SITDIR/john-32.ip"
  P1="$SITDIR/prompt-CLERK-SECRET-KEY.tmp"
  P2="$SITDIR/prompt-CLERK-ACCOUNT-DELETION-SECRET.tmp"
  P3="$SITDIR/prompt-HUMAN-DEPLOY-EVIDENCE-REF.tmp"
  rm -f "$KEYFILE" "$DBF" "$PGF" "$RDF" "$IPFILE" "$P1" "$P2" "$P3" || {
    echo "STOP: abandon sitting rm failed" >&2
    return 1
  }
  for _f in "$KEYFILE" "$DBF" "$PGF" "$RDF" "$IPFILE" "$P1" "$P2" "$P3"; do
    test ! -e "$_f" || {
      echo "STOP: abandon sitting path still exists after rm" >&2
      return 1
    }
  done
  KEYFILE=
  echo "PASS: abandon sitting removed sitting2 secret files (values not printed)"
  return 0
}
cosmabot_abandon_sitting_keyfile_cleanup || {
  echo "STOP: abandon sitting KEYFILE cleanup failed" >&2
  false
}
```

**Dead-terminal recovery** (paste when the Sitting 2 shell died and leftover
files may remain under `$HOME/.cosmabot-sitting2/`). Removes the **whole**
directory and verifies it is gone. Never prints file contents:

```bash
cosmabot_sitting2_dead_terminal_dir_recovery() {
  SITDIR="$HOME/.cosmabot-sitting2"
  if test ! -e "$SITDIR"; then
    echo "PASS: sitting2 dir already absent"
    return 0
  fi
  rm -rf "$SITDIR" || {
    echo "STOP: sitting2 dir rm -rf failed" >&2
    return 1
  }
  test ! -e "$SITDIR" || {
    echo "STOP: sitting2 dir still exists after rm -rf" >&2
    return 1
  }
  KEYFILE=
  echo "PASS: sitting2 dir removed (values not printed)"
  return 0
}
cosmabot_sitting2_dead_terminal_dir_recovery || {
  echo "STOP: sitting2 dead-terminal recovery failed" >&2
  false
}
```

Do not continue Sitting 2 secret work until the vault-closed verify passes.
If abandoning, run close-and-verify first, then the abandon cleanup (or
dead-terminal dir recovery) before leaving the machine.

### 4.5 Temporary SSH `/32` for secrets install (John, 14 Nov 2026 9:45am ET)

**Shell:** bash 3.2+ or default macOS zsh (fences use `#393`-style portable trap
save/restore: bash `trap -p`; zsh `trap` listing — never `trap -p` in zsh).
Session wrapper saves/restores EXIT/INT/TERM only; guarded open/install failures
still close-and-verify. Use `command -v`, not `type -t`.

John: "Yes, open sign-in to my address for the install, then close it."

**Prerequisite — one order** (Sitting 2 row 5 / after format-disk yes +
continue-prep yes): `#389` bootstrap first (so `/etc/cosmabot` exists), then
this §4.5 path. Sitting 2 already closed the vault — **second vault window**
required: re-open with §4.1 `cosmabot_kv_open_john_32`, run workstation
`--stage-from-vault` (complete staging or STOP before open), open
`TEMP-JOHN-SSH-SECRETS-INSTALL`, install, then close-and-verify NSG here and
vault with §4.1 `cosmabot_kv_close_john_32`. See §4.1 “Server access for
secrets install”. John's hands-on: `/32`, vault window, SSH key.

No Bastion. No Secrets Officer `az login` on the VM. No permanent NSG/Terraform
change. Fixed rule name `TEMP-JOHN-SSH-SECRETS-INSTALL`, priority `200`
(before `deny-all-other-ingress` at `4000`), NSG `nsg-cosmabot-prod-eus2-01`,
RG `rg-cosmabot-prod-eus2-01`. Detect John's IP with
`curl -fsS https://api.ipify.org` (prints IP only). Create uses `--output none`.

**No secret values on the prod disk outside final mode-0400 destinations.**
Workstation stages under a local mode-700 dir; install pipes each value over
`ssh` stdin into `secrets_transport.py --install-from-stdin` as root (umask
077). Do not `scp` secret values. Do not stage under `/tmp` or `/root` on the
VM. Local fence `mktemp` files hold NSG JSON / known_hosts / probe stderr only
— never secret values. Ship the module only; verify `sha256` against
`infra/beta/vm/host/secrets_transport.sha256` before running. Pin the VM
ed25519 host key via `az vm run-command` (public key only) into a per-session
`known_hosts`; `ssh` uses `StrictHostKeyChecking=yes`.

**Close-and-verify is MANDATORY after every outcome**, including STOP mid-way
and SIGINT. An out-of-band NSG rule shows as drift on the next Terraform plan —
finish close-and-verify before any plan or apply. Close requires deny-all at
priority `4000`, Python `--check-ssh-closed`, and an SSH probe that PASSes only
on connection refused or connect/operation timeout (macOS `Operation timed out`
counts; banner-exchange timeout, auth prompt, and password prompt = still
reachable = FAIL).

Define-only fence files (no `#` comment lines; sourcing has zero side effects)
live in `infra/beta/vm/host/fences/`:

| Step | Fence file |
| --- | --- |
| OPEN | `fence-ssh-nsg-open.sh` → `cosmabot_ssh_nsg_open` |
| INSTALL | `fence-ssh-secrets-install.sh` → `cosmabot_ssh_secrets_install` |
| CLOSE AND VERIFY | `fence-ssh-nsg-close-verify.sh` → `cosmabot_ssh_nsg_close_and_verify` |
| Session (always closes) | `fence-ssh-secrets-session.sh` → `cosmabot_ssh_secrets_session` |
| Terminal closed partway | `fence-ssh-nsg-recovery.sh` → `cosmabot_ssh_nsg_recovery_if_stranded` |

Use the same terminal and the same `$LOCAL_STAGING` folder from §4.1 step 2
(do not run `mktemp` again — a second folder would orphan the staged secrets).

**Before the session box:** export `RELEASE_ID` to the reviewed release id for
this install, `ADMIN_USERNAME` to the reviewed prod `admin_username`, and
`SSH_IDENTITY_PATH` to the private key path that matches
`admin_ssh_public_key`. You should see all three already set (`test -n`
succeeds) before you paste. `RG`, `PROD_KV_NAME`, and `LOCAL_STAGING` come from
the Sitting 2 start box and the stage-from-vault box. `VM_PUBLIC_IP` and
`SECRETS_TRANSPORT_PY` are derived in the box.

**Order:** with that `$LOCAL_STAGING` still set, source the open/install/close
fences, then invoke the session wrapper (it traps EXIT/INT/TERM so
close-and-verify always runs):

```bash
if ! test -n "${LOCAL_STAGING:-}"; then
  echo "STOP: session LOCAL_STAGING unset - paste the stage-from-vault box first" >&2
elif ! test -n "${RG:-}"; then
  echo "STOP: session RG unset - paste Sitting 2 start box first" >&2
elif ! test -n "${PROD_KV_NAME:-}"; then
  echo "STOP: session PROD_KV_NAME unset - paste Sitting 2 start box first" >&2
elif ! test -n "${RELEASE_ID:-}"; then
  echo "STOP: session RELEASE_ID unset - export the reviewed release id first" >&2
elif ! test -n "${ADMIN_USERNAME:-}"; then
  echo "STOP: session ADMIN_USERNAME unset - export the reviewed admin_username first" >&2
elif ! test -n "${SSH_IDENTITY_PATH:-}"; then
  echo "STOP: session SSH_IDENTITY_PATH unset - export the private key path matching admin_ssh_public_key first" >&2
elif ! test -f "$SSH_IDENTITY_PATH"; then
  echo "STOP: session SSH_IDENTITY_PATH missing" >&2
elif ! test -f infra/beta/vm/host/secrets_transport.py; then
  echo "STOP: session secrets_transport.py missing - run from the repo root" >&2
elif ! VM_PUBLIC_IP=$(az network public-ip show --resource-group "$RG" --name pip-cosmabot-prod-eus2-01 --query ipAddress -o tsv); then
  echo "STOP: session could not read pip-cosmabot-prod-eus2-01" >&2
elif ! test -n "$VM_PUBLIC_IP"; then
  echo "STOP: session VM_PUBLIC_IP empty" >&2
elif ! chmod 700 "$LOCAL_STAGING"; then
  echo "STOP: session chmod 700 LOCAL_STAGING failed" >&2
else
  export RELEASE_ID ADMIN_USERNAME SSH_IDENTITY_PATH LOCAL_STAGING RG PROD_KV_NAME VM_PUBLIC_IP
  export SECRETS_TRANSPORT_PY="$PWD/infra/beta/vm/host/secrets_transport.py"
  source infra/beta/vm/host/fences/fence-ssh-nsg-open.sh
  source infra/beta/vm/host/fences/fence-ssh-secrets-install.sh
  source infra/beta/vm/host/fences/fence-ssh-nsg-close-verify.sh
  source infra/beta/vm/host/fences/fence-ssh-secrets-session.sh
  cosmabot_ssh_secrets_session
fi
```

`LOCAL_STAGING` must match `mktemp -d /tmp/cosmabot-staging.XXXXXX` (six random
characters under `/tmp` or macOS `/private/tmp` only — never `/var/folders`).
Shape is checked before any secret write and before SSH opens.

Sourcing alone must never open or close the NSG rule. Secrets stay with John;
fences print names / rule metadata / pass-fail only.

#### Terminal closed partway — recovery

If the session dies while `TEMP-JOHN-SSH-SECRETS-INSTALL` may still exist, use
the paste box below. Prefer a terminal that still has `LOCAL_STAGING` set to
the same folder from §4.1 step 2 (the `mktemp -d /tmp/cosmabot-staging.XXXXXX`
path). Behaviour:

- `LOCAL_STAGING` set but the wrong shape: STOP (recovery does not run).
- `LOCAL_STAGING` unset (new or dead terminal): print a NOTE that any leftover
  staging folder must be checked and removed by hand, then still source
  **only** `fence-ssh-nsg-recovery.sh` and run
  `cosmabot_ssh_nsg_recovery_if_stranded` so the SSH `/32` rule is deleted.
- `LOCAL_STAGING` set with a valid shape: run as now (delete rule, verify
  deny-all at 4000, guarded staging rm).

If staging remains afterwards under a valid path: STOP, never PASS. Do not
plan/apply until the recovery PASS prints. Also close the vault (§4.1 /
`cosmabot_kv_close_john_32`) if it is still open.

```bash
if test -n "${LOCAL_STAGING:-}" && ! printf '%s' "$LOCAL_STAGING" | grep -Eq '^(/private)?/tmp/cosmabot-staging\.[A-Za-z0-9]{6}$'; then
  echo "STOP: recovery LOCAL_STAGING must match /tmp/cosmabot-staging.XXXXXX or /private/tmp/cosmabot-staging.XXXXXX" >&2
else
  if test -z "${RG:-}"; then
    RG=rg-cosmabot-prod-eus2-01
  fi
  if ! printf '%s' "$RG" | grep -Eq '^rg-cosmabot-prod-eus2-01$'; then
    echo "STOP: recovery RG must be rg-cosmabot-prod-eus2-01" >&2
  else
    if ! test -n "${LOCAL_STAGING:-}"; then
      echo "NOTE: recovery LOCAL_STAGING unset - check and remove any leftover cosmabot-staging folder by hand; continuing NSG recovery" >&2
    fi
    export RG
    if test -n "${LOCAL_STAGING:-}"; then
      export LOCAL_STAGING
    fi
    source infra/beta/vm/host/fences/fence-ssh-nsg-recovery.sh
    cosmabot_ssh_nsg_recovery_if_stranded
  fi
fi
```

### 4.4 Mac-side fence syntax proof

Every pasteable bash/sh fence in §4.1–§4.3 must parse under `bash -n` and
`zsh -n` (including kv-open, password file, other-secrets load, kv-close,
Step A, rotate, Fence 2, Step B, host-files, HTTP status, bundle-checks,
baseline, kv-closed verify, abandon-sitting cleanup, dead-terminal dir
recovery). Real evidence that a pasted interactive zsh prompt will not treat
`#` as a comment is that the fences contain **no `#` comment lines**
(parameter expansions like `${var#prefix}` are fine). The agent harness fails
if any line whose first non-space character is `#` appears inside a John-pasted
\`\`\`bash fence (Mac Sitting 2 paste path). VM-only fences
(`cosmabot_stop_llm_host_files`, `cosmabot_stop_llm_http_status`) run under
bash on the Linux VM and are out of that Mac-paste check scope, but still must
parse under `bash -n` / `zsh -n` and must not introduce `#` comment lines. Do **not** claim that
`zsh -n` honours a parent `unsetopt interactivecomments` — `zsh -n` always
treats `#` as a comment inside a file. Proof: extract each fence and run
`bash -n` / `zsh -n`; results for this revision are in the PR body / agent
artifact for **T-392-FU** / PR **#393** (this revision).

---

## 5. Azure OpenAI + `gpt-4.1-dzus`

Created in Sitting 1 apply when `enable_azure_openai: true`:

- `kind = "OpenAI"`, SKU `S0`, PE + `privatelink.openai.azure.com`
- Deployment `gpt-4.1-dzus`, model `gpt-4.1` / `2025-04-14`, DataZoneStandard
  capacity **1**
- John rotates **key1** (see §4.1) before loading vault
  `WORKSPACE-LLM-API-KEY` with `source-account=<account id>` (Sitting 2 / §4.1);
  leave `key2` untouched this sitting
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

### Verification (after agents finish post-secrets-closed work; John's admit yes)

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

**Order for first `/ready` (path 1) — same clock as §1 (Sitting 2 format +
continue-prep yes, then John's hands-on bootstrap/secrets, then agents):**

1. `#381` (§9 (a) decided) **and** `#377` (VM-runtime delete host-key mapping
   + production-review name allowance) are already **Merged**.
2. Sitting 1: apply `#356` (RG, VM, OpenAI `gpt-4.1-dzus`).
3. Sitting 2: §4.1 kv-open `/32` → Step A → rotate **key1** → Fence 2 →
   Step B → generate mode-600 passwords → load all other vault secrets
   (including `CLERK-ACCOUNT-DELETION-SECRET`) → **then** kv-close + verify;
   abandon `$KEYFILE` cleanup on interrupt (unset → STOP / re-export §4.1
   path). Host reach via `TEMP-JOHN-SSH-SECRETS-INSTALL` (#388 / §4.5).
4. **One order — John's hands-on** (Sitting 2 row 5 / after format-disk yes +
   continue-prep yes / checklist): `#389` prod host bootstrap with
   `--profile cosmabot-vm-prod-v1`, the receipt from `build_creation_receipt.py`
   placed at `/root/cosmabot-creation-receipt.json`, and hand-set
   `FORMAT_APPROVAL_DISK_ID` (`infra/beta/vm/host/bootstrap_host.py`) so
   `/etc/cosmabot` (including `host-bootstrap.json`) exists. The
   `cosmabot-prod.service` **file** exists; enable only after secrets and
   acceptance (step 10). Matches §1 John's hands-on step 1.
5. **Install — John's hands-on** mode-0400 secret files with
   `infra/beta/vm/host/secrets_transport.py` (T-PROD-3-SECRETS / `#388`):
   **second vault window** + `TEMP-JOHN-SSH-SECRETS-INSTALL` — re-open §4.1 →
   `--stage-from-vault` (complete or STOP) → §4.5 SSH open → ssh-stdin install
   (sha256-pinned module; no VM `/tmp`/`/root` value staging) →
   close-and-verify vault + NSG (§4.5); service-UID ownership; mode 0400; Run
   Command refused for values. Matches §1 John's hands-on step 2.
6. **STOP checks** (agents, after secrets closed) before AI-on: §4.1 (host
   files) and §4.2 (exact `https://api.beta.cosmas.ai` + Clerk
   issuer/publishable key on Info.plist / JSON; scan `$APP/public` only; refuse
   configured staging API origin forms; compare to known-good baseline). On
   failure: roll back; do not flip AI-on.
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
10. After secrets + acceptance: place `cosmabot-prod.service` with
    `/etc/cosmabot/active-release`, but **do NOT enable** it until **T-PROD-5**
    (backup units) and **T-PROD-6** (probe) are merged. Matches §1 agents step
    5. Once enabling is allowed: `systemctl start cosmabot-prod.service`,
    then `systemctl restart cosmabot-prod.service`, then reboot, then confirm
    `systemctl is-active cosmabot-prod.service` and that `/run/cosmabot` exists.
    Note: `host-preflight.py`'s `mountpoint -q /var/lib/cosmabot` is not
    trustworthy under the unit's `ReadWritePaths` (bind-mount visibility); the
    operator runs `findmnt /var/lib/cosmabot` **outside** the unit to prove the
    data disk mount.

### Other gaps

1. Host 0400 install: **one order** (Sitting 2 row 5 / after format-disk yes +
   continue-prep yes) — `#389` bootstrap first, then
   `infra/beta/vm/host/secrets_transport.py` (T-PROD-3-SECRETS / `#388`).
   Sitting 2 already closed the vault — open a **second vault window** (§4.1)
   for `--stage-from-vault` (complete staging or STOP before SSH), then
   `TEMP-JOHN-SSH-SECRETS-INSTALL` → ssh-stdin install → close-and-verify vault
   + NSG (**§4.5**; mandatory before any plan/apply). John's hands-on: `/32`,
   vault window, SSH key. Do not `az login` as Secrets Officer on the VM. No
   Bastion. Run Command must not carry values.
2. **T-PROD-4:** `infra/beta/vm/runtime/render.py` `SCRIPT_NAMES` still lists
   only `cosmabot-staging.service` (prod unit file exists but is not copied
   into rendered releases yet).
3. **T-PROD-5:** backup units under `infra/beta/vm/backup/` still
   `Requires=` / `PartOf=` / `After=` `cosmabot-staging.service`.
4. **T-PROD-6:** `infra/beta/vm/monitoring/probe.py` still observes
   `cosmabot-staging.service`.
5. **T-PROD-7:** `infra/beta/vm/runtime/start.sh` still hardwires Compose
   project name `cosmabot-staging`.
6. Endpoint kind: classic vs Foundry recreate — §7.
7. Password-name acceptance on prod entrypoint still unverified per `#356`
   guard-hardening notes — prove before admitting testers.
8. `#356` OpenAI is first-apply-only if omitted from Sitting 1 inputs.
9. TestFlight blocked until Alfred + John.
10. Staging ticket files named in the original ask were not in this checkout;
    this doc mirrors `release-r7` pointer-switch + in-repo host/runtime READMEs.

---

## 9. Workload recreate day (off-by-default; `--recreate-workload`)

Use only when John has approved a recreate of `azurerm_linux_virtual_machine.workload`
and `azurerm_managed_disk.data` for `rg-cosmabot-prod-eus2-01`. Mode is off by
default (`allow_workload_recreate=false`). Do not touch
`infra/beta/vm/host/bootstrap_host.py` or its 24h rule from this path. Coding
agents must not run apply. Order is mandatory. After go-live, the private
directory holds `workload-live.json` (mode 0600); `--recreate-workload` then
refuses in prepare, plan, and apply.

Pasteable fences below are wrapped in functions so a failed check stops the
paste with `return 1` without killing the operator SSH session. Do not add
`set -e` or bare `exit` at the top level of these pastes.

The recreated VM has a **new SSH host key**. Sitting 2 boxes must re-pin it;
do not reuse an old `known_hosts` entry from before the recreate.

### 9.0 Fingerprint for John's review (before any refresh)

Print the reviewed foundation digests and stop for John's eyes before a
module-snapshot refresh:

```bash
cosmabot_recreate_print_fingerprint() {
  SOURCE_SHA256="$(python3 -c 'from pathlib import Path; import sys; sys.path.insert(0, "infra/beta/vm/prod/foundation"); import bootstrap_local as b; print(b.fingerprint()["source_sha256"])')" || return 1
  LOCK_SHA256="$(python3 -c 'from pathlib import Path; import sys; sys.path.insert(0, "infra/beta/vm/prod/foundation"); import bootstrap_local as b; print(b.fingerprint()["lock_sha256"])')" || return 1
  echo "SOURCE_SHA256=${SOURCE_SHA256}"
  echo "LOCK_SHA256=${LOCK_SHA256}"
  echo "STOP: John reviews SOURCE_SHA256 and LOCK_SHA256 before any refresh or recreate continue"
  return 1
}
cosmabot_recreate_print_fingerprint
```

If the live private `module/` still pins the first-apply `*.tf` snapshot and
`--recheck` / `--recover` / `--recreate-workload` refuse with
`Private module snapshot changed`, run the sanctioned refresh first (clean
checkout of a commit on `origin/main` only; prints `*.tf` diffs; backs up
prior `manifest.source` to `manifest.source.pre-refresh-<UTC>.json` before
overwrite; binds the new digests John must approve):

```bash
cosmabot_refresh_module_snapshot() {
  test -n "${PRIVATE_DIR:-}" || { echo "STOP: PRIVATE_DIR unset" >&2; return 1; }
  test -n "${SOURCE_SHA256:-}" || { echo "STOP: SOURCE_SHA256 unset" >&2; return 1; }
  test -n "${LOCK_SHA256:-}" || { echo "STOP: LOCK_SHA256 unset" >&2; return 1; }
  python3 infra/beta/vm/prod/foundation/bootstrap_local.py refresh-module-snapshot \
    --private-dir "$PRIVATE_DIR" \
    --source-sha256 "$SOURCE_SHA256" \
    --lock-sha256 "$LOCK_SHA256" \
    --confirm-refresh || return 1
  echo "PASS: module snapshot refresh bound new digests; prior manifest.source backed up under PRIVATE_DIR"
}
cosmabot_refresh_module_snapshot
```

### 9.1 Disk metadata check

This fence checks Azure disk **metadata only** (`createOption`, size, attachment).
It does not prove the volume has never been written. Write-bytes / ops evidence
is Sitting 2 host bootstrap with the reviewed creation receipt
(`infra/beta/vm/host/bootstrap_host.py --format-new-empty-disk`, after step 9.7).
John's typed approval on the recreate plan hashes is John's acceptance that
recreating the data disk means **data loss** of whatever was on that volume.

```bash
cosmabot_recreate_disk_evidence() {
  test -n "${RG:-}" || { echo "STOP: RG unset" >&2; return 1; }
  test -n "${SUBSCRIPTION_ID:-}" || { echo "STOP: SUBSCRIPTION_ID unset" >&2; return 1; }
  echo "INFO: metadata-only check; write-bytes/ops evidence is Sitting 2 format with creation receipt"
  echo "INFO: recreate approval is John's acceptance of data loss on data-vm-cosmabot-prod-eus2-01"
  az disk show \
    --resource-group "$RG" \
    --subscription "$SUBSCRIPTION_ID" \
    --name data-vm-cosmabot-prod-eus2-01 \
    --query "{name:name,createOption:creationData.createOption,sizeGb:diskSizeGb,managedBy:managedBy}" \
    --output json || return 1
}
cosmabot_recreate_disk_evidence
```

Stop unless `createOption` is `Empty` and `sizeGb` is `128`.

### 9.2 Recheck is clean

Precondition: TEMP SSH is closed via the existing bootstrap-close box before
this step and through step 9.6. Do not open a TEMP SSH rule during recreate
plan/apply.

```bash
cosmabot_recreate_recheck() {
  test -n "${SUBSCRIPTION_ID:-}" || { echo "STOP: SUBSCRIPTION_ID unset" >&2; return 1; }
  test -n "${SOURCE_SHA256:-}" || { echo "STOP: SOURCE_SHA256 unset" >&2; return 1; }
  test -n "${LOCK_SHA256:-}" || { echo "STOP: LOCK_SHA256 unset" >&2; return 1; }
  test -n "${TOFU_BIN:-}" || { echo "STOP: TOFU_BIN unset" >&2; return 1; }
  test -n "${PROVIDER_MIRROR:-}" || { echo "STOP: PROVIDER_MIRROR unset" >&2; return 1; }
  test -n "${PROD_INPUTS:-}" || { echo "STOP: PROD_INPUTS unset" >&2; return 1; }
  test -n "${PRIVATE_DIR:-}" || { echo "STOP: PRIVATE_DIR unset" >&2; return 1; }
  bash infra/beta/review-cosmabot-prod-foundation.sh \
    --recheck \
    --subscription-id "$SUBSCRIPTION_ID" \
    --inputs "$PROD_INPUTS" \
    --private-dir "$PRIVATE_DIR" \
    --source-sha256 "$SOURCE_SHA256" \
    --lock-sha256 "$LOCK_SHA256" \
    --tofu "$TOFU_BIN" \
    --provider-mirror "$PROVIDER_MIRROR" || return 1
}
cosmabot_recreate_recheck
```

Stop unless this exits 0 (0 add / 0 change / 0 destroy / 0 replace).

### 9.3 Recreate plan

```bash
cosmabot_recreate_plan() {
  test -n "${SUBSCRIPTION_ID:-}" || { echo "STOP: SUBSCRIPTION_ID unset" >&2; return 1; }
  test -n "${SOURCE_SHA256:-}" || { echo "STOP: SOURCE_SHA256 unset" >&2; return 1; }
  test -n "${LOCK_SHA256:-}" || { echo "STOP: LOCK_SHA256 unset" >&2; return 1; }
  test -n "${TOFU_BIN:-}" || { echo "STOP: TOFU_BIN unset" >&2; return 1; }
  test -n "${PROVIDER_MIRROR:-}" || { echo "STOP: PROVIDER_MIRROR unset" >&2; return 1; }
  test -n "${PROD_INPUTS:-}" || { echo "STOP: PROD_INPUTS unset" >&2; return 1; }
  test -n "${PRIVATE_DIR:-}" || { echo "STOP: PRIVATE_DIR unset" >&2; return 1; }
  bash infra/beta/review-cosmabot-prod-foundation.sh \
    --recreate-workload \
    --subscription-id "$SUBSCRIPTION_ID" \
    --inputs "$PROD_INPUTS" \
    --private-dir "$PRIVATE_DIR" \
    --source-sha256 "$SOURCE_SHA256" \
    --lock-sha256 "$LOCK_SHA256" \
    --tofu "$TOFU_BIN" \
    --provider-mirror "$PROVIDER_MIRROR" || return 1
}
cosmabot_recreate_plan
```

Record the printed `plan_sha256` and `summary_sha256`. Confirm the summary lists
exact create-or-replace addresses for the workload VM, data disk, and data-disk
attachment (mid-replace recovery may be create-only for addresses absent from
state). Keep TEMP SSH closed (bootstrap-close) through this step.

### 9.4 John's typed yes on both hashes

John types **yes** on the exact recreate `plan_sha256` and `summary_sha256`, then
binds a four-key approval file (mode 0600, outside the repo) with `reviewer`,
`review_reference`, `plan_sha256`, and `summary_sha256` only. That **yes** is
John's acceptance of data loss on the recreated data disk.

### 9.5 Apply

```bash
cosmabot_recreate_apply() {
  test -n "${PRIVATE_DIR:-}" || { echo "STOP: PRIVATE_DIR unset" >&2; return 1; }
  test -n "${RECREATE_APPROVAL:-}" || { echo "STOP: RECREATE_APPROVAL unset" >&2; return 1; }
  bash infra/beta/apply-cosmabot-prod-foundation.sh \
    --recreate-workload \
    --confirm-apply \
    --approval "$RECREATE_APPROVAL" \
    --private-dir "$PRIVATE_DIR" || return 1
}
cosmabot_recreate_apply
```

Pre-apply refuses an unattached / wrong-VM `osdisk-vm-cosmabot-prod-eus2-01`.
Pre-apply also runs `az disk show` on `data-vm-cosmabot-prod-eus2-01` and refuses
unless `createOption` is `Empty`, `diskSizeGb` is `128`, and `managedBy` is empty
or the workload VM id. Post-apply (and ApplyAttempted) refuse if the OS disk is
missing or unattached. Keep TEMP SSH closed (bootstrap-close) through this step.

### 9.5a Orphan OS disk resolution (human decision; never deletes)

If preflight or post-apply refuses because `osdisk-vm-cosmabot-prod-eus2-01`
exists unattached or attached to the wrong VM, paste this fence. It only lists
facts and stops for John's decision. It never deletes, updates, or detaches.

```bash
cosmabot_recreate_os_disk_orphan_inspect() {
  test -n "${RG:-}" || { echo "STOP: RG unset" >&2; return 1; }
  test -n "${SUBSCRIPTION_ID:-}" || { echo "STOP: SUBSCRIPTION_ID unset" >&2; return 1; }
  echo "INFO: inspect-only; this fence never deletes or detaches disks"
  az disk show \
    --resource-group "$RG" \
    --subscription "$SUBSCRIPTION_ID" \
    --name osdisk-vm-cosmabot-prod-eus2-01 \
    --query "{name:name,managedBy:managedBy,diskState:diskState,timeCreated:timeCreated}" \
    --output json || return 1
  echo "STOP: human decision required before any recreate continue; do not delete from this paste"
  return 1
}
cosmabot_recreate_os_disk_orphan_inspect
```

### 9.5b Mid-replace recovery

If a prior recreate apply stopped after destroying the VM and/or data disk,
re-run prepare then plan then apply with `--recreate-workload`. The planner lists
state and passes `-replace` only for addresses still present; addresses absent
from state are planned as create-only. The sanitiser still requires the exact
three-address set (VM + data disk + attachment) and refuses any other touch.
If Azure still holds an orphan `osdisk-vm-cosmabot-prod-eus2-01` not attached to
`vm-cosmabot-prod-eus2-01`, preflight refuses until that disk is resolved via the
orphan-inspect fence above.

### 9.6 Recheck

Repeat step 9.2. Stop unless the post-recreate recheck exits 0. Keep TEMP SSH
closed (bootstrap-close) through this step.

### 9.7 Build the creation receipt and run Sitting 2 within 24h

Build the host creation receipt with
`infra/beta/vm/host/build_creation_receipt.py` (depends on PR #397 merging
first; do not invent a substitute). Then run Sitting 2 (format empty disk +
secrets install) within 24 hours of the recreate apply. Sitting 2 format with
the creation receipt is the write-bytes / ops evidence for the data disk.
Re-pin the new VM host key in Sitting 2; do not reuse pre-recreate `known_hosts`.

```bash
cosmabot_recreate_build_receipt() {
  test -n "${RECEIPT_OUT_DIR:-}" || { echo "STOP: RECEIPT_OUT_DIR unset" >&2; return 1; }
  test -f infra/beta/vm/host/build_creation_receipt.py || {
    echo "STOP: build_creation_receipt.py missing - merge #397 first" >&2
    return 1
  }
  python3 infra/beta/vm/host/build_creation_receipt.py \
    --profile cosmabot-vm-prod-v1 \
    --out-dir "$RECEIPT_OUT_DIR" || return 1
}
cosmabot_recreate_build_receipt
```

### 9.8 If 24h lapses

Stop. Do not continue Sitting 2 on a stale receipt. Restart at step 9.1 (disk
metadata check), then continue through fingerprint/review as needed, a new
recreate plan, a new typed **yes** on both new hashes, apply, recheck, rebuild
the receipt, and only then restart Sitting 2.

### 9.9 Go-live latch (after Sitting 2 succeeds)

When the workload is live and recreate must stay dark, write the latch (mode
0600) under the private directory:

```bash
cosmabot_recreate_write_workload_live_latch() {
  test -n "${PRIVATE_DIR:-}" || { echo "STOP: PRIVATE_DIR unset" >&2; return 1; }
  umask 077
  printf '%s\n' '{"go_live":true,"note":"synthetic latch; --recreate-workload refuses while present"}' \
    >"${PRIVATE_DIR}/workload-live.json" || return 1
  chmod 600 "${PRIVATE_DIR}/workload-live.json" || return 1
  echo "PASS: wrote ${PRIVATE_DIR}/workload-live.json mode 0600; recreate path refuses until removed by John"
}
cosmabot_recreate_write_workload_live_latch
```

## 10. Today's checklist (Fri 13 Nov)

- [ ] Agents: runbook PR green; `#383` watched (`#377` / `#381` Merged)
- [ ] Sitting 1: plan-hash yes → `#356` apply **or** `#383` `--recover` → IP recorded → Clerk public values sent
- [ ] Between: agent prep only (no secrets, no staging); host bootstrap tooling ready (T-PROD-2 / `#389`); do not install prod unit yet
- [ ] Sitting 2: export `KEYFILE=$HOME/.cosmabot-sitting2/llm-key1` once → kv-open `/32` → Fence 1 → pause → rotate **key1** → Fence 2 (`--file`, `--encoding utf-8`, `--output none`) → pause → Step B (tag proof; rm + `! -e` `$KEYFILE`) → mode-600 password file → load other six secrets → kv-close + verify → disk-format yes → DNS proxy off → continue-prep yes → **John's hands-on one order** (`#389` bootstrap → second vault window → complete stage → `TEMP-JOHN-SSH-SECRETS-INSTALL` → ssh-stdin install → close-and-verify)
- [ ] §4.3 if interrupted/abandoned: kv-close mandatory even after STOP; verify access+count only; abandon `$KEYFILE` cleanup (unset → STOP, re-export §4.1 path; never PASS)
- [ ] After secrets closed (= Sitting 2 row 5 / §9 (b) agent steps) **one order already done by John**; agents: STOP checks → flag flip → render/start → accept → place prod unit file; enable only after T-PROD-5 + T-PROD-6
- [ ] §4.1: kv-open/close; Fence 1 wrapper (no PASS after STOP); fail-closed rotate (`key1` only; `key2` later); `test -s`; anchored ACCOUNT_ID `^…$`; `--output none`; Step B tag-only; passwords before close; no key on screen/history; HTTP proof no `cat` of key file
- [ ] §4.2: Info.plist + `$APP/public` only; pk_live decode; `$APP/public` Clerk key **presence-only**; web `-F` key; staging host class `[a-z0-9.-]+`; baseline **Pending**
- [ ] `#377` / `#381` Merged; `#383` merged before any recover apply
- [ ] Account-delete vault `CLERK-ACCOUNT-DELETION-SECRET` → host `CLERK_ACCOUNT_DELETION_SECRET` (#356 README line 191)
- [ ] Flags: `WORKSPACE_LLM_BACKEND=azure_gpt41`, `WORKSPACE_LLM_USDZ_ENABLED=true` → `/ready` + `version.json`
- [ ] Eight switches false; synthetic only; staging untouched; no CosmasCode key in prod; never print secret values
