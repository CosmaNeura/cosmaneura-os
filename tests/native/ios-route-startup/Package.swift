// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "CosmaBotIOSRouteStartupTests",
  platforms: [.macOS(.v13)],
  dependencies: [
    .package(path: "../../../clients/capture/native-configured/ios-pcm-capture")
  ],
  targets: [
    .testTarget(
      name: "CosmaBotIOSRouteStartupTests",
      dependencies: [
        .product(name: "CosmaneuraIOSAVFoundationDriver", package: "ios-pcm-capture"),
        .product(name: "CosmaneuraIOSPCMCore", package: "ios-pcm-capture")
      ]
    )
  ]
)
