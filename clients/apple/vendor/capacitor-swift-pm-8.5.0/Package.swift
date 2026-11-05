// swift-tools-version:5.3
import PackageDescription

// Owned mirror of ionic-team/capacitor-swift-pm@8.5.0
// (revision 4f71d0b979f2f957326f04353eca7604ee937e1e).
// Local path binary targets replace the remote checksummed zip downloads so an
// offline iPhone composition does not fetch opaque vendor blobs at build time.
let package = Package(
    name: "capacitor-swift-pm",
    products: [
        .library(
            name: "Capacitor",
            targets: ["Capacitor"]
        ),
        .library(
            name: "Cordova",
            targets: ["Cordova"]
        )
    ],
    dependencies: [],
    targets: [
        .binaryTarget(
            name: "Capacitor",
            path: "Capacitor.xcframework"
        ),
        .binaryTarget(
            name: "Cordova",
            path: "Cordova.xcframework"
        )
    ]
)
