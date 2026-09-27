# Capture upload receipt reuse

CosmaBot's shared capture queue now registers an upload immediately after the
current upload succeeds and its `uploaded` state is durably saved. This removes
one redundant receipt request per successfully uploaded chunk. Interrupted or
reopened attempts still reconcile the server receipt before repeating an action.
Keys, payloads, retry limits, concurrency, and purge-after-registration rules are
unchanged. The queue is used by the configured Mac and iPhone capture paths.

The implementation and lost-registration regression are reused from Scribe
commit `6b342841954f4dc0c307d8547ee6f9d26f54e819` (PR168). CosmaBot's existing
1,080-record encrypted-queue recovery test remains part of local validation.
Request counts establish the removed round trip; actual device/service latency
has not been measured for this change.

The related source review found that the configured `visit-60m-v1` profile
intentionally limits a track to 360 ten-second chunks. Wider storage/protocol
bounds alone do not authorize a longer recording profile. Scribe's newer native
recording host is a separate integration involving native custody, UI selection,
and update/recovery compatibility; those recording limits are unchanged here.

Run the queue, configured-flow, BFF transport and desktop recorder suites locally,
plus the capture and desktop TypeScript checks. Record exact commands, reviewed
commit and results in the PR. No GitHub checks or external review are required by
this change, and local validation does not establish physical-device acceptance.
