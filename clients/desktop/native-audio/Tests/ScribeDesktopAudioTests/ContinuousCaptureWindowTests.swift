import Foundation
import Testing
@testable import ScribeDesktopAudio

private let run = "10000000-0000-4000-8000-000000000001"
private let wall = Date(timeIntervalSince1970: 1_800_000_000)
private let stamp = 1_800_000_000_000
private func owner(_ maximum: Int = 360) -> [String: Any] {
    ["runId": run, "generation": 1, "hardMaximumChunks": maximum,
     "maximumChunks": 89, "captureAuthorizedUntil": stamp + 900_000]
}
private func extensionValue() -> [String: Any] {
    ["runId": run, "generation": 2, "expiresAt": stamp + 850_000,
     "previousCaptureAuthorizedUntil": stamp + 900_000,
     "captureAuthorizedUntil": stamp + 1_740_000, "maximumChunks": 174]
}

@Test func nativeWindowExtendsSameOwnerAndReplayNeverRefreshesLifetime() throws {
    let clock = ContinuousClock.now
    let initial = try ContinuousCaptureWindow(owner(), maximumFrames: 89 * 160_000, now: wall, clock: clock)
    let permit = try ContinuousCapturePermit(extensionValue())
    let next = try initial.advanced(permit, now: wall.addingTimeInterval(840), clock: clock.advanced(by: .seconds(840)))
    #expect(next.generation == 2 && next.maximumChunks == 174)
    let replay = try next.advanced(permit, now: wall.addingTimeInterval(845), clock: clock.advanced(by: .seconds(845)))
    #expect(replay.deadline == next.deadline)
    #expect(throws: DesktopAudioFailure.self) {
        try next.advanced(permit, now: wall.addingTimeInterval(851), clock: clock.advanced(by: .seconds(851)))
    }
}

@Test func nativeWindowRejectsForeignSkippedChangedExpiredAndOverBudgetExtensions() throws {
    let clock = ContinuousClock.now
    let initial = try ContinuousCaptureWindow(owner(180), maximumFrames: 89 * 160_000, now: wall, clock: clock)
    for (key, value) in [("runId", UUID().uuidString.lowercased() as Any), ("generation", 3),
                         ("maximumChunks", 181), ("maximumChunks", 89),
                         ("previousCaptureAuthorizedUntil", stamp + 901_000), ("expiresAt", stamp + 900_001)] {
        var raw = extensionValue(); raw[key] = value
        #expect(throws: DesktopAudioFailure.self) {
            try initial.advanced(ContinuousCapturePermit(raw), now: wall.addingTimeInterval(840), clock: clock.advanced(by: .seconds(840)))
        }
    }
    // Rolling the wall clock back cannot resurrect the elapsed physical owner.
    #expect(throws: DesktopAudioFailure.self) {
        try initial.advanced(ContinuousCapturePermit(extensionValue()), now: wall, clock: clock.advanced(by: .seconds(901)))
    }
    #expect(throws: DesktopAudioFailure.self) {
        try initial.advanced(ContinuousCapturePermit(extensionValue()), now: wall, clock: clock.advanced(by: .seconds(851)))
    }
    var malformed = extensionValue(); malformed["generation"] = true
    #expect(throws: DesktopAudioFailure.self) { try ContinuousCapturePermit(malformed) }
}

@Test func nativeWindowBoundsDurationDespiteWallClockRollback() throws {
    let clock = ContinuousClock.now
    let initial = try ContinuousCaptureWindow(owner(), maximumFrames: 89 * 160_000, now: wall, clock: clock)
    let next = try initial.advanced(ContinuousCapturePermit(extensionValue()), now: wall,
                                    clock: clock.advanced(by: .seconds(840)))
    #expect(next.deadline == clock.advanced(by: .seconds(1740)))
}
