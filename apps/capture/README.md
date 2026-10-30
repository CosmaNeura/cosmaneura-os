# Recovered CosmaBot iPhone release source

This directory preserves the already-composed CosmaBot 0.1.147/1107 iPhone
project and six local native packages. It restores source that was present in
the local release but absent from GitHub main. It was recovered solely from
the existing CosmaBot release; no separate Scribe repository was imported or
modified for this change.

`SOURCE_PROVENANCE.json` records all 383 recovered files, their release and
repository SHA-256 hashes, current tracked equivalents and configuration
redactions. Only `ios/App/App/Info.plist` differs from the original release:
operational identity/OAuth fields are blank and authentication disabled. Team
signing remains unconfigured. Version/build numbers identify the recovered
baseline, not a new qualified build.

## Source owners and dependencies

- App-specific scaffold and Xcode project: `ios/App`.
- Shared auth, recording and queue implementations: authoritative sources in
  repository `clients/apple` and `clients/capture`. Corresponding copies under
  `native-plugins` are frozen composed 1107 evidence. Use the per-file
  `tracked_equivalent` mapping; do not evolve both copies independently.
- Vendored ClerkKit 1.5.5: `native-plugins/cosmas-native-auth/vendor`, with its MIT
  LICENSE and SDK source retained.
- Remote Swift dependency: Capacitor/Cordova 8.5.0, pinned revision
  `4f71d0b979f2f957326f04353eca7604ee937e1e` in Package.resolved.
- Legacy `CosmaneuraScribe*` package names identify the already-consumed generic
  components. Keep their names and attribution; they are not Scribe server code.

All 11 local package edges, 15 target directories, three declared resources and
Xcode source/config paths resolved in the recovery audit. Generated
`ios/App/App/public` is deliberately excluded. No native build ran here.

## Portable composition

`scripts/compose-portable-iphone.py` builds a fresh iPhone project input from
this frozen app scaffold plus the authoritative `clients/apple` and
`clients/capture` implementations. It reads those owners and this scaffold
only. It does not modify this directory, compile, sign, or install.

This directory remains a composed release closure, not the historical raw
source accepted by `scripts/prepare-apple-synthetic.py`. That script still
expects an external snapshot at `ea7f99d0278a05706531ffb1288cb1df7acf507b`.
Do not point it at this folder, fabricate that commit, or fetch/modify a
separate Scribe repository.

## What a Mac must still do before a qualified install

The portable composition is not a qualified install. Regenerate the web
renderer using `scripts/build-native-renderer.mjs` (dependencies come from
`web/package.json`), select explicit retained public native identity/profile
inputs, and populate fresh generated app assets before native compilation.
Then compile, sign, and install current source against the same reviewed
commit. Review required-reason API privacy declarations: app code uses
`ProcessInfo.systemUptime`, while this recovered app has no app-level
`PrivacyInfo.xcprivacy`; existing dependency manifests do not establish app
API coverage. Do not assume prior TestFlight processing completes that
release gate. A Linux agent can prepare the project inputs; Apple
compilation and signing require the Mac.

Exact prior artifacts and public inputs are retained privately in the local
workspace's ignored `.local-release/` and the final October 29 ZIP. This source
recovery has not compiled, signed, installed, launched or deployed a new app.
