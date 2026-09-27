# Desktop client composition

The Mac synthetic client reuses Scribe's sandboxed BrowserWindow configuration,
navigation/permission restrictions, diagnostics policy and finite static-asset
resolver at commit `fe22a435b6201c2d8013348927ea6a349e0b48c6`. The composition script
records source hashes. It expands only the resolver's explicit asset map to the
actual OS bundle and enables same-origin fetch on the existing local app scheme.
The original renderer CSP is the default. Authenticated capture builds can add
explicit HTTPS upload origins as described below.

The local renderer calls `app://cosmas/api`. A main-process bridge permits only
listed workspace/Provider Team and existing synthetic work routes to the fixed
`http://127.0.0.1:8018` API. It forwards synthetic identity headers and JSON only,
blocks redirects, bounds bodies, omits credentials, and returns safe errors.
Administrative identity and retention endpoints are excluded. Authentication and
Box/private-workspace checks remain enforced by the server. This bridge cannot
connect a hosted or real-data backend.

Build the web bundle with `VITE_COSMAS_ENV=synth_os`, `VITE_WORKSPACE_ENABLED=true`,
`VITE_DESKTOP_SYNTHETIC_ENABLED=true` and `VITE_API_BASE=app://cosmas/api`, then run
`scripts/prepare-desktop-synthetic.py` with the read-only Scribe path, web bundle
and a fresh isolated output. Run its `app` directory with official Electron
43.4.1, matching Scribe's existing pin. No Recall SDK is installed or activated by
this composition. `scripts/package-desktop-synthetic.py` packages a distinct local
test app from that official runtime. Capture, native authentication, release
signing and updates need their own subsequent integration and verification.

The iOS app uses Scribe's Capacitor shell. A Mac Catalyst qualification build of
that shell failed because the pinned Capacitor/Cordova XCFrameworks lack Catalyst
slices. The Electron desktop foundation avoids making Catalyst support a new
dependency for the beta.

The ordinary synthetic app uses an isolated state directory and an in-memory renderer session.
Model keys remain on the API server. Microphone, screen capture, downloads,
popups, webviews and arbitrary navigation remain denied by the reused desktop
boundary. The ordinary workspace UI and server-held notebook/team history are
shared with the browser and iPhone build.

For a side-by-side local verification build, the packaging script accepts
`--verification-variant w6` (a short lowercase alphanumeric suffix). It uses a
distinct bundle identifier; each composition already has its own state directory.
This allows testing a new build while preserving an older app and unsaved draft.

For a stable authenticated local installation, supply `--installation-profile w19a`
to the composer and the matching `--verification-variant w19a` to the packager.
The profile is independent of `--app-version` and `--build-number`; both are numeric
product values, separate from Electron's pinned version. An optional
`--installation-root` places local test storage outside versioned build/source
directories. Otherwise it belongs under Application Support/CosmasOS Synthetic.
The profile marker binds the qualified storage generation, Electron version,
renderer partition and native helper identity. Missing, incompatible or unsafe
storage is refused without resetting it. Keep the same qualified identity for an
update; use a separate profile for an independent trial. Legacy compositions keep
their original paths and receive no automatic migration.

[W19 local update evidence](../../docs/reference/cosmasos-beta/W19_LOCAL_UPDATE_CHECKPOINT.md)
qualifies compatible development bundle replacement/rollback with saved encrypted
work. It does not qualify an automatic updater, unsaved typing during app closure,
cross-schema rollback, signing or distribution. New storage/runtime identities
need explicit migration and recovery work before changing that compatibility marker.

[W20 deliberate-close evidence](../../docs/reference/cosmasos-beta/W20_CLOSE_RECOVERY_CHECKPOINT.md)
adds a native warning when the renderer has unsaved edits, pending saves or active
capture. Keep working/Escape retains the window; explicit Close anyway proceeds.
Auth helper and IPC cleanup happen on `will-quit`, preserving the session after a
canceled quit. The registry stores presence flags only. It is not an autosave or
crash-recovery store, and cannot protect against forced OS termination.

[W21 encrypted draft evidence](../../docs/reference/cosmasos-beta/W21_DRAFT_RECOVERY_CHECKPOINT.md)
adds a separate encrypted notebook/team draft journal and exact parent-request
recovery. Actual Mac forced exit and Apple simulator termination preserve committed
records. Restore always checks current server authority. The desktop proxy forwards
the validated draft-recovery compatibility header; a paired backend can
require it with `workspace_draft_recovery_required`. That setting defaults off and
does not grant authentication or action authority. Before release, qualify the
paired current clients, CORS configuration and server gate. Remaining child editors,
independent operation requests and distribution rollback remain open; no last
keystroke is guaranteed before its local commit.

[W22 clinical draft evidence](../../docs/reference/cosmasos-beta/W22_CLINICAL_DRAFT_RECOVERY_CHECKPOINT.md)
extends recovery to private/Core note and transcript editors. Current clients send
`X-Cosmas-Draft-Recovery: 2`; the proxy permits 1 or 2 and a current backend with
the gate enabled rejects generation 1. Clinical-sized encrypted records survive
actual Mac exit and iPhone simulator termination. Private-note API retries are
qualified locally; fresh Core/Scribe editor integration and independent operation
recovery remain open. Release must qualify the paired backend, including missing
recovery-scope behavior, actual device/services and distribution.

The current startup recovery shell also accepts one-way `ready` and `failed`
notices from its exact current packaged main frame. Only React readiness ends
the startup deadline; an HTML load alone does not. The 30-second deadline counts
visible, focused, non-minimized time. A runtime failure or replacement main
document latches the launch closed: auth and IPC close, the owned BrowserWindow
is force-closed, and native guidance waits for both window and renderer destruction.
The implicit last-window quit is suppressed during this failure path. Failed
destruction or a five-second confirmation timeout exits without waiting for a
dialog; confirmed destruction offers only closing the app. No path reloads, retries a request,
restarts capture, or clears the persistent profile. Reopening remains explicit;
unsaved or not-yet-committed data and in-flight requests require review.

## Signed local workspace transport (W8u)

The optional native-auth composition uses a separate `main-authenticated.mjs`
entry and fixed loopback API on **8046**. The existing 8018 synthetic composition
is unchanged. Supply `--native-auth-helper` to `prepare-desktop-synthetic.py`
only after composing the pinned ClerkKit/native sources with
`prepare-native-auth-proof.py --include-desktop`, compiling them with
`build-desktop-auth-helper.py`, and packaging the helper with
`package-desktop-auth-helper.py --compiler-receipt` pointing to that build's
`compiler-receipt.json`. See `docs/operational-native-build.md` for the full commands.
The generated helper's SDK
configuration remains disabled. These scripts do not activate an account.

The web build also requires `VITE_WORKSPACE_AUTHENTICATED_ENABLED=true` and
`VITE_WORKSPACE_DESKTOP_AUTH_ENABLED=true`, alongside the desktop synthetic flags
above. Apple-specific native/transport flags must be false. The API requires its
own `workspace_desktop_local_transport_enabled` gate and the existing signed,
synthetic, local-data profile with exact `app://cosmas` origin and authorized party.

The sandboxed preload exposes auth state, explicit sign-in/sign-out, state
subscriptions and the two literal lifecycle notices above. Main obtains fresh JWTs from the native helper over bounded
dedicated pipes and sends them through direct loopback HTTP. The renderer receives
only a session revision for requests. Routes, payloads, current session, response
bounds and private server authority are checked independently. A nonsecret access
enum in the isolated app state directory persists explicit login/logout intent;
it contains no token or account identifier. Native credential custody remains the
SDK/Keychain responsibility and is not qualified by the offline tests.

The authenticated shell uses a persistent partition inside its isolated state
directory. This retains the existing encrypted IndexedDB capture queue and its
nonextractable keys after process restart, so an unconfirmed upload can be
retried. Credentials still remain in the native helper/main process. Persistence
does not qualify hardware key custody or authorize a real-data build.

For capture, supply `--capture-upload-origin https://storage.invalid` (repeatable,
at most four exact HTTPS origins) alongside the native-auth helper. The web
bundle's `VITE_CAPTURE_UPLOAD_ORIGINS` and Core upload-origin policy must match.
The composer and runtime reject wildcards, credentials, paths, queries, fragments,
explicit ports and injected CSP directives. Only `connect-src` expands; the
retained script, navigation, permission and sandbox restrictions remain. An
ordinary build has no upload-origin allowance. The local fixture origin above
does not activate blob storage, microphone access or an external service.

`--microphone-capture` separately stages microphone support. It requires the
authenticated helper and exact upload origins; the web bundle also needs
`VITE_CAPTURE_E2E_MICROPHONE_ENABLED=true`. Both defaults remain off. The shell
allows audio only from its own current signed-in main frame at the exact app URL.
Other frames, origins, video, display capture and unrelated permissions remain
denied. The package supplies a purpose-specific macOS microphone usage description.
The retained recorder still requires consent and an explicit Start, stops its
input track before asynchronous audio cleanup, and never restarts capture after
an interruption or relaunch without the existing recovery/Start flow.

W9f verifies this path with Chromium's generated fake device, the real
`getUserMedia`/AudioWorklet implementation, encrypted queue and local services.
Its first file-based fake input was rejected by the audio sandbox; the final
test uses the built-in generated device without disabling any sandbox.
Physical microphone/TCC behavior and real identity/STT remain separate checks.

Run `node --test clients/desktop/*.test.mjs` with `COSMAS_DESKTOP_COMPOSED` pointing
at the composed app. The direct-HTTP test temporarily owns loopback port 8046;
stop only the corresponding local test API before running it. The checkpoint at
`docs/reference/cosmasos-beta/W8_DESKTOP_AUTH_CHECKPOINT.md` records actual Mac
window, signed-API and process-restart evidence and the remaining live-login,
device, microphone and release work.

## Release helper builds

`scripts/build-desktop-auth-helper.py --configuration release` compiles the
qualified native helper with Swift's Release configuration. Omit the option for
the existing Debug default. Version-2 compiler receipts record the configuration
and bind it to the compiler command; packaging continues to accept retained
version-1 Debug receipts. The normal helper packager accepts either completed
build. Building or packaging a Release helper does not sign, notarize, install,
or launch it.
