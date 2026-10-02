# Standalone CosmaBot and its platform connections

The owner reaffirmed this boundary on September 25, 2026: CosmaBot is a separate
app and experience. It connects through APIs to the main Cosmaneura platform's
features, including SOAP notes. Scribe is a main connector for CosmaBot users.

| Component | Owns | Connection |
| --- | --- | --- |
| CosmaBot / CosmasOS | Desktop/mobile workspace, chat, configurable coworkers, private context, research and operational work tracking | Its own UI and API, in `cosmaneura-os` |
| Main Cosmaneura platform | Clinical features and their authoritative records, including SOAP notes | Authenticated, versioned platform APIs |
| Scribe | Capture/transcription and documentation capabilities exposed to the connected workflow | Existing Scribe integration, with platform authority where required |

CosmaBot may retain private drafts and exact source/version references for its
workspace. Those are not an independent authoritative clinical record. Editing
or saving a platform note uses the existing platform API and its permissions;
CosmaBot does not connect directly to the platform database or import its server
implementation. Users retain the required clinical review and signing authority.

The repository includes reused capture client components under `clients/capture`
and documented native helpers. Their presence does not turn this into the Scribe
server application. Existing provenance files identify that reuse. The HTTP
adapters under `src/cosmas_os/adapters` are the CosmaBot side of the integrations.

Initial release includes both desktop and mobile. Their presentation can differ,
but they use the same workspace, identity and API contracts. Connections are
configured explicitly; platform access is checked for the current user and
encounter. Athena access remains read-only.

This source integration preserves the prior Scribe connector snapshot. It adds
no new Scribe implementation, device work, service activation or release. Ongoing
Scribe work remains separate. Staging deployment is managed by the owner.

## Accepted owner decision — September 25, 2026

The following is the agreed product direction, not a claim that the complete
experience is implemented or deployed. Scribe implementation remains paused in
this task while the separate Scribe work proceeds.

Selecting the Scribe avatar opens the complete Scribe workspace inside CosmaBot.
The embedded workspace and standalone Scribe share versioned recording and
review components, with native adapters for their device capabilities. They
retain the selected encounter context. Opening the workspace does not begin a
recording: consent and the action to start recording remain explicit.

The experience preserves durable recording, upload, processing, review and save
states so users can see progress and recover saved work. SOAP notes remain
editable for human review. Saving to the Cosmaneura platform is an explicit
action through its authenticated APIs and current permissions; CosmaBot does
not automatically sign a note.

The iPhone presents a focused Scribe workflow. The Mac supports Scribe and the
CosmaBot workspace side by side. Saved encounter work may reopen on another
authorized device, but an active recording cannot transfer between the phone
and Mac. Saved context may be shared with other bots within the user's existing
workspace and access permissions.

CosmaBot retains its separate app and hosting. The main Cosmaneura platform
remains authoritative for clinical records, reached through authenticated APIs.
This decision adds no direct platform database access, independent clinical
record authority or automatic clinical signing.

## Visit Prep patient package integration

The October 2 Visit Prep branch adds a distinct patient-package reader to the
existing Visit Prep coworker. Core owns the package and protected interpretation;
CosmaBot renders current patient/caregiver words, corrections, unanswered topics
and cited synthesis without saving that content in chat. No chart or encounter
grant is invented. Session Prep and its selected-brief chat path are unchanged.

The receiver is implemented in
[Core draft PR 627](https://github.com/CosmaNeura/cosmaneura/pull/627). Architecture
v3.6 and ADR 0028 are ratified at
`6b879150205f275612d1a3fd2318530dfa331857`. This branch selectively reuses current
provider correspondence, bot source restrictions, bounded credential/HTTP
transport, request ownership and native desktop dispatch. It does not import
Core server source or connect to Core's database.

The view now has an explicit Core preparation picker. It lists the invitation
first name and role, appointment timezone, lifecycle and chart-link status,
with pagination. No email, phone or patient response is in the list. Core
reuses its dashboard owner-list domain; selecting a row confers no authority,
and opening rechecks the connection and current package access. The additive
list wire contract is recorded in the Core feature branch and still requires
canonical architecture reconciliation before release. The panel is available
before selecting an encounter and within the Visit Prep coworker.
Content clears on scope changes, focus loss and offline/denied reads. The
transport verifies closed receipts, current citations and echoed scope.

Both sides remain default-off. CosmaBot requires
`WORKSPACE_VISIT_PREP_ENABLED`, its explicitly configured companion managed
identity/scope and the existing reviewed Core connection; the renderer requires
`VITE_WORKSPACE_VISIT_PREP_ENABLED`. Core separately requires its Visit Prep
permission. No configuration file activates these flags. Local synthetic
qualification is not live web/Mac/iPhone acceptance. No release, deployment,
messages, model analysis or broader agent action is authorized by this reader.

Recovery is flag-off and revert of the additive increment. Remaining work
includes live cross-service and complete native acceptance, independently
governed AI context/actions, patient clarification integration and qualified
delivery. The source branch remains a draft until those release gates are met.

A localhost-only provider preview uses the real panel and invented wire replies:
`node node_modules/vite/bin/vite.js --config vite.visit-prep-lab.config.ts`
from `web/`, at `http://127.0.0.1:5197/`. Its separate aliases replace only the
remote ports; normal builds and release flags are unchanged. The preview is
not connected patient-to-provider or native/service acceptance.
