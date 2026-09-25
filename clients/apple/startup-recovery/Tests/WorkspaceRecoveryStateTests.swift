import XCTest
@testable import CosmasWorkspaceRecoveryPolicy

final class WorkspaceRecoveryStateTests: XCTestCase {
    func testOnlyExpectedMainFrameMayDeclareReadiness() {
        var state = WorkspaceRecoveryState(generation: "current")
        XCTAssertFalse(state.receive(.ready, generation: "old", mainFrame: true, sameOrigin: true))
        XCTAssertFalse(state.receive(.ready, generation: "current", mainFrame: false, sameOrigin: true))
        XCTAssertFalse(state.receive(.ready, generation: "current", mainFrame: true, sameOrigin: false))
        XCTAssertEqual(state.phase, .opening)
        XCTAssertTrue(state.receive(.ready, generation: "current", mainFrame: true, sameOrigin: true))
        XCTAssertEqual(state.phase, .active)
    }

    func testFailureAfterReadinessCannotBeUndoneByLateReady() {
        var state = WorkspaceRecoveryState(generation: "current")
        XCTAssertTrue(state.receive(.ready, generation: "current", mainFrame: true, sameOrigin: true))
        XCTAssertTrue(state.receive(.failed, generation: "current", mainFrame: true, sameOrigin: true))
        XCTAssertFalse(state.receive(.ready, generation: "current", mainFrame: true, sameOrigin: true))
        XCTAssertFalse(state.fail())
        XCTAssertEqual(state.phase, .failed)
        XCTAssertFalse(state.canReopen)
    }

    func testTimeoutCountsOnlyForegroundIntervalsIncludingActivityEdges() {
        var state = WorkspaceRecoveryState(timeout: 45)
        XCTAssertFalse(state.tick(now: 100, sceneActive: true))
        XCTAssertFalse(state.tick(now: 110, sceneActive: false))
        XCTAssertEqual(state.remainingForegroundSeconds, 35)
        XCTAssertFalse(state.tick(now: 1000, sceneActive: false))
        XCTAssertFalse(state.tick(now: 2000, sceneActive: true))
        XCTAssertFalse(state.tick(now: 2034, sceneActive: true))
        XCTAssertTrue(state.tick(now: 2035, sceneActive: true))
        XCTAssertEqual(state.phase, .failed)
        XCTAssertFalse(state.tick(now: 3000, sceneActive: true))
    }

    func testActiveWorkspaceDoesNotExpire() {
        var state = WorkspaceRecoveryState(generation: "current", timeout: 1)
        _ = state.tick(now: 100, sceneActive: true)
        _ = state.receive(.ready, generation: "current", mainFrame: true, sameOrigin: true)
        XCTAssertFalse(state.tick(now: 1000, sceneActive: true))
        XCTAssertEqual(state.phase, .active)
        XCTAssertFalse(state.beginStopCheck())
    }

    func testReopenRemainsBlockedDuringStopFailureAndConcurrentRetry() {
        var state = WorkspaceRecoveryState()
        state.finishStopCheck(idle: true)
        XCTAssertFalse(state.canReopen)
        _ = state.fail()
        XCTAssertTrue(state.beginStopCheck())
        XCTAssertFalse(state.beginStopCheck())
        XCTAssertFalse(state.canReopen)
        state.finishStopCheck(idle: false)
        XCTAssertEqual(state.stopState, .blocked)
        XCTAssertFalse(state.canReopen)
        XCTAssertTrue(state.beginStopCheck())
        state.finishStopCheck(idle: true)
        XCTAssertTrue(state.canReopen)
        // A fresh check revokes a previously successful result while work is pending.
        XCTAssertTrue(state.beginStopCheck())
        XCTAssertFalse(state.canReopen)
        state.finishStopCheck(idle: false)
        XCTAssertFalse(state.canReopen)
    }

    func testNewBridgeDoesNotInheritReadinessOrStopProof() {
        var old = WorkspaceRecoveryState()
        _ = old.fail()
        _ = old.beginStopCheck()
        old.finishStopCheck(idle: true)
        var replacement = WorkspaceRecoveryState()
        XCTAssertNotEqual(old.generation, replacement.generation)
        XCTAssertFalse(replacement.receive(.ready, generation: old.generation, mainFrame: true, sameOrigin: true))
        XCTAssertEqual(replacement.phase, .opening)
        XCTAssertEqual(replacement.stopState, .unchecked)
        XCTAssertFalse(replacement.canReopen)
    }
}
