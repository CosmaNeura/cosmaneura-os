// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "CosmaneuraNativeRecordingPCM",
  platforms: [.iOS(.v17), .macOS(.v14)],
  products: [.library(name: "CosmaneuraNativeRecordingPCM", targets: ["CosmaneuraNativeRecordingPCM"])],
  dependencies: [
    .package(path: "../native-recording"),
    .package(path: "../ios-pcm-capture"),
  ],
  targets: [
    .target(name: "CosmaneuraNativeRecordingPCM", dependencies: [
      .product(name: "CosmaneuraNativeRecording", package: "native-recording"),
      .product(name: "CosmaneuraIOSPCMCore", package: "ios-pcm-capture"),
      .product(name: "CosmaneuraIOSAVFoundationDriver", package: "ios-pcm-capture"),
    ]),
    .testTarget(name: "CosmaneuraNativeRecordingPCMTests", dependencies: [
      "CosmaneuraNativeRecordingPCM",
      .product(name: "CosmaneuraIOSPCMCore", package: "ios-pcm-capture"),
      .product(name: "CosmaneuraIOSPCMBridgeCore", package: "ios-pcm-capture"),
      .product(name: "CosmaneuraIOSAVFoundationDriver", package: "ios-pcm-capture"),
    ]),
  ]
)
