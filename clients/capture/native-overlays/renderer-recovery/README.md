# Native renderer-loss capture closure

This W31 overlay applies only to a fresh archive of Scribe commit
`ea7f99d0278a05706531ffb1288cb1df7acf507b`, after the qualified
`renewable-authority` overlay. It changes five explicitly enumerated Swift source
and test files. The original Scribe tree, prior overlays and finalized packages
remain unchanged. This overlay does not add a native recovery screen or select
itself in the Apple composer.

`scripts/apply-native-renderer-recovery-overlay.py` exposes
`apply(output: Path, source_ref: str)`. Call it after the renewable overlay and
before writing `composition.json`, then include its returned provenance in the
new composition manifest. Its CLI accepts `--output` and `--source-ref`. It checks
the full prerequisite overlay, exact source/patch hashes, the entire patch file
list and post-apply hashes. Source links, drift, finalized archives, Git roots,
extra changed paths and reapplication are rejected before mutation.

The native controller can import `CosmaneuraIOSPCMCapacitor` and call:

```swift
try await plugin.fenceAndStopForRendererLoss()
let idle = IOSPCMCapacitorPlugin.confirmProcessCaptureIdle()
```

Both methods are `@nonobjc`; JavaScript plugin registrations remain byte-for-byte
unchanged. The stop method returns no token, audio or fabricated idle result. An
unloaded plugin is permanently prevented from initializing after renderer loss;
the static idle check still checks all capture owners in this process.

The existing bridge lock serializes the permanent start fence with `begin`.
Closure targets only the exact current session on that bridge and reuses its
verified `stop(token, mode: .discard)` path. Concurrent calls coalesce. Failed
freeze/release keeps ownership and the fence; an explicit retry can finish the
same closure. The facade never stops another bridge's session or clears the
process ownership registry. A successful local stop can therefore coexist with
`idle == false` when another owner remains.

The controller must retain the old plugin while awaiting closure, require an
affirmative process-idle check, and require an explicit user action before
constructing a fresh bridge. The old bridge cannot be unfenced. These methods do
not reopen a WebView, start capture, restore consent, replay requests, authorize
follow-up or clear durable storage. Already dispatched operations still require
normal outcome reconciliation.

Discarding closes volatile, unacknowledged audio and may lose that uncommitted
tail. Existing encrypted queues and drafts are outside the facade. Native UI
must distinguish preserved saved work from unconfirmed recent work; this is not
a lossless native audio handoff.

Validation uses actual Swift Core/transport implementations with fake permission
and audio drivers: pending permission, freeze/release failure and retry, concurrent
closure, racing Begin, late frames, permanent old-bridge rejection, and retained
ownership in a different bridge. iOS 17 simulator module compilation checks the
actual plugin API against cached Capacitor 8.5.0. Native renderer termination,
physical-device behavior and the complete recovery UI remain separate acceptance
work. Local evidence and immutable before snapshots are in
`/private/tmp/cosmas-w31-native-stop`.
