# CosmaBot production VM hosting (draft)

Production copy of the East US 2 CosmaBot VM staging foundation. **Nothing in
this folder is applied by coding agents.** John reviews the plan and cost, then
applies only after an explicit yes.

This tooling is **first-apply-only** by default. OpenAI opt-in must be in the
first apply's inputs or wait for a separately reviewed day-2 tool. Do not run
raw tofu by hand. Partial-apply recovery: keep the private directory, retain
encrypted state/plans/logs, and use `--recover` on the reviewed recovery
tooling (see Recovery below) before any retry.

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

Press Ctrl-C once for a graceful stop of a running apply. A second Ctrl-C does
not stop OpenTofu; it only detaches the wrapper while tofu must be left to
finish (follow the uniquely named `logs/apply-*.log`). Apply failures and
interrupts exit with code **2**. Partial-apply recovery: keep that private
directory and follow **Recovery** below (do not delete encrypted state or the
passphrase; do not run raw tofu by hand).

## Recovery (partial first apply; `--recover`)

Use this only when a reviewed first apply created most of `rg-cosmabot-prod-eus2-01`
but stopped short (for example the OpenAI private endpoint and its NIC). Keep the
existing private directory. Never regenerate, print, or move the passphrase.
Never wipe encrypted state except through tofu's own state handling on a later
approved apply.

1. Re-fingerprint this foundation after checking out the recovery tooling, and
   pass the new operator-supplied `--source-sha256` / `--lock-sha256` (the
   fingerprint covers `bootstrap_local.py`, `name_guards.py`, and the review /
   apply scripts).
2. Print-only recover plan (no apply):

```bash
bash infra/beta/review-cosmabot-prod-foundation.sh \
  --recover \
  --subscription-id "$SUBSCRIPTION_ID" \
  --inputs /absolute/path/to/same-reviewed-prod-inputs.json \
  --private-dir /absolute/path/outside/repo/cosmabot-prod-foundation-fresh \
  --source-sha256 "$SOURCE_SHA256" \
  --lock-sha256 "$LOCK_SHA256" \
  --tofu /absolute/path/to/tofu-1.12.5 \
  --provider-mirror /absolute/path/to/verified-azurerm-mirror
```

The recover path reuses the existing private dir in place, requires
`state/foundation.tfstate` and `encryption.passphrase`, allows only the existing
production resource group to pre-exist, and writes `plans/recover-<UTC>.tfplan`
plus `recover-plan-summary-<UTC>.json` / `recover-plan-result-<UTC>.json`. It
never overwrites `plans/first.tfplan` or the first-apply summary/result files.
Before planning it also writes `state/foundation.tfstate.pre-recover-<UTC>` and
`manifest.first-apply.json` (0600). The plan is accepted for approval only when
it is ADD-ONLY (0 change, 0 replace, 0 destroy), every create's
`resource_group_name` / scope and every nested ARM
`/subscriptions/.../resourceGroups/.../` id resolve to this subscription and
`rg-cosmabot-prod-eus2-01` (case-insensitive; unknown id fields in
`after_unknown` are refused), and name guards refuse cross-environment /
staging names.

3. John reviews the printed `plan_sha256` / `summary_sha256` and types yes on
   that new recovery plan hash only.
4. Bind a four-key approval file (0600, outside the repo) to those exact recover
   hashes, then apply once:

```bash
bash infra/beta/apply-cosmabot-prod-foundation.sh \
  --recover \
  --confirm-apply \
  --approval /absolute/path/outside/repo/recovery-approval.json \
  --private-dir /absolute/path/outside/repo/cosmabot-prod-foundation-fresh
```

On failure: stop, keep the artifacts, do not retry. Coding agents must not run
apply.

## Load secrets into Key Vault (separate later secrets ticket)

**Loading secrets into Key Vault and installing them onto the host as 0400 files
is a separate later secrets ticket.** #356 creates infrastructure only; the prod
VM holds no secrets until a release ticket. Secrets never go in the inputs JSON,
the private plan directory, or an `azurerm_key_vault_secret` resource. See
`infra/beta/vm/runtime/README.md` for the eventual mode-0400 host-file contract
(`server.key`, `users.acl`, TLS public certs). `allow_extension_operations`
stays **true** so the Azure Monitor agent extension can install (**CTO
decision, 11 Nov 2026**). **Run Command must never carry secret values** and
must never be used for secret install (**CTO decision, 11 Nov 2026**). Do not
add Bastion, VPN, or jump-host resources.

### Key Vault network path (**CTO decision, 11 Nov 2026**)

Vault IaC keeps `public_network_access_enabled = false` with ACL default Deny.
`publicNetworkAccess Disabled` overrides firewall allow rules, so an own-IP
rule alone does not work while public access stays Disabled. John's temporary
path (option a), for the later secrets ticket: from John's workstation, briefly
set public network access Enabled with default Deny plus a single `/32` for
John's own public IPv4, load secrets with `--file`, then the trap/remove path
sets public access Disabled again, removes the `/32`, and verifies
`publicNetworkAccess == Disabled` and an empty `ipRules` list (print the whole
list). No Bastion and no in-VNet path. No runnable load script is checked in on
this PR; the full load/verify/cleanup script belongs in the secrets ticket.

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

`WORKSPACE_LLM_API_KEY` is **not** declared in the first-apply profile. It
belongs only to the later LLM cutover (below).

## Later LLM cutover (separate tickets; not #356)

Opt-in in this PR creates resources only (`routes_runtime_traffic: false`). The
first-apply profile sets `WORKSPACE_LLM_BACKEND` to `disabled`. A later,
separately approved cutover must include, in order:

1. An **app** change to accept the prod OpenAI endpoint (separate app ticket
   after filming; not this PR).
2. Set `WORKSPACE_LLM_ENDPOINT` to the value derived from module output
   `azure_openai_endpoint` in the **exact form the app ticket defines**. The
   account base URL alone is not a valid app setting.
3. Set `WORKSPACE_LLM_BACKEND` to `azure_gpt41` and `WORKSPACE_LLM_USDZ_ENABLED=true`.
4. Remove the deployment pin or set it to `gpt-4.1-dzus`.
5. Load the **new prod account's** key into Key Vault and onto the host; the
   shared model account's key must never be loaded into prod.
6. Raise DataZoneStandard capacity only in that cutover ticket (first-apply
   capacity stays 1).

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
