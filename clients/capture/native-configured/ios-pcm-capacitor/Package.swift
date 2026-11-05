// swift-tools-version: 6.0

import PackageDescription

let package = Package(
  name: "CosmaneuraIOSPCMCapacitor",
  platforms: [
    .iOS(.v17),
    .macOS(.v13),
  ],
  products: [
    .library(
      name: "CosmaneuraIOSPCMCapacitor",
      targets: ["CosmaneuraIOSPCMCapacitor"]
    ),
    .library(
      name: "CosmaneuraScribeCapacitorIosPcm",
      targets: ["CosmaneuraIOSPCMCapacitor"]
    )
  ],
  dependencies: [
    .package(name: "CosmasNativeAuthQualification", path: "../cosmas-native-auth"),
    .package(path: "../ios-pcm-capture"),
    .package(
      name: "capacitor-swift-pm",
      path: "../../../apple/vendor/capacitor-swift-pm-8.5.0"
    ),
  ],
  targets: [
    .target(
      name: "CosmaneuraIOSPCMCapacitorTransport",
      dependencies: [
        .product(name: "CosmaneuraIOSPCMBridgeCore", package: "ios-pcm-capture"),
        .product(name: "CosmaneuraIOSPCMCore", package: "ios-pcm-capture")
      ]
    ),
    .target(
      name: "CosmaneuraIOSPCMCapacitor",
      dependencies: [
        .product(name: "CosmasNativeAuth", package: "CosmasNativeAuthQualification"),
        "CosmaneuraIOSPCMCapacitorTransport",
        .product(name: "CosmaneuraIOSPCMCore", package: "ios-pcm-capture"),
        .product(
          name: "Capacitor",
          package: "capacitor-swift-pm",
          condition: .when(platforms: [.iOS])
        ),
        .product(
          name: "Cordova",
          package: "capacitor-swift-pm",
          condition: .when(platforms: [.iOS])
        ),
      ]
    ),
  ]
)
