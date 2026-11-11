# CosmaBot standalone host preparation

Offline renderer only. It never installs packages, starts services, deploys, or
rotates secrets. Public inputs produce a startup-held review package.

## Default

Without extra flags, capture and Chief agent tools stay dark:

- `WORKSPACE_AGENT_TOOLS_ENABLED=false`
- `WORKSPACE_CAPTURE_BACKEND=disabled`
- Core capture origins empty
- Web / desktop / Apple `VITE_WORKSPACE_CAPTURE_ENABLED=false`

That default must stay byte-identical to main for existing live synthetic hosts.
Key absent is the live-compatible path. Explicit
`syntheticBetaCaptureAndTools: false` matches absent for every rendered file
except the echoed `host-input.json` value.

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
- Web, desktop, and iOS `VITE_WORKSPACE_CAPTURE_ENABLED=true` with real
  microphone modes (`browser_microphone` on web/desktop, `ios_native` on Apple)
- Capture routes are available to all signed-in Box users on that host
- The tool loop applies to all new non-analysis admissions
  (`model_work.py:790-800`); connector/delivery families
  (`agent_tools.py:217-225`) can reach real Google/Microsoft account content
  when those overlays are on
- Network requirements allow exact Core capture HTTPS egress to
  `staging-app.cosmaneura.com` and the IMDS token path
  `http://169.254.169.254/metadata/identity/oauth2/token`
  (from `core_capture_connection.py:168-174`)
- `platform_connections` records the Core staging capture connection; capture
  content is live microphone audio on a synthetic-only host

Rules:

- Absent keeps byte-identical main output. Explicit `false` differs only by the
  `host-input.json` echo.
- Real-patient recording process switch stays off. This renderer never ships
  that process switch on; the server process guard is untouched.
- Opt-in is refused for dedicated practice hosts, production CosmaBot hosts
  (`app.cosmas.ai`, `cosmas.ai`), and `*.cosmaneura.com` web origins. Cosmas/MCD
  production configs are never edited here.
- Inputs are public non-secret values only. Do not add, print, or rotate secrets.
- Turning the opt-in off on a later render leaves in-flight v2 tool/capture
  handoffs to drain or fail closed; there is no automatic replay.

## Checks

synth-ci does **not** run the standalone Node render suites or
`test_settings_contract.py` today (no `.github/workflows` edits in this ticket).
Enrollment Node tests under `infra/enrollment/` are CI-guarded; these standalone
files are local-only until a separate CI-list ticket lands.

Local commands (all must pass):

```bash
node --test infra/standalone/render.test.mjs \
  infra/standalone/render-beta.test.mjs \
  infra/standalone/render-capture-tools.test.mjs
uv run python -m unittest infra.standalone.test_settings_contract -v
```

| File | CI today | Local |
| --- | --- | --- |
| `render.test.mjs` | not run by synth-ci | `node --test …` above |
| `render-beta.test.mjs` | not run by synth-ci | `node --test …` above |
| `render-capture-tools.test.mjs` | not run by synth-ci | `node --test …` above |
| `test_settings_contract.py` | not run by synth-ci | `uv run python -m unittest …` above |
