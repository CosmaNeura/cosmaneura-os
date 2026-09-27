@preconcurrency import Capacitor
import CosmasNativeAuth
import Foundation
import WebKit

@objc(CosmasWorkspaceAuthPlugin)
@MainActor
public final class CosmasWorkspaceAuthPlugin: CAPPlugin, @preconcurrency CAPBridgedPlugin, @unchecked Sendable {
    // Capacitor's Objective-C superclass has no Sendable annotations. Entry
    // points below only enqueue MainActor work; all app-owned mutable state,
    // SDK calls, listener notifications and response completion stay there.
    public let identifier = "CosmasWorkspaceAuthPlugin"
    public let jsName = "CosmasWorkspaceAuth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getState", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "signIn", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "signOut", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getToken", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "prepareProviderSource", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "closeProviderSource", returnType: CAPPluginReturnPromise),
    ]

    private var auth: NativeWorkspaceAuth?
    private var recordNavigation: CosmaneuraNavigationHandler?
    private var providerConnection: NativeProviderConnection?
    private var sourceRecovery: NativeSourceRecovery?
    private var providerSourceOwner: NativeSourceStartOwner?
    private var providerSourcePreparation: NativeSourcePreparation?
    private var providerSourceRevision: String?
    private var providerSourceID: UUID?
    private let sourceLifecycle = NativeRendererSourceLifecycle()
    private var providerRequestsAvailable: Bool {
        guard Bundle.main.bundleIdentifier == "com.cosmasos.beta.ios",
              let value = Bundle.main.object(forInfoDictionaryKey: "CosmasConfiguredCapture") as? [String: Any]
        else { return false }
        return value["enabled"] as? Bool == true
    }


    /// Called by the owned host before its first document load, never by JS.
    public func prepareCosmaneuraNavigation(on webView: WKWebView) throws {
        guard recordNavigation == nil, bridge?.webView === webView else { throw CosmaneuraNavigationError.unavailable }
        initializeAuth()
        let raw = Bundle.main.object(forInfoDictionaryKey: "CosmaneuraWebOrigin")
        guard raw == nil || raw is String else { throw CosmaneuraNavigationError.unavailable }
        let client = Bundle.main.object(forInfoDictionaryKey: "SchedulingGoogleClientID")
        let callback = Bundle.main.object(forInfoDictionaryKey: "SchedulingGoogleCallbackURI")
        guard (client == nil || client is String), (callback == nil || callback is String) else { throw CosmaneuraNavigationError.unavailable }
        let googleClient = Bundle.main.object(forInfoDictionaryKey: "GoogleConnectionClientID")
        let googleCallback = Bundle.main.object(forInfoDictionaryKey: "GoogleConnectionCallbackURI")
        guard (googleClient == nil || googleClient is String), (googleCallback == nil || googleCallback is String) else { throw CosmaneuraNavigationError.unavailable }
        let microsoftTenant = Bundle.main.object(forInfoDictionaryKey: "MicrosoftConnectionTenantID")
        let microsoftClient = Bundle.main.object(forInfoDictionaryKey: "MicrosoftConnectionClientID")
        let microsoftCallback = Bundle.main.object(forInfoDictionaryKey: "MicrosoftConnectionCallbackURI")
        guard (microsoftTenant == nil || microsoftTenant is String), (microsoftClient == nil || microsoftClient is String),
              (microsoftCallback == nil || microsoftCallback is String) else { throw CosmaneuraNavigationError.unavailable }
        let policy = try CosmaneuraRecordNavigation(webOrigin: raw as? String ?? "",
            schedulingClientID: client as? String ?? "", schedulingCallbackURI: callback as? String ?? "",
            microsoftTenantID: microsoftTenant as? String ?? "", microsoftClientID: microsoftClient as? String ?? "", microsoftCallbackURI: microsoftCallback as? String ?? "", googleClientID: googleClient as? String ?? "", googleCallbackURI: googleCallback as? String ?? "")
        let navigation = CosmaneuraNavigationHandler(webView: webView, policy: policy) { [weak self] in self?.auth?.state() }
        try navigation.install()
        recordNavigation = navigation
    }

    nonisolated public override func load() {
        Task { @MainActor in self.initializeAuth() }
    }

    @MainActor private func initializeAuth() {
        guard auth == nil else { return }
        let settings = Bundle.main.object(forInfoDictionaryKey: "CosmasNativeAuth") as? [String: Any] ?? [:]
        if settings["enabled"] as? Bool != true {
            auth = NativeWorkspaceAuth(enabled: false, organizationID: "",
                driver: { throw NativeAuthError.unavailable }, accessBlock: { throw NativeAuthError.unavailable })
        } else {
            do {
                guard let key = settings["publishableKey"] as? String,
                      let origin = settings["frontendOrigin"] as? String,
                      let organization = settings["organizationId"] as? String,
                      let audience = settings["audience"] as? String,
                      let profile = NativeIdentityProfile(rawValue: settings["profile"] as? String ?? "synthetic"),
                      let bundle = Bundle.main.bundleIdentifier else { throw NativeAuthError.unavailable }
                let configuration = try NativeClerkConfiguration(publishableKey: key, frontendOrigin: origin,
                    organizationID: organization, bundleIdentifier: bundle, profile: profile)
                let policy = try NativeTokenPolicy(issuer: origin, audience: audience,
                    nativeSessionWithoutOrigin: profile != .synthetic,
                    sharedStagingSession: profile == .operationalStaging)
                auth = NativeWorkspaceAuth(enabled: true, organizationID: organization, tokenPolicy: policy,
                    driver: { try ClerkKitWorkspaceDriver(configuration: configuration) },
                    accessBlock: { try KeychainAccessBlock(bundleIdentifier: bundle, profile: profile) })
            } catch {
                auth = NativeWorkspaceAuth(enabled: true, organizationID: "",
                    driver: { throw NativeAuthError.unavailable }, accessBlock: { throw NativeAuthError.unavailable })
            }
        }
        auth?.onChange = { [weak self] state in
            self?.providerConnection?.authChanged(state)
            if state.phase != .ready || state.revision != self?.providerSourceRevision {
                self?.invalidateProviderSource()
            }

            self?.notifyListeners("authStateChanged", data: Self.payload(state))
        }
    }

    @objc nonisolated public func getState(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard call.options.isEmpty else { return Self.reject(call) }
            self.initializeAuth()
            guard let auth = self.auth else { return Self.reject(call) }
            call.resolve(Self.payload(auth.state()))
        }
    }

    @objc nonisolated public func signIn(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard call.options.isEmpty else { return Self.reject(call) }
            self.initializeAuth()
            do {
                guard let auth = self.auth else { throw NativeAuthError.unavailable }
                call.resolve(Self.payload(try await auth.signIn()))
            } catch { Self.reject(call) }
        }
    }

    @objc nonisolated public func signOut(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard call.options.isEmpty else { return Self.reject(call) }
            self.initializeAuth()
            do {
                guard let auth = self.auth else { throw NativeAuthError.unavailable }
                call.resolve(Self.payload(try await auth.signOut()))
            } catch { Self.reject(call) }
        }
    }

    @objc nonisolated public func getToken(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard call.options.count == 1, let revision = call.getString("expectedRevision"),
                  UUID(uuidString: revision)?.uuidString.lowercased() == revision else { return Self.reject(call) }
            self.initializeAuth()
            do {
                guard let auth = self.auth else { throw NativeAuthError.unavailable }
                let token = try await auth.token(expectedRevision: revision)
                call.resolve(["token": token, "revision": revision])
            } catch { Self.reject(call) }
        }
    }

    @objc nonisolated public func prepareProviderSource(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard self.providerRequestsAvailable,
                  Set<AnyHashable>(call.options.keys.filter { $0 != AnyHashable("firstSequenceNumber") }) == ["revision", "workspaceId", "sessionId",
                    "leaseId", "leaseReceiptId", "leaseGeneration", "captureAuthorizedUntil"],
                  let revision = call.getString("revision"),
                  let workspace = call.getString("workspaceId").flatMap(UUID.init(uuidString:)),
                  let session = call.getString("sessionId").flatMap(UUID.init(uuidString:)),
                  let lease = call.getString("leaseId").flatMap(UUID.init(uuidString:)),
                  let receipt = call.getString("leaseReceiptId").flatMap(UUID.init(uuidString:)),
                  let number = call.options["leaseGeneration"] as? NSNumber,
                  CFGetTypeID(number) != CFBooleanGetTypeID(),
                  number.doubleValue.rounded(.down) == number.doubleValue,
                  number.doubleValue > 0, number.doubleValue < 2_147_483_648,
                  let generation = call.getInt("leaseGeneration"),
                  let deadline = call.getString("captureAuthorizedUntil") else {
                return Self.rejectProvider(call)
            }
            do {
                let operation = try self.sourceLifecycle.beginOperation()
                defer { self.sourceLifecycle.finishOperation(operation) }
                self.initializeAuth()
                guard let auth = self.auth, auth.state().phase == .ready,
                      auth.state().revision == revision else { throw ProviderNativeError.unavailable }
                let preparation = try NativeSourcePreparation(workspaceID: workspace,
                    sessionID: session, leaseID: lease, leaseReceiptID: receipt,
                    leaseGeneration: generation, captureAuthorizedUntil: deadline, source: .ios,
                    firstSequenceNumber: nativeSourceFirstSequence(call.options["firstSequenceNumber"]))
                if let prior = self.providerSourcePreparation, prior != preparation {
                    throw ProviderNativeError.unavailable
                }
                if self.providerConnection == nil {
                    guard let settings = Bundle.main.object(forInfoDictionaryKey: "CosmasConfiguredCapture") as? [String: Any]
                    else { throw ProviderNativeError.unavailable }
                    self.providerConnection = NativeProviderConnection(auth: auth,
                        wire: try WorkspaceSourceTransport(settings: settings))
                }
                guard let connection = self.providerConnection else { throw ProviderNativeError.unavailable }
                try await self.recoverSources(connection: connection)
                try self.sourceLifecycle.requireOpen()
                guard auth.state().phase == .ready, auth.state().revision == revision,
                      let sourceRecovery = self.sourceRecovery else { throw ProviderNativeError.unavailable }
                try sourceRecovery.requireReady()
                if let prior = self.providerSourcePreparation, prior != preparation {
                    throw ProviderNativeError.unavailable
                }
                if self.providerSourceOwner == nil {
                    guard let connection = self.providerConnection,
                          let identity = auth.state().identity else { throw ProviderNativeError.unavailable }
                    self.providerSourceOwner = try NativeSourceStartOwner(connection: connection,
                        revision: revision, preparation: preparation, identity: identity,
                        journal: sourceRecovery.journal, stopRevision: { [weak connection] in
                            guard let connection else { throw ProviderNativeError.unavailable }
                            return try connection.stopRevision(for: identity)
                        })
                    self.providerSourcePreparation = preparation
                    self.providerSourceRevision = revision; self.providerSourceID = UUID()
                }
                guard let owner = self.providerSourceOwner, let ownerID = self.providerSourceID else {
                    throw ProviderNativeError.unavailable
                }
                try NativeCaptureStartGate.install(owner: ownerID, renew: { request in
                    try await owner.extend(request)
                }) {
                    try await owner.consumeForMicrophone()
                }
                _ = try await owner.prepare()
                try self.sourceLifecycle.requireOpen()
                guard self.providerSourceID == ownerID, auth.state().phase == .ready,
                      auth.state().revision == revision else { throw ProviderNativeError.unavailable }
                call.resolve(["revision": revision, "sessionId": session.uuidString.lowercased()])
            } catch { Self.rejectProvider(call) }
        }
    }

    @objc nonisolated public func closeProviderSource(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard Set(call.options.keys) == ["sessionId"], let session = call.getString("sessionId"),
                  let identifier = UUID(uuidString: session),
                  self.providerSourcePreparation == nil
                    || self.providerSourcePreparation?.sessionID == identifier else {
                return Self.rejectProvider(call)
            }
            do {
                let operation = try self.sourceLifecycle.beginOperation()
                defer { self.sourceLifecycle.finishOperation(operation) }
                if let owner = self.providerSourceOwner, let ownerID = self.providerSourceID {
                    try NativeCaptureStartGate.confirmStopped(owner: ownerID)
                    try await owner.confirmStopped()
                    guard self.providerSourceID == ownerID else { throw ProviderNativeError.unavailable }
                }
                self.clearProviderSource(); call.resolve()
            } catch { Self.rejectProvider(call) }
        }
    }

    /// Called synchronously by the native host before discarding a renderer.
    /// Neither method is registered as a JavaScript plugin operation.
    @nonobjc public func fenceForRendererLoss() {
        sourceLifecycle.fence { self.invalidateProviderSource() }
    }

    @nonobjc public func closeForRendererLoss(
        stopCapture: @MainActor () async throws -> Void,
        captureIsIdle: @MainActor () -> Bool
    ) async throws {
        fenceForRendererLoss()
        try await sourceLifecycle.close(stopCapture: stopCapture, captureIsIdle: captureIsIdle) {
            if let owner = self.providerSourceOwner, let ownerID = self.providerSourceID {
                try NativeCaptureStartGate.confirmStopped(owner: ownerID)
                try await owner.confirmStopped()
                guard self.providerSourceID == ownerID, self.providerSourceOwner === owner else {
                    throw ProviderNativeError.unavailable
                }
                self.clearProviderSource()
            } else {
                guard self.providerSourceOwner == nil, self.providerSourceID == nil,
                      self.providerSourcePreparation == nil, self.providerSourceRevision == nil else {
                    throw ProviderNativeError.unavailable
                }
            }
            // Verify the existing global barrier; never clear a different owner.
            try await NativeCaptureStartGate.recoverWhileIdle {}
        }
    }

    private func recoverSources(connection: NativeProviderConnection) async throws {
        if sourceRecovery == nil {
            guard let group = Bundle.main.object(forInfoDictionaryKey: "CosmasSourceAccessGroup") as? String else { throw ProviderNativeError.unavailable }
            let journal = try NativeSourceProofJournal(platform: .ios,
                backing: KeychainNativeSourceJournal(platform: .ios,
                    bundleIdentifier: Bundle.main.bundleIdentifier ?? "", accessGroup: group))
            sourceRecovery = NativeSourceRecovery(journal: journal)
        }
        guard let sourceRecovery else { throw ProviderNativeError.unavailable }
        try await sourceRecovery.recover(connection: connection)
    }

    private func invalidateProviderSource() {
        // Revoke every possible start while retaining original stop-only custody.
        // Process recovery must pass the native idle barrier before journal retirement.
        if let owner = providerSourceID { NativeCaptureStartGate.retire(owner: owner) }
        providerSourceOwner?.retireForAuthenticationChange()
    }

    private func clearProviderSource() {
        if let owner = providerSourceID { NativeCaptureStartGate.clear(owner: owner) }
        providerSourceOwner?.close(); providerSourceOwner = nil; providerSourcePreparation = nil
        providerSourceRevision = nil; providerSourceID = nil
    }

    private static func rejectProvider(_ call: CAPPluginCall) {
        call.reject("Provider request unavailable", "provider_native_unavailable")
    }
    @MainActor private static func payload(_ state: NativeAuthState) -> [String: Any] {
        let identity: Any = state.identity.map {
            ["userId": $0.userID, "sessionId": $0.sessionID, "organizationId": $0.organizationID]
        } ?? NSNull()
        return ["phase": state.phase.rawValue, "revision": state.revision, "identity": identity]
    }

    private static func reject(_ call: CAPPluginCall) {
        call.reject("Secure session operation unavailable", NativeAuthError.unavailable.rawValue)
    }
}
