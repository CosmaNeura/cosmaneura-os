# Staging BuildKit image publication

`build-images.py prepare` makes two private contexts from `git archive` of the
selected full commit. It never copies the current checkout's edits, dependency
directories, credential files or Git metadata. The API uses that commit's
`Dockerfile`; the account uses its `Dockerfile.web`, with exactly seven public
account fields. Both Dockerfiles, base-image digests, package security fixes,
offline installation and `RUN --network=none` remain unchanged.

The selected foundation must be the dedicated `enrollment-foundation.v1`
staging registry. The account fields must select only
`https://onboarding.staging.cosmas.ai` and
`https://enrollment-api.staging.cosmas.ai`, the matching Development `pk_test`
issuer, account-only routing and the same full source commit. Build flags do
not open registration, activate a trial or grant practice access.

Preparation reads the explicitly supplied protected credential files into
memory and rejects their values anywhere in either context. Select the Clerk
and Stripe secret `.env` files plus any task-owned database/admission secret
files available on the build machine. Simple quoted/unquoted `.env`
assignments are supported; public publishable keys and non-secret metadata are
excluded from the private-value scan. Other inputs are raw secret-value files.
Inputs must be owner-only regular 0600 files. Values and their hashes are never
printed or included in recipes/receipts. Foundation, credential references and
preparation receipts remain outside the uploaded context.
The private outer directories are 0700; archived source descendants retain
their committed 0644/0755 read/execute permissions so Docker COPY remains
readable by the non-root runtime. Context hashes also bind those modes.

## Prepare locally

```bash
python infra/enrollment/build-images.py prepare \
  --source /path/to/canonical-checkout --commit FULL_40_HEX_COMMIT \
  --public-config /protected/public-account-build.json \
  --foundation /protected/foundation.json \
  --secret-file /protected/clerk.env \
  --secret-file /protected/stripe.env \
  --secret-file /protected/enrollment-runtime-admission.secret \
  --output /protected/new-buildkit-images
```

The output has separate `api/` and `account/` contexts and one
`prepared.json`. ACR YAML context upload selects root `.dockerignore`, rather
than the Dockerfile-specific ignore used by ordinary Docker builds. The
account context therefore overlays root `.dockerignore` with the selected
commit's complete `Dockerfile.web.dockerignore`. Each root ignore additionally
admits only the generated `cosmabot-acr-task.yaml`. These ignore overlays and
the generated public task are the only additions/changes to archived source;
the selected source and original ignore/Dockerfile hashes are recorded.

The task uses the officially documented ACR multi-step `build` with
`env: [DOCKER_BUILDKIT=1]`. Unlike quick `az acr build`, it has no default push.
Before its explicit push, the API image must import the actual modules and
serve closed configuration through the deployed
`python -m cosmas_os.enrollment.api` entry point, without database/vendor
credentials. This catches a module that imports successfully but exits without
starting its server. The account must run non-root, pass nginx configuration,
carry the exact source/host/issuer/account-only manifest and public key, and
serve its actual local health route. Neither check qualifies hosted database,
vendor sign-in or a customer journey.
Validation uses no optional ACR step `network` field: Microsoft Learn's field
type and the current official runner schema disagree. Its startup configuration
is closed, contains no vendor/database credentials and requests only loopback;
the Dockerfiles' offline `RUN --network=none` restrictions remain intact.

The subsequent scanner uses the exact Trivy digest from the selected commit's
CI and its existing `vuln`, `HIGH,CRITICAL`, `--ignore-unfixed`, `--exit-code 1`
gate. It scans the built image through the ACR task Docker daemon before push.
ACR's runner supplies its normal build-host Docker socket and registry-login
home mounts to task containers; no new mount or credential is supplied by this
recipe. Deployed runtime containers have no build-host socket mount. A failed
startup or scanner prevents the push step.
Do not replace unavailable scanning with an unscanned push.

## Owner-operated cloud steps

Preparation does not call Azure. Separately authorize the actual operator run:

```bash
python infra/enrollment/build-images.py queue \
  --prepared /protected/new-buildkit-images --kind api
python infra/enrollment/build-images.py queue \
  --prepared /protected/new-buildkit-images --kind account
```

Queue verifies the selected Azure subscription/tenant and exact registry,
rescans and hashes the prepared context, and calls `az acr run` with a local
YAML task, `linux/amd64`, `--no-wait` and `--no-logs`. It captures the actual
returned `runId`, or the official `Queued a run with ID:` line on CLIs that do
not emit JSON; it never assumes that quiet quick-task output is JSON. No raw
CLI streams, source-upload SAS URLs or provider credentials are forwarded.

The intent file is written before queueing. Repeating that prepared job is
denied, including after a timeout or unknown response. Inspect the actual
owned ACR run and reconcile an uncertain operation before preparing a new
build. Do not delete its intent file and automatically retry.

Read actual status with a fresh protected receipt path per observation:

```bash
python infra/enrollment/build-images.py collect \
  --prepared /protected/new-buildkit-images --kind api \
  --receipt /protected/api-run-observation.json
python infra/enrollment/build-images.py collect \
  --prepared /protected/new-buildkit-images --kind account \
  --receipt /protected/account-run-observation.json
```

Pending/failed runs have no admitted image or successful validation/scan flag.
Only a successful task whose output image agrees with the actual registry
manifest digest produces an immutable owned `image@sha256:` reference. A local
Docker configuration ID is never substituted. Collection is one bounded read,
not a polling loop. All receipts keep `deployed` and
`hosted_journey_qualified` false. Actual account/API deployment, TLS and the
owner-to-Chief journey remain separate acceptance gates.

Official reference:
<https://learn.microsoft.com/en-us/azure/container-registry/container-registry-tasks-reference-yaml>

Focused offline checks:

```bash
python -m py_compile infra/enrollment/build-images.py
python -m pytest -q infra/enrollment/tests/test_build_images.py
```

The queue/digest tests use invented Azure responses and perform no cloud calls.
