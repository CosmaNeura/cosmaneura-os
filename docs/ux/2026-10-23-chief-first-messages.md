# Chief-first Messages implementation

Owner approval: October 23, 2026; decision `DL-20261023-01`.
Baseline: merged PR #203, `b1a76cc` (source tree identical to `7134cf1`).

## Accepted experience

Messages is the phone default after setup, with Chief as the first conversation
when available. Owner-disabled bots stay disabled. Other bots are opened through
existing chats or New message, using their actual supported workflows. Scribe's
recording and Research's deliberate source selection remain available.

The conversation header identifies its bot and visit/private-note context.
Changing context opens the corresponding history and preserves the prior draft.
Existing delegation results appear as attributed review cards. Activity reveals
coordination details when requested; it does not become the default transcript.

Keep one persistent bottom navigation and hide unavailable destinations. Review
cards open the relevant complete workflow directly. Secondary tasks are grouped
around Review, Notes and sources, and Activity; avoid a large miscellaneous menu.

## Shared behavior and delivery

The session is plain TypeScript. React subscribes through a separate adapter.
One shared owner retains identity, loaded data, exact pending requests, recovery,
approvals and recording lifetime. Both layouts render and invoke that owner.
Host adapters retain browser navigation, focus, visibility and native surfaces.

Extraction proceeds in small commits: lifecycle/request state; loading/routes;
draft journal/recovery; saves; model requests; handoffs/review; recording; team
settings; shell/presentation separation. Existing screen tests and browser
journeys retain their assertions during extraction. Each moved behavior gains
session-level failure/recovery coverage. Existing route, operation, authority,
generation and draft-edit guards are preserved.

The shared entry projection supplies both layouts. Inbox summaries identify a
bot conversation within its workspace, including actual reply activity,
attention and human read state. Workspace revisions alone are not an activity
clock. Manual Mark unread is separate from the monotonic seen watermark.
Summary access and previews preserve existing ownership, patient-link and
selected-source revocation protections. Unknown attention cannot become idle in
the production-default inbox.

The recorder stays above both presentations. Layout switching within a context
is distinct from navigating to another visit. Pending unconfirmed writes and
recording start/stop transitions keep their existing protections. Layout
preference is per device; the rollout flag gates availability and defaults as
well as the switch until parity is verified.

Parity checks compare resulting saves, retry bodies/keys, approval revision/hash
bindings, retained drafts and recording identity, in addition to rendered
entries and reachable actions. Camera attachments, live dictation, push and
continuous cross-visit bot history are later work.

## UI/UX QC

The owner requested a dedicated independent QC reviewer. The `ui_ux_qc` agent
reviews visible milestones and reports pass, needs adjustment or release blocker
with a specific screen, reproduction and smallest correction.

- Default chat has one header, context control, conversation and composer.
- Keep at most two useful empty-state starters; starters insert editable text.
- Back and sheet dismissal return to the originating chat, draft and scroll.
- Review cards clearly name the proposing bot, context, current state and next
  action. Confirmed completion is required before complete/sent/saved wording.
- Recovery stays next to the affected request; check status and retry retain
  their distinct meanings. Disabled actions explain the required next step.
- Check narrow phones, long names, keyboard open/closed, enlarged text,
  VoiceOver, reduced motion, 44px targets and focus restoration.
- New replies preserve the reader's position when reading older content.
- Layout parity must not turn Details into a second application inside a sheet.

Concrete QC stop criteria:

- A second permanent mode strip, bot-filter row or duplicated navigation system
  stops the milestone for redesign.
- Details starts with Review, Notes and sources, and Activity. Additional
  top-level groups require QC review. Opening a task must not stack sheets.
- A review card reaches its complete review screen in one tap. Every sheet has
  a visible way back and restores its originating chat.
- Outstanding human decisions remain discoverable without opening Activity.
  Unread and needs review remain distinct.
- Clipped Send, Back or review controls, lost drafts, changed context,
  interrupted recording, or unconfirmed work labelled complete are release
  blockers, including with the keyboard open and enlarged text.
- Each visible milestone supplies narrow-phone screenshots and completed
  workflow evidence. Component tests alone do not establish visual acceptance.

## Current implementation

The plain TypeScript session owns lifecycle, durable saves and model requests,
loading, team settings, clinical preparation, recording descriptors, navigation,
review return routing, selected-source verification and recovery access. The
shell keeps child workflow instances above presentation changes.

The shared conversation projection now renders the existing Workspace history
and attributed review cards. Chief receives specialist results as cards without
adding their internal brief/reply transcript. Exact attempt/result/hash matching
controls review labels. Composer preparation and note-save continuations use the
same shared actions.

The additive server inbox identifies one bot within a visit or private note.
Only human-opened chats and existing direct conversations enter the inbox;
delegations do not automatically add specialist chats. Replies use their actual
arrival time, independently of workspace revisions. Read watermarks are monotonic
and manual unread has a separate versioned flag. Bounded pages use batch reads and
retain current owner/patient-reference checks. Previews for workspaces with
selected connector sources are deliberately withheld until the conversation's
full source checks run. Unconfirmed model states remain needs-check.

Messages now supplies a Chief-first inbox, explicit chat/context picker, device
layout preference, per-bot/context drafts, attributed review cards and three
Details groups. Workspace and Messages use the same composer, notebook,
request/recovery controllers and fixed recording/workflow hosts. Opening Scribe,
Visit Prep or Research retains unread status until its reply history is displayed.
Unavailable bots retain their attention status. Research requests, recording
transitions and unconfirmed recording metadata block layout changes without
changing their existing consent, recovery or exact retry behavior.

The rollout remains gated while the final frozen-build visual and native checks
run. Ordinary builds still keep Messages disabled; the separate invented-data
phone preview is documented below.

## Validation

- Session and screen extraction checks retain existing assertions. The latest
  focused screen/session run passed 343 tests; seven focused composer/projection
  cases also passed. TypeScript and Vite production builds passed.
- Independent browser QC passed Workspace 21/21 on the unchanged baseline and
  extracted candidate; 27 Axe scans reported zero violations. Connections passed
  12/12 after preserving the existing checks and correcting current UI selectors
  plus a real stretched-row layout issue.
- Ten real PostgreSQL inbox integration tests passed, covering owner/human access,
  revoked visits and selected sources, private notes, bounded paging, delegation,
  unknown model outcomes, exact per-bot watermarks, stale read/manual-unread races,
  arrival clocks, no-store responses and database monotonicity.
- Physical VoiceOver, first-install cold start and final Messages keyboard/layout
  acceptance still require their dedicated checks. Earlier browser evidence does
  not establish Messages or native acceptance.

### October 23 implementation verification

- Real-shell parity: nine tests pass across both layouts, covering notebook
  writes, Chief messages, exact retry after a lost response, approval
  attempt/result/hash/revision binding, change requests and linked revisions,
  retained composer/editor instances and directions on review return.
- Shared conversation tests: nine pass, including bot/context drafts, late
  results, interrupted requests, device preferences, deferred read markers,
  Research locks and recording transition locks.
- Full web run exercised 4,369 executable tests plus 103 skips. Seven failures
  from in-progress recorder edits and an over-broad visit-link navigation lock
  were corrected; the final affected five-file rerun passes all 178 tests.
  TypeScript, production build and the static Messages rehearsal build pass.
- Desktop conversation/transport contracts: 73 tests pass, including real
  disposable loopback sockets, deadlines, payload bounds and sign-out fencing.
- Fresh PostgreSQL: all 14 inbox tests pass. The combined migration/review run
  passed 134 tests, including every historical migration case; its one inbox
  setup failure under local contention passes in the subsequent isolated run.
  The earlier broader integration pass covered 272 successful cases; its new
  query-count fixture was corrected and now passes for 20 populated chats.
- Inbox review state now uses the existing source/team/review validators with
  batch-loaded typed inputs; no separate approximation grants review authority.
- Browser checks have verified exact draft acceptance/return and a visible Send
  control at a 390 × 420 viewport. The frozen rehearsal now also completes Research query/source review and
  selected-excerpt saving. Generated audio continues in the same recorder through
  Messages → Workspace → Messages and saves all 18 generated chunks. Development
  Fast Refresh is excluded from this recording continuity evidence. Physical
  keyboard, VoiceOver and first-install timing remain unverified.

### Final workflow corrections

- A New message context reopen could treat the temporary empty Chief composer as
  an edit and overwrite its retained draft. Preparation now belongs to the
  workspace generation. Two tests use the real loader and reproduce both timing
  cases; the browser now retains separate Chief and Follow-up drafts in both
  directions. Automated encrypted-store tests establish reload persistence; a
  guarded browser reload alone is not evidence that a new document loaded.
- During chat restoration, Send, Enter, form submission and the shared model
  controller reject submission until the destination draft is ready. A delayed
  restoration test proves the previous bot’s text cannot be dispatched.
- Long context labels and 200% text no longer consume the chat viewport or push
  New message beyond the right edge. The full context remains available in
  Details. Short-screen layout follows the measured visual viewport, and its
  composer remains reachable above the bottom navigation.
- Messages sheets have a persistent close control. Opening a Details task focuses
  its heading and returning restores the previous conversation scroll position.
- Research's explicit context picker shows visits only. Team activity and account
  connector controls stay in their relevant Details destinations.
- GitHub's full web, Python lint/type, infrastructure and all three signed UI
  jobs passed on 7cc047a. The backend stopped after 2,457 passes because the
  current-head downgrade test expected the prior migration's refusal message.
  The assertion now checks the new migration's retained-read-history refusal;
  27 fresh PostgreSQL workspace/inbox tests pass, including that full migration
  and data-preservation case. Runtime downgrade protections are unchanged.

- A final standard-size preview caught a legacy 350px history cap. Messages now
  has one scrolling history container; the inner transcript grows naturally.
  The real browser preserves a 437.5px reading position across both layouts and
  keeps older content in place as a new reply arrives. The normal composer no
  longer inherits Workspace’s separate sticky safe-area offset.
- Final 6034815 checks: the full GitHub web job, all three signed UI jobs and
  the complete backend pass (7,485 workspace, 27 deployment-profile and 23 compact
  tests).
  Local full web passes 4,371 cases with 103 skips; all 65 cases from the three
  files affected by socket permissions/timeouts pass in an isolated rerun.
  The isolated unsigned simulator build compiles and is installed under its
  separate synthetic bundle. Browser QC, generated-audio checks and this build
  do not establish physical microphone or native accessibility acceptance.

The release-image scan then identified three fixable high-severity pypdf issues
in the pre-existing 6.19.0 pin. The optional inbound-PDF dependency is updated to
6.21.2 with official locked hashes; no other package version changes. All 180
existing PDF/parser/security cases pass in an isolated environment. The scanner’s
severity and failure policy remain unchanged.

The rollout flag stays off in ordinary builds. The synthetic rehearsal flag
only enables the candidate for local validation; current physical-device results
are recorded in the October 24 follow-up below.

### October 24 completion pass and deliberate simplifications

The inbox has local search over loaded conversations, Chief / Needs you / Recent
sections, activity dates and one visible conversation-actions menu. Pin and Hide
store only workspace/bot identifiers and flags in the existing encrypted,
account-scoped device journal. Hidden conversations have a visible restore path.
Rename opens the existing notebook title editor after a fresh revision read; it
does not invent an independent visit title. Search explicitly offers loading
older results when more pages exist.

Messages now uses quiet human/bot bubbles, 15-minute/day separators, delivery
labels, a one-to-five-line composer and two editable empty-thread suggestions.
Both layouts omit routine model badges and use Delivered for a confirmed saved
request; failure notices and source/revision provenance remain available. The
seven invented parity fixtures compare one actual mounted session across both
layouts, including entry identifiers, review states, delivery and enabled actions.

Read acknowledgment waits for the actual end of the displayed history to be
visible, with current ownership and source checks. New incoming replies preserve
older reading positions and expose one jump control. Explicit manual-unread
changes are protected against older automatic acknowledgments. The server's
watermark identifies arrival activity, not a transcript position: this release
uses unread dots and the observed-new-message jump instead of fabricating a
historical unread divider. A precise historical boundary would require an
additional authorized entry/attempt reference and a chronological arrival view;
a late reply to an old request cannot be marked accurately by workspace revision.

The Settings-only layout switch and the visible actions menu intentionally replace
the handoff's three switch locations and hidden swipe/long-press commands. The
persistent bottom tabs follow the owner's approved responsive-navigation choice.
Phone labels are brief (Chats, Visits, Work, Settings); accessible names retain Messages,
Visits and notes / Practice work. The compact header omits its redundant context
kind line, while Details retains the full context.

Native presentation support stays in the owned composition overlay. It uses
public UIKit feedback generators, a light status-bar appearance matching the
current light header, and the existing guarded route history for back gestures.
Feedback accepts only enumerated presentation hints from the current local main
frame and generation, while foreground and capture-idle checks suppress unwanted
vibration. It cannot carry messages, credentials or workflow commands. The
existing UIKit keyboardLayoutGuide remains the sole native keyboard resize owner;
the system accessory Done control is retained. No additional Keyboard/Haptics/
StatusBar package, private API or Scribe-source mutation is introduced. Physical
haptics, gesture, keyboard and VoiceOver acceptance remain required before the
ordinary-build rollout gate is removed.

The API image passes the unchanged high/critical vulnerability policy after the
pypdf update. The web image also required an existing Alpine Brotli dependency
pin update to 1.2.1-r0 (CVE-2026-111497); its rebuilt image passes the same scan and
nginx configuration check. No scan exception or policy weakening was added.

Browser acceptance also exercises consecutive Back actions, not just individual
popstate events: dismissing Details must preserve the inbox history entry so the
next Back reaches the inbox. Consumed traversal restores the existing route entry
instead of overwriting its parent, with equivalent protection for Forward and
pending requests.


### October 24 physical-device follow-up and restart recovery

GitHub run 40073093050, attempt 2, passed all nine required jobs on 8040b3f,
including the full backend, web, signed UI and unchanged image-security gate.
The subsequent run 40098235982 also passed all nine jobs on 44c1087. Both
6b03415 and 44c1087 are pushed to PR #204. The previously reported Actions
availability block is resolved.

The separate CosmaBot Preview, bundle `com.cosmasos.synthetic.w206`, is installed
on the owner's iPhone 12. Build 7 comes from 6b03415; the regular CosmaBot app
remains build 1102. The preview uses invented information and simulated services
and audio. It does not qualify real microphone capture or authenticated backend
acceptance. No backend deployment was performed.

The owner confirmed VoiceOver can read and activate Chief, Details, the message
field and Send in build 6. They reported no vibration in both builds 6 and 7;
retaining view-associated UIKit feedback generators has therefore not established
a fix. A real Send through iPhone Mirroring in build 7 reached both
`receivePresentation` and UIKit `impactOccurred`; the invented message was
visibly Delivered with a scripted reply. This establishes native command
delivery, not a felt vibration. The debugger was detached after the trace.

The owner reported that the direct Chief conversation header disappears when
the keyboard opens, while the private-note route retains it. Native Messages
chat now uses a fixed safe-area frame inside the existing UIKit-resized WebView,
matching the established native Workspace frame. The browser frame is unchanged;
UIKit's keyboardLayoutGuide remains the only native resize owner. The rehearsal
notice stays in the inbox and Settings and no longer shifts native chat geometry.
Fresh build 9 simulator replay confirms Chief, Back and Details remain below the
notch on first direct focus, including actual Text Size 9. Native geometry inspection traced a remaining lower gap after Done to a
keyboard layout guide retaining 68pt of dismissed accessory space. The root
container now returns to its full bottom anchor after UIKit confirms dismissal,
and synchronously lays out the keyboard guide before WebKit handles the next
opening. Simulator build 14 passes three open/settled-Done cycles. The navigation
measurement now observes its border box so safe-area padding changes also update
the reserved tab height. Native Settings scrolls its section into view while
focusing the heading, keeping the preceding Done navigation reachable. Build 14 also verifies Settings →
Your team → All settings retains Done and returns to Chief. Final acceptance
checks draft switching and enlarged text independently of component tests.

Messages-enabled builds now require the server's conversations contract before
rendering the workspace. A mounted compatibility test proves an older server is
blocked, then admitted after Retry returns the required contract. Ordinary
Workspace builds retain their previous compatibility requirements. An unauthenticated
staging 401 does not establish that the new inbox endpoint is deployed.

The first physical preview launch recorded a native first frame at 1.159 seconds.
This is not a completed WebView or authenticated workspace readiness measurement;
first-install readiness and full operational native capture remain unverified.

The Mac restarted at 08:25:59 EDT, clearing temporary working/build directories.
The permanent checkout passes Git object verification and all 33 saved evidence
files match their SHA-256 manifest. Four uncommitted frame/rehearsal files were
restored in the permanent checkout. All 62 affected parity, history, frame,
compatibility and native-helper tests pass, as do production and rehearsal
TypeScript checks and the rehearsal renderer build. Subsequent build recipes,
receipts and UI evidence are saved under the permanent October 24 resumed handoff.

The final affected layout, parity, history, Settings and shell run passes all 49
tests after the navigation measurement correction. Production and rehearsal
TypeScript checks and the new rehearsal renderer build pass. The separate native
scene/recovery suite passes all 11 cases. Existing React act and bundle-size
warnings remain; no failing check was suppressed.


### Follow-up from direct phone and cross-layout QC

Direct iPhone Mirroring testing found that old attributed draft cards were
appended after a newly delivered conversation turn. The shared projection now
orders turns and review cards by their existing saved workspace positions:
handoff result/context, note revision, and linked work or its source note. Both
layouts keep identical entries and actions. This is display ordering; it does not
replace inbox arrival clocks or grant read/review authority. New regression cases
cover older cards before a later turn and a genuinely later result after it.

Native Settings now keeps its brand/sidebar in normal flow, and its existing
focus/scroll effect also runs when the layout changes. This prevents the Workspace
brand or a change to Messages geometry from covering Done. Switching from Workspace
Tools through Settings to Messages retains the complete Tools task, including its
heading, controls and Back to chat. Returning preserves the same composer,
notebook and exact draft; request and recording guards are unchanged.

The final focused pass has 111 passing cases across seven suites, and both
TypeScript configurations pass. The complete web suite on 4203cc4 passes 4,466
tests with 103 existing skips (324 passing files, 17 skipped).

Preview 17, composed from 4203cc4, passes the final simulator workflow replay:
direct Chief keyboard focus and settled Done retain the header and full height;
Settings keeps Done reachable in both layouts; Workspace Tools → Settings →
Messages retains the complete task and returns to the exact draft. Actual iOS
Text Size 9 enlarges chat, composer and Details content, and the scrolled Details
sheet closes successfully. Header and navigation labels do not all scale, so
this establishes partial Dynamic Type response and control reachability, not
universal scaling. The new-reply jump shows the latest reply after older cards.
Text Size 3 and Capture Keyboard off were restored. The 22 screenshots and exact
observations are saved in the permanent October 24 resumed handoff under
`simulator-preview17-qc/evidence.json`. This scripted simulator pass does not
establish physical haptics, VoiceOver speech, edge-swipe, interactive keyboard
dismissal, real microphone capture or authenticated backend acceptance.

Preview 17 is also installed on the physical iPhone 12. Through iPhone Mirroring,
an invented send shows Delivered and its scripted Chief reply; Details opens and
closes, Settings retains Done through both layout choices, and Done returns to
the same conversation. Chief, Back and Details remain visible during hardware-
keyboard input, and settled dismissal restores the full frame. Mirroring does
not establish ordinary physical soft-keyboard or tactile acceptance. Read-only
checks found global Vibration and System Haptics enabled; the phone settings were
not changed. The physical evidence is retained under `phone-preview17-qc/`.

A final source audit found that an older review card changing state could create
an inaccurate “new message” indicator whose jump went to the end of the chat.
Only incoming turn replies now count toward that indicator. Creating a review
card or changing its status keeps its attributed card and review controls without
claiming a new chat message; inbox attention and exact read-marker synchronization
are unchanged. The mounted-shell regression covers both review changes and card
creation above the bottom; the existing incoming-reply case retains exact
watermark acknowledgment only after the jump. All 60 focused presentation, frame,
projection and read-marker cases pass, as do both TypeScript configurations. The
complete web suite after this correction passes 4,467 tests with 103 existing
skips (324 passing files, 17 skipped).


### October 24 phone-independent recovery review

The resumed review confirmed three recovery defects and their corrections:

- An opened chat discarded its exact read acknowledgment before the server
  confirmed it. The same watermark and marker version now survive a failed
  attempt; automatic watermarks wait for it, and simultaneous visibility events
  share one attempt. Current 401/403 responses from acknowledgment and Mark unread
  use the existing access-loss handler. Late responses remain generation-fenced.
- A selected saved-note task with empty optional directions could be erased
  before draft hydration. It now survives switching and reopening. A newer note
  selection wins over an older pending journal read; explicitly removing a
  hydrated selection still remains removed.
- At 390 × 420 with 200% text, an unconfirmed notebook save placed Retry same save
  below an overflow-hidden chat frame. Blocking recovery now uses document flow;
  settling the save restores the fixed chat frame. Other notices scroll before
  the transcript, preserving its end as the read-visibility anchor. Save/retry
  handlers, exact request bodies, disabled guards and workflow owners are shared.

Regression tests reproduced the lost acknowledgment, duplicate retry burst,
note-selection loss/race and swallowed access denials before correction. The
parity test now returns from Notebook to chat before retrying a lost save. An
existing connector recovery test waits for its field to finish restoring before
editing; its controller identity and exact-retry assertions remain intact.

The final full web run passes 4,479 tests with 103 existing skips (324 passing
files, 17 skipped). Both TypeScript configurations, the production build and the
frozen synthetic rehearsal build pass. The native scene/recovery Swift package
passes 15 tests. Existing React act and bundle-size warnings are retained.

The frozen browser replay uses 390 × 420, 200% text, long names and the native
layout fixture. Retry is fully visible and enabled; the exact invented note is
saved once as revision 6, and header, composer and Send return inside the frame.
This browser fixture does not exercise UIKit or the physical keyboard.

Earlier in this resumed chat, Preview 18's physical software-keyboard layout
showed Chief, Back, Details, composer and Send unobscured. Device Hub did not apply
the attempted typing/taps, so this does not establish a completed physical
typing/Done cycle. Felt haptics, physical gestures, real microphone capture and
authenticated backend acceptance remain open. Ordinary-build rollout stays off;
the preview remains invented-data-only and PR #204 remains a draft.
