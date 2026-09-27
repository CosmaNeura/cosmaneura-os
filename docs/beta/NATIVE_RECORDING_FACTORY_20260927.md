# Authenticated native recording factory and retained bridge

The iPhone factory joins the native recording host to the signed OS account,
Core-backed encounter context, and existing protected queue. Its Capacitor
operations return recording metadata; audio samples and unwrapped keys stay native.

`openProviderRecording` accepts only `requestId`, `revision`, `workspaceId`, and
`sessionId`. Native code fetches `/provider-team/identity`, fetches the immutable
recording context, and checks the identity again before constructing custody.
The identity request is a fixed-origin GET with no body/query, both version-2
headers, a 1,024-byte response limit, and a 15-second caller deadline. Cancellation
and account changes discard late results. The existing workspace route verifies
the encounter belongs to the signed account; a Box ID is not a workspace ID.

The recovery UUID is the first 16 bytes of SHA-256 over UTF-8:

    cosmas-native-recording-recovery-v1 + NUL + accountDigest + NUL + recovery_scope

The UUID version/variant bits are set to UUIDv8/RFC 9562. This namespace remains
stable across SDK session renewal, but changes with the native identity policy,
user/organization, or server recovery scope. It grants no recording authority.
Metadata includes the verified workspace and recovery UUID for the subsequent
ciphertext uploader. Existing legacy recordings are not renamed or adopted.

`providerRecordingCommand` accepts the recorder ID, revision, request ID, and
one of read/start/pause/seal/close/input. Opening does not start the microphone.
Close can physically stop after sign-out, returns no private recording metadata,
and still requires the original account for the service's stop confirmation.

One process runtime retains authentication, connection, source recovery, and the
recording bridge across WebView replacement. Auth changes retire recording even
with no renderer listener. Renderer source operations are serialized, retain their
ownership through awaits, and exclude native custody before source preparation.
Renderer recovery verifies physical legacy idleness and can preserve only the
exact native gate owner held by the retained recording. It does not clear another
owner or treat a live native microphone as physically stopped.

Local verification exercises malformed account replies, independent namespace
vectors, renewed sessions, account changes, cancelled and stalled reads, retained
auth/recovery objects, replacement observers, source exclusion, metadata parsing,
recording reopen, and sign-out without a WebView. The actual Swift transport is
also passed through the OS identity protocol boundary using synthetic fixtures.
Mac helper and unsigned iPhone archive builds check the real package composition.

Remaining operational work: select this bridge in the provider recording UI,
connect its ciphertext namespace and frozen completion intent to upload recovery,
finish the desktop capture/storage adapter, and qualify recording through a
reviewed SOAP note on real signed-in devices and services. Native compilation
and synthetic fixtures do not establish those runtime outcomes. This change does
not activate Core permissions, install an app, deploy staging, or delete audio.
