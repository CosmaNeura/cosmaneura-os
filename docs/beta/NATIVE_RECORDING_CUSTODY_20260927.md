# Native recording custody integration — September 27, 2026

The native recording service now uses CosmaBot's existing native account owner
and fixed OS API connection for public-key lookup, key binding, lease issue and
renewal, and chunk reservations. Core binding/nonce/freshness verification stays
in the OS adapter; the native service verifies the OS envelope and each typed
receipt, and rechecks the account after I/O.

The recording custody package is derived from Scribe commit
`ec511ff1c3b979901e80f5033c1f02a05f65c4b3`; its file provenance is retained in
`clients/capture/native-recording/UPSTREAM.json`. It retains key-bind, lease,
reservation and completion intents across ambiguous responses and writes.
Recovery requires the original encryption key and authenticates stored packets.
An existing queue without the matching native flow journal cannot be adopted.

CosmaBot uses its own keychain service and native journal prefixes. Neither the
existing `cosmas-queue:v1` renderer records nor the separate Scribe application
are migrated, deleted, or adopted. The public capture envelope remains CSCRIBE1
for compatibility with the platform's encryption protocol.

The normal Mac helper and iPhone bridge source compositions include the service
and its package. It is native-only: the generic renderer action initializer
rejects the new operation, and the transport permits only the five required
operation kinds. No renderer-provided endpoint, token or tenant is introduced.
The pinned Clerk SDK inventory remains separate from owned recording sources.

Validation:
- 46 native custody tests: encryption/reopen, lost writes, stable intents,
  reservation conflicts, lease recovery and sealed recording recovery.
- 33 native service and existing transport tests: actual Swift request builders
  against current Python wire models, malformed receipts, denial, account change,
  and renderer/action confusion rejection.
- Actual optimized Mac helper build using the pinned Clerk SDK.
- Native auth/custody modules and service type-checked for arm64 iOS 17.

This is an integration prerequisite, not acceptance of the new recording flow.
The existing recorder remains selected. Still required: native PCM/driver and
retained host integration, protected queue adapter, account-bound recovery
namespace, bridge/UI selection with old-recording recovery, matching app builds,
and real device/service recording-to-reviewed-note acceptance. No duration
profile, installed app, or staging deployment changes in this increment.
