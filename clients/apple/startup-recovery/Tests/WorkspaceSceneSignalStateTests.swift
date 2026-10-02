import XCTest
@testable import CosmasWorkspaceRecoveryPolicy

final class WorkspaceSceneSignalStateTests: XCTestCase {
    private let generation = "00000000-0000-4000-8000-000000000001"

    private func ready(_ state: inout WorkspaceSceneSignalState) {
        state.ready(generation: generation, mainFrame: true, sameOrigin: true)
    }

    func testInitialActiveSceneWaitsForReadyThenEmitsOnce() {
        var state = WorkspaceSceneSignalState(generation: generation)
        state.setSceneActive(true)
        XCTAssertNil(state.pending)
        ready(&state)
        XCTAssertEqual(state.pending, true)
        state.didDispatch(true, generation: generation)
        XCTAssertNil(state.pending)
        state.setSceneActive(true)
        ready(&state)
        XCTAssertNil(state.pending)
    }

    func testInitialInactiveSceneEmitsFalseAfterReady() {
        var state = WorkspaceSceneSignalState(generation: generation)
        XCTAssertNil(state.pending)
        ready(&state)
        XCTAssertEqual(state.pending, false)
        state.didDispatch(false, generation: generation)
        XCTAssertNil(state.pending)
    }

    func testInactiveAndForegroundTransitionsAreDistinct() {
        var state = WorkspaceSceneSignalState(generation: generation)
        state.setSceneActive(true)
        ready(&state)
        state.didDispatch(true, generation: generation)
        state.setSceneActive(false)
        XCTAssertEqual(state.pending, false)
        state.didDispatch(false, generation: generation)
        state.setSceneActive(false)
        XCTAssertNil(state.pending)
        state.setSceneActive(true)
        XCTAssertEqual(state.pending, true)
    }

    func testForeignGenerationFrameOrOriginCannotMarkReady() {
        var state = WorkspaceSceneSignalState(generation: generation)
        state.setSceneActive(true)
        state.ready(generation: "old", mainFrame: true, sameOrigin: true)
        state.ready(generation: generation, mainFrame: false, sameOrigin: true)
        state.ready(generation: generation, mainFrame: true, sameOrigin: false)
        XCTAssertFalse(state.isReady)
        XCTAssertNil(state.pending)
    }

    func testFailedSchedulingDoesNotConsumePendingState() {
        var state = WorkspaceSceneSignalState(generation: generation)
        state.setSceneActive(true)
        ready(&state)
        // No live web view exists yet: caller does not acknowledge dispatch.
        XCTAssertEqual(state.pending, true)
        state.didDispatch(true, generation: "old")
        state.didDispatch(false, generation: generation)
        XCTAssertEqual(state.pending, true)
        state.didDispatch(true, generation: generation)
        XCTAssertNil(state.pending)
    }

    func testQuarantineOrDisconnectClosesGenerationPermanently() {
        var state = WorkspaceSceneSignalState(generation: generation)
        state.setSceneActive(true)
        ready(&state)
        state.close()
        state.setSceneActive(false)
        ready(&state)
        state.didDispatch(true, generation: generation)
        XCTAssertTrue(state.isClosed)
        XCTAssertNil(state.pending)
    }

    func testCloseBeforeInitialReadyCannotReopen() {
        var state = WorkspaceSceneSignalState(generation: generation)
        state.close()
        ready(&state)
        XCTAssertFalse(state.isReady)
        XCTAssertNil(state.pending)
    }

    func testReplacementNeedsOwnReadyAndDoesNotInheritDispatch() {
        var old = WorkspaceSceneSignalState(generation: generation)
        old.setSceneActive(true)
        ready(&old)
        old.didDispatch(true, generation: generation)
        old.close()
        let replacementGeneration = "00000000-0000-4000-8000-000000000002"
        var replacement = WorkspaceSceneSignalState(generation: replacementGeneration)
        replacement.setSceneActive(true)
        replacement.ready(generation: generation, mainFrame: true, sameOrigin: true)
        XCTAssertNil(replacement.pending)
        replacement.ready(generation: replacementGeneration, mainFrame: true, sameOrigin: true)
        XCTAssertEqual(replacement.pending, true)
        XCTAssertNil(old.pending)
    }

    func testScriptRejectsUserInputAndContainsOnlySceneHint() {
        XCTAssertNil(WorkspaceSceneSignalState.script(generation: "'; privateToken()", active: true))
        XCTAssertNil(WorkspaceSceneSignalState.script(generation: "", active: false))
        let script = WorkspaceSceneSignalState.script(generation: generation, active: true)
        XCTAssertNotNil(script)
        XCTAssertTrue(script!.contains("cosmas:native-scene-state"))
        XCTAssertTrue(script!.contains("window.__cosmasWorkspaceGeneration !== detail.generation"))
        XCTAssertFalse(script!.contains("fetch("))
        XCTAssertFalse(script!.contains("getToken"))
    }
}
