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

## Current checkpoint

The first extraction moves shared pending-request/connection state and the
session lifetime cell out of `EncounterWorkspace`, and moves `PendingSave` into
the presentation-independent model. The legacy export remains compatible.
Screen markup and existing tests are unchanged. Feature action extraction,
inbox/server work and the Messages presentation are subsequent checkpoints.
