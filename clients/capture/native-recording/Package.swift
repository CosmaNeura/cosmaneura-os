// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "CosmaneuraNativeRecording",
  platforms: [.iOS(.v17), .macOS(.v14)],
  products: [.library(name: "CosmaneuraNativeRecording", targets: ["CosmaneuraNativeRecording"])],
  targets: [
    .target(name: "CosmaneuraNativeRecording"),
    .testTarget(name: "CosmaneuraNativeRecordingTests", dependencies: ["CosmaneuraNativeRecording"]),
  ]
)
