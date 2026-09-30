# Retained Scribe recorder

This is the bounded recorder library reused from Scribe commit
`ea7f99d0278a05706531ffb1288cb1df7acf507b`, through
`scripts/import-scribe-capture.py`. `provenance.json` records each original source
path and hash. The original Scribe checkout and its application UI are unchanged.
The public-key mock fixture is synthetic and used only by tests.

OS extends the controller, preparation types and encrypted flow store with
`prepareAdmitted(sessionId)`. That path starts from Core's genuine admission,
stores no browser-selected clinical identity or fabricated consent/session receipt,
and reuses key binding, capabilities, leases, reservations, encrypted chunks,
upload reconciliation and interruption handling. Preparing/restoring never starts
the microphone. The original direct Scribe preparation path remains supported.

The Core session reference is a consistency check, never capture authority. The
workspace transport must reauthorize each operation. Scope local stores to the
current private workspace and keep the origin-wide flow lock. Keep queued work on
network/access failure. Explicit human start and interruption review remain required.

`WorkspaceCaptureBff` carries the twelve capture/status/source-transcript operations
through the first-party signed workspace. It never creates consent or sessions.
`restoreAdmittedResult` reopens a completed or pending server result after local
cleanup without new key binding, leases or recording. It refuses to bypass a
retained local capture/gap; that state continues through normal recovery.

W9n adds `prepareAdmitted(sessionId, profileRequest)` for explicit longer-visit
selection. The intended request and retry key are encrypted before selection;
the validated receipt is saved before obtaining a lease. Restoration recovers
the same receipt and acknowledges it on capabilities/reservations. Legacy
preparations retain their original policy. The workspace's
`VITE_WORKSPACE_CAPTURE_LONG_VISITS_ENABLED` and OS's
`WORKSPACE_CAPTURE_LONG_VISITS_ENABLED` default off and gate new selection;
turning them off does not discard pending profiles or queues. Core and Scribe
have independent default-off selection gates.

Configured workspace sessions use standard server capabilities and renewable
leases for fresh recordings. With the long-visit client feature enabled, the
existing standard continuous controller applies its one-hour local limit without
calling the optional profile-selection endpoint. Saved profile intentions and
receipts retain their original recovery protocol; a failed or unknown profile
request is never silently replaced. This path was qualified with generated PCM,
including one hour across four lease renewals and encrypted offline restoration.

A browser preparation rejected before profile confirmation can offer **Continue
preparation**. This explicitly retains the original encrypted intent and switches
the empty local setup to standard capture only after checking an untouched server
session, full standard capacity, no local key/lease, and an empty audio queue.
The checks repeat on the click; Start recording remains a separate action.
Unknown replies, confirmed profiles, native journals and existing audio keep their
original recovery path.

The shared recorder currently selects only the microphone track and enforces
360 ten-second chunks for the longer profile. The backend supports two tracks,
but continuous lease/reservation renewal and dual-track native recording remain
unqualified. A sixty-minute budget is not permission to record beyond the
current fifteen-minute authority window. See the W9 OS profile checkpoint.

These sources do not qualify native authentication, microphone recording, STT,
physical devices or release. The main preview and existing Mac draft stay intact.

W8n selects the retained iOS PCM adapter and Keychain-backed native chunk queue
together on eligible iOS builds. Native queue keys are scoped by workspace and
session, and decoded session references are checked on create/read/list/CAS.
Queue selection is retained in flow metadata across relaunch; unfinished browser
records or a changed capture profile cannot be silently replaced. Flow records
and session keys still use the existing encrypted IndexedDB/WebCrypto store.

The Capacitor proxy must be wrapped in a plain object when returned by an async
loader: the proxy synthesizes `then`, so returning it directly stalls Promise
resolution. This is covered by a regression test and the real simulator probe.

Native PCM → WAV/encryption → scoped queue → upload/complete/transcript passes
the local protocol test with generated PCM and a fake native bridge. The real
Swift bridge responds without starting audio. W8z subsequently qualified simulator
queue/key custody with the approved local entitlement experiment, and W8p/W8r
connected receiver-backed gap recovery. W9d/W9e verify the complete synthetic
Mac/iPhone-simulator loop across relaunches. Physical-device capture, real native
sign-in and live services remain unqualified; interruption still requires review
and explicit Start. Preserve the retained gap evidence.
