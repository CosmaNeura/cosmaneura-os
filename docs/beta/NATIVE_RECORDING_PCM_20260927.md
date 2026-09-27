# Native encrypted audio graph and app composition

CosmaBot now composes the native PCM graph, encrypted packet sink and short-lease
continuation machinery with the native custody and service connection introduced
in PR24–PR26. Source is reused from Scribe commit
`ec511ff1c3b979901e80f5033c1f02a05f65c4b3`; the local `UPSTREAM.json` and configured
capture manifest record provenance and adaptations.

The graph accepts audio through the bounded PCM core and acknowledges a packet
only after its encrypted queue record is committed. Native heartbeat and renewal
tasks are separate, so a suspended network renewal cannot suspend the source
deadline watchdog. Renewal verifies the original source and exact lease and
reservation receipts. A failed physical stop stays retryable.

The native driver profile allows an already armed recorder to remain active
across background notifications; startup still requires the foreground.
Interruptions, input route changes, loss of microphone permission, expiration and
storage failures continue to stop capture. This library alone neither grants
recording authority nor adds an app background mode.

CosmaBot adaptations preserve the old renderer's permanent loss fence, its
automatic voice-chat routing, and its extension-decision expiry checks. The
general PCM core can support 2,048 positions, but the existing app source owner
continues selecting its 360-position limit. No longer visit profile is selected
by this change.

The Apple composer supplies a single shared PCM package to both the existing
Capacitor plugin and the auth host. Separate desktop/auth qualification packages
contain their own complete local dependency graph. All owned recording sources
remain outside the pinned Clerk SDK inventory.

Local verification uses invented audio and service receipts:

- 37 Swift tests pass: 21 XCTest cases and 16 Swift Testing cases. These include
  a complete accelerated three-hour PCM/encryption stream, fourteen short leases,
  delayed/lost renewal replies, source mismatch, storage failure, retryable stop,
  native background behavior, renderer-loss closure and the original run limit.
- Five Swift modules compile for arm64 with the iPhone SDK and iOS 17 target.
- 82 Python service/transport/build checks pass. One older Apple recovery test
  skips because its fixed relative Scribe checkout path is absent. The real Apple
  composition and complete unsigned Release archive are built separately.
- The actual Mac Release auth helper and unsigned iPhone Release app archive
  compile from the new composition, using pinned cached dependencies.

This does not yet select the native graph in the recording screen. The next
integration is the protected queue adapter and retained app host, followed by
native bridge/UI selection and matching release packaging. The Mac still needs
its live audio adapter connected to this graph. The accelerated test is not a
three-hour device or live-service acceptance result. No app is installed, no
existing recording is migrated, and no staging deployment is performed here.

Exact commands, source hashes, logs and compiler receipts are retained under
`native-recording-pcm-20260927-r1` in the local integration workspace; the PR
records the final tested and reviewed commit.
