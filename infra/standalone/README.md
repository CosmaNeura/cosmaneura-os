# CosmaBot standalone host preparation

Offline renderer only. It never installs packages, starts services, deploys, or
rotates secrets. Public inputs produce a startup-held review package.

## Default

Without extra flags, capture and Chief agent tools stay dark:

- `WORKSPACE_AGENT_TOOLS_ENABLED=false`
- `WORKSPACE_CAPTURE_BACKEND=disabled`
- Core capture origins empty
- Web `VITE_WORKSPACE_CAPTURE_ENABLED=false`

That default must stay byte-identical to main for existing live synthetic hosts.

## Synthetic beta capture + tools opt-in (default off)

For the synthetic CosmaBot staging/beta owned VM only, set:

```json
{
  "syntheticBetaCaptureAndTools": true,
  "core_capture_origin": "https://staging-app.cosmaneura.com",
  "core_web_origin": "https://staging-app.cosmaneura.com",
  "core_capture_scope": "api://invented-core-audience/.default",
  "core_capture_managed_identity_client_id": "00000000-0000-4000-8000-0000000000aa"
}
```

When `true`, the renderer turns on Upload Recording (PR #350 Core capture path)
and Chief agent tools together:

- `WORKSPACE_AGENT_TOOLS_ENABLED=true`
- `WORKSPACE_CAPTURE_NOTES_ENABLED=true`
- `WORKSPACE_CAPTURE_BACKEND=core`
- `WORKSPACE_CAPTURE_PROXY_ENABLED=true`
- `WORKSPACE_CAPTURE_PROXY_ORIGIN=<CosmaBot api_origin>`
- Core origin/scope/managed-identity client id from the public inputs above
- Web `VITE_WORKSPACE_CAPTURE_ENABLED=true`

Rules:

- Absent or `false` keeps the capture-dark main output.
- Real-patient recording stays off. This renderer never ships that process
  switch on; the server process guard is untouched.
- Opt-in is refused for dedicated practice hosts and any non-staging/beta owned
  CosmaBot profile. Cosmas/MCD production configs are never edited here.
- Inputs are public non-secret values only. Do not add, print, or rotate secrets.

## Checks

```bash
node --test infra/standalone/render.test.mjs \
  infra/standalone/render-beta.test.mjs \
  infra/standalone/render-capture-tools.test.mjs
uv run python -m unittest infra.standalone.test_settings_contract -v
```
