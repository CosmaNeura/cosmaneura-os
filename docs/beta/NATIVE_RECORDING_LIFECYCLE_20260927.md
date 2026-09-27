# Retained native recording lifecycle

The native run and visit host now connect the encrypted PCM recorder to the
existing CosmaBot source owner and gate. The run handles one microphone interval;
the host retains the visit's key, queue, lease and completion intent across
pause/resume, interruption and stop retries. Opening or refreshing the host does
not start the microphone. Its factory and recording-screen selection are still
pending, so this is integration source rather than device acceptance.

The gate separates the existing renderer consumer from the encrypted native
consumer. Native start requires both physical-idle probes. A plugin reload cannot
replace a still-active probe, and retirement prevents late permission, service
or readiness replies from starting audio. Physical closure precedes the original
authenticated source-stop operation; an unsuccessful stop retains its owner and
proof for an exact retry. A retired run cannot request permission even if it has
not installed its gate yet.

Native continuation now requires the actual source-extension decision in addition
to renewed lease and reservation receipts. The source owner checks the same
consumed source, account/session revision, original proof and extension chain.
The gate preserves the exact decision on retry. PCM independently rechecks the
decision expiry when applying it and rejects a different source, generation,
deadline or cumulative limit. A full unused reservation window cannot extend an
idle source indefinitely. A resumed interval keeps its admitted lease generation.

The current selected CosmaBot source profile remains 360 ten-second positions.
The host caps new reservations accordingly, and the graph uses the actual
remaining limit in the consumed permit. The library's larger position/storage
capacity is not permission for a longer operational visit. The required longer
visit profile still needs end-to-end admission, native extension and device
acceptance; standalone three-hour synthetic storage/PCM evidence is narrower.

Run and host source are reused from Scribe commit
`ec511ff1c3b979901e80f5033c1f02a05f65c4b3`. Exact original blobs and adaptations
are in `tests/native/recording-run/UPSTREAM.json`. The Scribe checkout is read-only.
The actual Mac helper and Apple bridge compositions include the same source
owners and share the existing native recording packages.

Local checks cover interrupted/pending starts, concurrent stop, physical/server
stop failure and exact retry, renderer exclusion, plugin reload, account/session
retirement, source-extension response loss/replay, and real encrypted PCM passing
through the retained run with synthetic audio adapters. The visit-host checks use
actual custody owners and encrypted records for pause/resume, seal/reopen,
empty recording, expired lease and factory/stop/recovery failures. They exercise
neither an OS microphone nor the renderer UI.

The native PCM regression suite also covers generation preservation, insufficient
admitted capacity, absent/expired/wrong source decisions, deadline and stop races,
and its longer synthetic library profile. Existing native identity/renderer
lifecycle and Apple composition contracts remain applicable. Commands, complete
logs, source hashes, final build results and exact commit evidence are retained
outside the checkout in `../native-recording-run-20260927-r1/` and in the PR.

Next: resolve the authenticated native recovery namespace, instantiate the visit
host with the shared secure queue, connect the recording screen and ciphertext
uploader, and wire the Mac's live audio/storage adapter. Matching native releases,
physical-device behavior and real-service recording-to-reviewed-SOAP acceptance
remain required. Existing Core activation, native sign-in and certificate
dependencies remain explicit; this increment does not activate or deploy them.
