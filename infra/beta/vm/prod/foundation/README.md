# CosmaBot production VM foundation (East US 2)

Production twin of `infra/beta/vm/foundation`. Creates `rg-cosmabot-prod-eus2-01`
and `vm-cosmabot-prod-eus2-01` (D2s_v5) with private Premium ACR, Key Vault, two
storage accounts, private endpoints/DNS, and Log Analytics alerts.

Operator entrypoints live one level up:

- Review (plan + cost): `infra/beta/review-cosmabot-prod-foundation.sh`
- Apply (requires `--confirm-apply` and `--approval`): `infra/beta/apply-cosmabot-prod-foundation.sh`
- Offline dry-run: `infra/beta/vm/prod/dry_run.py`

See `../README.md` for John's exact commands. This helper is **first-apply-only**
by default; pass `--recover` on prepare/plan/apply for the separately reviewed
partial-apply recovery path (reuses encrypted state/passphrase; writes
`plans/recover-<UTC>.tfplan`). OpenAI opt-in must be in the first apply's inputs
or wait for a separately reviewed day-2 tool. Do not run raw tofu by hand.

Azure OpenAI is a separate module (variable default `false`). John's first-apply
reviewed inputs set `"enable_azure_openai": true` to include `gpt-4.1-dzus` at
capacity **1**, the OpenAI private endpoint, and `privatelink.openai.azure.com`.
That creates resources only (`routes_runtime_traffic` stays false).

A shared-module refactor with staging is a later ticket. Staging files stay
byte-unchanged here.

## Encrypted local prepare / plan / apply

```text
python3 bootstrap_local.py prepare --private-dir <new-absolute-private-dir> --inputs <actual-public-inputs.json> --source-sha256 <reviewed-source-hash> --lock-sha256 <reviewed-lock-hash> --tofu <pinned-tofu-path> --provider-mirror <verified-cache-root>
python3 bootstrap_local.py plan --private-dir <same-private-dir>
python3 bootstrap_local.py apply --confirm-apply --approval <absolute-approval.json> --private-dir <same-private-dir>
```

Inputs omit generated `state_namespace` and `bootstrap_key_file`; the preparer
supplies them. No application secret is accepted. Provider-generated sensitive
attributes can still exist inside encrypted state/plans (**CTO decision, 11 Nov
2026**). Keep the whole folder private, retain the key with a separately
protected recovery copy, and never print or commit decrypted state/plans or
private command logs. Losing the key makes these artifacts unrecoverable.
Encryption does not protect against a compromised operator account that can
also read the key.

With `enable_azure_openai=true`, the Azure OpenAI account keys land in tofu
state. The state must stay encrypted, its encryption key is never in the repo,
and the backend is the private local encrypted backend — handled like staging's
state. Host secret install and LLM cutover are separate later tickets; see
`../README.md`.
