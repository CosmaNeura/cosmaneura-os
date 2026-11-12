# CosmaBot production VM hosting (draft)

Production copy of the East US 2 CosmaBot VM staging foundation. **Nothing in
this folder is applied by coding agents.** John reviews the plan and cost, then
applies only after an explicit yes.

This tooling is **first-apply-only**. OpenAI opt-in must be in the first apply's
inputs or wait for a separately reviewed day-2 tool. Do not run raw tofu by
hand. Partial-apply recovery: keep the private directory, retain encrypted
state/plans/logs, and open a separately reviewed recovery ticket before retry.

A shared-module refactor of staging/prod foundation is a later ticket. Staging
files under `infra/beta/vm/foundation` stay byte-unchanged in this PR.

## What this creates (after John applies)

| Item | Value |
| --- | --- |
| Resource group | `rg-cosmabot-prod-eus2-01` |
| Region | East US 2 |
| VM | `vm-cosmabot-prod-eus2-01` (`Standard_D2s_v5`) with Postgres 16 + Redis on the host |
| Registry | Premium ACR `acrcbotprdeus2*` (private) |
| Secrets | Key Vault `kv-cbot-prd-*` — values live in Key Vault; the runtime identity cannot read the vault. Installing secrets onto the host as 0400 files is a **separate later ticket**. This PR creates infrastructure only; the prod VM holds no secrets until a release ticket. |
| Storage | Two accounts `stcbotprdapp*` / `stcbotprdbak*` |
| Network | Private endpoints + private DNS zones |
| Monitoring | Log Analytics workspace + metric alerts |
| Hostnames | `beta.cosmas.ai`, `api.beta.cosmas.ai` (placeholders only in profile; DNS cutover is out of scope for #356) |
| Azure OpenAI | Separate module; variable default `false`. John's first-apply reviewed inputs set `enable_azure_openai: true` (see opt-in file). |

Staging names are refused by the production profile. Staging files stay untouched.

Real-patient recording stays **off**. Prod runs with **no LLM traffic** until a
separate, later cutover ticket (see below). `routes_runtime_traffic` is **false**:
`enable_azure_openai=true` creates the prod OpenAI account and `gpt-4.1-dzus`
resources only; it does not route runtime traffic. The shared model account's
key is never loaded into prod. App code still hardcodes the shared endpoint for
`workspace_llm_available` — accepting the prod endpoint is a separate app ticket
after filming, not part of this PR.

## Prerequisites (John)

1. `az login` to John's tenant.
2. Subscription id as an explicit input (must equal `inputs.subscription_id`).
3. Pinned OpenTofu **1.12.5** and a verified local `azurerm` provider mirror
   (see Mac setup).
4. Reviewed public inputs JSON. No secret values.
5. Operator-supplied `--source-sha256` and `--lock-sha256` from a fingerprint
   review of this foundation.

### Mac setup

Install OpenTofu **1.12.5** and verify its checksum before use. Build or verify
the filesystem provider mirror the review script expects (`--tofu` and
`--provider-mirror`). Commands only; nothing here talks to Azure:

```bash
# Example pin locations — adjust to John's machine layout.
TOFU=/absolute/path/to/tofu-1.12.5
MIRROR=/absolute/path/to/verified-azurerm-mirror
"$TOFU" version -json   # terraform_version must be 1.12.5
# Verify the tofu binary checksum against the published 1.12.5 release digest
# John recorded at download time (sha256sum / shasum -a 256).
# Mirror layout must serve registry.opentofu.org/hashicorp/azurerm for AzureRM 4.81.
ls "$MIRROR"
# Produce reviewed hashes (from a clean checkout of this foundation):
python3 infra/beta/vm/prod/foundation/bootstrap_local.py fingerprint
# Pass source_sha256 and lock_sha256 from that JSON to the review script.
# Do not point --private-dir at a path that is a symlink under /tmp unless the
# resolved absolute path stays outside the repository.
```

Default example inputs (`inputs.example.json`; invented placeholders only). The
**variable default** and this README example stay `false`:

```json
{
  "subscription_id": "00000000-0000-4000-8000-000000000001",
  "tenant_id": "00000000-0000-4000-8000-000000000002",
  "resource_name_suffix": "abcd1234",
  "vnet_address_prefix": "10.249.0.0/24",
  "admin_username": "cosmasoperator",
  "admin_ssh_public_key": "ssh-ed25519 AAAAOPENSSHPLACEHOLDER reviewer@example.invalid",
  "release_operator_object_id": "00000000-0000-4000-8000-000000000003",
  "alert_contact_email": "owner@example.invalid",
  "enable_azure_openai": false
}
```

### First-apply OpenAI opt-in (John's reviewed inputs)

John asked for the AI resource in the same first-apply pass. Use
`inputs.optin.example.json` (or equivalent reviewed inputs) with:

```json
"enable_azure_openai": true
```

The module variable default remains `false`. Deployment capacity is pinned at
**1** (smallest DataZoneStandard capacity unit). Capacity increases only in the
later LLM cutover ticket. SSH public key, release operator object id, and alert
email remain placeholders in the example file. No secret values.

## Review (what-if / plan + cost)

From the repository root, after `az login`:

```bash
bash infra/beta/review-cosmabot-prod-foundation.sh \
  --subscription-id "$SUBSCRIPTION_ID" \
  --inputs /absolute/path/to/reviewed-prod-inputs.json \
  --private-dir /absolute/path/outside/repo/cosmabot-prod-foundation-fresh \
  --source-sha256 "$SOURCE_SHA256" \
  --lock-sha256 "$LOCK_SHA256" \
  --tofu /absolute/path/to/tofu-1.12.5 \
  --provider-mirror /absolute/path/to/verified-azurerm-mirror
```

Cost-only (no Azure calls; safe offline):

```bash
bash infra/beta/review-cosmabot-prod-foundation.sh --cost-only
```

The review command prints dual standing totals, name guards, a sanitised plan
summary (create counts by type, effective `enable_azure_openai`, subscription,
tenant, `plan_sha256` / `summary_sha256`), and refuses delete/replace. It does
**not** apply. After review it prints the hashes and points here for apply; it
does not print an apply command line with `--confirm-apply`.

## Apply (only after John's yes)

Bind an approval file (0600, outside the repo) to the exact plan John reviewed:

```json
{
  "reviewer": "john@example.invalid",
  "review_reference": "ticket-or-message-id",
  "plan_sha256": "<from review output>",
  "summary_sha256": "<from review output>"
}
```

```bash
bash infra/beta/apply-cosmabot-prod-foundation.sh \
  --confirm-apply \
  --approval /absolute/path/outside/repo/approval.json \
  --private-dir /absolute/path/outside/repo/cosmabot-prod-foundation-fresh
```

Both `--confirm-apply` and `--approval` are required. Coding agents must not run
apply.

## Load secrets into Key Vault (release operator, after apply)

John runs these himself. Secrets never go in the inputs JSON, the private plan
directory, or an `azurerm_key_vault_secret` resource. The recorded versioned
secret id (`--query id --output tsv`) is the custody evidence.

**Installing those values onto the host as 0400 files is a separate later
ticket.** #356 creates infrastructure only; the prod VM holds no secrets until
a release ticket. See `infra/beta/vm/runtime/README.md` for the eventual
mode-0400 host-file contract (`server.key`, `users.acl`, TLS public certs).
`allow_extension_operations` stays **true** so the Azure Monitor agent
extension can install (**CTO decision, 11 Nov 2026**). **Run Command must never
carry secret values** and must never be used for secret install (**CTO
decision, 11 Nov 2026**). Do not add Bastion, VPN, or jump-host resources.

### Key Vault network path (**CTO decision, 11 Nov 2026**)

Vault IaC keeps `public_network_access_enabled = false` with ACL default Deny.
`publicNetworkAccess Disabled` overrides firewall allow rules, so an own-IP
rule alone does not work while public access stays Disabled. John's temporary
path (option a): from John's workstation, briefly set public network access
Enabled with default Deny plus a single `/32` for John's own public IPv4, load
secrets with `--file`, then the trap/remove path sets public access Disabled
again, removes the `/32`, and verifies `publicNetworkAccess == Disabled` and an
empty `ipRules` list (print the whole list). No Bastion and no in-VNet path.

Value files: Linux prefers `/dev/shm`; macOS uses a RAM disk recipe below.
Every set uses `--file`, `--encoding utf-8`, and `--query id --output tsv`.
Never use `--value`, never echo secret bytes, no `set -x`, no `--debug`.

```bash
#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${OPERATOR_IP:?set OPERATOR_IP to John's current public IPv4}"
: "${RESOURCE_NAME_SUFFIX:?set RESOURCE_NAME_SUFFIX from the applied foundation}"
VAULT_NAME="kv-cbot-prd-${RESOURCE_NAME_SUFFIX}"
RG="rg-cosmabot-prod-eus2-01"

if [[ "$(uname -s)" == "Darwin" ]]; then
  # macOS RAM disk (~32 MiB) for value files.
  RAMDEV="$(hdiutil attach -nomount ram://65536)"
  diskutil erasevolume HFS+ 'cosmabotkv' "$RAMDEV"
  TMP="/Volumes/cosmabotkv/cosmabot-kv-$$$$"
  mkdir -p -m 700 "$TMP"
else
  TMP="$(mktemp -d /dev/shm/cosmabot-kv-XXXXXX)"
fi

cleanup() {
  # Revert the time-boxed public-access window even on failure.
  az keyvault update \
    --name "$VAULT_NAME" \
    --resource-group "$RG" \
    --public-network-access Disabled \
    --only-show-errors >/dev/null 2>&1 || true
  az keyvault network-rule remove \
    --name "$VAULT_NAME" \
    --resource-group "$RG" \
    --ip-address "${OPERATOR_IP}/32" \
    --only-show-errors >/dev/null 2>&1 || true
  if [[ -n "${TMP:-}" && -d "${TMP}" ]]; then
    shred -u "${TMP}"/* 2>/dev/null || rm -f "${TMP}"/*
    rmdir "${TMP}" 2>/dev/null || true
  fi
  if [[ "$(uname -s)" == "Darwin" && -d /Volumes/cosmabotkv ]]; then
    diskutil eject /Volumes/cosmabotkv >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

az keyvault update \
  --name "$VAULT_NAME" \
  --resource-group "$RG" \
  --public-network-access Enabled \
  --only-show-errors
az keyvault network-rule add \
  --name "$VAULT_NAME" \
  --resource-group "$RG" \
  --ip-address "${OPERATOR_IP}/32" \
  --only-show-errors

# Generate distinct URL-safe 32–128 character passwords (runtime README rule).
openssl rand -base64 48 | tr -d '\n' | tr '+/' '-_' >"$TMP/database_password"
openssl rand -base64 48 | tr -d '\n' | tr '+/' '-_' >"$TMP/postgres_password"
openssl rand -base64 48 | tr -d '\n' | tr '+/' '-_' >"$TMP/redis_password"
# Clerk and deploy-evidence value files: John writes them into TMP himself.
# Paths are placeholders only; no secret bytes in this repository.

az keyvault secret set \
  --vault-name "$VAULT_NAME" \
  --name CLERK-SECRET-KEY \
  --file "$TMP/clerk_secret_key" \
  --encoding utf-8 \
  --query id --output tsv

az keyvault secret set \
  --vault-name "$VAULT_NAME" \
  --name CLERK-ACCOUNT-DELETION-SECRET \
  --file "$TMP/clerk_account_deletion_secret" \
  --encoding utf-8 \
  --query id --output tsv

az keyvault secret set \
  --vault-name "$VAULT_NAME" \
  --name DATABASE-PASSWORD \
  --file "$TMP/database_password" \
  --encoding utf-8 \
  --query id --output tsv

az keyvault secret set \
  --vault-name "$VAULT_NAME" \
  --name POSTGRES-PASSWORD \
  --file "$TMP/postgres_password" \
  --encoding utf-8 \
  --query id --output tsv

az keyvault secret set \
  --vault-name "$VAULT_NAME" \
  --name REDIS-PASSWORD \
  --file "$TMP/redis_password" \
  --encoding utf-8 \
  --query id --output tsv

az keyvault secret set \
  --vault-name "$VAULT_NAME" \
  --name HUMAN-DEPLOY-EVIDENCE-REF \
  --file "$TMP/human_deploy_evidence_ref" \
  --encoding utf-8 \
  --query id --output tsv

# Explicit revert + verify (also covered by trap).
az keyvault update \
  --name "$VAULT_NAME" \
  --resource-group "$RG" \
  --public-network-access Disabled \
  --only-show-errors
az keyvault network-rule remove \
  --name "$VAULT_NAME" \
  --resource-group "$RG" \
  --ip-address "${OPERATOR_IP}/32" \
  --only-show-errors

az keyvault show \
  --name "$VAULT_NAME" \
  --resource-group "$RG" \
  --query properties.publicNetworkAccess -o tsv
# Expect: Disabled

az keyvault network-rule list \
  --name "$VAULT_NAME" \
  --resource-group "$RG" \
  -o json
# Expect: empty ipRules list (print the whole list).
```

Names-only mapping (Key Vault name → host file → services). Host install of these
files is the later release ticket; do not invent a transport here.

| Key Vault secret name | Host file name | Service directories | Source |
| --- | --- | --- | --- |
| `CLERK-SECRET-KEY` | `CLERK_SECRET_KEY` | `api`, `worker` | Clerk |
| `CLERK-ACCOUNT-DELETION-SECRET` | `CLERK_ACCOUNT_DELETION_SECRET` | `api`, `worker` | Clerk |
| `DATABASE-PASSWORD` | `DATABASE_PASSWORD` | `api`, `worker`, `prepare` | John-generated |
| `POSTGRES-PASSWORD` | `POSTGRES_PASSWORD` | `prepare`, `postgres` | John-generated (distinct) |
| `REDIS-PASSWORD` | `REDIS_PASSWORD` | `api`, `worker`, `redis` | John-generated (distinct) |
| `HUMAN-DEPLOY-EVIDENCE-REF` | `HUMAN_DEPLOY_EVIDENCE_REF` | `api`, `worker` | John-generated deploy evidence |

`WORKSPACE_LLM_API_KEY` is **not** declared in the first-apply profile and is
**not** loaded here. It belongs only to the later LLM cutover (below).

## Later LLM cutover (separate tickets; not #356)

Opt-in in this PR creates resources only (`routes_runtime_traffic: false`). A
later, separately approved cutover must include, in order:

1. An **app** change to accept the prod OpenAI endpoint (separate app ticket
   after filming; not this PR).
2. Set `WORKSPACE_LLM_ENDPOINT` to the account base URL from module output
   `azure_openai_endpoint` (account base URL, not the chat-completions path).
3. Set `WORKSPACE_LLM_USDZ_ENABLED=true`.
4. Remove the deployment pin or set it to `gpt-4.1-dzus`.
5. Load the **new prod account's** key into Key Vault and onto the host; the
   shared model account's key must never be loaded into prod.
6. Raise DataZoneStandard capacity only in that cutover ticket (first-apply
   capacity stays 1).

OpenAI key load at cutover only (placeholder paths; John writes the value file):

```bash
az cognitiveservices account keys list \
  --name "oai-cbot-prd-${RESOURCE_NAME_SUFFIX}" \
  --resource-group "$RG" \
  --query key1 -o tsv >"$TMP/workspace_llm_api_key"
az keyvault secret set \
  --vault-name "$VAULT_NAME" \
  --name WORKSPACE-LLM-API-KEY \
  --file "$TMP/workspace_llm_api_key" \
  --encoding utf-8 \
  --query id --output tsv
```

## DNS

Nothing in #356 touches DNS.

## Offline dry-run (CI-safe)

```bash
python3 infra/beta/vm/prod/dry_run.py
python3 infra/beta/vm/prod/dry_run.py --enable-azure-openai
uv run pytest tests/unit/test_cosmabot_prod_hosting.py -q
```

No Azure credentials, logins, or API calls.

## Encrypted state and OpenAI keys (CTO decision, 11 Nov 2026)

Provider-generated sensitive attributes can still exist inside encrypted
state/plans. Keep the whole private folder private, retain the encryption key
with a separately protected recovery copy, and never print or commit decrypted
state/plans or private command logs. Losing the key makes these artifacts
unrecoverable. Encryption does not protect against a compromised operator
account that can also read the key.

With `enable_azure_openai=true`, the Azure OpenAI account keys land in tofu
state. The state must stay encrypted, its encryption key is never in the repo,
and the backend is the private local encrypted backend — handled like staging's
state. After first apply, rotate the OpenAI account keys (John) before any
cutover that loads a key into Key Vault: create a new key in the account, load
the new value via `--file` in the cutover ticket, then retire the old key.
