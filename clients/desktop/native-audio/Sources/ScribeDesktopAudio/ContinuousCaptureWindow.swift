import CoreFoundation
import Foundation

/// Auth-helper metadata carried by the dedicated parent pipe. This can only
/// extend an already active process; it is never a start command or owner proof.
struct ContinuousCapturePermit: Sendable, Equatable {
    let runID: String
    let generation: Int
    let expiresAt: Int
    let previousCaptureAuthorizedUntil: Int
    let captureAuthorizedUntil: Int
    let maximumChunks: Int

    init(_ raw: Any?) throws {
        let value = try captureObject(raw, keys: ["runId", "generation", "expiresAt",
            "previousCaptureAuthorizedUntil", "captureAuthorizedUntil", "maximumChunks"])
        runID = try captureUUID(value["runId"])
        generation = try captureInteger(value["generation"], maximum: 2_147_483_647)
        expiresAt = try captureInteger(value["expiresAt"])
        previousCaptureAuthorizedUntil = try captureInteger(value["previousCaptureAuthorizedUntil"])
        captureAuthorizedUntil = try captureInteger(value["captureAuthorizedUntil"])
        maximumChunks = try captureInteger(value["maximumChunks"], maximum: 360)
    }
    var wireValue: [String: Any] {
        ["runId": runID, "generation": generation, "expiresAt": expiresAt,
         "previousCaptureAuthorizedUntil": previousCaptureAuthorizedUntil,
         "captureAuthorizedUntil": captureAuthorizedUntil, "maximumChunks": maximumChunks]
    }
}

struct ContinuousCaptureWindow: Sendable {
    let runID: String
    let hardMaximumChunks: Int
    let wallAnchor: Int
    let clockAnchor: ContinuousClock.Instant
    let hardDeadline: ContinuousClock.Instant
    private(set) var generation: Int
    private(set) var captureAuthorizedUntil: Int
    private(set) var maximumChunks: Int
    private(set) var deadline: ContinuousClock.Instant
    private(set) var permitDeadline: ContinuousClock.Instant?
    private var latest: ContinuousCapturePermit?

    init(_ raw: Any?, maximumFrames: Int, now: Date = Date(), clock: ContinuousClock.Instant = .now) throws {
        let value = try captureObject(raw, keys: ["runId", "generation", "hardMaximumChunks", "maximumChunks", "captureAuthorizedUntil"])
        runID = try captureUUID(value["runId"])
        generation = try captureInteger(value["generation"], maximum: 2_147_483_647)
        hardMaximumChunks = try captureInteger(value["hardMaximumChunks"], maximum: 360)
        maximumChunks = try captureInteger(value["maximumChunks"], maximum: hardMaximumChunks)
        captureAuthorizedUntil = try captureInteger(value["captureAuthorizedUntil"])
        wallAnchor = Int(now.timeIntervalSince1970 * 1000); clockAnchor = clock
        hardDeadline = clock.advanced(by: .seconds(hardMaximumChunks * 10))
        guard captureAuthorizedUntil > wallAnchor, maximumFrames > 0,
              maximumFrames <= maximumChunks * 160_000 else { throw DesktopAudioFailure.invalidAudio }
        deadline = min(hardDeadline, clock.advanced(by: .milliseconds(captureAuthorizedUntil - wallAnchor)))
    }

    /// An exact replay preserves the original monotonic deadline. Wall-clock
    /// changes cannot replenish lifetime, and an expired owner cannot revive.
    func advanced(_ permit: ContinuousCapturePermit, now: Date = Date(),
                  clock: ContinuousClock.Instant = .now) throws -> ContinuousCaptureWindow {
        let wall = Int(now.timeIntervalSince1970 * 1000)
        guard deadline > clock, captureAuthorizedUntil > wall, permit.runID == runID,
              permit.expiresAt > wall else { throw DesktopAudioFailure.windowExpired }
        if latest == permit {
            guard let permitDeadline, permitDeadline > clock else { throw DesktopAudioFailure.windowExpired }
            return self
        }
        guard permit.generation == generation + 1,
              abs(permit.previousCaptureAuthorizedUntil - captureAuthorizedUntil) <= 1,
              permit.expiresAt <= captureAuthorizedUntil,
              permit.captureAuthorizedUntil > captureAuthorizedUntil,
              permit.maximumChunks > maximumChunks, permit.maximumChunks <= hardMaximumChunks else {
            throw DesktopAudioFailure.invalidAudio
        }
        let nextDeadline = min(hardDeadline,
            min(clockAnchor.advanced(by: .milliseconds(permit.captureAuthorizedUntil - wallAnchor)),
                clock.advanced(by: .milliseconds(permit.captureAuthorizedUntil - wall))))
        let permissionDeadline = min(clockAnchor.advanced(by: .milliseconds(permit.expiresAt - wallAnchor)),
            clock.advanced(by: .milliseconds(permit.expiresAt - wall)))
        guard nextDeadline > deadline, permissionDeadline > clock else { throw DesktopAudioFailure.windowExpired }
        var next = self
        next.generation = permit.generation; next.captureAuthorizedUntil = permit.captureAuthorizedUntil
        next.maximumChunks = permit.maximumChunks; next.deadline = nextDeadline; next.latest = permit
        next.permitDeadline = permissionDeadline
        return next
    }
}

private func captureObject(_ raw: Any?, keys: Set<String>) throws -> [String: Any] {
    guard let value = raw as? [String: Any], Set(value.keys) == keys else { throw DesktopAudioFailure.invalidAudio }
    return value
}
private func captureUUID(_ raw: Any?) throws -> String {
    guard let value = raw as? String, UUID(uuidString: value)?.uuidString.lowercased() == value else {
        throw DesktopAudioFailure.invalidAudio
    }
    return value
}
private func captureInteger(_ raw: Any?, maximum: Int = 9_007_199_254_740_991) throws -> Int {
    guard let value = raw as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
          value.doubleValue >= 1, value.doubleValue <= Double(maximum),
          value.doubleValue.rounded(.down) == value.doubleValue else { throw DesktopAudioFailure.invalidAudio }
    return value.intValue
}
