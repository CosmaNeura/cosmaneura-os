# D3 beta web host and release contract

Status: **SOURCE IMPLEMENTED / NOT DEPLOYED**
Data boundary: **SYNTHETIC LAB ONLY UNTIL A SEPARATE AUTHORIZED-BETA GATE**

The D3 environment declares a dedicated static web Container App alongside the
API and worker. It is a new Track B resource inside the isolated beta resource
group and Terraform state. It does not reuse the D2 app, D2 image, Track A
hosting, identity, state, or domain.

## Fixed hosting contract

- Azure Container Apps provides the public HTTPS certificates and external
  origins. Plain HTTP is disabled for both web and API ingress.
- The foundation creates the Container Apps environment while
  `deploy_workloads=false`. For production Clerk, the recommended pending owner
  decision selects `web_custom_domain = "beta.cosmaneura.com"` with
  `web_custom_domain_dns_ready = false`; once accepted, its `web_origin` and
  `api_origin` outputs reserve the final owned web origin and deterministic API
  hostname before either workload exists.
- The human must configure the production Cosmas OS Clerk instance for that
  exact `web_origin`. The workload plan refuses any different approved origin.
- The API derives `CORS_ALLOWED_ORIGINS` and `CLERK_AUTHORIZED_PARTIES` from
  the same Terraform origin; wildcard or caller-selected origins are not used.
- `web_custom_domain` remains nullable for non-production validation, but D3
  production Clerk must use the dedicated hostname accepted by the exact owner
  decision; the current recommendation is `beta.cosmaneura.com`. It cannot use
  the shared `azurecontainerapps.io` default. Terraform rejects
  uppercase/invalid hostnames and explicitly refuses the existing
  `app.cosmaneura.com`, `staging-app.cosmaneura.com`, `chat.cosmaneura.com`,
  and `staging-chat.cosmaneura.com` names. This stack does
  not select a hostname or create/change Cloudflare DNS records.
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

Replace the placeholders with explicit public configuration. API and web origins
must match the verified foundation outputs. Core and upload values must be exact,
credential-free HTTPS origins without ports, paths, queries or fragments. Uploads
accept one to four distinct origins separated by commas without spaces. Web
capture mode is `browser_microphone` or `synthetic`.

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

1. After the pending exact owner decision accepts the hostname, apply only the
   reviewed foundation plan with `deploy_workloads=false`,
   `web_custom_domain="beta.cosmaneura.com"`, and
   `web_custom_domain_dns_ready=false`.
2. Run the protected `probe-network` operation and record the non-secret
   `public_configuration.web_origin`, `public_configuration.api_origin`, and
   `public_configuration.acr_login_server` values from its validated,
   self-hashed artifact. Confirm the hostnames are inside the new D3 Container
   Apps environment. Do not inspect or export raw Terraform state to obtain
   them.
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

1. The exact owner decision package selects `beta.cosmaneura.com` before the
   foundation plan. Do not use or modify the existing `app.cosmaneura.com`,
   `staging-app.cosmaneura.com`, `chat.cosmaneura.com`, or
   `staging-chat.cosmaneura.com` records.
2. Retain `web_custom_domain = "beta.cosmaneura.com"`, keep
   `web_custom_domain_dns_ready = false`, and set
   `web_origin = "https://beta.cosmaneura.com"` in the initial workload plan.
   This creates the app without claiming the custom-domain binding is ready. Do
   not admit testers during this stage.
3. Re-run the protected `probe-network` operation for the post-apply state,
   then run `transport-to-protected-runner.sh domain-verification` with the
   exact source SHA and release ID. Its mode-`0600`, self-hashed artifact
   exposes only the selected hostname, ACA CNAME target, `asuid` TXT name/value,
   and source/release/state binding; it does not return the raw Terraform
   output or any credential. In the Cloudflare-hosted `cosmaneura.com` zone, a
   human creates exactly those CNAME and TXT records. Terraform does not own or
   mutate them.
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
6. Apply only that reviewed plan, then verify the managed certificate, HTTPS,
   `/healthz`, Clerk login/redirects, exact-origin CORS, and authenticated API
   access. Record evidence without storing session tokens or user data.

The AzureRM 4.81 managed-certificate contract intentionally omits certificate
IDs and binding type. Both fields are lifecycle-ignored because Azure fills
them asynchronously; removing those ignores can cause replacement churn.

Rollback is another reviewed plan that changes `web_image_digest` and/or
`image_digest` to a previously scanned digest. Do not rebuild an old tag or
change Clerk authority as a rollback shortcut.
