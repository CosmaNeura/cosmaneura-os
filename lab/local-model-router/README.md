# Local model job router (lab only)

What happens tonight to existing live users: nothing. This is a developer-only
tool under `lab/local-model-router/`. It is not part of the product runtime,
deploys, or infra, but it is now part of `synth-ci` via a required job named
`lab-local-model-router`.

## What it does

Rule-based router for CoS on John's Mac:

| Work | Lane |
| --- | --- |
| CI / build / test log summaries, diff pre-review | `gemma4:12b` |
| Unit tests, single-file fixes, strict structured output (T1–T3) | `inkling-2-mini` |
| Lint/doc batches (T3 start) | `gemma4-26b` |
| Oversize / local failures | Azure `codex-mini` → `gpt-5.3-codex` → Cursor cloud agent |

Thresholds, step-up/step-down rules, Inkling `num_predict` / timeout, and
promotion (`3` runs per cell) live in `config/router_config.json`.

## Hard guards (CTO amendments)

1. Truncation: `tokens_processed < tokens_sent` → FAIL. Long logs → 12B only.
2. 12B summaries: every number/ID in the summary must appear in the source.
3. Memory: heavy models only after 12B unload; abort if free memory `< 5%` or
   swap watchdog trips (memory reader is injectable for tests).
4. Promotion only after 3 runs per cell.
5. Out of scope for v1: Inkling briefs/prompts and agent-chatter templates.
6. Metrics JSONL: tokens per merged PR by vendor/activity, review rounds,
   Fable rejection after gates, escalation rate.

Fable review is mandatory for every coding lane plan
(`fable_review_required: true` and not config-disableable). Local pre-review is
a filter only.

## Approval gate

Local and Azure batches refuse to start without an explicit per-run approval
token from CoS after John's yes:

```bash
cd lab/local-model-router
uv run --project ../.. python -m local_model_router plan-batch \
  --approved-run-id cos-yes-YYYYMMDD-NNN \
  --batch-kind local \
  --job-json fixtures/sample_job_unit.json
```

The token is a recorded string, not a secret. Azure endpoint URLs are read from
env **names** in config only (`AZURE_CODEX_MINI_ENDPOINT`,
`AZURE_GPT_5_3_CODEX_ENDPOINT`); no keys or live endpoints are stored.

## Dry-run (synthetic jobs only)

```bash
cd lab/local-model-router
uv run --project ../.. python -m local_model_router dry-run fixtures/synthetic_jobs.json
```

Output is a table: job, lane, reason, guards. Fixture covers every task type
plus truncation and low-memory cases. No model calls; no network.

## Harness (plan only)

Builds Aider / pytest / ruff commands; never runs a model in CI.

- `OLLAMA_API_BASE=http://127.0.0.1:11434`
- `--map-tokens 0`
- One Aider attempt → pytest + ruff → one follow-up → escalate
- No Codex full-access or bypass flags, ever

## Inkling / 26B caps (config + Modelfile snippet)

- Inkling: `num_predict` raised to `8192`, timeout `480s` in
  `config/router_config.json` so thinking cannot starve the diff.
- Documented Modelfile snippet for gemma4-26b coder:
  `docs/MODELFILE_gemma4_26b_coder.snippet` (`PARAMETER num_predict 2048`).
  Do not apply from this repo onto John's Mac.

## Tests

Collected via the `lab-local-model-router` job in `synth-ci`: `cd lab/local-model-router && uv run --no-project --with pytest --with pyyaml python -m pytest -q`.

Locally:
```bash
cd lab/local-model-router
uv run --project ../.. pytest -c pytest.ini
```

From repo root:

```bash
uv run pytest -c lab/local-model-router/pytest.ini lab/local-model-router/tests
```

## Out of scope

- Product, infra, CI workflows, rulesets, Trivy
- Production / PHI logs
- Applying Modelfiles on John's Mac from this change
- Contacting Fable (Build Lead does that after CI green)
