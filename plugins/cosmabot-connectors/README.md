# CosmaBot Connectors

This operational MCP plugin calls the existing authenticated CosmaBot API. It
uses configured provider adapters and saved bot work rather than the lab runtime.
The API checks current identity, accounts, revisions, source grants and approvals.
In the CosmaBot encounter interface, use the current signed-in application
session. Browser requests use the normal session-authenticated workspace client;
desktop requests use the existing main-process authenticated workspace proxy.
These transports keep credentials with the session owner and invalidate work
when that identity/session changes. No manually exported JWT file is needed for
this application path. Enabled configuration still does not prove an account is
connected or a provider operation completed.

Install the project's `mcp` extra into the existing Python 3.13 virtual environment.
Create an application-session profile by selecting the actual API origin:

```sh
python -m cosmas_os.plugins.configure --source /absolute/path/to/cosmaneura-os \
  --output /absolute/path/to/new/cosmabot-connectors \
  --origin https://api.staging.cosmas.ai
```

This writes `app-session.json` for a trusted application host. It records public
origin/workspace selection and requires that host's authenticated adapter; it
does not create a stdio server entry or claim that Chrome sign-in is available
to a separate process. Python hosts can bind the same runtime without obtaining
tokens:

```python
from cosmas_os.plugins.runtime import AuthenticatedSession, PluginRuntime

runtime = PluginRuntime(api_origin, workspace_id=workspace_id,
    session=AuthenticatedSession(host_authenticated_request, host_session_revision))
```

The trusted request callback accepts httpx-style method/URL and
`headers`, `json`, `params`, `timeout`, returning a streaming `httpx.Response`.
It must use the existing authenticated client/proxy, enforce redirects and
deadlines, and cancel on sign-out. The revision callback returns a nonsecret
session identity revision, or `None` when signed out. The runtime pins that
revision, checks it before dispatch and while/after reading responses, bounds
response bytes, and accepts only locally defined operation paths, schemas and
headers. Neither callback comes from a tool argument. It adds no listener,
browser-storage access, credentials or account grants. `create_server(runtime)`
and `main(..., session=adapter)` use this same bound runtime for embedded MCP.

For an external stdio MCP client, authentication must be configured separately.
If its session owner already maintains an owner-only credential file, adding
`--token-file /absolute/private/path/current-session.jwt` preserves that optional
compatibility path and writes `.mcp.json`. CosmaBot does not export the browser
session to that file, and starting stdio without an authenticated adapter or
explicit file reports the missing authentication rather than claiming readiness.

Use `--workspace-id` to restrict encounter tools to one encounter. An explicit token file
must be an owner-only regular file (0600); its contents are reread for every API
request so the existing session owner can refresh it. Never paste tokens into
tool arguments, configuration, source files or chat. This plugin does not create
credentials or retrieve tokens from browser storage. Load the generated external
MCP package only after its authentication is configured. `cosmabot-connectors --check` performs signed
configuration discovery only; it does not call a provider or claim account health.

Connect Google as john@cosmaneura.com and other development providers as
dev@cosmaneura.com in CosmaBot Connections. Email addresses alone do not install
fax accounts, portal mappings or grants. The existing account setup must bind
each provider's exact account, credential reference and independent capabilities.

For a bot journey: reopen the encounter, read currently shared evidence, ask Chief
for a saved-source draft, and inspect each specialist's saved handoff. Request
changes or accept results through the human encounter interface. The bot can
prepare a revision from an existing exact human feedback receipt. Recovery tools
observe the original command/key; they never automatically repeat uncertain work.

Tools include bounded Google/Microsoft reads, current Google source custody,
approved SRFax/Documo image acquisition, retained fax PDFs, vendor/portal/Stripe
proposals and status, Core/Scribe/Scheduling/Research reads and recovery, and
read-only Elation appointment, problem, medication, and lab pages. Elation tools
call the existing signed EHR read route. They say in plain language when Elation
is not connected or when that read is not supported. They do not prescribe, sign,
book, or change the chart. See `docs/plugins/elation-reads.md`.
Tebra appointment, visit, authorized-patient, and medication tools are read-only pages on that same route. They say when Tebra is not connected or a read is not supported. See `docs/plugins/tebra-reads.md`.
Enabled tools depend on signed server configuration; current grants are checked
again when called. Spruce fax images remain unavailable until verified download
hosts exist. Spruce's installed registry supports retained inbox work; fresh inbox
fetching still requires a durable provider-read admission path. Human review,
recording initiation, consent, account changes and destination execution remain
in the existing product interface.
