// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "CosmaneuraLazyMicEngineTests",
  platforms: [.macOS(.v13), .iOS(.v17)],
  dependencies: [
    .package(path: "../ios-pcm-capture")
  ],
  targets: [
    .testTarget(
      name: "CosmaneuraLazyMicEngineTests",
      dependencies: [
        .product(name: "CosmaneuraIOSAVFoundationDriver", package: "ios-pcm-capture"),
        .product(name: "CosmaneuraIOSPCMCore", package: "ios-pcm-capture")
      ]
    )
  ]
)
