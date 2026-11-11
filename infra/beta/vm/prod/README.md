# CosmaBot production VM hosting (draft)

Production copy of the East US 2 CosmaBot VM staging foundation. **Nothing in
this folder is applied by coding agents.** John reviews the plan and cost, then
applies only after an explicit yes.

## What this creates (after John applies)

| Item | Value |
| --- | --- |
| Resource group | `rg-cosmabot-prod-eus2-01` |
| Region | East US 2 |
| VM | `vm-cosmabot-prod-eus2-01` (`Standard_D2s_v5`) with Postgres 16 + Redis on the host |
| Registry | Premium ACR `acrcbotprdeus2*` (private) |
| Secrets | Key Vault `kv-cbot-prd-*` (Clerk read by secret **name** only) |
| Storage | Two accounts `stcbotprdapp*` / `stcbotprdbak*` |
| Network | Private endpoints + private DNS zones |
| Monitoring | Log Analytics workspace + metric alerts |
| Hostnames | `beta.cosmas.ai`, `api.beta.cosmas.ai` (DNS-only, no proxy) |
| Azure OpenAI | Separate module, **OFF by default** (needs its own John yes) |

Staging names (`rg-cosmas-os-vm-staging-eus2-lab01`, `staging.cosmas.ai`,
`acrcbotstgeus2*`, `kv-cbot-stg-*`, `stcbotapp*` / `stcbotbak*`) are refused by
the production profile. The staging profile helper refuses production names.
Staging files under `infra/beta/vm/foundation` stay untouched.

Real-patient recording stays **off** in `profile/runtime-public.json`. Model
backend/deployment match staging (`azure_gpt41` / `gpt-4.1`).

## Prerequisites (John)

1. `az login` to John's tenant.
2. Subscription id as an explicit input (no default subscription selection).
3. Pinned OpenTofu **1.12.5** and a verified local `azurerm` provider mirror.
4. Reviewed public inputs JSON (subscription/tenant/suffix/VNet/admin SSH public
   key/release operator object id/alert email). No secret values.

Example inputs shape (invented values only in tests):

```json
{
  "subscription_id": "00000000-0000-4000-8000-000000000001",
  "tenant_id": "00000000-0000-4000-8000-000000000002",
  "resource_name_suffix": "abcd1234",
  "vnet_address_prefix": "10.249.0.0/24",
  "admin_username": "cosmasoperator",
  "admin_ssh_public_key": "ssh-ed25519 AAAA... reviewer@example.invalid",
  "release_operator_object_id": "00000000-0000-4000-8000-000000000003",
  "alert_contact_email": "owner@example.invalid"
}
```

## Review (what-if / plan + cost)

From the repository root, after `az login`:

```bash
bash infra/beta/review-cosmabot-prod-foundation.sh \
  --subscription-id "$SUBSCRIPTION_ID" \
  --inputs /absolute/path/to/reviewed-prod-inputs.json \
  --private-dir /absolute/path/outside/repo/cosmabot-prod-foundation \
  --tofu /absolute/path/to/tofu-1.12.5 \
  --provider-mirror /absolute/path/to/verified-azurerm-mirror
```

Cost-only (no Azure calls; safe offline):

```bash
bash infra/beta/review-cosmabot-prod-foundation.sh --cost-only
```

The review command:

1. Prints the checked-in monthly cost estimate from
   `prices/monthly-estimate.json` (labeled **estimate**, with **price_date**).
2. Prints a loud warning if the estimate exceeds **$300/month**.
3. Proves production↔staging name refusal both ways.
4. Runs the encrypted local OpenTofu **plan** (same prepare/plan pattern as
   staging). It does **not** apply.

## Apply (only after John's yes)

```bash
bash infra/beta/apply-cosmabot-prod-foundation.sh \
  --confirm-apply \
  --private-dir /absolute/path/outside/repo/cosmabot-prod-foundation
```

Without `--confirm-apply` the script refuses. Coding agents must not run apply.

## Offline dry-run (CI-safe)

```bash
python3 infra/beta/vm/prod/dry_run.py
uv run pytest tests/unit/test_cosmabot_prod_hosting.py -q
```

No Azure credentials, logins, or API calls.

## DNS

Publish `beta.cosmas.ai` and `api.beta.cosmas.ai` as DNS-only records (no CDN /
proxy) to the foundation public IP after apply. Terraform does not change the
DNS provider.
