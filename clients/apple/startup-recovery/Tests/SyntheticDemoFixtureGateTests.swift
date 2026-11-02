import XCTest
@testable import CosmasWorkspaceRecoveryPolicy

final class SyntheticDemoFixtureGateTests: XCTestCase {
    func testDemoFixtureIsDebugOnlyAndSyntheticScoped() {
        #if DEBUG
        XCTAssertTrue(
            SyntheticDemoFixtureGate.isCompiledIntoThisBinary,
            "DEBUG builds must compile the synthetic demo fixture gate in"
        )
        XCTAssertTrue(SyntheticDemoFixtureGate.shouldPresent(bundleIdentifier: "com.cosmasos.synthetic"))
        XCTAssertFalse(SyntheticDemoFixtureGate.shouldPresent(bundleIdentifier: "com.cosmasos.beta.ios"))
        XCTAssertFalse(SyntheticDemoFixtureGate.shouldPresent(bundleIdentifier: nil))
        #else
        XCTAssertFalse(
            SyntheticDemoFixtureGate.isCompiledIntoThisBinary,
            "Release builds must compile the synthetic demo fixture out"
        )
        XCTAssertFalse(SyntheticDemoFixtureGate.shouldPresent(bundleIdentifier: "com.cosmasos.synthetic"))
        XCTAssertFalse(SyntheticDemoFixtureGate.shouldPresent(bundleIdentifier: "com.cosmasos.beta.ios"))
        #endif
    }

    func testWorkspaceViewControllerWrapsDemoSurfaceInDebugGuard() throws {
        // Source audit: CosmasWorkspaceViewController is App-composed, not in this
        // package. Prove the owned source keeps the demo surface behind #if DEBUG
        // so Release/TestFlight cannot reach it even if a future call site regresses.
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // Tests/
            .deletingLastPathComponent() // startup-recovery/
        let source = try String(contentsOf: root.appendingPathComponent("CosmasWorkspaceViewController.swift"), encoding: .utf8)
        XCTAssertTrue(source.contains("#if DEBUG\n        if CosmasSyntheticDemoSurface.isEnabled"),
                      "early demo return must be behind #if DEBUG")
        XCTAssertTrue(source.contains("CosmasSyntheticDemoSurface"), "demo surface type must exist under DEBUG")
        XCTAssertTrue(
            source.contains("Bundle.main.bundleIdentifier == \"com.cosmasos.synthetic\""),
            "demo surface must stay scoped to the synthetic Simulator bundle"
        )
        // Class body itself is also DEBUG-only; Release keeps a stub enum that is never presented.
        XCTAssertTrue(source.contains("#if DEBUG\n/// Debug + `com.cosmasos.synthetic` only"))
        XCTAssertTrue(source.contains("static let isCompiledIntoThisBinary = false"))
    }
}
