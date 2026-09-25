import Foundation

/// A generation belongs to one bridge, never to a retry of its document.
struct WorkspaceRecoveryState {
    enum Phase: Equatable { case opening, active, failed }
    enum Signal: String { case ready, failed }
    enum StopState: Equatable { case unchecked, checking, blocked, idle }

    let generation: String
    private(set) var phase: Phase = .opening
    private(set) var stopState: StopState = .unchecked
    private(set) var remainingForegroundSeconds: TimeInterval
    private var activeSince: TimeInterval?

    init(generation: String = UUID().uuidString, timeout: TimeInterval = 45) {
        self.generation = generation
        remainingForegroundSeconds = timeout
    }

    mutating func receive(_ signal: Signal, generation: String,
                          mainFrame: Bool, sameOrigin: Bool) -> Bool {
        guard mainFrame, sameOrigin, generation == self.generation, phase != .failed else { return false }
        switch signal {
        case .ready:
            guard phase == .opening else { return false }
            phase = .active
            activeSince = nil
        case .failed: fail()
        }
        return true
    }

    @discardableResult mutating func fail() -> Bool {
        guard phase != .failed else { return false }
        phase = .failed
        activeSince = nil
        return true
    }

    /// Called on both activity transitions and timer ticks; background time is excluded.
    mutating func tick(now: TimeInterval, sceneActive: Bool) -> Bool {
        guard phase == .opening else { return false }
        if let previous = activeSince { remainingForegroundSeconds -= max(0, now - previous) }
        activeSince = sceneActive ? now : nil
        if remainingForegroundSeconds <= 0 { return fail() }
        return false
    }

    mutating func beginStopCheck() -> Bool {
        guard phase == .failed, stopState != .checking else { return false }
        stopState = .checking
        return true
    }

    mutating func finishStopCheck(idle: Bool) {
        guard phase == .failed, stopState == .checking else { return }
        stopState = idle ? .idle : .blocked
    }

    var canReopen: Bool { phase == .failed && stopState == .idle }
}
