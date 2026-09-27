# Configured iPhone microphone source

This source is composed into CosmaBot's authenticated iPhone builds after the
renewable-authority and renderer-recovery overlays. `manifest.json` binds every
copied Swift input. The earlier overlay files remain unchanged.

The activation-route fix adapts Scribe PR137, commit
`ca8c70840b312c5ca21c0f143f32a943e62ec1f7`. AVAudioSession can announce a route
change while synchronous category/activation setup is still running, including
after Pause. Those setup notifications must not fail the recording before any
frames are admitted.

`AppleInputRouteEvents` scopes setup notifications to that synchronous operation.
The live adapter binds the single input selected by the existing audio-session
profile, verifies it before the tap and before/after engine start, and clears
the binding after deactivation. Later route changes and all non-route
interruptions retain the driver's existing terminal behavior.

CosmaBot preserves its existing foreground play-and-record/voice-chat policy,
automatic input selection, permanent renderer-loss fence and fresh extension
decision checks. The September 27 native PCM integration additionally provides
a native-only measurement-input profile, bounded signal/startup diagnostics,
and the driver lifecycle used by `../native-recording-pcm`. That profile permits
background events only after foreground startup has completed. Interruptions,
route changes and permission loss remain terminal. The renderer cannot select
this lifecycle through its existing JavaScript bridge.

Both the existing PCM plugin and the auth host resolve one shared PCM package
in the Apple composition. Native encrypted graph code is compiled, but its
retained app host and UI selection are not yet integrated. The
selected duration profile remains unchanged.

The native queue adapter now shares the existing encrypted queue's device key,
file format, revision checks and process lock. The generic Capacitor interface
cannot read or mutate `cosmas-native-*` journals; bulk clear rejects before
removing any files while native custody exists. Ciphertext upload records retain
their existing interface. Existing `cosmas-queue:v1` records are not migrated.
The `secure-queue` overlay also includes the pinned privacy resource for its
disk-space check. Native queue implementation and tests derive from Scribe
`ec511ff1c3b979901e80f5033c1f02a05f65c4b3`, with CosmaBot journal prefixes.

Do not rename the existing Keychain service/account or the
`Application Support/CosmaneuraSecureQueue/v1` storage location: those identify
retained files and their existing device key.

The helper derives from upstream blob
`5c1073986d10239947f285cfb74152169547928f` with its comment adjusted for
CosmaBot's input binding. The Swift regression fixture is unchanged from upstream
blob `cc3a3bf009cb859e5742ec54d4ed6bb49e903198`. It exercises the actual configured
driver, using an explicit fake audio system for repeated pause/resume,
failed activation, startup interruptions and active route changes.

Run it locally from the repository root:

```sh
swift test --disable-sandbox --package-path tests/native/ios-route-startup --filter InputRouteStartupTests
```

The Mac-hosted test does not compile the iOS-only AVAudioSession implementation.
An actual iPhone SDK composition/archive is also required. Neither check proves
physical microphone signal or the real-service recording-to-SOAP workflow.
