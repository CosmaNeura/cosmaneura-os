@preconcurrency import Capacitor
import CosmasNativeAuth
import Foundation

/// Root host supplies complete immutable service/runtime/navigation ports before
/// document load. This interface is not a source of URL, issuer or Org authority.
/// Absent or incomplete ports always advertise availability=false.
@MainActor public protocol NativePracticeConnectionHost: AnyObject {
    var available: Bool { get }
    var enrollmentAvailable: Bool { get }
    var isRegisteredPracticeActive: Bool { get }
    func currentSnapshot() async throws -> NativePracticeActiveWorkspaceSnapshot?
    func observeAccount(_ observer: @escaping @MainActor (NativePracticeAccountView) -> Void)
    func accountStatus() async throws -> NativePracticeAccountView
    func beginAccountSignIn() async throws -> NativePracticeAccountView
    func accountToken(expectedRevision: String) async throws -> String
    func activatePracticeOrganization(expectedRevision: String) async throws -> NativePracticeOrganizationToken
    func activateRegisteredPractice(expectedRevision: String) async throws -> NativePracticeActiveWorkspaceSnapshot
    func returnToBeta(expectedRevision: String) async throws
    func signOut(expectedRevision: String) async throws -> NativePracticeAccountView
    func enrollmentRequest(_ request: NativePracticeEnrollmentRequest) async throws -> NativePracticeEnrollmentReply
    /// Host opens only its cached, last authenticated server-reviewed Stripe URL
    /// for the current account/practice. A returned open does not prove payment;
    /// foreground status/recover must recheck the actual server.
    func openEnrollmentDestination(expectedRevision: String, destination: NativePracticeEnrollmentDestination) async throws
}

@objc(CosmasNativePracticeConnectionPlugin)
@MainActor public final class CosmasNativePracticeConnectionPlugin: CAPPlugin, @preconcurrency CAPBridgedPlugin, @unchecked Sendable {
    public let identifier = "CosmasNativePracticeConnectionPlugin"
    public let jsName = "CosmasNativePracticeConnection"
    public let pluginMethods: [CAPPluginMethod] = [
        "capabilities", "accountStatus", "beginAccountSignIn", "accountToken", "activatePracticeOrganization",
        "activateRegisteredPractice", "returnToBeta", "signOut", "enrollmentRequest", "openEnrollmentDestination",
    ].map { CAPPluginMethod(name: $0, returnType: CAPPluginReturnPromise) }
    private static var processHost: (any NativePracticeConnectionHost)?
    @nonobjc public static var installedHost: (any NativePracticeConnectionHost)? { processHost }

    /// Native startup only; not registered as a renderer/plugin operation.
    @nonobjc public static func install(host: any NativePracticeConnectionHost) throws {
        guard processHost == nil else { throw NativePracticeProfileError.busy }
        processHost = host
    }
    nonisolated public override func load() {
        Task { @MainActor [weak self] in
            Self.processHost?.observeAccount { [weak self] state in self?.notifyListeners("accountStateChanged", data: state.payload) }
        }
    }
    private func host(enrollment: Bool = false) throws -> any NativePracticeConnectionHost {
        guard let host = Self.processHost, host.available, !enrollment || host.enrollmentAvailable else {
            throw NativePracticeProfileError.unavailable
        }
        return host
    }
    private static func empty(_ call: CAPPluginCall) throws {
        guard call.options.isEmpty else { throw NativePracticeProfileError.invalidBinding }
    }
    private static func revision(_ call: CAPPluginCall, additional: Set<String> = []) throws -> String {
        guard let options = call.options as? [String: Any],
              Set(options.keys) == additional.union(["expectedRevision"]),
              let revision = call.getString("expectedRevision"),
              UUID(uuidString: revision)?.uuidString.lowercased() == revision else { throw NativePracticeProfileError.invalidBinding }
        return revision
    }
    private static func reject(_ call: CAPPluginCall) {
        call.reject("Practice connection is unavailable. Please try again.", NativePracticeProfileError.unavailable.rawValue)
    }
    @objc nonisolated public func capabilities(_ call: CAPPluginCall) {
        Task { @MainActor in
            do { try Self.empty(call); call.resolve(["contract_version": "cosmabot.native-practice-connection.v1",
                "available": Self.processHost?.available == true,
                "enrollment_available": Self.processHost?.available == true && Self.processHost?.enrollmentAvailable == true]) }
            catch { Self.reject(call) }
        }
    }
    @objc nonisolated public func accountStatus(_ call: CAPPluginCall) {
        Task { @MainActor in do { try Self.empty(call); call.resolve(try await self.host().accountStatus().payload) } catch { Self.reject(call) } }
    }
    @objc nonisolated public func beginAccountSignIn(_ call: CAPPluginCall) {
        Task { @MainActor in do { try Self.empty(call); call.resolve(try await self.host().beginAccountSignIn().payload) } catch { Self.reject(call) } }
    }
    @objc nonisolated public func accountToken(_ call: CAPPluginCall) {
        Task { @MainActor in
            do { let revision = try Self.revision(call); let host = try self.host(enrollment: true)
                let token = try await host.accountToken(expectedRevision: revision)
                let current = try await host.accountStatus()
                guard current.phase == .accountReady, current.revision == revision, !token.isEmpty, token.utf8.count <= 8192 else {
                    throw NativePracticeProfileError.sessionChanged
                }
                call.resolve(["token": token, "revision": revision])
            } catch { Self.reject(call) }
        }
    }
    @objc nonisolated public func activatePracticeOrganization(_ call: CAPPluginCall) {
        Task { @MainActor in
            do { let revision = try Self.revision(call), host = try self.host()
                let result = try await host.activatePracticeOrganization(expectedRevision: revision)
                let current = try await host.accountStatus()
                guard result.revision == revision, current.revision == revision, current.phase == .accountReady else {
                    throw NativePracticeProfileError.sessionChanged
                }
                call.resolve(result.payload)
            } catch { Self.reject(call) }
        }
    }
    @objc nonisolated public func activateRegisteredPractice(_ call: CAPPluginCall) {
        Task { @MainActor in do { let revision = try Self.revision(call); call.resolve(try await self.host().activateRegisteredPractice(expectedRevision: revision).payload) } catch { Self.reject(call) } }
    }
    @objc nonisolated public func returnToBeta(_ call: CAPPluginCall) {
        Task { @MainActor in do { let revision = try Self.revision(call); try await self.host().returnToBeta(expectedRevision: revision); call.resolve() } catch { Self.reject(call) } }
    }
    @objc nonisolated public func signOut(_ call: CAPPluginCall) {
        Task { @MainActor in do { let revision = try Self.revision(call); call.resolve(try await self.host().signOut(expectedRevision: revision).payload) } catch { Self.reject(call) } }
    }
    @objc nonisolated public func enrollmentRequest(_ call: CAPPluginCall) {
        Task { @MainActor in
            do {
                let keys = Set(call.options.keys), allowed: Set<String> = ["expectedRevision", "operation", "body", "idempotencyKey"]
                guard keys.isSubset(of: allowed), keys.contains("expectedRevision"), keys.contains("operation"),
                      let operation = call.getString("operation").flatMap(NativePracticeEnrollmentOperation.init(rawValue:)),
                      let revision = call.getString("expectedRevision") else { throw NativePracticeProfileError.invalidBinding }
                let body: Data?
                if keys.contains("body") {
                    guard let value = call.getObject("body") else { throw NativePracticeProfileError.invalidBinding }
                    body = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes])
                } else { body = nil }
                let key = call.getString("idempotencyKey")
                guard !keys.contains("idempotencyKey") || key != nil else { throw NativePracticeProfileError.invalidBinding }
                let request = try NativePracticeEnrollmentRequest(expectedRevision: revision, operation: operation, body: body, idempotencyKey: key)
                let host = try self.host(enrollment: true), before = try await host.accountStatus()
                guard before.revision == revision, operation == .config || before.phase == .accountReady else {
                    throw NativePracticeProfileError.sessionChanged
                }
                let reply = try await host.enrollmentRequest(request), after = try await host.accountStatus()
                guard after.revision == revision, after.identity?.userID == before.identity?.userID,
                      after.identity?.sessionID == before.identity?.sessionID else {
                    throw NativePracticeProfileError.sessionChanged
                }
                call.resolve(reply.payload)
            } catch { Self.reject(call) }
        }
    }
    @objc nonisolated public func openEnrollmentDestination(_ call: CAPPluginCall) {
        Task { @MainActor in
            do { let revision = try Self.revision(call, additional: ["destination"])
                guard let destination = call.getString("destination").flatMap(NativePracticeEnrollmentDestination.init(rawValue:)) else {
                    throw NativePracticeProfileError.invalidBinding
                }
                try await self.host(enrollment: true).openEnrollmentDestination(expectedRevision: revision, destination: destination)
                call.resolve(["status": "opened"])
            } catch { Self.reject(call) }
        }
    }
}
