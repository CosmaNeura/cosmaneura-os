# Desktop recording with the current Scribe API

The desktop host previously selected `visit-60m-v1` before preparing a recording.
Current Scribe main has no capture-profile endpoint. New desktop recordings now
use the standard capture protocol, preserving the native one-hour recording
limit, automatic lease renewal, encrypted recovery, and creator review.

## Recording policy

The trusted desktop host opts into standard continuous capture. The controller
validates the server's actual capabilities and applies the stricter local limit:
360 ten-second chunks and at most 360 times the maximum envelope size. It never
manufactures a remote profile receipt or changes server authority. A source
extension still needs the current lease, reservation batch and native permit.

New preparation and active journals use schema 7. Standard renewal intents use
version 2 without a profile receipt ID. Existing schema 5/6 profile receipts and
version 1 renewal intents retain their original validators. Restoring an older
standard recording preserves its stored policy. A host that has not opted into
the new policy rejects schema 7 before issuing recorder API requests. Explicit
continuation cannot downgrade the new journal to the older schema 4.

Stop and restart recovery retain the existing durable renewal intent and exact
idempotency keys. An uncertain renewal is observed/reconciled before completion;
it cannot silently start another native recording source.

## Local evidence and acceptance limits

The desktop integration test generates 360 full-size ten-second PCM chunks with
a simulated clock, uses the actual desktop host, encryption and SQLite journal,
and requires four renewals, one physical-source start, and one completion. The
fixture rejects profile operations. Separate controller cases cover committed
and uncommitted lost renewal replies, Stop/pause/teardown during extension,
encrypted-journal reopening, and legacy policy preservation.

These checks use synthetic input, identity, custody, native presentation and
service responses. They do not prove microphone fidelity, deployed service
acceptance, or distribution signing. The current Core/Scribe continuation
receivers must be deployed and enabled under their separate authority before
connected native acceptance. No deployment settings are changed by this patch.
