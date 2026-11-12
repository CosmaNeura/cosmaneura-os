// swift-tools-version:5.3
import PackageDescription

// Owned mirror of ionic-team/capacitor-swift-pm@8.5.1
// (revision 6afa7424fd2fcd8ca1e577478e8a00af284b7e82).
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
