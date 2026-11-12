# CosmaBot standalone host preparation

Offline renderer only. It never installs packages, starts services, deploys, or
rotates secrets. Public inputs produce a startup-held review package.

## Explicit-false backend switches

`test_settings_contract.py` requires every `Settings` bool to appear in the
rendered public environment for both `audience` and `shared_staging` policies.
These eight backend switches default to `False` in
`src/cosmas_os/config.py` when unset. The renderer emits them as `'false'` only
(never `'true'`), so prepared hosts match code defaults without changing
off-state behavior:

- `WORKSPACE_CAPTURE_PROXY_ENABLED`
- `GOOGLE_CONNECTION_BROKER_ENABLED`
- `WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED`
- `WORKSPACE_ENROLLMENT_MANAGED`
- `COSMAS_EHR_REAL_DATA_ENABLED`
- `WORKSPACE_RX_SANDBOX_ENABLED`
- `REAL_PATIENT_RECORDING_ENABLED`
- `WORKSPACE_EFAX_SANDBOX_ENABLED`

## Checks

synth-ci does **not** run the standalone Node render suites or
`test_settings_contract.py` today (adding them to CI is a separate ticket).
Local commands that must pass for this directory:

```bash
node --test infra/standalone/render.test.mjs \
  infra/standalone/render-beta.test.mjs \
  infra/standalone/render-goldens.test.mjs
uv run python -m unittest infra.standalone.test_settings_contract -v
```

`render-goldens.test.mjs` locks SHA-256 fingerprints of `JSON.stringify(render(...))`
for invented audience, shared_staging, and owned-staging inputs. Those fingerprints
changed because the eight switches above are now present as `"false"` in
`api-public.json` / `api-public.env`, and because `invented-host-input.json`
`schema_revision` was aligned to `EXPECTED_SCHEMA_REVISION` (`a46f2c09d853`).
Off-state flag behavior matches the previous unset defaults.
