import Foundation

/// Host-owned request/capture resources for one immutable API. fence is
/// synchronous; close proves original source custody idle, without discarding
/// encrypted drafts or retargeting old stop/retry requests to another API.
@MainActor public protocol NativePracticeRequestResources: AnyObject {
    var apiOrigin: String { get }
    var isIdle: Bool { get }
    func fence()
    func close() async throws
}

@MainActor public final class NativePracticeRuntime {
    /// nil denotes the retained default graph, not an enrolled new profile.
    public let profile: NativePracticeProfile?
    public let auth: NativeWorkspaceAuth
    public let resources: any NativePracticeRequestResources
    public init(profile: NativePracticeProfile?, auth: NativeWorkspaceAuth,
                resources: any NativePracticeRequestResources) throws {
        if let profile {
            guard profile.apiOrigin == resources.apiOrigin,
                  auth.matches(organizationID: profile.organizationID, policy: try profile.tokenPolicy) else {
                throw NativePracticeProfileError.invalidBinding
            }
        }
        self.profile = profile; self.auth = auth; self.resources = resources
    }
    public func retire() { auth.retire(); resources.fence() }
}

/// Produced only by the selected API after a fresh native JWT, workspace
/// protocol and current membership/Box admission have actually been verified.
public struct NativePracticeWorkspaceBinding: Sendable {
    public let identity: NativeAuthIdentity
    public let boxID: UUID
    public let actorID: UUID
    public let apiOrigin: String
    public init(identity: NativeAuthIdentity, boxID: UUID, actorID: UUID, apiOrigin: String) {
        self.identity = identity; self.boxID = boxID; self.actorID = actorID; self.apiOrigin = apiOrigin
    }
}

@MainActor public protocol NativePracticeWorkspaceAdmission: AnyObject {
    func admit(_ runtime: NativePracticeRuntime, expectedRevision: String) async throws -> NativePracticeWorkspaceBinding
}

public struct NativePracticeActivationState: Equatable, Sendable {
    public enum Phase: String, Sendable { case ready, activating, unavailable }
    public let phase: Phase
    public let revision: String
    public let profileID: UUID?
}

/// A profile switch is explicit. Failure leaves a fenced recoverable state;
/// it never silently falls back, forces the default user into onboarding, or
/// copies credentials/drafts. The default SDK configure path is not called here.
@MainActor public final class NativePracticeActivationOwner {
    public typealias RuntimeFactory = @MainActor (NativePracticeProfile) async throws -> NativePracticeRuntime
    private let factory: RuntimeFactory
    private let admission: any NativePracticeWorkspaceAdmission
    private var retained: NativePracticeRuntime?
    private var transition: UUID?
    private var phase: NativePracticeActivationState.Phase
    private var revision = UUID().uuidString.lowercased()
    public var onChange: (@MainActor (NativePracticeActivationState) -> Void)?

    public init(retainedDefault: NativePracticeRuntime? = nil, admission: any NativePracticeWorkspaceAdmission,
                factory: @escaping RuntimeFactory) {
        retained = retainedDefault; phase = retainedDefault == nil ? .unavailable : .ready
        self.admission = admission; self.factory = factory
    }

    public var current: NativePracticeRuntime? { phase == .ready ? retained : nil }
    public func state() -> NativePracticeActivationState {
        .init(phase: phase, revision: revision, profileID: retained?.profile?.id)
    }

    public func activate(_ profile: NativePracticeProfile, expectedRevision: String) async throws -> NativePracticeActivationState {
        guard transition == nil else { throw NativePracticeProfileError.busy }
        guard revision == expectedRevision, profile.expiresAt > Date() else {
            throw NativePracticeProfileError.sessionChanged
        }
        let operation = UUID(); transition = operation
        defer { if transition == operation { transition = nil } }
        // Fence before any suspension. Keep the original graph until its SDK
        // operations and original API/source custody have actually drained.
        retained?.retire()
        change(.activating)
        var candidate: NativePracticeRuntime?
        do {
            if let previous = retained {
                try await previous.resources.close()
                try Task.checkCancellation()
                guard previous.resources.isIdle, !previous.auth.hasUnsettledOperations else {
                    throw NativePracticeProfileError.busy
                }
            }
            try Task.checkCancellation()
            guard transition == operation else { throw NativePracticeProfileError.sessionChanged }
            let next = try await factory(profile)
            candidate = next
            guard next.profile == profile, next.resources.apiOrigin == profile.apiOrigin,
                  !next.auth.isRetired else { throw NativePracticeProfileError.invalidBinding }
            try Task.checkCancellation()
            var authState = next.auth.state()
            if authState.phase != .ready { authState = try await next.auth.signIn() }
            guard authState.phase == .ready, let identity = authState.identity,
                  identity.userID == profile.account.userID, identity.organizationID == profile.organizationID else {
                throw NativePracticeProfileError.invalidBinding
            }
            let checked = try await admission.admit(next, expectedRevision: authState.revision)
            try Task.checkCancellation()
            guard transition == operation, next.auth.state() == authState,
                  profile.expiresAt > Date(), checked.identity == identity,
                  checked.boxID == profile.boxID, checked.apiOrigin == profile.apiOrigin else {
                throw NativePracticeProfileError.invalidBinding
            }
            retained = next; change(.ready)
            return state()
        } catch {
            if let candidate { candidate.retire(); try? await candidate.resources.close() }
            // Retain a failed candidate's unsettled SDK ownership too, so retry
            // cannot reconfigure over a late native sign-in/token task.
            if let candidate { retained = candidate }
            change(.unavailable)
            throw error
        }
    }

    private func change(_ next: NativePracticeActivationState.Phase) {
        phase = next; revision = UUID().uuidString.lowercased(); onChange?(state())
    }
}
