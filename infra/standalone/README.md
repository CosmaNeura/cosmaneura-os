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

## Production-review (`beta.cosmas.ai`) account delete

Owned `https://beta.cosmas.ai` is the production-review CosmaBot host. Account
delete name mapping on that host is exclusive:

- Identity policy must be `audience` (never `shared_staging`).
- Identity profile must be `operational-production-v1`.
- Clerk issuer must be exactly `https://clerk.beta.cosmas.ai` (added condition;
  never the sole admit). Other issuers (`clerk.staging.cosmas.ai`,
  `clerk.cosmas.ai`, invented) are refused.
- `operational-beta-v1` on `beta.cosmas.ai` is refused.
- Host key name (private mount / env alias): `CLERK_ACCOUNT_DELETION_SECRET`.
  Azure Key Vault object name (hyphens): `CLERK-ACCOUNT-DELETION-SECRET`.
  Render maps that host key into app env `ACCOUNT_DELETE_CLERK_SECRET_KEY`.
- Staging keeps vault secret `account-delete-clerk-secret-key` and vault
  `kv-cbot-stg-stg0925c1` unchanged; production-review never emits those.
- Shared predicate: `src/cosmas_os/production_review_profile.py::classify_review_profile`
  (JS twin `classifyAccountDeleteProfile` in `render.mjs`).

No live users are on `api.beta` yet; this contract change is listed as
out-of-scope of the delete-name ticket in the PR body with that reason.

## Explicit-false backend switches

`test_settings_contract.py` requires every `Settings` bool to appear in the
rendered public environment for both `audience` and `shared_staging` policies.
These eight backend switches default to `False` in
`src/cosmas_os/config.py` when unset. The renderer emits them as `'false'` by
default so prepared hosts match code defaults (Fable hole 2a / PR #361):

- `WORKSPACE_CAPTURE_PROXY_ENABLED`
- `GOOGLE_CONNECTION_BROKER_ENABLED`
- `WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED`
- `WORKSPACE_ENROLLMENT_MANAGED`
- `COSMAS_EHR_REAL_DATA_ENABLED`
- `WORKSPACE_RX_SANDBOX_ENABLED`
- `REAL_PATIENT_RECORDING_ENABLED`
- `WORKSPACE_EFAX_SANDBOX_ENABLED`

Only the synthetic beta capture + tools opt-in below may set
`WORKSPACE_CAPTURE_PROXY_ENABLED=true` (with `WORKSPACE_CAPTURE_PROXY_ORIGIN`).
The other seven stay `'false'` even when that opt-in is on.
`REAL_PATIENT_RECORDING_ENABLED` is never rendered `'true'`.

## Synthetic beta capture + tools opt-in (default off)

For the synthetic CosmaBot staging/beta owned VM only, set:

```json
{
  "syntheticBetaCaptureAndTools": true,
  "core_capture_origin": "https://staging-app.cosmaneura.com",
  "core_web_origin": "https://staging-app.cosmaneura.com",
  "core_capture_scope": "api://invented-core-audience/.default",
  "core_capture_managed_identity_client_id": "00000000-0000-4000-8000-0000000000aa",
  "core_capture_upload_host": "inventedcaptureacct.blob.core.windows.net"
}
```

When `true`, the renderer turns on Upload Recording (PR #350 Core capture path)
and Chief agent tools together:

- `WORKSPACE_AGENT_TOOLS_ENABLED=true`
- `WORKSPACE_CAPTURE_NOTES_ENABLED=true`
- `WORKSPACE_CAPTURE_BACKEND=core`
- `WORKSPACE_CAPTURE_PROXY_ENABLED=true`
- `WORKSPACE_CAPTURE_PROXY_ORIGIN=<CosmaBot api_origin>`
- Core origin/scope/managed-identity client id and upload blob host from the
  public inputs above (`core_capture_upload_host` is an exact lowercase
  `<account>.blob.core.windows.net` hostname; invented account in fixtures)
- Web, desktop, and iOS `VITE_WORKSPACE_CAPTURE_ENABLED=true` with real
  microphone modes (`browser_microphone` on web/desktop, `ios_native` on Apple)
- Capture routes are available to all signed-in Box users on that host
- The tool loop applies to all new non-analysis admissions
  (`model_work.py:790-800`); connector/delivery families
  (`agent_tools.py:217-225`) can reach real Google account content (Google is
  always on for an opt-in host) and Microsoft when that overlay is on
- Network requirements allow exact Core capture HTTPS egress to
  `staging-app.cosmaneura.com`, the IMDS token path
  `http://169.254.169.254/metadata/identity/oauth2/token`
  (from `core_capture_connection.py:168-174`), and HTTPS PUT egress to the
  declared Core capture upload blob host (from
  `capture_upload_proxy.py:295-311`). Runtime pins `CORE_CAPTURE_UPLOAD_HOST`
  exactly (https on port 443 only); host egress is defense in depth.
- `platform_connections` records the Core staging capture connection and upload
  blob host; capture content is live microphone audio on a synthetic-only host.
  Client manifests keep `platformAccess:'disabled'`; Core capture uses that
  connection entry, not Cosmaneura platformAccess.

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

synth-ci beta-infra-static runs `render.test.mjs` and `render-beta.test.mjs`
(PR #360). It does not run `render-goldens.test.mjs`,
`render-capture-tools.test.mjs`, or `test_settings_contract.py` (no
`.github/workflows` edits in this ticket). Fable hole 2a moved to the render
ticket (#361), which landed the eight explicit-false switches; the full
settings-contract module is expected green after that merge.

Local commands that must pass for this directory:

```bash
node --test infra/standalone/render.test.mjs \
  infra/standalone/render-beta.test.mjs \
  infra/standalone/render-goldens.test.mjs \
  infra/standalone/render-capture-tools.test.mjs
uv run python -m unittest infra.standalone.test_settings_contract -v
```

| File | CI today | Local |
| --- | --- | --- |
| `render.test.mjs` | beta-infra-static (PR #360) | `node --test …` above |
| `render-beta.test.mjs` | beta-infra-static (PR #360) | `node --test …` above |
| `render-goldens.test.mjs` | not run by synth-ci | `node --test …` above |
| `render-capture-tools.test.mjs` | not run by synth-ci | `node --test …` above |
| `test_settings_contract.py` | not run by synth-ci | `uv run python -m unittest …` above |

`render-goldens.test.mjs` locks SHA-256 fingerprints of `JSON.stringify(render(...))`
for invented audience, shared_staging, and owned-staging inputs. Regenerated in
the post-#354 Clerk follow-up when `invented-host-input.json` moved the beta
identity to `clerk.cosmas.ai` (shared_staging fingerprint unchanged because that
case overrides identity). Off-state opt-in-absent output must stay byte-identical
to those goldens. `render-capture-tools.test.mjs` reuses the same dedicated and
owned-staging fingerprints as `MAIN_*_FINGERPRINT`.

Regen (repo root; print audience fingerprint of the committed sample):

```bash
node --input-type=module -e "
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {render} from './infra/standalone/render.mjs';
const sample=JSON.parse(await readFile('./infra/standalone/invented-host-input.json','utf8'));
const fp=f=>createHash('sha256').update(JSON.stringify(f)).digest('hex');
console.log(fp(render(structuredClone(sample))));
"
```
