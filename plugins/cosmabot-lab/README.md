# CosmaBot Lab MCP package

This checked-in package is an **unconfigured scaffold**: `.mcp.json` intentionally
has no servers. Generate a local copy to connect an MCP client. Generating files
does not install the package, change a personal marketplace or activate it.

The default is one new, isolated `walk_in` / `chief` / `replay` episode, using
invented data and deterministic internal coworker replies. No provider login,
credential acquisition, network installation or external delivery is performed.

## Configure a local copy

Use Python 3.13 with this repository's dependencies and optional `mcp` extra
already installed. The tested SDK pin is `mcp==2.2.0`. Dependency installation is a
separate, deliberate setup step; neither the doctor nor the launcher runs pip.

For a new project environment, run this setup once from the repository root using
an already installed `uv`. It installs the exact locked dependencies into `.venv`:

```sh
uv sync --frozen --python 3.13 --extra dev --extra mcp
```

From the repository root, with your environment's Python:

```sh
/path/to/venv/bin/python -m lab.mcp_doctor \
  --postgres-bin /absolute/postgresql/bin \
  --output-parent /absolute/existing/lab-output

/path/to/venv/bin/python -m lab.mcp_config \
  --postgres-bin /absolute/postgresql/bin \
  --output-parent /absolute/existing/lab-output \
  --package-output /absolute/existing/packages/cosmabot-lab
```

The package destination must be new; its parent must exist. Output storage must
be outside the repository. Omit `--output-parent` to use the system temporary
directory. The doctor checks imports, Python 3.13, SDK availability, matching
PostgreSQL binaries and writable temporary storage without starting a database.
It refuses a checkout containing `.env` or a `.env` symlink before project imports;
use a clean checkout rather than moving or exposing an existing configuration.
It reports fixed checks and local paths, never environment values or credentials.

Use `--python /absolute/venv/bin/python` to select another prepared interpreter.
The generator preserves its venv executable path, resolves the repository and
PostgreSQL paths, and writes command arguments as JSON without a shell. If
`--postgres-bin` is omitted, it discovers the directory using `pg_config --bindir`.
Use `--repo /absolute/repository` when configuring from another directory.

For a client configuration file instead of a package copy, replace
`--package-output` with `--config-output /absolute/new/project-mcp.json`. That file
references the source package's launcher; keep the source checkout available.
Both outputs contain machine-specific absolute paths. Regenerate after moving
this checkout, environment or package; do not treat the generated file as portable
between computers unchanged. Existing configuration files are never overwritten.

The generated package remains linked to the specified source checkout; it is not
a standalone redistribution of CosmaBot. Its `.mcp.json` is ready for a local MCP
client that supports stdio `command` / `args`. Follow that client's deliberate
project-plugin loading flow. This package does not create a global configuration
or a marketplace entry and is not automatically activated.

## Episode and tool boundaries

The generated launcher accepts `--case`, `--role` and `--fault` only as startup
choices, with `--mode replay`. Each launch omits the server's `--output` argument,
so the server creates a fresh temporary episode under the validated output
parent. A persistent client config never points to an old episode. Exiting the
client should close its owned worker/database; keep its cleanup evidence when
qualifying a client integration.

Chief can call `delegate_team` to run bounded internal coworkers within **that
same episode**. Starting several external MCP servers instead creates separate
episodes; it does not create shared role identity, shared artifacts or cross-server
authority. The selected role is fixed at startup. Tool callers cannot impersonate
another role or invoke human approval, account login, external sending or clinical
decision tools.

The server reuses the seven existing World schemas, filtered by its startup role:

| Tool | Purpose |
| --- | --- |
| `list_sources` | Discover the permitted saved synthetic sources. |
| `read_source` | Read a listed original source before citing it. |
| `list_artifacts` | List explicitly shared drafts and their exact hashes. |
| `read_artifact` | Read one shared draft by its ID and hash. |
| `save_artifact` | Save a source-cited immutable private draft. |
| `delegate_team` | Chief delegates bounded internal coworker work. |
| `application_status` | Inspect the saved application workflow state. |

The resources `cosmabot://lab/status`, `cosmabot://lab/case` and
`cosmabot://lab/capabilities` describe the episode and capability metadata. The
last resource describes existing HTTP operations; it does not make live provider
operations callable through this lab.

The optional startup faults are `read_timeout` and `lost_save_reply`, in addition
to `none`. They exercise exact recovery; they do not authorize new keys or silent
replacement of an uncertain save. Successful tool calls return the same World
JSON in text and `structuredContent.result`. A saved draft is not approved care,
a sent message, a booked appointment or a production connector certification.

The server's separate direct CLI may support explicitly authorized Azure model
runs. This package intentionally generates replay-only configurations and does
not inherit Azure credentials. No network provider is needed for its default.

## Validation

The source package and generated copy are checked with the plugin-creator skill's
`scripts/validate_plugin.py`. The repository's `lab.mcp_check` wire checker exercises
the actual stdio server separately; schema validation alone does not prove a
working server or clean process shutdown. See the local acceptance evidence for
which startup modes and faults were actually run.

To run all three replay episodes (`none`, `read_timeout`, `lost_save_reply`) with
the prepared interpreter, use a new report directory outside the repository:

```sh
/path/to/venv/bin/python -m lab.mcp_check \
  --postgres-bin /absolute/postgresql/bin \
  --output /absolute/existing/lab-output/new-wire-check \
  --fault all
```

This check starts owned local PostgreSQL instances, calls the seven tools through
the official SDK, checks exact fault recovery and verifies worker/database cleanup.
It uses no provider login or public search.

## Connector tools in the virtual clinic

Add `--connector-tools` when generating a configuration with `lab.mcp_config`
(or starting `lab.mcp_server`) to offer the extra offline tools. This is an
explicit local test profile. It does not install tools in the Mac/iPhone engine
or activate a real account.

Chief, Visit Prep and Follow-up can check Google/Microsoft account health, read
bounded email headers/calendar summaries, and explicitly save selected items as
workspace evidence. Chief and Follow-up can read fax readiness, discover saved
proposals, prepare an exact private proposal, and inspect its receipt. Research
can run the fixture's pre-reviewed cardiac-trial lookup, recover its saved result
and save selected source hashes. Scribe retains saved-source/draft tools.

Each MCP process owns one separate episode. Fax sources are reviewed by the
synthetic provider during startup. New evidence invalidates that source review;
no agent tool can renew it. For a combined encounter use:

```sh
python -m lab.runner --cases connector_tools --repeat 2 --mode replay \
  --postgres-bin /path/to/postgresql/bin --output /new/output/directory
```

That scenario runs upstream observations first, then a separate scripted
provider source review, Follow-up's private fax proposal, and Chief's receipt
verification. `--mode azure` uses the already-configured optional model and its
bounded budget; replay is deterministic and does not call a model. Both use
actual application records and offline provider responses. Neither approves or
sends the fax. The existing first-party HTTP catalog remains discovery only.

The connector profile also offers short saved-source references and role-based
shared-draft reads. Saving a compact draft still binds the exact source IDs and
previously read dependency hashes. Compact fax preparation uses only a readiness
snapshot that the same agent already read; compact receipt inspection uses only
a proposal that the same agent already listed. No implicit review or send is
performed. These paths reduce copying mistakes without removing source checks.

The opt-in connector profile also exposes Google metadata intake and Scheduling
availability/private proposal inspection. The Google flow saves selected headers
and a metadata-review draft; full-message clinical triage remains unavailable.
Scheduling checks the active caller through a reviewed synthetic Follow-up grant
and retains exact observed slots and proposal bindings. Separate scripted human
review/acceptance or appointment execution is never registered as an MCP tool.
Use `lab.runner --cases administrative_tools` for the phased combined workflow;
a standalone MCP session cannot perform those human steps.
