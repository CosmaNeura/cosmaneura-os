# Apple client composition

Current source ownership and the recovered 1107 app are documented in
[the source index](../../docs/COSMABOT_SOURCE_OF_TRUTH.md) and
[apps/capture](../../apps/capture/README.md). CosmaBot owns the app source
preserved in this repository; shared implementation owners are `clients/*`.
The separate Scribe server application and repository are outside this work.

## Historical composition path

The material below describes the earlier reuse of a pinned Apple shell. It is
historical build evidence, not a portable current-source build instruction.
The old composer still requires that raw snapshot and cannot consume the
already-composed recovered 1107 tree. Qualify the owned-source build path before
another native release; do not fetch or modify a separate Scribe repository to
work around missing CosmaBot source.

`scripts/prepare-apple-synthetic.py` reads four client-only paths at Scribe commit
`ea7f99d0278a05706531ffb1288cb1df7acf507b` into a fresh output directory. It records
source and composed file hashes, copies an already-built web bundle, removes the
signing team from the isolated project and uses `com.cosmasos.synthetic` so testing
cannot replace the existing Scribe app. It does not change Scribe's checkout.
The owner approved **iOS 17+** on 2026-09-17. Composition sets the app/project
deployment targets and aggregate Swift package platform to iOS 17 and records
that minimum in `composition.json`; the pinned Scribe source hashes remain intact.

Use `--verification-variant w8m` for a side-by-side test app with bundle ID
`com.cosmasos.synthetic.w8m`. The original synthetic app keeps its own container.
Variants accept milestone labels only; the composition cannot select a product
bundle ID or signing identity.

Build input: the current OS web bundle with `VITE_WORKSPACE_ENABLED=true`,
`VITE_COSMAS_ENV=synth_os` and the separately selected synthetic API URL. No model
key or other credential belongs in this bundle. Loopback is suitable for the iOS
simulator on the same Mac; a physical iPhone requires its own reachable,
authenticated backend connection.

```sh
python3 scripts/prepare-apple-synthetic.py \
  --scribe-source /path/to/read-only/scribe-checkout \
  --web-dist /path/to/synthetic/web-dist \
  --output /private/tmp/cosmas-apple-fresh-build
xcodebuild \
  -project /private/tmp/cosmas-apple-fresh-build/apps/capture/ios/App/App.xcodeproj \
  -scheme App -configuration Debug -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /private/tmp/cosmas-apple-fresh-build/DerivedData \
  CODE_SIGNING_ALLOWED=NO build
```

The pinned shell uses Capacitor 8.5.0 and its official checksummed Swift binary
packages. Dependency resolution is performed by Xcode when building, not by the
composition script. The iOS 17 target records the product minimum; actual
dependency support and build/device behavior must still be verified.

First physical target supplied by the owner: likely **iPhone 12**, using its latest
installed OS. Confirm the model and exact OS build at installation. Simulator
evidence is recorded separately and cannot establish physical microphone,
interruption, encrypted queue, or background/lifecycle behavior.

This composition is a local synthetic development build. It is not signed beta
distribution, an approved production backend connection, or permission to record.
Native capture is enabled only through the consent/session integration once that
flow is implemented and tested; linked plugin code alone does not establish it.

W8m qualifies direct signed loopback requests from `capacitor://localhost` using
`VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED=true` and the separate server flag
`WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED=true`. Both default off. The server still
requires the authenticated synthetic workspace profile, a local `w1a_` database,
local blobs, explicit exact CORS/Clerk authorized parties and current private
ownership. Keep `WORKSPACE_NATIVE_SYNTHETIC_ENABLED=false` in this signed profile.
The existing Electron synthetic proxy remains unable to carry bearer tokens.

Transport acceptance does not enable native login. `RuntimeApp` refuses
to initialize its web Clerk provider in the Apple shell. The simulator transport
proof supplies an offline identity outside the product bundle and uses the real
OS API/JWT verifier/Postgres with an explicit Core fixture. Real Clerk session
acquisition, native PCM/queue integration and physical-device qualification are
remaining work. See the W8m checkpoint for the exact evidence and next step.

W8t adds an optional native ClerkKit adapter and Capacitor workspace entry. The
composition command accepts `--native-auth-clerk-archive /path/to/clerk-1.5.5.tar.gz`;
the exact public archive hash is checked before importing the unmodified SDK core.
This adds the plugin but always writes `CosmasNativeAuth.enabled = false` in the
app's Info.plist. No real instance, organization, publishable key or audience is
generated. Native runtime selection additionally requires
`VITE_WORKSPACE_NATIVE_AUTH_ENABLED=true`, authenticated/workspace flags, the
Apple local-transport flag, the exact Capacitor origin and the local API profile.
An incomplete native profile fails closed and cannot fall back to a demo user.

The native adapter keeps SDK credentials native, acquires fresh tokens and binds
them to the current user/session/organization, issuer, audience and native origin.
The server remains responsible for signature and current authority verification.
Sign-out closes access before remote work and persists a local block. Keychain
failures close access; a failed Keychain write cannot establish durable blocking
across restart. Real SDK token claims and device Keychain behavior remain
unqualified. See `docs/reference/cosmasos-beta/W8_NATIVE_AUTH_CHECKPOINT.md`.

W8n connects native queue selection and verifies the actual Swift PCM bridge
without microphone access. W8z resolves its simulator key-persistence failure:
the simulator app needs a local identity in Xcode's `__TEXT,__entitlements`
section. Putting those restricted entitlements in an ad-hoc signature caused
AMFI to reject launch. No Apple account, release identity or AMFI bypass is used.

For a separately authorized synthetic simulator test, add `--simulator-custody`
and a `--verification-variant` to the composition command. It emits a fixed
invented prefix plus that variant's bundle ID and adds the simulator-specific
`LD_ENTITLEMENTS_SECTION` setting only to the app target. Continue building with
`CODE_SIGNING_ALLOWED=NO`; do not pass the test entitlements to `codesign`.
Default composition emits no simulator identity, and device SDK settings receive
no test entitlement section. The composition script never signs, installs,
launches or records. Preserve the same test prefix/bundle when verifying recovery
of an existing container; another variant has a separate identity and key group.

The approved `com.cosmasos.synthetic.w8n` simulator test now passes encrypted
native queue persistence, non-extractable WebView session-key recovery, duplicate
update rejection and workspace isolation through relaunch and an iOS 17 build
update. This establishes simulator custody only; native login, actual microphone
capture and physical-device signing/storage still require their own evidence.
See `docs/reference/cosmasos-beta/W8_SIMULATOR_CUSTODY_CHECKPOINT.md`.
The existing `clients/capture` dependency already supplies the exact Capacitor
8.5.0 JS package, verified against Scribe's pinned lockfile and cached tarball.

The optional W36 local workspace policy adds an explicit CSP to a fresh separate
Apple variant. Pass `--workspace-api-origin http://127.0.0.1:8046` to
`scripts/prepare-apple-synthetic.py`; this must match the web bundle's
`VITE_API_BASE`. If capture is included, pass each exact local ciphertext upload
origin with `--capture-upload-origin`, matching `VITE_CAPTURE_UPLOAD_ORIGINS` and
the configured Core upload policy. At most four upload origins are accepted.
Only exact loopback HTTP origins with explicit ports are supported by this local
policy. Hosted storage or service origins require a separately qualified policy.
Omitting the new options preserves the previous composition behavior.

The policy pins `capacitor://localhost`, explicitly disables Capacitor's native
HTTP replacement, and retains WKWebView fetch with its CORS, redirect, stream and
abort semantics. C1 delivery, finance work, portal setup, portal work and finance
setup use the shared closed clients; Apple has no Electron route copy list.
Their exact contract headers, input/response limits and fresh native token
acquisition remain active. Verified PDFs use raw PUT/GET up to 8 MiB and a local
blob iframe only after length/hash validation. Bundled scripts, audio worklets,
bot images, inline React styles and local media remain permitted; arbitrary
network origins, remote frames, object embeds and form submissions do not.

Native private recovery retains the same account scope and SecureQueue identity:
portal setup 16 KiB, portal work 64 KiB, and delivery/payment/settings records
128 KiB. These bounds include the journal wrapper. Package/source and unit checks
do not qualify actual WebKit cross-origin bursts, large PDF rendering, physical
device memory/lifecycle or live sign-in. In particular, combined Work startup
can request more fresh tokens concurrently than the native driver's eight-task
limit; actual scheduling and recovery must be tested before acceptance. No token
limit or deadline is widened by this policy. Existing app profiles are preserved.
