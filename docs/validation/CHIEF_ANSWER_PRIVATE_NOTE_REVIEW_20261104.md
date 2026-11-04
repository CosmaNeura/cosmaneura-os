# Chief answer to private note review

A provider can choose **Message details → Review as note** on one completed Chief conversation answer. The current note editor adopts that exact answer only after the explicit action. Nonempty editor text requires **Replace editor with draft** or **Keep my text**. Selection makes no note save, review, model call, handoff or external action. The original answer and unsent message stay unchanged.

The API advertises `note.allowed_reply_roles` only for linked workspaces whose latest note is editable. The client treats an absent capability as unsupported. Unlinked notebooks and Core-backed notes do not offer this action. This preserves the current appointment gate and read-only note hooks.

The server resolves the saved reply and corresponding conversation entry within the same workspace, Box and owner. Chief output must use an available `azure_gpt41` backend. Where a model admission exists, it must be completed and its result, agent and frozen workspace/role/context must match the saved reply. An answer created before the immutable appointment-link revision is rejected; `note.chief_source_min_revision` lets the client avoid offering it. Existing selected-connector lineage restrictions stay in place.

Older sources within the same bound visit remain usable through the existing source-change, explicit reconciliation, save and exact review workflow. Source fingerprints, saved revisions, history, review acknowledgments and existing Scribe behavior stay intact. Replacement is additionally bound to the current explicit selection episode, so loss of access or selection cannot adopt a stale answer.

## Validation

- `MessagesNoteReviewJourney.test.tsx`: the existing note/notes journeys plus the new server-capability, exact selected answer, replacement/keep-text, unsent-message, explicit-save and explicit-review journey.
- `chief-note-source.test.ts`: absent server capability and completed/available/scoped-context eligibility.
- `tests/integration/test_note_review.py`: completed Chief output, preserved source reconciliation, pre-appointment-link rejection, uncompleted admission, nonconversation/unavailable output and cross-workspace/owner/Box rejection.
- Local final web checks: all five cases and TypeScript passed. The contained final backend run: all nine new cases passed. The first contained run also passed all fourteen unchanged note-review cases, including Scribe lineage, ownership, immutable reviews and concurrency; four newly added setup cases were corrected and passed in the final run.
- Required CI has not run for this feature commit. No client renderer/build/signing or API deployment performed.

## Delivery requirement

This feature requires the matching API source before it becomes available. A new client on an older API keeps the action hidden, even when a completed Chief answer exists. Local mounted tests use synthetic fixtures and do not prove a hosted or native operational journey. The subsequent release must verify the actual API capability and provider journey.
