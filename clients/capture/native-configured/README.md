# Configured iPhone microphone source

This source is composed into CosmaBot's operational iPhone builds after the
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

CosmaBot preserves its existing play-and-record/voice-chat policy and automatic
input selection. This adaptation does not import Scribe's newer microphone
picker, signal diagnostics, background recorder or secure-queue changes.
It does not change permissions, renewal, storage or network contracts.

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
