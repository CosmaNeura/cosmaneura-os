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
| Secrets | Key Vault `kv-cbot-prd-*` — values live in Key Vault and are installed by the release operator as 0400 host files; the runtime identity cannot read the vault |
| Storage | Two accounts `stcbotprdapp*` / `stcbotprdbak*` |
| Network | Private endpoints + private DNS zones |
| Monitoring | Log Analytics workspace + metric alerts |
| Hostnames | `beta.cosmas.ai`, `api.beta.cosmas.ai` (placeholders only in profile) |
| Azure OpenAI | Separate module; variable default `false`. Opt-in via inputs (see below). |

Staging names are refused by the production profile. Staging files stay untouched.

Real-patient recording stays **off**. With `enable_azure_openai=false`, prod has
**no LLM endpoint** until the OpenAI opt-in. Prod never references or falls back
to any shared model account. With opt-in true, set `WORKSPACE_LLM_ENDPOINT` from
the module output `azure_openai_endpoint`, keep model **gpt-4.1**, use deployment
`gpt-4.1-dzus` created by the module, and load `WORKSPACE_LLM_API_KEY` from Key
Vault per the secret-loading section.

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
```

Default example inputs (`inputs.example.json`; invented placeholders only):

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

### Opt-in (separate John yes)

Filled public template with OpenAI enabled: `inputs.optin.example.json`.

```json
"enable_azure_openai": true
```

SSH public key, release operator object id, and alert email remain placeholders
in that file. No secret values.

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
tenant, `plan_sha256`), and refuses delete/replace. It does **not** apply.

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

## Load secrets (release operator, after apply, before any runtime start)

John runs these himself. Secrets never go in the inputs JSON, the private plan
directory, or an `azurerm_key_vault_secret` resource. The recorded versioned
secret id (`--query id --output tsv`) is the custody evidence.

Value files live on tmpfs under `umask 077` and are shredded afterwards. Every
set uses `--file`, `--encoding utf-8`, and `--query id --output tsv`. Never use
`--value`, never echo secret bytes, no `set -x`, no `--debug`.

Vault is private-only (`public_network_access_enabled = false`, network ACL
bypass `None`, default `Deny`). There is no SSH, bastion, VPN, or jump host in
this foundation. **Approved temporary path:** from John's workstation, add a
Key Vault network ACL allow rule for John's own public IP just before loading,
load secrets, remove that rule immediately, then verify the rule is gone. Never
use Azure VM Run Command. Do not add bastion/VPN/jump-host resources. Do not
turn on broader public access beyond that single own-IP allow rule.

```bash
umask 077
TMP=$(mktemp -d /dev/shm/cosmabot-kv-XXXXXX)
# OPERATOR_IP is John's current public IPv4 (placeholder).
az keyvault network-rule add \
  --name kv-cbot-prd-<suffix> \
  --resource-group rg-cosmabot-prod-eus2-01 \
  --ip-address "<OPERATOR_IP>/32"

# Clerk secret key (placeholder path only).
az keyvault secret set \
  --vault-name kv-cbot-prd-<suffix> \
  --name CLERK-SECRET-KEY \
  --file "$TMP/clerk_secret_key" \
  --encoding utf-8 \
  --query id --output tsv

# Account-deletion Clerk secret (placeholder path only).
az keyvault secret set \
  --vault-name kv-cbot-prd-<suffix> \
  --name CLERK-ACCOUNT-DELETION-SECRET \
  --file "$TMP/clerk_account_deletion_secret" \
  --encoding utf-8 \
  --query id --output tsv

# DB password: John generates into the tmpfs file himself. Never through Run Command or any agent.
az keyvault secret set \
  --vault-name kv-cbot-prd-<suffix> \
  --name DATABASE-PASSWORD \
  --file "$TMP/database_password" \
  --encoding utf-8 \
  --query id --output tsv

# Prod Azure OpenAI account key (only when enable_azure_openai=true was applied).
# Write straight to tmpfs; no agent ever reads it.
az cognitiveservices account keys list \
  --name oai-cbot-prd-<suffix> \
  --resource-group rg-cosmabot-prod-eus2-01 \
  --query key1 -o tsv > "$TMP/workspace_llm_api_key"
az keyvault secret set \
  --vault-name kv-cbot-prd-<suffix> \
  --name WORKSPACE-LLM-API-KEY \
  --file "$TMP/workspace_llm_api_key" \
  --encoding utf-8 \
  --query id --output tsv

az keyvault network-rule remove \
  --name kv-cbot-prd-<suffix> \
  --resource-group rg-cosmabot-prod-eus2-01 \
  --ip-address "<OPERATOR_IP>/32"
az keyvault network-rule list \
  --name kv-cbot-prd-<suffix> \
  --resource-group rg-cosmabot-prod-eus2-01 \
  --query "ipRules[?value=='<OPERATOR_IP>/32']" -o tsv
# Expect empty output: the temporary own-IP rule is gone.

shred -u "$TMP"/* 2>/dev/null || rm -f "$TMP"/*
rmdir "$TMP"
```

Names-only mapping (Key Vault name → host file → services). Install onto the
host as 0400 files per the protected secret-file contract in
`infra/beta/vm/runtime/README.md` (mode-0400 single-link files under
`/etc/cosmabot/runtime/<release_id>`); do not invent a different procedure.

| Key Vault secret name | Host file name | Service directories | Source account |
| --- | --- | --- | --- |
| `CLERK-SECRET-KEY` | `CLERK_SECRET_KEY` | `api`, `worker` | Clerk |
| `CLERK-ACCOUNT-DELETION-SECRET` | `CLERK_ACCOUNT_DELETION_SECRET` | `api`, `worker` | Clerk |
| `DATABASE-PASSWORD` | `DATABASE_PASSWORD` | `api`, `worker`, `prepare` | John-generated |
| `POSTGRES-PASSWORD` | `POSTGRES_PASSWORD` | `prepare`, `postgres` | John-generated (distinct) |
| `REDIS-PASSWORD` | `REDIS_PASSWORD` | `api`, `worker`, `redis` | John-generated (distinct) |
| `WORKSPACE-LLM-API-KEY` | `WORKSPACE_LLM_API_KEY` | `api`, `worker` | Prod OpenAI account `oai-cbot-prd-<suffix>` (when opted in) |

## DNS

Pointing `beta.cosmas.ai` / `api.beta.cosmas.ai` at prod is a separate later
ticket (John's named yes, a healthy prod release first, a written rollback).
Nothing in #356 touches DNS.

## Offline dry-run (CI-safe)

```bash
python3 infra/beta/vm/prod/dry_run.py
python3 infra/beta/vm/prod/dry_run.py --enable-azure-openai
uv run pytest tests/unit/test_cosmabot_prod_hosting.py -q
```

No Azure credentials, logins, or API calls.

## Encrypted state and OpenAI keys (documented exception)

Provider-generated sensitive attributes can still exist inside encrypted
state/plans. Keep the whole private folder private, retain the encryption key
with a separately protected recovery copy, and never print or commit decrypted
state/plans or private command logs. Losing the key makes these artifacts
unrecoverable. Encryption does not protect against a compromised operator
account that can also read the key.

With `enable_azure_openai=true`, the Azure OpenAI account keys land in tofu
state. The state must stay encrypted, its encryption key is never in the repo,
and the backend is the private local encrypted backend — handled like staging's
state. After first apply, rotate the OpenAI account keys (John): create a new
key in the account, load the new value into Key Vault via `--file` as above,
update host 0400 files per the runtime README, then retire the old key.
