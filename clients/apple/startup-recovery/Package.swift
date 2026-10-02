// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "CosmasWorkspaceRecoveryPolicy",
    platforms: [.macOS(.v13), .iOS(.v17)],
    targets: [
        .target(name: "CosmasWorkspaceRecoveryPolicy", path: ".",
                exclude: ["CosmasBridgeViewController.swift", "CosmasWorkspaceViewController.swift", "SceneDelegate.swift", "Tests"],
                sources: ["WorkspaceRecoveryState.swift", "WorkspaceSceneSignalState.swift"]),
        .testTarget(name: "CosmasWorkspaceRecoveryPolicyTests", dependencies: ["CosmasWorkspaceRecoveryPolicy"], path: "Tests"),
    ]
)
