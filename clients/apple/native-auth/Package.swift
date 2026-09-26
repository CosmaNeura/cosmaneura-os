// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "CosmasNativeAuth",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "CosmasNativeAuth", targets: ["CosmasNativeAuth"])],
    targets: [
        .target(name: "CosmasNativeAuth"),
        .testTarget(name: "CosmasNativeAuthTests", dependencies: ["CosmasNativeAuth"]),
    ]
)
