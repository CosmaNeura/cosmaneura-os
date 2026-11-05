# Owned Capacitor 8.5.0 Swift PM mirror

Exact Capacitor and Cordova XCFrameworks from
`ionic-team/capacitor-swift-pm` 8.5.0
(`4f71d0b979f2f957326f04353eca7604ee937e1e`), retained under
`clients/apple` so iPhone composition does not download remote binary zips.

`SOURCE_MANIFEST.json` records the upstream release asset SHA-256 digests that
were verified before unpacking. `Package.swift` exposes local `binaryTarget`
paths only.

`scripts/compose-portable-iphone.py` copies this package into the composed
`apps/capture/native-plugins/capacitor-swift-pm` tree and rewrites CapApp-SPM
and plugin manifests to the local path. Offline `xcodebuild` must keep
`-disableAutomaticPackageResolution` and must not reintroduce the GitHub URL.
