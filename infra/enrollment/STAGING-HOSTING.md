# Separate staging account hosting

This source owns only `onboarding.staging.cosmas.ai` and
`enrollment-api.staging.cosmas.ai`, in the independent enrollment resource
group/environment/registry. It does not select the existing
`staging.cosmas.ai` beta host or any production host. Public DNS is published
separately; Terraform never changes the DNS provider or zone. The private API
secret-reference inputs and its identity remain the enrollment runtime's inputs.

The account web app has one dedicated image-pull identity and no vault,
database, clinical, Core or provider credentials. Both apps expose HTTPS only.
The web app reuses the pinned `Dockerfile.web` Node/nginx images, security
package fixes, port 8080 and `/healthz` probes. The default image profile remains
`beta`; account hosting explicitly selects `WEB_BUILD_PROFILE=enrollment`.
The separately implemented central API probe uses `/operational-ready`: its own
migrated database can be healthy while registration stays closed. `/ready`
continues to report registration readiness and may correctly return 503.
Operational health grants no registration, billing or private tenant access.

## Prepare the account image

Render the reviewed enrollment manifest with these exact origins and the
selected **Development** Clerk issuer/key. The renderer still controls whether
registration and trial activation are open; an account build flag is not
registration permission.

```text
app_origin: https://onboarding.staging.cosmas.ai
api_origin: https://enrollment-api.staging.cosmas.ai
```

`web-build-env.json` contains only public account settings and the exact source
commit. `build:enrollment` rejects mixed workspace/native/runtime/provider
settings, a mismatched Clerk issuer/key, foreign hosts or a short source ID.
Every browser path in this account-only build remains in the saved account
flow, including `/`, `/onboarding`, `/sign-in`, `/sign-up` and an obsolete
`/workspaces` bookmark. Ordinary workspace builds keep their original routing.
The built `cosmas-enrollment-build.json` records the public source/host/issuer
binding and identifies the image as an account build, not a clinical workspace.

On the separately authorized build/publish runner, use the renderer's public
arguments as an argument array, not shell evaluation. For example, in Bash:

```bash
mapfile -t account_build_args < <(jq -r 'to_entries[] | "--build-arg=\(.key)=\(.value)"' "$rendered_dir/web-build-env.json")
docker buildx build --file Dockerfile.web \
  --build-arg WEB_BUILD_PROFILE=enrollment \
  "${account_build_args[@]}" --tag "$reviewed_account_image_tag" .
```

Publish only to the dedicated enrollment ACR through the existing build
conventions. Scan the actual image and select its immutable `@sha256:` reference
as `staging_web_image`. The account host check below must later confirm the
actual deployed source/issuer/host manifest; an image name alone is not proof.

## First deployment: apps, without public domain binding

Use the independent foundation and the actually qualified central database
preparation receipt. Keep the reviewed private API image and secret references.
In the runtime's reviewed variables, set:

```text
environment = staging
deploy_workload = true
database_preparation_qualified = true
deploy_staging_web = true
staging_web_image = OWNED_ENROLLMENT_ACR/account-web@sha256:EXACT_REVIEWED_DIGEST
bind_staging_custom_domains = false
```

Apply through the existing owner-operated enrollment deployment flow. The new
web app is `ca-cosmabot-enroll-web-staging`; the separate API remains
`ca-cosmabot-enrollment-staging`. The first stage creates both apps and exposes
their actual Azure DNS targets and ownership tokens. It does not bind domains.
Export only this protected publication output from the actual runtime state:

```bash
umask 077
tofu output -json staging_account_dns_records > "$protected_dns_manifest"
```

The output contains these exact record names with values obtained from the
created apps; no guessed Azure suffix or placeholder ownership token is valid:

| Type | Fully qualified record name | Value in the output |
| --- | --- | --- |
| CNAME | `onboarding.staging.cosmas.ai` | `account.cname.value` |
| TXT | `asuid.onboarding.staging.cosmas.ai` | `account.txt.value` |
| CNAME | `enrollment-api.staging.cosmas.ai` | `api.cname.value` |
| TXT | `asuid.enrollment-api.staging.cosmas.ai` | `api.txt.value` |

Confirm the actual authoritative delegation and publish these records through
the owned DNS provider. Use direct DNS CNAME records to the selected Azure apps;
proxy/CDN targets do not pass this certificate gate. The TXT values are public
DNS ownership material, not application credentials, but raw state and all
unrelated outputs stay protected.

## Second deployment: verify DNS, then request managed certificates

After propagation, change only `bind_staging_custom_domains` to `true` in the
reviewed runtime variables. OpenTofu refreshes `verify-dns.py` for both apps in
the domain plan/apply. It requires each exact CNAME and `asuid` TXT at both
`1.1.1.1` and `8.8.8.8`, with records derived from the current app state. Foreign,
beta, production, proxy, stale replacement-app or incomplete records fail.
A Boolean, rendered file or previous receipt cannot replace that check.

Review and promptly apply that fresh plan. AzureRM 4.81 then creates the two
owned custom-domain resources and lets Azure issue/bind its managed
certificates, matching the existing beta convention: asynchronous certificate
fields are omitted and lifecycle-ignored. DNS publication, plan success and
resource creation do not prove usable TLS. Wait for actual issuance, and run
the read-only host verifier on the public HTTPS routes:

```bash
node infra/enrollment/verify-staging-hosts.mjs \
  --rendered "$rendered_dir" --output "$new_protected_host_receipt"
```

It checks TLS at the fixed hosts, the deployed account build's exact source and
Clerk issuer, nginx health/assets, all account bookmarks, API synthetic identity,
its measured `/operational-ready`, account CORS/cache headers, the selected public key, and current registration /
activation flags. It reads only the public renderer files. A failed check keeps
activation closed. The host receipt explicitly does not qualify a customer
journey or production.

The real account → practice → signed BAA → card-only trial → private owner setup
→ Chief journey, two isolated practice runtimes, cancellation/recovery and
cross-practice denial still require the separate factory/runtime and staging
qualification steps. Only successful staging evidence precedes production.
Do not substitute host health or a DNS receipt for those checks.

## Focused local checks

```bash
node --test infra/enrollment/render.test.mjs infra/enrollment/verify-staging-hosts.test.mjs web/scripts/enrollment-hosting.test.mjs
python3 -m unittest discover -s infra/enrollment/runtime/tests -p test_dns.py -v
cd infra/enrollment/runtime
tofu fmt -check
tofu init -backend=false -input=false -lockfile=readonly
tofu validate -no-color
tofu test -no-color -filter=tests/staging-hosting.tftest.hcl
```

All five OpenTofu test runs mock Azure/external DNS. The DNS tests use invented
records and no network requests. The public host verifier is run against actual
staging only after the separately executed deployment/TLS stage.
