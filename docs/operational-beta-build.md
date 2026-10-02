# Complete beta client builds

Select `VITE_WORKSPACE_FEATURE_PROFILE=operational-beta-v1`. The shared profile
includes appointments, intake/inbox and handoff, Scribe capture and note/source/
correction/recovery controls, preparation and work, the private bot team and AI
activity, routines, membership, messaging/fax, payment, portal and all implemented
account connections. Athena remains read-only. Server readiness, access grants,
service enablement and per-action human approval still control actual use.

Use `web/.env.hosted.example` with exact public origins and a publishable Clerk
key, then run the ordinary `build:beta` command. Vite also validates the profile
when called directly for a hosted build. Individual conflicting, unknown or stale
feature gates fail the build. The profile emits `cosmas-beta-features.json` beside
the hosted transport manifest. Dockerfile.web uses this same profile.
For desktop and Apple renderer bundles, use `scripts/build-native-renderer.mjs`
with the retained public client inputs as described in operational-native-build.md;
the hosted `build:beta` command generates a web-only Nginx policy.

Capture mode is explicit: `browser_microphone` for web/desktop, `ios_native` for
Apple, or `synthetic` for synthetic-only development. Choosing a source stages
its existing Scribe adapter; it does not start recording. iOS mode refuses an
unavailable native platform instead of falling back to synthetic silence.
`VITE_CAPTURE_UPLOAD_ORIGINS` contains one to four distinct comma-separated HTTPS
origins, without paths, ports, spaces or wildcards. `VITE_COSMANEURA_WEB_ORIGIN`
pins record navigation. Both are required so visible controls have a complete
transport configuration. Actual service acceptance remains separate.

Native composers consume the emitted profile and reject mismatched origins,
source mode, microphone permission or native custody/recovery configuration
before creating output. Desktop microphone mode needs `--microphone-capture` and
matching `--capture-upload-origin`; Apple mode needs the existing renewable
capture, renderer recovery and simulator custody overlays. Both require matching
Core web and API origins. The default synthetic compositions keep native auth
disabled and Apple output on Simulator. An explicit operational identity file
supports configured native sign-in, stable desktop storage and a device-only
Apple project; see operational-native-build.md. Installation, device custody,
signing and release qualification remain unfinished. No launch is performed by
these build tools.

The hosted `build:beta` command generates `web/.beta/nginx.conf` from the emitted
feature manifest. Docker copies that generated server configuration. A browser
microphone build permits microphone only for its own origin; the user still
must grant browser permission and explicitly start consented recording. A
synthetic build retains the microphone denial. Camera, geolocation and payment
remain denied. Missing/partial/non-web feature manifests stop policy generation.
The static `web/nginx.conf` template stays deny-by-default.

The profile includes Gmail inbox summaries and reviewed full-message work. Full
message reads require the separately configured, default-off server flag and
explicit expanded consent described in `google-personal-connection.md`. Both native composers require an
explicit --google-connection-client-id and --google-connection-callback-uri
matching the reviewed server client and /connections/google/callback. These
settings are separate from the Scheduling Google login configuration.

The current operational client requires the signed [workspace compatibility handshake](workspace-compatibility.md). Distribute a matching client/backend pair and retain WORKSPACE_DRAFT_RECOVERY_REQUIRED=true for the hosted service. An unsupported server pauses online work while keeping the existing editor and recovery state mounted.
