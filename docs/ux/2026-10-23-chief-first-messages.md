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
run. No Messages build has been released to the phone.

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

The physical iPhone is currently unavailable and the Mac is locked. Native UI
acceptance remains pending, the rollout flag stays off in ordinary builds, and
no Messages build has been installed on the phone. The synthetic rehearsal flag
only enables the candidate for local validation.
