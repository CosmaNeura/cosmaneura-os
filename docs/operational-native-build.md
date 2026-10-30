# Operational native build inputs

> Current ownership/checkpoint: [source index](COSMABOT_SOURCE_OF_TRUTH.md),
> [recorded release ledger](COSMABOT_RELEASE_STATE_20261030.md), and
> [recovered iPhone baseline](../apps/capture/README.md). The inputs below
> describe existing composers; the Apple composer still requires its historical
> raw snapshot. A portable build from the newly owned app source is pending
> qualification. Historical deferrals below are not a current release inventory.


The existing Scribe-based composers now support an explicit operational identity.
Optional account connections do not block native capture packaging. Omit both
Gmail client/callback arguments until that connector is configured; native Google
navigation then remains unavailable and the account panel explains the missing
connection. Partial or malformed settings are rejected. The full feature profile,
capture configuration, service authorization and account-consent requirements
remain unchanged. A successful build does not qualify an unconfigured connector
or complete operational Beta acceptance.
Use --native-identity-config with a public JSON document containing exactly:

```json
{
  "version": 1,
  "profile": "operational-beta-v1",
  "client": "apple",
  "apiOrigin": "https://api.example.invalid",
  "publishableKey": "",
  "frontendOrigin": "https://clerk.example.invalid",
  "organizationId": "",
  "audience": "cosmas-os-beta"
}
```

Replace the empty fields and invented origins in the reviewed build configuration.
The client is apple or desktop. A production pk_live key must decode to the exact
HTTPS frontend host. Test keys, test Clerk frontends, extra fields, duplicate JSON
keys and mismatched API/client profiles are refused. No server secret, token or
user credential belongs here. The native SDK retains its exact frontend request
boundary, current organization selection, fresh token policy and app-scoped
Keychain custody. Configuring the build does not register a callback, create a
membership, contact Clerk or authorize clinical data.

For synthetic staging with real sign-in, pass `--data-mode synthetic` to
`prepare-workspace-identity.mjs` and to each native composer
(`prepare-desktop-synthetic.py` and `prepare-apple-synthetic.py`). The renderer
builder consumes the explicit mode in the retained `*-build-env.json`; desktop
packaging requires its manifest to match the composed app. A production-format
Clerk identity keeps the operational app identity and device custody in either
data mode. The key is not PHI authorization; the selected data mode remains a
separate input.

Omitting the option preserves the existing operational `authorized_beta`
default; legacy compositions without an operational identity remain synthetic.
Always select the mode explicitly for a new staging candidate. Existing desktop
installation metadata binds the data mode as well as the account and API;
changing those values refuses startup and preserves saved data. Do not relabel
an existing installation or substitute the retained invented build inputs.

For the first-owner native staging milestone, additionally pass
`--native-feature-profile first-owner-staging-v1` to identity preparation and
desktop auth-helper packaging. This native-only feature profile requires
`--data-mode synthetic`, keeps the operational Clerk identity and app custody,
and enables workspace/team access, AI activity and routines. It explicitly
disables capture, Core navigation, Google/Microsoft connections, Scheduling and
the other connected Beta workflows. The default `operational-beta-v1` profile
still requires the complete feature set and its actual connection inputs.

Use the generated native inputs with the same renderer builders. For the native
composers, omit microphone, capture-upload, Core navigation and provider OAuth
arguments for this profile; their presence is refused. Apple can retain the
existing recovery/capture source overlays for compilation, while
`CosmasConfiguredCapture.enabled` is false. Desktop composition omits the native
capture package and requires the helper's capture setting to be false. No native
capture implementation or authentication boundary changes for this milestone.

A staging candidate remains unsigned and unlaunched. The API must separately
admit `app://cosmas` and `capacitor://localhost` through its existing hosted
transport flags, CORS and Clerk authorized-party settings before native use.
Build completion does not establish that admission, owner enrollment, actual
native sign-in or full operational Beta completion.

Native auth uses the normal Clerk session token, whose custom `aud` claim must
match the configured API audience. Clerk native requests omit `Origin`, so that
token may omit `azp`. The API admits this only for one explicitly enabled native
request origin present in both allowlists; signed issuer, audience, session and
Organization checks remain mandatory. A present `azp` must match that native
origin. Browser/default verification still requires `azp`. JWT templates are
unsuitable here because they cannot include the session-bound `sid` claim.

Use the identity-only preparation command for these client inputs. The broader
`prepare-operational-startup.py` still prepares Core/Scribe/Scheduling service
overlays and is not a limited, non-Scribe staging shortcut. Actual public keys,
organization and API/web/upload origins must be supplied before a connected
build; public health checks do not establish companion API authorization.

Build each native renderer from the retained public `clients` directory emitted
by `scripts/prepare-workspace-identity.mjs` or
`scripts/prepare-operational-startup.py`. Use Node 24 and the existing locked web
and capture-client dependencies. From the repository root:

```sh
node scripts/build-native-renderer.mjs \
  --inputs /absolute/path/to/retained-startup/clients \
  --client desktop --output /absolute/path/to/new-desktop-renderer
node scripts/build-native-renderer.mjs \
  --inputs /absolute/path/to/retained-startup/clients \
  --client apple --output /absolute/path/to/new-apple-renderer
```

Each command consumes that client's `*-identity.json` and `*-build-env.json`,
requires their complete current profile, production-format public identity and
API origin to agree, and verifies both emitted manifests. All profile flags and
normal native transport constraints apply. Ambient `VITE_*` settings are refused;
dotenv files are not loaded. Output must be fresh and separate from the repository
and retained inputs, with an existing parent directory. Failed output retains an
`.incomplete` marker; inspect it before choosing a new output.

Pass `<output>/dist` as `--web-dist` to the existing native composers below.
`native-renderer-build.json` records the selected public input hashes and verified
profile. This command compiles web assets only; it does not generate hosted Nginx
policy, compile native code, package, sign or launch an app. The hosted web build
continues to use `build:beta`. Existing synthetic compositions retain their
previous defaults and cannot consume an operational identity file or silently
inherit its data/storage profile.

For desktop, first compose the current native auth helper with
`prepare-native-auth-proof.py --include-desktop`. Compile and package it with
Python 3.13, an explicit installed Swift toolchain and fresh output directories:

```sh
python3 scripts/build-desktop-auth-helper.py \
  --qualification /absolute/path/to/native-auth-qualification \
  --swift /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift \
  --output /absolute/path/to/new-native-auth-build
python3 scripts/package-desktop-auth-helper.py \
  --qualification /absolute/path/to/native-auth-qualification \
  --products /absolute/path/to/new-native-auth-build/products \
  --compiler-receipt /absolute/path/to/new-native-auth-build/compiler-receipt.json \
  --native-identity-config /absolute/path/to/retained-startup/clients/desktop-identity.json \
  --output /absolute/path/to/CosmasAuth.app
```

The compiler wrapper checks the complete qualification inventory and copies it
into its own output. It builds only `CosmasDesktopAuth` in debug configuration,
using an owned child-process home and owned scratch, package, module and temporary
caches. It disables automatic
dependency resolution and runs Swift under macOS `sandbox-exec` with all network
access denied. The selected Swift executable is explicit; ambient compiler and
package settings are not inherited. This does not install dependencies.

Only a successful invocation with unchanged source and verified executable and
SDK resource hashes produces `compiler-receipt.json`. A failed build retains
`.incomplete` and its log; choose a new output after inspecting the failure.
Keep the entire successful build directory in place through packaging, including
its copied source, scratch products and log. Packaging requires this receipt and
checks its source and product binding before creating the app. The receipt stays
outside the app and is not added to its runtime helper manifest.

The receipt is a local compiler record that detects stale or mixed inputs. It is
not a cryptographic attestation against someone who can rewrite the receipt and
all retained files. A hand-written receipt or historical W90/W92 binary is not
evidence that the wrapper compiled the current qualification. The renderer
receipt above provides no native compiler evidence.

The Mac compiler can emit ad-hoc signatures on its executable and resource
bundle without a signing identity or TeamIdentifier. Packaging preserves those
compiler products; these signatures do not establish release signing,
notarization or distribution acceptance.

Operational packaging uses `--native-identity-config` with no verification
variant. Synthetic packaging instead requires its existing `--verification-variant`
and keeps the SDK disabled; it still requires the compiler receipt.
Pass the same identity file to prepare-desktop-synthetic.py with
--installation-profile beta, the hosted API, required connection/capture origins
and normal Scribe inputs. Package without a verification variant. The app is
com.cosmasos.beta.desktop, helper com.cosmasos.beta.desktop.auth. Its stable
CosmasOS Beta application-support directory and renderer partition are separate
from synthetic installations. Updates retain the same identity; changed backend,
organization, frontend/key or audience is refused without rewriting saved data.

For iPhone, use prepare-apple-synthetic.py with the identity file, hosted workspace,
renewable native capture and renderer recovery. Omit --verification-variant and
--simulator-custody. This stages com.cosmasos.beta.ios for iphoneos only. Its
Keychain group uses the actual provisioning AppIdentifierPrefix; no invented
Simulator team is embedded. The minimum remains iOS17. The generated project
sets no developer team and performs no signing. An unsigned device build can be
compiled with CODE_SIGNING_ALLOWED=NO; it is not installable or distributable.

For the Xcode 27 offline build, retain the exact `Package.resolved` in the
composed project and copy the verified pinned package cache into a fresh
`apple-packages` directory. Use a fresh build root with owned `home`, `tmp`,
`xdg-cache`, `xdg-config`, `module-cache` and `swift-module-cache` directories.
Pass an explicit environment: `HOME` and `CFFIXED_USER_HOME` select that home;
`TMPDIR`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, `CLANG_MODULE_CACHE_PATH` and
`SWIFTPM_MODULECACHE_OVERRIDE` select the corresponding owned directories.
Set `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` and a fixed `PATH`
containing Node 24, that developer directory's `usr/bin`, and system tools.
Do not inherit credentials or package/compiler settings.

With `build_root`, `network_profile` and `environment` set to those explicit
paths and settings, pass this argument list directly to Python's subprocess API:

```python
subprocess.run([
    "/usr/bin/sandbox-exec", "-f", str(network_profile),
    "/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild",
    "-IDEPackageSupportDisableManifestSandbox=YES",
    "-project", str(build_root / "apple-composed/apps/capture/ios/App/App.xcodeproj"),
    "-scheme", "App", "-configuration", "Debug", "-sdk", "iphoneos",
    "-destination", "generic/platform=iOS",
    "-derivedDataPath", str(build_root / "DerivedData"),
    "-clonedSourcePackagesDirPath", str(build_root / "apple-packages"),
    "-packageCachePath", str(build_root / "package-cache"),
    "-disablePackageRepositoryCache", "-disableAutomaticPackageResolution",
    "-skipPackageUpdates", "-onlyUsePackageVersionsFromResolvedFile",
    "-resultBundlePath", str(build_root / "apple-build.xcresult"),
    "CODE_SIGNING_ALLOWED=NO", "CODE_SIGNING_REQUIRED=NO", "DEVELOPMENT_TEAM=",
    "ONLY_ACTIVE_ARCH=NO", "ARCHS=arm64",
    "CLANG_MODULE_CACHE_PATH=" + str(build_root / "module-cache"),
    "OTHER_SWIFT_FLAGS=$(inherited) -Xfrontend -disable-sandbox",
    "build",
], cwd=build_root, env=environment, shell=False, check=True, timeout=1200)
```

The two sandbox controls apply only to this invocation: the single argument
`-IDEPackageSupportDisableManifestSandbox=YES` avoids the nested SwiftPM manifest
sandbox; the single literal build-setting argument
`OTHER_SWIFT_FLAGS=$(inherited) -Xfrontend -disable-sandbox` avoids the nested Swift
macro subprocess sandbox. Do not split this setting into separate arguments or
shell-evaluate `$(inherited)`. The outer sandbox must still deny external network
access while allowing loopback build IPC. Pinned package and signature validation,
resolution/update restrictions and unsigned generic-device compilation remain in
force; no persistent Xcode defaults change. Retain the argv, explicit environment,
log and product inventory as local compilation evidence.

Both paths reuse the pinned Scribe sources and ClerkKit1.5.5. Public production
configuration in an unlaunched development artifact does not establish real login,
device capture/custody, signing, account acceptance or deployment. Those remain
separate operational acceptance steps. Native launches remain deferred.

The current desktop recorder selects the mixed-audio sixty-minute profile before
key binding and uses the private `sourceExtend` RPC on its original native owner.
The running audio helper validates owner/generation, the original monotonic
deadline, short permit lifetime and cumulative chunk budget before extending its
existing engine, mixer and chunker. Stop, source failure and auth retirement fence
further extension. Main-process limits accept already reserved PCM before the
native acknowledgment; unknown outcomes keep the old stop deadline. The Scribe
API candidate must include the matching default-off `continuation` setting.
This source change does not select a replacement for W92 or qualify a device.

The operational Mac package can additionally enter the Scribe-based ASAR and
Electron-fuse packaging step described in desktop-release-packaging.md. This
keeps the native executable outside the archive while protecting its verification
manifest inside it. Signing and distribution follow that step separately.
