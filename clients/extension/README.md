# CosmaBot local extension sign-in proof

Unpacked Manifest V3, draft experiment, synthetic data only. The extension talks
only to a local CosmaBot Box and uses that practice's CosmaBot Clerk development
instance. Core and Scribe are outside this proof.

The fixed ID is `dafmlbjpkdfjnchpcnghgkeckdbmofhf`. The manifest `key` is an RSA
**public** identity descriptor for that ID, not a Clerk key or signing secret.
No private key was retained. Do not change it between Chrome and Edge loads.

## Build

From the repository root:

```sh
./scripts/install-client-deps.sh
node clients/extension/build.mjs
```

Supply the following names in the process environment, or set
`COSMABOT_EXTENSION_ENV_FILE` to one explicitly selected local env file. Never
commit that file or generated `dist/` output. The build embeds only the selected
publishable development key, organization and issuer; it rejects live keys and
mismatched issuers. No Clerk secret key is needed.

| Variable | Selection |
| --- | --- |
| `COSMABOT_EXTENSION_CLERK_PUBLISHABLE_KEY` | Existing CosmaBot development publishable key |
| `COSMABOT_EXTENSION_CLERK_ISSUER` | Exact matching `https://…clerk.accounts.dev` origin |
| `COSMABOT_EXTENSION_CLERK_ORGANIZATION_ID` | Existing synthetic development organization |
| `COSMABOT_EXTENSION_DATABASE_URL` | Dedicated `postgresql+psycopg` database `cosmabot_extension_synth` at `127.0.0.1`, explicit port and user |
| `COSMABOT_EXTENSION_BOX_ID` | Invented canonical UUID for the local Box |
| `COSMABOT_EXTENSION_CLERK_SUBJECT` | Existing development test account subject; setup only |

To inspect the bundle without credentials:

```sh
node clients/extension/build.mjs --unconfigured
```

That artifact disables sign-in. It is not evidence of successful authentication.

## Local Box and invented fixture

Use a fresh, dedicated local PostgreSQL database named
`cosmabot_extension_synth`. The profile refuses other database names, remote
hosts, and production Clerk issuers. The setup command refuses a nonempty
public schema or an existing proof schema. It creates only a synthetic Box,
human, reviewed Clerk identity binding, and the local observations table.
It does not run hosted migrations or seed patient records.

```sh
uv run python clients/extension/run-local.py --init
uv run python clients/extension/run-local.py
```

In another terminal:

```sh
uv run python -m http.server 8765 --bind 127.0.0.1 --directory clients/extension/fixture
```

The API binds `127.0.0.1:8766`. It accepts exactly the fixed extension Origin,
exact loopback Host and a loopback client, including on preflight. Clerk JWTs
must have the exact extension `azp`, development issuer, active session,
configured organization and a currently active local human-to-Box binding.
Default development sessions must omit `aud`; a different or missing `azp`
fails closed. Synthetic identity headers do not bypass sign-in.

## Browser check procedure

1. Open `chrome://extensions` or `edge://extensions`, enable developer mode,
   and load `clients/extension/dist` unpacked. Check that the ID matches above.
2. Open `http://127.0.0.1:8765/schedule.html`, then open the extension's side panel
   from its toolbar action.
3. Sign in with an existing CosmaBot **development** test account. This smallest
   proof supports a password-complete sign-in. MFA, SSO, CAPTCHA or other required
   steps show a visible blocked state; this proof does not bypass them. No web
   app sync host, remote authentication UI or second Clerk application is added.
4. “Check local Box” makes the authenticated call through the service worker.
   “Read invented schedule” reads selectors from the bundled JSON pack, posts
   evidence, and shows stub prep. “Copy prep” copies that text only.
5. Remove or rename a required selector in the local fixture and reload the
   fixture. Read again: “Screen not recognised” must appear, previous prep must
   clear, and copy must be disabled. Restore the fixture and retry.
6. Sign out and retry the local call. It must refuse access. A different extension
   Origin or signed `azp` must also be refused.

Host permission patterns list only the fixture and API ports. The content
script matches only the local schedule path and repeats the exact origin/path
check at runtime. The panel's CSP permits bundled scripts only, no frames or
remote code. Its connection policy adds only the selected Clerk development
issuer to the fixed API origin. The service worker never returns tokens to
content scripts or the panel. Clerk manages its own client credential in the
extension's local storage; session tokens are obtained fresh for each call.

Observations are append-only Postgres rows with canonical UTF-8 JSON and a
SHA-256 verified by a database CHECK. Database triggers reject UPDATE, DELETE
and TRUNCATE. Repeated reads create new observations, not approvals or actions.
A failed append returns a generic error; a retry can create a new observation.
A lost successful response can therefore produce duplicate evidence on retry.
There is no observation update/delete API, form-fill, page click, page submit,
recording, capture, pack recorder or generator. The prep is an invented stub.
The database owner can change DDL; this proof is not a tamper-proof storage claim.

The provided runner disables HTTP access logs and SQL parameter echo. Validation,
auth and storage errors are generic and never include the request body or raw
exception. Do not run this proof with alternate verbose request/body middleware.

## Automated checks and limitations

The normal backend test command discovers `tests/integration/test_extension_local.py`
and `tests/unit/test_extension_client.py`. The client installer installs the pinned
extension SDK and bundler; the unit test runs the worker tests and builds an
unconfigured artifact. The normal `cd web && corepack pnpm test` command discovers
`web/src/extension-signin.test.ts` and exercises actual DOM selectors and panel
states. CI remains required and unchanged.

The automated checks cover accepted/rejected request Origins and signed `azp`,
preflight, spoofed identity, wrong issuer/audience/organization, missing or
invalid sign-in, local human revocation, payload/error log scrubbing, immutable
storage/hash constraints, append failure/retry, missing selector and recovery.

Clerk's [extension quickstart](https://clerk.com/docs/getting-started/quickstart/chrome-extension-js)
requires Native API support. Some instances also require the fixed extension
origin to be already allowed. This test does not alter Clerk settings. If the
existing development configuration cannot admit this extension, stop there and
record the specific blocker. Do not change a live setting to complete this test.

At implementation time no CosmaBot development Clerk env/key was available,
so actual sign-in plus a browser-to-local-Box call is **unverified**. Chrome
157.0.8103.79 was found on the Mac, but Computer Use did not permit access to it;
unpacked loading was **not checked**. Edge was not installed, so its loading
was **not checked**. The fixed-ID manifest and bundle are checked by tests;
those checks do not substitute for either browser load. Password sign-in,
Native API enablement, current origin allowlisting, organization activation,
and resulting `azp` still require a browser check with existing development
configuration. Never describe this as “just works.”

The referenced `/workspace/fable/arch-extension-2026-11-16.md` was unavailable
on this Mac. Implementation follows the supplied 17 Nov test prompt; comparison
against Fable's Challenge item 1 and PLAN packet remains unverified. Fable's
review of the final head remains outstanding. No cross-task contact is made by
this implementation.
