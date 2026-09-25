# Operational native build inputs

The existing Scribe-based composers now support an explicit operational identity.
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

Build the corresponding complete web bundle with data mode authorized_beta and
the same API origin. All30 feature flags and normal native transport constraints
apply. Existing synthetic builds retain their previous defaults and cannot consume
an operational identity file or silently inherit its data/storage profile.

For desktop, first compose and compile the current native auth helper with
prepare-native-auth-proof.py. Package that fresh product with
package-desktop-auth-helper.py --native-identity-config (no verification variant).
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
