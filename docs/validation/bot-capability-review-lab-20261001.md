# Bot capability teams and reviewer loops

This local synthetic lab exercises actual application services and durable
handoffs. It adds seven Research scenarios, seven Scribe/Visit Prep scenarios,
eight operations scenarios, and a Chief-led packet review with three reviewer
personas. No production account, live registry, recording device or patient
action is used. The personas model nontechnical clinician preferences; they
are not validated psychometric profiles.

## Product changes

Native Chief organizes saved encounter sources and reads current next steps
from already-linked work, before model or connector setup. Owner/encounter
scope is checked again; reads are bounded to twelve linked records. Unavailable
links stay visible without cached private details. Frozen model envelopes are
unchanged. This native overview does not dispatch handoffs.

Native Scribe preserves supplied transcript, prep and notebook evidence rather
than requiring a notebook. Excerpts and omitted passages are explicit. Newly
saved transcript packets retain original segment versions and reviewed
translation lineage. A source lookup does not generate or approve a note.

Research retains trial conditions under the existing retained-text budget and
rejects malformed conditions. Registry recruitment, site status, study phase,
eligibility criteria and uncertainty remain distinct. Conditions do not
establish patient eligibility or treatment benefit.

## Repeatable workflow

Run from the repository root with its existing Python environment:

```sh
python -m lab.runner --mode replay --cases bot_research,bot_documentation,bot_operations,review_loops --repeat 2 --concurrency 3 --postgres-bin /opt/homebrew/opt/postgresql@16/bin --output /private/tmp/cosmabot-capabilities
python -m lab.runner --mode azure --cases review_loops --repeat 2 --concurrency 3 --max-calls 80 --max-tokens 400000 --max-seconds 900 --postgres-bin /opt/homebrew/opt/postgresql@16/bin --output /private/tmp/cosmabot-review-model
```

Replay executes services, database constraints and offline provider responses;
it makes no model decisions. Azure mode uses the existing configured model for
Chief, recipient drafts and reviewer decisions. Only invented clinical sources
enter that transport. Calls, tokens, retries and submissions are recorded.

The review case saves invented intake, prep and typed Scribe outputs, performs
an offline Research lookup, and carries the full selected evidence plus its
save/context receipt into the handoffs. Chief creates three real durable
assignments. Recipients claim, generate and publish their own private drafts.
The provider, nurse and PA reviewers inspect exact material hashes. Initial
facts-only drafts deliberately omit responsibility and completion detail.
Reviewers request edits; Chief reads their feedback and returns concise
instructions. The application attaches the exact saved feedback to new
assignments, without asking the model to repeat it. Only rejected materials
are reassigned; accepted materials retain their exact review. Recipients
publish distinct revisions and reviewers review again. Revised submissions
require structured owner, next-action and done-when fields, rendered into the
saved material so they cannot silently disappear.

The runner accepts a sign-off only when the material includes explicit owner,
next-action and done-when fields. This guards against a model rubber-stamping
implied responsibility. It does not prove clinical correctness. A reviewer can
still request further edits; three rounds is the limit, and unfinished work
fails visibly. Unknown facts may remain unavailable with an assigned next step.

Every material node includes its real application entry, agent, admission and
content hash. Chief nodes include actual publication status and saved handoff
briefs; generated plan text is separately identified because the product saves
queue status as its Chief reply. Exact duplicate reviews are idempotent;
wrong scope, role, version and unchanged revisions are rejected. Graph state
survives reopening. The graph is evaluation evidence, not another product
approval queue. Only simulated review of the latest private packet is marked
complete. Clinical approval, referral, sending, booking and charging remain
outside reviewer-agent authority.

## Evidence and limits

The dashboard shows dependencies, revisions after feedback, exact materials,
reviewer comments and saved receipts. Shared lesson files link declared
scenarios to actual results, retaining failed and unrun work. Earlier failed
calibration results are preserved separately from final qualification.

The operations matrix tests inbox triage, follow-up review/source changes,
scheduling receipt recovery/expiry, membership review/source changes, and
lost-payment-response suppression. Local completion and external receipt
meaning are kept separate. Documentation scenarios include optional DOB,
recording-consent contracts, translation lineage and stale source/review
rejection. They use typed inputs; real microphone, telehealth and iPhone
recording quality is unmeasured. Synthetic latency is not production latency.

Applicable validation includes Research transport/analysis, native Chief and
Scribe contracts, reviewer refusal/replay/restart, migrated application
handoffs and source custody. Exact commit and final results belong in the PR
and the local evidence directory; model tests are not substitutes for these
application checks.
