# D3 beta web host and release contract

Status: **SOURCE IMPLEMENTED / NOT DEPLOYED**
Data boundary: **SYNTHETIC LAB ONLY UNTIL A SEPARATE AUTHORIZED-BETA GATE**

The D3 environment declares a dedicated static web Container App alongside the
standalone CosmaBot API and worker. It is a new Track B resource inside the
isolated beta resource group and Terraform state. It does not reuse the D2 app,
D2 image, Track A hosting, identity, state, or domain.

On 2026-09-25 the owner confirmed `staging.cosmas.ai` for testing, reserving
`bot.cosmas.ai` for the user-facing CosmaBot app. This supersedes the earlier
`bot.cosmas.ai` staging candidate. The examples below use the confirmed staging
hostname; they do not establish deployment, DNS binding, or approval of a
particular foundation or workload plan. Retain that hostname through all
staging release stages.

Prepare a staging web bundle with the nginx procedure below. That procedure
does not publish the bundle. The Container Apps contract that follows is
source-only. It is not how the last recorded staging web update was made, and
this procedure does not apply it.

## Staging web update

This procedure prepares a static web bundle for `https://staging.cosmas.ai`
only. It does not change the API, the database, Clerk, DNS, or production.

`scripts/package-staging-web.mjs` is the only command. It accepts `--dist` and
`--output` and no other flags. The only origin written in that file is
`https://staging.cosmas.ai`. An argument that names production
(`app.cosmaneura.com`, `staging-app.cosmaneura.com`, `chat.cosmaneura.com`,
`staging-chat.cosmaneura.com`, `bot.cosmas.ai`, `app.cosmas.ai`,
`api.cosmas.ai`, `www.cosmas.ai`), or that says production, Terraform, Azure,
or kubectl, stops the helper before it writes anything. Its only subprocess is
local `tar`. It does not call a shell, SSH, Docker, a cloud CLI, or Terraform,
so there is no path from this command to a production host.

Do not run the helper as a deployment. It builds a local archive and stops.

1. At one reviewed commit, with synth-ci green including the image scan, build
   the web so `web/dist/version.json` exists. The file contains the 40-character
   commit and the UTC build time. `pnpm build` and `pnpm run build:beta` both
   emit it. The image build passes the same commit as `VITE_BUILD_SHA`.
2. Package that directory into a new local folder:

   ```sh
   node scripts/package-staging-web.mjs --dist web/dist --output /protected/staging-web-PACKAGE
   ```

   The folder receives `cosmabot-web-<commit>.tar.gz` and `receipt.json`.
   The receipt records `target` `https://staging.cosmas.ai`, `server` `nginx`,
   and `deployed: false`.
3. Open `version.json` inside the archive and check that `commit` is the
   reviewed SHA before anyone copies the archive. A Beta Tester re-score can
   then be tied to that commit by fetching `/version.json` on staging.
4. Putting the archive on the staging nginx document root, and any reload, is
   a separate human step. This repository does not perform it. Use only the
   staging path that served the last recorded web archive. Do not point that
   step at a production hostname, and do not use it as a reason to apply the
   Container Apps plan or the beta VM runtime below.

### How staging is updated today

These facts are from this repository. They are not a live inspection.

- The last recorded hosted web advance is `release-r6r1` on 29 October 2026.
  The web artifact was the static archive
  `cosmabot-web-0e70fe6-0.1.147-1107.tar.gz`. The API was not rebuilt; it stayed
  on R5 source `b770fe05f339e15c681a0df2b4b4b329e47d770d`. There was no
  data, schema, or identity change. See
  `docs/COSMABOT_RELEASE_STATE_20261030.md`. The commands that unpacked that
  archive are not in git. The private package that holds the receipts is outside
  this repository.
- The web image this repository builds is nginx, not Caddy. `Dockerfile.web`
  copies `web/dist` to `/usr/share/nginx/html` in
  `nginxinc/nginx-unprivileged` and listens on port 8080. `web/nginx.conf`
  serves `/healthz`, fingerprinted assets, and `/version.json`. A missing
  version file returns 404 instead of the application shell.
- `infra/beta` is a different design, and it is built on Caddy. The VM runtime
  still runs the nginx web container, then puts Caddy in front of it
  (`reverse_proxy web:8080` for `staging.cosmas.ai`). That runtime README says
  rendering does not deploy, the VM path is not qualified, and a test render
  must not be copied onto staging. `infra/standalone/render.mjs` says the
  existing staging VM's TLS is already owned by Caddy, and for
  `vm-cosmabot-staging-eus2-lab01` it refuses to emit a second listener.
  Replacing a Caddyfile, rendering a new VM release, or applying Terraform is
  not the update recorded for R6r1, and this procedure does not do those things.
- `docs/beta/CONNECTOR_UX_AND_ACTIVATION_20260928.md` says a maintenance window
  deploys the API first and then the web at `staging.cosmas.ai`. It does not
  give the command. `docs/beta/STAGING_VM_OPTION_20260925.md` says the
  configured name `staging.cosmas.ai` does not prove DNS, a certificate, or a
  running app.

### Not confirmed from the repository

John or Shawn would have to confirm these. This change did not log in to a
host, query Azure, or request the live site.

- The live nginx document root, and whether today's staging web is that
  unprivileged container or a host nginx reading an unpacked archive.
- The exact command used to install
  `cosmabot-web-0e70fe6-0.1.147-1107.tar.gz`.
- Whether Caddy on `vm-cosmabot-staging-eus2-lab01` is currently the public
  edge in front of nginx, or is only the beta design. The standalone renderer
  and the beta VM runtime disagree with a plain "nginx only" description, and
  the R6r1 record describes a static web archive rather than a Caddy change.
- Which machine answers `staging.cosmas.ai` now, and whether its certificate
  and DNS match the names in the docs.

## Fixed hosting contract

- Azure Container Apps provides the public HTTPS certificates and external
  origins. Plain HTTP is disabled for both web and API ingress.
- The foundation creates the Container Apps environment while
  `deploy_workloads=false`. Record the confirmed hostname in the foundation
  inputs as `web_custom_domain = "staging.cosmas.ai"` with
  `web_custom_domain_dns_ready = false`. Applying the reviewed foundation plan
  supplies `web_origin` and `api_origin`, reserving the selected web origin and
  deterministic API hostname before either workload exists.
- The human must configure the shared Cosmaneura Clerk instance for that exact
  `web_origin`, with separate CosmaBot permissions (`DL-20260927-01`). The
  workload plan refuses any different approved origin. A separate production
  Clerk application is not the accepted identity topology.
- The API derives `CORS_ALLOWED_ORIGINS` and `CLERK_AUTHORIZED_PARTIES` from
  the same Terraform origin; wildcard or caller-selected origins are not used.
- `web_custom_domain` remains nullable for non-production validation, but D3
  production Clerk must use the dedicated hostname accepted by the exact owner
  decision; the confirmed staging hostname is `staging.cosmas.ai`. It cannot
  use the shared `azurecontainerapps.io` default. Terraform rejects
  uppercase/invalid hostnames and explicitly refuses the existing
  `app.cosmaneura.com`, `staging-app.cosmaneura.com`, `chat.cosmaneura.com`,
  and `staging-chat.cosmaneura.com` names. This stack does
  not select a hostname or create/change public DNS records.
- The frontend is served by a separate, non-root Nginx image on port 8080.
  `/healthz` is the only unauthenticated host probe and contains no app data.
- The image contains only static assets. It receives no runtime secret and has
  no managed-identity permissions beyond the ACR pull needed to start it.

## Fail-closed frontend artifact

`Dockerfile.web` builds the checked-in React application with the fixed
`operational-beta-v1` feature profile and `web` client. The existing feature
compiler supplies `VITE_COSMAS_ENV=early_adopter_beta` and the feature gates.
The protected builder consumes exactly the seven uppercase fields used by
`web-build-arguments.json`:

```json
{
  "VITE_CLERK_PUBLISHABLE_KEY": "<PK_LIVE_PUBLISHABLE_KEY>",
  "VITE_WORKSPACE_HOSTED_API_ORIGIN": "<D3_API_ORIGIN>",
  "VITE_WORKSPACE_WEB_ORIGIN": "<D3_WEB_ORIGIN>",
  "VITE_WORKSPACE_DATA_MODE": "synthetic",
  "VITE_COSMANEURA_WEB_ORIGIN": "<REVIEWED_CORE_WEB_ORIGIN>",
  "VITE_CAPTURE_UPLOAD_ORIGINS": "<REVIEWED_CAPTURE_UPLOAD_ORIGIN>",
  "VITE_WORKSPACE_CAPTURE_MODE": "browser_microphone"
}
```

Replace the placeholders with explicit public configuration. `<D3_API_ORIGIN>`
must be the standalone CosmaBot API origin from the validated protected
`probe-network` artifact's `public_configuration.api_origin`. The foundation
derives it from the dedicated API Container App name and its Container Apps
environment domain; it cannot be inferred from `staging.cosmas.ai` or replaced
with the Core staging origin. `<D3_WEB_ORIGIN>` must match that artifact's
`public_configuration.web_origin` and the selected approved web hostname.
Core and upload values must be exact, credential-free HTTPS origins without
ports, paths, queries or fragments. Uploads
accept one to four distinct origins separated by commas without spaces. Web
capture mode is `browser_microphone` or `synthetic`.

The public observation recorded at 2026-09-25 14:25 UTC established
`https://staging-app.cosmaneura.com` as the Core/platform web and Python API
origin: its root, healthcheck, and explicitly linked public configuration
returned successfully with normal TLS validation. It is the observed staging
value for `<REVIEWED_CORE_WEB_ORIGIN>`, subject to the release's exact public
configuration review. It does not identify a separate CosmaBot API, an upload
origin, or the deployed Core commit. The local task receipt, retained outside
this repository, is
`w100-github-integration-r1/platform-staging-address-review-r1/live-inspection/RESULT.json`.

The public schema observation recorded at 2026-09-25 14:30 UTC in the local task
receipt (also retained outside this repository)
`w100-github-integration-r1/platform-connector-contract-r1/RESULT.json` did not
qualify protected CosmaBot-to-Core connectors. The inspected connection,
appointment, Athena, and record-context routes are absent from that schema and
intentionally excluded from OpenAPI in retained Core source. Their live
availability and authorization remain unverified; schema omission establishes
neither a missing route nor compatibility. Public reachability does not qualify
authenticated, clinical, or Scribe workflows or authorize connector activation.

`infra/beta/validate_web_build.py` runs in both the human-side transport and the
protected builder using Python 3.10+. It rejects duplicate, extra, missing,
overlarge and malformed inputs. This D3 path still requires a production
`pk_live_` publishable key and **synthetic** data mode; it refuses an
`authorized_beta` build file until that separate deployment gate is implemented
and approved. The image label and accepted build evidence hash all seven public
inputs. `web/scripts/validate-beta-build.mjs` independently checks the complete
feature/origin profile during the offline Docker build.

The Clerk secret key (`sk_live_...`), session tokens, user records, Box IDs,
database credentials, and Azure credentials must never be build arguments,
Vite variables, static files, image labels, or browser configuration. A Clerk
publishable key is designed for browser distribution; it is not an API secret.
The runtime continues to render its blocked screen and makes zero API calls if
the client configuration, signed-in session, active Organization, or fresh
session token is unavailable.

## Human-owned release sequence

1. Using the recorded staging hostname decision, apply only the
   reviewed foundation plan with `deploy_workloads=false`,
   `web_custom_domain="staging.cosmas.ai"`, and
   `web_custom_domain_dns_ready=false`.
2. Run the protected `probe-network` operation and record the non-secret
   `public_configuration.web_origin`, `public_configuration.api_origin`, and
   `public_configuration.acr_login_server` values from its validated,
   self-hashed artifact. Confirm the API hostname belongs to the new D3 Container
   Apps environment and the web origin matches the selected custom hostname.
   This supplies the concrete CosmaBot API target required for the build. Do not
   inspect or export raw Terraform state to obtain these values.
3. Create/configure the production Cosmas OS Clerk instance for the exact web
   origin, recreate the empty Cosmas Beta Lab Organization there, and retain
   Clerk secrets only in the human-controlled service. Do not invite testers.
4. At one clean reviewed source SHA, prepare the seven-field public configuration
   above as a mode-`0600` file outside the repository. Validate it locally, then
   use the existing protected build/push path for the API and web images:

   ```text
   python3 infra/beta/validate_web_build.py validate \
     /protected/ephemeral/web-build-arguments.json
   bash infra/beta/transport-to-protected-runner.sh build-push \
     --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
     --source-sha <FULL_REVIEWED_SOURCE_SHA> \
     --release-id <REVIEWED_RELEASE_ID> \
     --web-build-config /protected/ephemeral/web-build-arguments.json \
     --artifact-out /protected/ephemeral/d3-beta-build.json
   ```

   Only the validator is a local source check. `build-push` performs cloud
   mutations and must run from the approved human-controlled path; do not run it
   during source validation. The protected builder binds both origins to live
   foundation outputs and preserves source/network checks, immutable tags,
   vulnerability scans and offline dependency installation/build steps.
5. Scan both images and the static bundle. Record the source SHA, immutable
   `sha256` digests, public build configuration, scan result, and rollback
   digests in protected release evidence. Do not record any token or secret.
6. Supply `image_digest`, `web_image_digest`, the exact derived `web_origin`,
   `web_release_evidence_reference`, the structured
   `database_preparation_attestation`, and the separate
   `runner_live_network_evidence_reference` to the reviewed workload plan.
   Mutable tags are forbidden; the API/worker and web resources pull their
   distinct digest references.
7. Apply the exact reviewed plan, then verify HTTPS-only ingress, `/healthz`,
   security headers, the signed-out zero-API-call behavior, production Clerk
   login, required Beta Lab Organization membership, exact-origin CORS, and
   authenticated API access using invented data only.

## Required production custom-domain stage

A managed-certificate custom domain uses two reviewed workload plans because
Azure exposes the app-specific domain-verification value only after the web
Container App exists.

1. The exact owner decision package records the confirmed `staging.cosmas.ai`
   hostname before the foundation plan. Do not use or modify the existing
   `app.cosmaneura.com`, `staging-app.cosmaneura.com`, `chat.cosmaneura.com`, or
   `staging-chat.cosmaneura.com` records.
2. Retain `web_custom_domain = "staging.cosmas.ai"`, keep
   `web_custom_domain_dns_ready = false`, and set
   `web_origin = "https://staging.cosmas.ai"` in the initial workload plan.
   This creates the app without claiming the custom-domain binding is ready. Do
   not admit testers during this stage.
3. Re-run the protected `probe-network` operation for the post-apply state,
   then run `transport-to-protected-runner.sh domain-verification` with the
   exact source SHA and release ID. Its mode-`0600`, self-hashed artifact
   exposes only the selected hostname, ACA CNAME target, `asuid` TXT name/value,
   and source/release/state binding; it does not return the raw Terraform
   output or any credential. A human confirms the selected hostname's actual
   authoritative DNS zone and provider from its DNS delegation, then creates
   exactly those CNAME and TXT records there. Do not assume the zone is
   `cosmaneura.com` or that its provider is Cloudflare. Terraform does not own
   or mutate these records.
4. Verify both records externally, wait for propagation, and configure the
   production Cosmas OS Clerk application with the exact custom HTTPS origin
   and redirect URLs. Keep wildcard origins disabled.
5. Run the protected `inspect-stage` operation for `workloads`. Prepare a new
   mode-`0600` workload tfvars file that changes only
   `web_custom_domain_dns_ready` from `false` to `true` and replaces
   `runner_live_network_evidence_reference` with the fresh post-apply probe.
   Have the owner approve the exact current artifact inventory and replacement
   tfvars hash, then run `stage-generation` with transition mode
   `planned_workloads_progression`. This archives the first successful stage
   generation instead of overwriting it. Create and review the second plan
   from the newly staged variables. Any other tfvars change fails closed.
6. Apply only that reviewed plan and refresh `probe-network` for its resulting
   state. Run `transport-to-protected-runner.sh workload-verify` with the same
   bootstrap outputs, source SHA and release ID and a new `--artifact-out` path.
   This read-only command derives the expected configuration from the resident
   reviewed plan and checks the live API, worker and web revisions, exact
   workspace/native settings, secret references, replica limits, routing and
   HTTPS readiness. Retain its plan-bound v2 receipt. If readiness is still
   settling, resolve the reported failure and re-run verification without
   applying the infrastructure again.
7. Verify Clerk login/redirects, exact-origin CORS behavior and authenticated
   API access using invented data. The infrastructure receipt does not prove
   account or clinical workflow acceptance. Record evidence without storing
   session tokens or user data.

The AzureRM 4.81 managed-certificate contract intentionally omits certificate
IDs and binding type. Both fields are lifecycle-ignored because Azure fills
them asynchronously; removing those ignores can cause replacement churn.

Rollback is another reviewed plan that changes `web_image_digest` and/or
`image_digest` to a previously scanned digest. Do not rebuild an old tag or
change Clerk authority as a rollback shortcut.
