import Foundation

public struct NativeCapturePermit: Sendable {
    public let runID: String
    public let startExpiresAt: Date
    public let captureExpiresAt: Date
    public let generation: Int
    public let hardMaximumChunks: Int

    public init(runID: String, startExpiresAt: Date, captureExpiresAt: Date,
                generation: Int = 1, hardMaximumChunks: Int = 360) throws {
        guard UUID(uuidString: runID)?.uuidString.lowercased() == runID,
              startExpiresAt > Date(), captureExpiresAt >= startExpiresAt,
              generation > 0, generation < 9_007_199_254_740_991,
              (1...360).contains(hardMaximumChunks) else {
            throw NativeAuthError.unavailable
        }
        self.runID = runID; self.startExpiresAt = startExpiresAt
        self.captureExpiresAt = captureExpiresAt
        self.generation = generation; self.hardMaximumChunks = hardMaximumChunks
    }
}

/// Untrusted renewal metadata. Only a native owner can exchange it for a permit.
public struct NativeCaptureExtensionRequest: Equatable, Sendable {
    public let leaseReceiptID: UUID
    public let leaseGeneration: Int
    public let captureAuthorizedUntil: String
    public let reservationBatchID: UUID
    public let firstSequenceNumber: Int
    public let reservationCount: Int

    public init(leaseReceiptID: UUID, leaseGeneration: Int, captureAuthorizedUntil: String,
                reservationBatchID: UUID, firstSequenceNumber: Int, reservationCount: Int) throws {
        guard leaseGeneration > 1, leaseGeneration < 9_007_199_254_740_991,
              (1...359).contains(firstSequenceNumber), (1...90).contains(reservationCount),
              firstSequenceNumber + reservationCount <= 360,
              captureAuthorizedUntil.utf8.count <= 40 else { throw NativeAuthError.unavailable }
        self.leaseReceiptID = leaseReceiptID; self.leaseGeneration = leaseGeneration
        self.captureAuthorizedUntil = captureAuthorizedUntil; self.reservationBatchID = reservationBatchID
        self.firstSequenceNumber = firstSequenceNumber; self.reservationCount = reservationCount
    }
}

/// Native-only result; cannot authorize starting another source.
public struct NativeCaptureExtensionPermit: Sendable {
    public let runID: String
    public let generation: Int
    public let expiresAt: Date
    public let previousCaptureExpiresAt: Date
    public let captureExpiresAt: Date
    public let maximumChunks: Int

    public init(runID: String, generation: Int, expiresAt: Date, previousCaptureExpiresAt: Date,
                captureExpiresAt: Date, maximumChunks: Int) throws {
        guard UUID(uuidString: runID)?.uuidString.lowercased() == runID,
              generation > 1, generation < 9_007_199_254_740_991,
              expiresAt > Date(), expiresAt <= previousCaptureExpiresAt,
              captureExpiresAt > previousCaptureExpiresAt, (1...360).contains(maximumChunks) else {
            throw NativeAuthError.unavailable
        }
        self.runID = runID; self.generation = generation; self.expiresAt = expiresAt
        self.previousCaptureExpiresAt = previousCaptureExpiresAt
        self.captureExpiresAt = captureExpiresAt; self.maximumChunks = maximumChunks
    }
}

/// The standalone native microphone and authenticated provider bridge share this
/// in-process gate. JavaScript can neither install a handler nor supply a permit.
@MainActor public enum NativeCaptureStartGate {
    public enum Consumer { case renderer, nativeEncryptedMicrophone }
    private static var owner: UUID?
    private static var consumer: Consumer = .renderer
    private static var nativeIdle: (@MainActor () -> Bool)?
    private static var authorize: (@MainActor () async throws -> NativeCapturePermit)?
    private static var renew: (@MainActor (NativeCaptureExtensionRequest) async throws -> NativeCaptureExtensionPermit)?
    private static var activePermit: NativeCapturePermit?
    private static var latestExtension: NativeCaptureExtensionPermit?
    private static var extending = false
    private static var idle: (@MainActor () -> Bool)?
    private static var retiring = false
    private static var authorizing = false
    private static var recovering = false

    /// Native PCM supplies the process-wide ownership check; no JS callback.
    public static func registerIdleProbe(_ probe: @escaping @MainActor () -> Bool) {
        if let previous = idle, owner != nil || recovering || authorizing || extending {
            // A plugin reload cannot hide an older recorder still shutting down.
            idle = { previous() && probe() }
        } else { idle = probe }
    }

    public static func install(owner: UUID,
                               renew: (@MainActor (NativeCaptureExtensionRequest) async throws -> NativeCaptureExtensionPermit)? = nil,
                               authorize: @escaping @MainActor () async throws -> NativeCapturePermit) throws {
        guard !recovering, !authorizing, !extending, activePermit == nil,
              self.owner == nil || (self.owner == owner && !retiring && consumer == .renderer)
        else { throw NativeAuthError.busy }
        if self.owner == nil { retiring = false }
        consumer = .renderer
        nativeIdle = nil
        self.owner = owner; self.authorize = authorize
        self.renew = renew
    }

    /// Native custody and the renderer share one physical-source exclusion gate.
    public static func installEncrypted(owner: UUID, idle probe: @escaping @MainActor () -> Bool,
        renew: @escaping @MainActor (NativeCaptureExtensionRequest) async throws -> NativeCaptureExtensionPermit,
        authorize: @escaping @MainActor () async throws -> NativeCapturePermit) throws {
        guard self.owner == nil, !recovering, !authorizing, !extending,
              let idle, idle(), probe() else { throw NativeAuthError.busy }
        self.owner = owner; consumer = .nativeEncryptedMicrophone; nativeIdle = probe
        self.authorize = authorize; self.renew = renew; retiring = false
    }

    public static func requireActiveEncryptedOwner(_ expected: UUID) throws {
        guard owner == expected, consumer == .nativeEncryptedMicrophone,
              !retiring, !recovering, activePermit != nil, nativeIdle != nil else {
            throw NativeAuthError.unavailable
        }
    }

    /// Replacing a WebView does not stop an independently retained native run.
    /// Only that exact run may account for an occupied gate. This does not grant
    /// permission to start, clear ownership, or retire a saved source proof.
    public static func confirmRendererReplacement(retaining expected: UUID? = nil) throws {
        guard let idle, idle(), !recovering else { throw NativeAuthError.busy }
        if let owner {
            guard owner == expected, consumer == .nativeEncryptedMicrophone,
                  nativeIdle != nil else { throw NativeAuthError.busy }
        } else {
            guard !authorizing, !extending else { throw NativeAuthError.busy }
        }
    }

    public static func clear(owner: UUID) {
        if self.owner == owner {
            if consumer == .nativeEncryptedMicrophone {
                retiring = true
                guard !authorizing, !extending, let idle, idle(), nativeIdle?() == true else { return }
            }
            self.owner = nil; self.authorize = nil; renew = nil; retiring = true
            activePermit = nil; latestExtension = nil; nativeIdle = nil
        }
    }

    /// Keep the owner marker until physical closure is confirmed. An in-flight
    /// authorization cannot cross this fence, even after the same account returns.
    public static func retire(owner: UUID) {
        if self.owner == owner { retiring = true; authorize = nil; renew = nil }
    }

    /// Capture before the first permission await so an old start can never
    /// consume a replacement owner's decision after close or navigation.
    public static func startTicket() throws -> UUID {
        guard let owner, !retiring, consumer == .renderer else { throw NativeAuthError.unavailable }
        return owner
    }

    /// Final check and native begin execute together on MainActor, with no await
    /// between them. Retirement fences both pending authorization and later starts.
    public static func consume<T>(owner expected: UUID,
        consumer expectedConsumer: Consumer = .renderer,
        start: @MainActor (NativeCapturePermit) throws -> T) async throws -> T {
        guard owner == expected, consumer == expectedConsumer,
              !retiring, !authorizing, activePermit == nil, let authorize else {
            throw NativeAuthError.unavailable
        }
        authorizing = true; defer { authorizing = false }
        let permit = try await authorize()
        guard owner == expected, consumer == expectedConsumer, !retiring, permit.startExpiresAt > Date() else {
            throw NativeAuthError.unavailable
        }
        let result = try start(permit)
        activePermit = permit
        return result
    }

    /// The physical owner rechecks its monotonic deadline when applying this
    /// permit. A JavaScript expiry or chunk count is never a native grant.
    public static func extend<T>(owner expected: UUID, consumer expectedConsumer: Consumer = .renderer,
        request: NativeCaptureExtensionRequest,
        apply: @MainActor (NativeCaptureExtensionPermit) async throws -> T) async throws -> T {
        guard owner == expected, consumer == expectedConsumer, !retiring, !authorizing, !extending,
              let activePermit, let renew else { throw NativeAuthError.unavailable }
        extending = true; defer { extending = false }
        let permit = try await renew(request)
        let generation = latestExtension?.generation ?? activePermit.generation
        let deadline = latestExtension?.captureExpiresAt ?? activePermit.captureExpiresAt
        let replay = latestExtension.map { prior in
            prior.runID == permit.runID && prior.generation == permit.generation &&
            prior.expiresAt == permit.expiresAt && prior.captureExpiresAt == permit.captureExpiresAt &&
            prior.previousCaptureExpiresAt == permit.previousCaptureExpiresAt && prior.maximumChunks == permit.maximumChunks
        } ?? false
        guard owner == expected, !retiring, permit.expiresAt > Date(), deadline > Date(),
              permit.runID == activePermit.runID, permit.maximumChunks <= activePermit.hardMaximumChunks,
              replay || (permit.generation == generation + 1 && permit.previousCaptureExpiresAt == deadline) else {
            throw NativeAuthError.unavailable
        }
        let result = try await apply(permit)
        guard owner == expected, !retiring else { throw NativeAuthError.unavailable }
        latestExtension = permit
        return result
    }

    /// Native boot recovery must hold idle for the entire authenticated stop.
    /// A missing PCM idle probe is not evidence of physical cessation.
    public static func recoverWhileIdle(_ operation: @MainActor () async throws -> Void) async throws {
        guard owner == nil, !authorizing, !extending, !recovering, let idle, idle() else { throw NativeAuthError.busy }
        recovering = true; defer { recovering = false }
        try await operation()
        guard owner == nil, !authorizing, idle() else { throw NativeAuthError.busy }
    }

    public static func confirmStopped(owner expected: UUID) throws {
        guard owner == expected else { throw NativeAuthError.unavailable }
        retiring = true
        guard !authorizing, !extending, let idle, idle(),
              consumer == .renderer || nativeIdle?() == true else { throw NativeAuthError.busy }
    }
}
