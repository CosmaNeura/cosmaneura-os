# CosmaBot virtual agent laboratory

This is a runnable local test environment for real agent tool use, collaboration,
workflow recovery, interface states and performance measurement. It uses invented
cases, an owned disposable PostgreSQL cluster, the actual CosmaBot application
services, and a separate store of evaluation artifacts. It does not deploy or
modify the installed Mac/iPhone application.

## Start a run

From the repository root, use Python 3.13 with this project's dependencies and
PostgreSQL 16 tools. On the current development Mac the working Python is
`/Users/jw/Desktop/Cosmas/d3-compact-proof-worktree/.venv/bin/python`.

```sh
# Fast deterministic baseline; no model calls.
python -m lab.runner --mode replay --cases all --fault lost_save_reply --serve

# Real five-agent team, all nine cases, bounded model budget.
python -m lab.runner --mode azure --cases all --concurrency 3 \
  --fault lost_save_reply --max-tokens 500000 --checks --serve
```

The launcher prints a new output directory and a dashboard URL on
`http://127.0.0.1:5190`. `--output` can select a new empty directory outside the
repository. `--postgres-bin` selects a PostgreSQL installation. The database
listens only on loopback, uses a random password, and stops when the run ends.
The finished database files remain in the run directory for inspection; the
temporary password file is removed. `cleanup.json` records shutdown.

Azure mode uses the existing Azure CLI login with the fixed CosmaBot endpoint
`https://cosmascode.services.ai.azure.com/openai/v1/chat/completions` and deployment
`gpt-4.1`. It sends only generated case data. Credentials stay in memory and are
never included in artifacts. There is no arbitrary endpoint, shell, browser,
email or vendor tool in the agent tool set. Defaults and CLI limits bound calls,
tokens, elapsed time, agent turns, tool count and concurrent workers.

The tool-enabled runner is an experiment alongside the product. The deployed
GPT-4.1 chat adapter still rejects tool calls; this lab does not silently replace
that contract. The next production integration must explicitly admit the same
tool envelope, identity, provenance and recovery behavior before activation.

## What the agents actually do

Chief reads the selected synthetic source and delegates to Visit Prep, Scribe and
Research. Those coworkers execute typed tools, read the saved application source,
and persist individual drafts. Their artifact IDs, hashes, citations and allowed
recipients are recorded. Follow-up reads all three exact saved artifacts plus the
original source before saving its combined draft. Chief reads that result and
the current application status. A generated “done” response cannot pass without
the required saved artifacts.

These are actual model decisions in Azure mode. Replay mode follows a fixed
script through the same tools and is explicitly labeled as deterministic. The
agent identities are installed through CosmaBot's provider-team service; current
identity and team configuration are rechecked before model calls and every tool.
The experiment gives these five agents access only to their selected synthetic
case and explicitly shared evaluation artifacts.

For the follow-up case, a **separate scripted synthetic provider** imports the
Scribe draft into the real note service, reviews exact content and source hashes,
proposes the Follow-up text, and approves the immutable F-8 revision. The harness
closes its database session after saving approval intent, then recovers delivery
in a new session. Duplicate proposal, approval and completion requests must yield
one operation, one decision and two receipts. An agent approval attempt must fail.
The final receipt is local synthetic delivery plus a simulated human completion
attestation, never evidence of a real patient message.

Other cases currently produce grounded, shared agent drafts. `--checks` also runs
the existing application contract suites for their actual service paths. This is
a separate evidence level: it uses existing deterministic fake provider ports,
not model-chosen vendor operations. The coverage table keeps that distinction
visible instead of claiming every integration is operational.

| Case | Agent task | Application regression suite |
| --- | --- | --- |
| `visit` | Source-backed agenda and missing medication context | Workspace prep and scope checks |
| `documentation` | Typed notes, planned versus completed actions | Capture-note contract; no live recording |
| `research` | Conflicting invented evidence | Research query/analysis contracts |
| `inbox` | Urgent clinical message escalation | Inbox ingestion, triage, stale/duplicate sources |
| `scheduling` | Unavailable slot and unconfirmed alternative | Appointment execution, lost response, revocation |
| `intake` | Missing consent and pending identity | Capture admission and consent boundary |
| `follow_up` | Administrative confirmation invitation | Generated draft through real F-8 recovery loop |
| `membership` | Failed-payment discrepancy without inferring cancellation | Membership review, privacy and evidence |
| `operations` | Unowned overdue work | Durable handoffs and routines |

Full Scribe recording remains deferred. Live Microsoft/Gmail, fax, payment,
Scheduling, portal, Core and Scribe endpoints are not used by this lab. Unsupported
operations remain coverage gaps; they are not replaced with optimistic receipts.

## Diagnose and improve

Each run saves:

- `report.html` / `report.json`: outcomes, coverage, timings, token usage and source provenance.
- `events.jsonl`: per-agent model, tool, sharing, failure and synthetic-provider events.
- `artifacts.sqlite3`: saved evaluation drafts and exact dependency hashes.
- `application-checks/`: commands, logs and source hashes when `--checks` is selected.
- `cleanup.json`: temporary database shutdown evidence.

Use `--fault read_timeout` or `--fault lost_save_reply` to test recovery. Lost-save
recovery requires the agent to observe a successful exact retry or read its saved
receipt; merely saying “saved” is insufficient. Tool failures identify the next
valid operation. Unknown tools, unread citations, changed hashes, missing
dependencies, wrong recipients and revoked agents are rejected.

To compare concurrency, run the same cases, source, model, fault and repeat count
with `--concurrency 1` and `--concurrency 3`, then:

```sh
python -m lab.compare /path/to/sequential-run /path/to/parallel-run
```

The comparator refuses failed or mismatched runs. It reports median elapsed time,
sample count and total tokens. A small synthetic speedup is not a production
performance claim. Improvements already incorporated into the lab include
parallel independent work, cached short-lived model authentication, HTTP
connection reuse, direct source metadata, precise error recovery, and ending an
agent turn on its saved receipt without an extra model paraphrase.

Outcome text checks are narrow regression heuristics, not clinical quality
certification. `python -m lab.evaluate /path/to/run` can rescore saved outputs with
a newer evaluator without spending model tokens again. It preserves the original
report and cannot repair missing artifacts, agent failures or failed service
checks. Review the actual draft and trace when a text check fails.

## Interface and accessibility tests

The UX lab mounts the production `SettingsHub` with local fixture adapters. It
includes connected, pending, new, partially failed, offline and slow states. It
does not sign in to accounts or simulate detail-editor functionality.

```sh
cd lab/browser
pnpm install --frozen-lockfile --ignore-scripts
pnpm exec playwright install chromium
pnpm test
```

Playwright starts or reuses the local fixture server on port 5187. The suite tests
1280px desktop and 390px phone viewports, keyboard navigation, status labels,
target sizes, overflow and axe WCAG A/AA rules. It retains failure traces and saves
screenshots. This is browser viewport coverage, not physical iPhone or native
sign-in acceptance. Request interception denies non-loopback URLs.

The connection directory now uses compact rows and actual account-status reads.
It distinguishes connected, pending, sign-in needed, admin setup and failed
checks. Administrative details are disclosed when needed. Existing editors and
unsaved-draft recovery remain intact. The lab provides a repeatable place to add
the rest of the provider journeys as they are wired to synthetic fixtures.

## Tool choices

Implemented now: the existing Python/httpx/SQLAlchemy application stack,
PostgreSQL, a bounded Azure tool loop, SQLite evaluation artifacts,
[Playwright](https://playwright.dev/docs/trace-viewer), and
[axe](https://playwright.dev/docs/accessibility-testing).

The research also evaluated Microsoft Agent Framework/DevUI, Inspect AI,
OpenTelemetry/Phoenix, Storybook, LangGraph, OpenAI Agents SDK, k6 and Toxiproxy.
They are options for a next increment, not installed integrations. A framework
migration is deferred until this measured tool contract can be adopted without
bypassing the application's existing admission and F-8 approval records.
