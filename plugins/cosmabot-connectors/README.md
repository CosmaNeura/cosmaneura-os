# CosmaBot Connectors

This operational MCP plugin calls the existing authenticated CosmaBot API. It
uses configured provider adapters and saved bot work rather than the lab runtime.
The API checks current identity, accounts, revisions, source grants and approvals.

Install the project's `mcp` extra into the existing Python 3.13 virtual environment.
Create a local runnable copy, selecting the actual API origin and private sign-in
file supplied by your existing authenticated session:

```sh
python -m cosmas_os.plugins.configure --source /absolute/path/to/cosmaneura-os \
  --output /absolute/path/to/new/cosmabot-connectors \
  --origin https://api.staging.cosmas.ai \
  --token-file /absolute/private/path/current-session.jwt
```

Use `--workspace-id` to restrict encounter tools to one encounter. The token file
must be an owner-only regular file (0600); its contents are reread for every API
request so the existing session owner can refresh it. Never paste tokens into
tool arguments, configuration, source files or chat. This plugin does not create
credentials or retrieve tokens from browser storage. Load the generated package
in your MCP client. The repository template has no configured server until this
step selects the real environment. `cosmabot-connectors --check` performs signed
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
proposals and status, and Core/Scribe/Scheduling/Research reads and recovery.
Enabled tools depend on signed server configuration; current grants are checked
again when called. Spruce fax images remain unavailable until verified download
hosts exist. Spruce's installed registry supports retained inbox work; fresh inbox
fetching still requires a durable provider-read admission path. Human review,
recording initiation, consent, account changes and destination execution remain
in the existing product interface.
