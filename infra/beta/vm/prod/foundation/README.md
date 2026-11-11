# CosmaBot production VM foundation (East US 2)

Production twin of `infra/beta/vm/foundation`. Creates `rg-cosmabot-prod-eus2-01`
and `vm-cosmabot-prod-eus2-01` (D2s_v5) with private Premium ACR, Key Vault, two
storage accounts, private endpoints/DNS, and Log Analytics alerts.

Operator entrypoints live one level up:

- Review (plan + cost): `infra/beta/review-cosmabot-prod-foundation.sh`
- Apply (requires `--confirm-apply`): `infra/beta/apply-cosmabot-prod-foundation.sh`
- Offline dry-run: `infra/beta/vm/prod/dry_run.py`

See `../README.md` for John's exact commands. Azure OpenAI is a separate module
defaulting to off (`enable_azure_openai=false`). This helper prepares and plans
only; it does not apply.
