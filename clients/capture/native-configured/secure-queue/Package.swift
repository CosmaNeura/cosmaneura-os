// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "CosmaneuraSecureQueue",
    platforms: [.iOS(.v17)],
    products: [
        .library(
            name: "CosmaneuraScribeCapacitorSecureQueue",
            targets: ["CosmaneuraSecureQueue"]
        ),
    ],
    dependencies: [
        .package(path: "../native-recording"),
        .package(
            name: "capacitor-swift-pm",
            path: "../../../apple/vendor/capacitor-swift-pm-8.5.0"
        ),
    ],
    targets: [
        .target(
            name: "CosmaneuraSecureQueue",
            dependencies: [
                .product(name: "CosmaneuraNativeRecording", package: "native-recording"),
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm"),
            ],
            path: "ios/Sources/CosmaneuraSecureQueue",
            resources: [.process("PrivacyInfo.xcprivacy")]
        ),
    ]
)
