// swift-tools-version: 5.9
import PackageDescription

// DO NOT MODIFY THIS FILE - managed by Capacitor CLI commands
let package = Package(
    name: "CapApp-SPM",
    platforms: [.iOS(.v17)],
    products: [
        .library(
            name: "CapApp-SPM",
            targets: ["CapApp-SPM"])
    ],
    dependencies: [
        .package(name: "CosmasNativeAuthQualification", path: "../../../native-plugins/cosmas-native-auth"),
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", exact: "8.5.0"),
        .package(name: "CosmaneuraScribeCapacitorIosPcm", path: "../../../native-plugins/ios-pcm-capacitor"),
        .package(name: "CosmaneuraScribeCapacitorSecureQueue", path: "../../../native-plugins/secure-queue")
    ],
    targets: [
        .target(
            name: "CapApp-SPM",
            dependencies: [
                .product(name: "CosmasWorkspaceAuthPlugin", package: "CosmasNativeAuthQualification"),
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm"),
                .product(name: "CosmaneuraScribeCapacitorIosPcm", package: "CosmaneuraScribeCapacitorIosPcm"),
                .product(name: "CosmaneuraScribeCapacitorSecureQueue", package: "CosmaneuraScribeCapacitorSecureQueue")
            ]
        )
    ]
)
