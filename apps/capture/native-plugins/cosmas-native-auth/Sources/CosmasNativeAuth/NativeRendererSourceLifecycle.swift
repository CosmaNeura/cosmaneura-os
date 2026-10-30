import Foundation

/// Native-only lifetime fence for one renderer's configured source owner.
/// Physical closure and original proof confirmation remain separate operations.
@MainActor public final class NativeRendererSourceLifecycle {
    private var fenced = false
    private var operations: Set<UUID> = []
    private var closing = false

    public init() {}

    public func requireOpen() throws {
        guard !fenced else { throw NativeAuthError.unavailable }
    }

    public func beginOperation() throws -> UUID {
        try requireOpen()
        let operation = UUID()
        operations.insert(operation)
        return operation
    }

    public func finishOperation(_ operation: UUID) {
        operations.remove(operation)
    }

    /// The caller retires only its own admission and preserves stop custody.
    public func fence(retireOwner: @MainActor () -> Void) {
        fenced = true
        retireOwner()
    }

    /// One explicit attempt. Pending work and failures never schedule a retry.
    public func close(
        stopCapture: @MainActor () async throws -> Void,
        captureIsIdle: @MainActor () -> Bool,
        confirmOwner: @MainActor () async throws -> Void
    ) async throws {
        guard fenced, !closing else { throw NativeAuthError.busy }
        closing = true
        defer { closing = false }
        try await stopCapture()
        guard captureIsIdle(), operations.isEmpty else { throw NativeAuthError.busy }
        try await confirmOwner()
        guard captureIsIdle(), operations.isEmpty else { throw NativeAuthError.busy }
    }
}
