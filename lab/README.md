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

# Joined encounter, connector failure matrix, and actual recorder qualification.
python -m lab.runner --mode replay --cases clinic,connectors \
  --fault read_timeout --checks --capture-checks --serve

# Real agents use synthetic account tools and pass generated outputs to Chief.
python -m lab.runner --mode azure --cases clinic --repeat 3 \
  --fault lost_save_reply --max-tokens 500000 --serve

# All specialist cases, the Chief journey and the expanded clinic.
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
send, approval or booking tool in the agent tool set. The clinic adds two bounded
synthetic account-read tools for Visit Prep only. Defaults and CLI limits bound calls,
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

### Chief prepares actual private handoffs

`--cases journey` starts with three saved outputs for one invented encounter:
patient intake, a conflicting derived Session Prep summary, and unreviewed typed
Scribe notes. Chief reads them and creates exactly three structured assignments
for Visit Prep, Scribe and Follow-up. Each records its owner, next action, cited
inputs, prerequisites, completion criteria and required human review.

These assignments use the existing application's durable private-handoff service
and model-work admission, claim, source-fencing and publication paths. Each
recipient receives its admitted inputs upfront and acknowledges their exact hash,
then submits a draft bound to the exact assignment
hash, and saves an attributed application reply. Chief then reads the actual
saved results and cites all three result IDs in its verification. Fresh database
sessions and duplicate publication/request recovery exercise durability.

The three independent drafts run concurrently through separate application
claims and database sessions. Chief's planning finishes before they start, and
Chief's result verification waits for all three to settle. Only exact admissions
from the selected encounter are dispatched; this is not a second work queue.
`--concurrency 1` restores serial execution. `--journey-inputs tool` restores the
extra model round trip for fetching inputs; the default `inline` delivers the
already admitted input with the first model request and requires its exact hash
in the output. The trace distinguishes application input delivery from model tool
calls. Missing inline input must be recovered using the read tool.

Each model response records elapsed time. The report separates Chief planning,
recipient work and Chief verification, plus each recipient's persisted queue
wait and execution time. Draft-generation timeouts, connection failures and
HTTP 500/502/503/504 responses get at most one 250 ms retry; both requests consume
the shared budget, unknown calls retain their token reservation, and authority
is checked again before retrying. No returned tool executes before a response is
received. This does not retry any application or vendor delivery operation.
Other failures remain visible and are not retried here.

The lab supplies the model transport using Azure CLI authentication; a scoped
synthetic marker satisfies the application's key-based availability gate and is
never used for authentication or sent over the network. The normal deployment
adapter and configuration are unchanged. Replay uses the same service paths with
scripted content and is labeled accordingly.

```sh
python -m lab.runner --mode azure --cases journey --fault lost_save_reply --checks

# Compare the former serial/read-tool path with the optimized path on one source.
python -m lab.runner --mode azure --cases journey --repeat 3 --concurrency 1 \
  --journey-inputs tool --output /tmp/chief-before
python -m lab.runner --mode azure --cases journey --repeat 3 --concurrency 3 \
  --journey-inputs inline --output /tmp/chief-after
python -m lab.compare /tmp/chief-before /tmp/chief-after
```

This tests Chief's decomposition and recipient draft work. The three starting
outputs are fixtures, not outputs generated by live intake, Session Prep or
recording services. It does not approve a note, resolve consent, contact a patient
or execute clinical tasks. Private draft completion remains distinct from human
review and any later approved external action. Journey receipts are not changed
by the text-rescoring command.

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
| `journey` | Chief decomposes three encounter outputs, assigns drafts and verifies results | Actual durable private handoffs plus regression suite |

Full Scribe recording remains deferred. Live Microsoft/Gmail, fax, payment,
Scheduling, portal, Core and Scribe endpoints are not used by this lab. Unsupported
operations remain coverage gaps; they are not replaced with optimistic receipts.

## Expanded virtual clinic

`--cases clinic` keeps one application encounter throughout. Invented intake and
typed clinician notes seed it. Real agents in Azure mode read those inputs,
prepare individual drafts, share their exact saved outputs and combine a
follow-up draft. Visit Prep must also execute actual Microsoft mail/calendar
adapter reads against an offline provider twin. Only that role sees those tools;
calls by another role or for another account are rejected.

A scripted human-test actor imports the generated Visit Prep and Scribe outputs
as explicitly derived evidence. Chief then uses the real durable handoff service
to create three assignments, collect attributed recipient replies and verify
the saved results. The original inputs are retained. This is a joined workflow,
not a claim that Core Session Prep or speech recognition generated those outputs.

After successful handoffs, a separate scripted human actor records resolution
of the invented contact-consent/preference gap and edits the message to a minimal
administrative confirmation request. It then reviews the exact note and exercises
the existing F-8 follow-up loop. Arbitrary model prose is never treated as an
approved message. Finally, the actual vendor-work service binds a valid generated
PDF to the reviewed note, obtains the synthetic human's exact approval, dispatches
through the real Documo adapter, reads delivery status and records separate human
verification. A fresh database session reopens the same encounter. The PDF is a
fixed synthetic administrative test document, not a model-generated clinical packet.

`--cases connectors` runs 24 independent scenarios through the real adapters and
owned PostgreSQL. Microsoft, Gmail and Google Calendar each cover connection/read, timeout and
explicit recovery, throttling, token refresh, oversized responses and account
revocation during a read. Microsoft also rejects an invalid calendar timezone.
Documo covers complete delivery, failure, partial pages, lost submission response
and wrong-account status. Its five scenarios use real artifact custody, immutable
F-8 approval/dispatch and duplicate-request recovery. Unknown delivery remains
unresolved; it cannot cause an automatic resend or a successful closure.

All provider HTTP is handled by strictly allowlisted `httpx.MockTransport`
responders, so no provider network request is possible. These are not vendor-hosted
sandboxes. Calendar writes, incoming-fax ingestion, live OAuth UI,
physical audio and speech-to-text remain explicit gaps. There is no live-account
mode in this runner.

`--capture-checks` adds the existing generated-PCM, encrypted queue, continuous
capture, interrupted upload/restoration, desktop recorder and selected Swift
audio mixing/alignment tests. It saves commands' logs, test counts and source
hashes under `capture-checks/`, and displays their separate qualification tier
in the dashboard. It needs the pinned `clients/capture` dependencies, Node and
Xcode. Desktop tests temporarily reuse the capture dependency directory when
needed; that link is removed afterward. Swift outputs stay outside the checkout.
These checks do not use a microphone, require an attached phone, or prove native
OS permissions, meeting-app routing, speech accuracy, or real-time endurance.

`--capture-stress-checks` includes the normal recorder tier and adds full one-hour
generated PCM in both configured modes, twenty-minute offline recovery after
reopening encrypted storage, a lost upload receipt, and missing/duplicate chunks.
It also runs the native engine's three-hour generated PCM/encryption/lease tests,
with route, background and storage interruptions. Allow about 15 minutes.
The configured bridge remains bounded to one hour; the owned native engine is
tested separately to three hours. These use accelerated clocks, not three hours
of physical recording. Reports count executed tests separately from skipped tests,
and include both XCTest and Swift Testing results.

Every report distinguishes scripted replay, real model work, synthetic human
decisions, adapter requests and recorder qualification. Fault results, including
failed attempts, are retained rather than reclassified by text rescoring.

## Diagnose and improve

### Clinician usability agents

`clinician-personas.json` defines two invented, clinically confident but technically
inexperienced testers: a family physician and a family nurse practitioner. These
are explicit behavioral settings, not validated psychometric scores or claims
about either profession. Give each tester the saved protocol and its own fresh
browser tab. Let it act through visible controls, state expectations before
clicking, and stop for help after two plausible wrong choices. Do not coach the
agent using source code or count model deliberation as human dwell time.

Run `pnpm exec vite --config vite.clinician-lab.config.ts` from `web` to serve the
actual EncounterWorkspace at `http://127.0.0.1:5188/`. It supports an invented
encounter, a prepared brief, notebook saves, saved Scribe drafts, private note
review and Chief handoff inspection. Responses and existing drafts are scripted;
this is UI evidence, separate from the real-model/application runs above. The
fixture uses per-tab session storage, blocks service fetches, and does not simulate
recording, sign-in or delivery. Closing the tab clears its fixture state. Real
encrypted/native draft recovery and backend durability are not qualified here.

The existing `:5187` connection directory is a separate fixture. Its detail pages
are placeholders and cannot prove account setup or sign-in success. Record such
gaps separately from product defects. Run the fixture smoke checks with
`LAB_CLINICIAN_URL=http://127.0.0.1:5188 pnpm exec playwright test clinician.spec.ts`
from `lab/browser`; this checks actual save/review controls and tab isolation,
not clinician adoption or clinical correctness.

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
