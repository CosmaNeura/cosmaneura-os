import CosmasNativeAuth
import Foundation
import UIKit

@MainActor public final class NativePracticeSceneTransition {
    let prepareAccountRealm: @MainActor () async throws -> Void
    let replaceRenderer: @MainActor (NativePracticeActiveWorkspaceSnapshot?) async throws -> Void
    public init(prepareAccountRealm: @escaping @MainActor () async throws -> Void,
                replaceRenderer: @escaping @MainActor (NativePracticeActiveWorkspaceSnapshot?) async throws -> Void) {
        self.prepareAccountRealm = prepareAccountRealm; self.replaceRenderer = replaceRenderer
    }
}
@MainActor public protocol NativePracticeBrowser: AnyObject { func open(_ reviewedURL: URL) async throws }
@MainActor public final class NativePracticeSystemBrowser: NativePracticeBrowser {
    public init() {}
    public func open(_ reviewedURL: URL) async throws {
        guard UIApplication.shared.applicationState == .active, reviewedURL.scheme == "https",
              ["checkout.stripe.com", "billing.stripe.com"].contains(reviewedURL.host),
              reviewedURL.user == nil, reviewedURL.password == nil, reviewedURL.port == nil else {
            throw NativePracticeProfileError.invalidBinding
        }
        try await NativeAuthAwait<Void>().run(timeout: .seconds(15), onAbandon: {}) {
            try await withCheckedThrowingContinuation { continuation in
                UIApplication.shared.open(reviewedURL, options: [:]) { accepted in
                    if accepted { continuation.resume() }
                    else { continuation.resume(throwing: NativePracticeProfileError.unavailable) }
                }
            }
        }
        // Open acceptance is not Checkout completion. Foreground status/recover
        // runs the real account service; no callback fabricates payment success.
    }
}

/// Executable native account-service host. Constructor is SDK/network inert for
/// marker-free beta users. Only explicit setup intent enters the account realm;
/// marked restarts restore the previously selected realm and revalidate it.
@MainActor public final class NativePracticeConnectionController: NativePracticeConnectionHost {
    private let configuration: NativePracticeBundleConfiguration?
    private var scene: NativePracticeSceneTransition
    private let browser: any NativePracticeBrowser
    private let wire: (any NativePracticeAccountWire)?
    private let store: any NativePracticeSelectionStore
    private var marker: NativePracticeSelectionMarker?
    private var driver: ClerkKitAccountDriver?
    private var accountBlock: KeychainAccessBlock?
    private var registered: NativePracticeRuntime?
    // A failed candidate remains owned until its real native SDK/API work has
    // drained. A timeout must not release it and permit realm reconfiguration.
    private var pendingCandidate: NativePracticeRuntime?
    private var enteredRealm = false
    private var phase: NativePracticeAccountView.Phase = .signedOut
    private var revision = UUID().uuidString.lowercased()
    private var account: NativeAccountIdentity?
    private var email = ""
    private var displayName = ""
    private var transition = false
    private var observers: [@MainActor (NativePracticeAccountView) -> Void] = []
    private var destinations: [NativePracticeEnrollmentDestination: (account: NativeAccountIdentity, practice: UUID, url: URL)] = [:]
    public var available: Bool { configuration != nil }
    public var enrollmentAvailable: Bool { configuration != nil && wire != nil }
    public var isRegisteredPracticeActive: Bool { marker != nil || registered != nil }

    public init(configuration: NativePracticeBundleConfiguration?, scene: NativePracticeSceneTransition,
                browser: any NativePracticeBrowser = NativePracticeSystemBrowser(),
                wire: (any NativePracticeAccountWire)? = nil, selectionStore: (any NativePracticeSelectionStore)? = nil) throws {
        self.configuration = configuration; self.scene = scene; self.browser = browser
        self.wire = wire ?? configuration.map { NativePracticeAccountHTTP(binding: $0.binding) }
        guard let bundle = Bundle.main.bundleIdentifier else { throw NativePracticeProfileError.invalidBinding }
        store = try selectionStore ?? KeychainNativePracticeSelectionStore(bundleIdentifier: bundle)
        // One new metadata item only. No SDK or existing beta credential query.
        marker = try store.read()
        if marker != nil { phase = .unavailable }
    }
    /// Native reconnect only. Never redirect a transition that already owns
    /// another scene's close/replace callbacks; retry after it has settled.
    public func rebindScene(_ scene: NativePracticeSceneTransition) throws {
        guard !transition else { throw NativePracticeProfileError.busy }
        self.scene = scene
    }
    public var isAccountRealmActive: Bool { enteredRealm }
    public var shouldResumeAccountSetup: Bool { enteredRealm && registered == nil }

    public func observeAccount(_ observer: @escaping @MainActor (NativePracticeAccountView) -> Void) {
        if observers.count < 32 { observers.append(observer) }
    }
    private func changed(_ next: NativePracticeAccountView.Phase) {
        phase = next; revision = UUID().uuidString.lowercased()
        if let view = try? view() { for observer in observers { observer(view) } }
    }
    private func view() throws -> NativePracticeAccountView {
        let identity = phase == .accountReady && account != nil
            ? try NativePracticeAccountView.Identity(account: account!, email: email, displayName: displayName) : nil
        return try .init(phase: phase, revision: revision, identity: identity)
    }
    private func currentAccount() -> NativeAccountIdentity? {
        if let registered, let profile = registered.profile {
            let state = registered.auth.state()
            guard state.phase == .ready, let identity = state.identity,
                  identity.organizationID == profile.organizationID else { return nil }
            return try? .init(issuer: profile.configuration.frontendOrigin, userID: identity.userID, sessionID: identity.sessionID)
        }
        return driver?.identity
    }
    public func accountStatus() async throws -> NativePracticeAccountView {
        if phase == .accountReady, currentAccount() != account { account = nil; changed(.unavailable) }
        return try view()
    }
    private func expect(_ expected: String, ready: Bool = true) throws -> NativeAccountIdentity? {
        guard revision == expected, !transition, !ready || (phase == .accountReady && currentAccount() == account && account != nil) else {
            throw NativePracticeProfileError.sessionChanged
        }
        return account
    }
    public func beginAccountSignIn() async throws -> NativePracticeAccountView {
        guard let configuration, !transition else { throw NativePracticeProfileError.unavailable }
        transition = true; defer { transition = false }
        account = nil; destinations.removeAll(); changed(.signingIn)
        do {
            try await scene.prepareAccountRealm()
            try await CosmasWorkspaceAuthPlugin.retireProcessForPracticeTransition()
            // Restoration is required from this point even if Keychain/SDK
            // configuration fails before an account session is established.
            enteredRealm = true
            try CosmasWorkspaceAuthPlugin.holdProcessForAccountSetup()
            registered?.retire(); registered = nil
            try await retireCandidateRuntime()
            try await retireAccountDriver()
            let block = try KeychainAccessBlock(bundleIdentifier: configuration.binding.realm.bundleIdentifier,
                profile: configuration.binding.realm.profile, profileNamespace: configuration.binding.realm.storageNamespace)
            try block.setBlocked(true); accountBlock = block
            driver = try await ClerkKitAccountDriver.reconfigured(configuration: configuration.binding.realm, audience: configuration.binding.audience)
            enteredRealm = true
            let identity = try await driver!.signIn()
            guard driver?.identity == identity else { throw NativePracticeProfileError.sessionChanged }
            try block.setBlocked(false)
            account = identity; email = driver?.email ?? ""; displayName = driver?.displayName ?? ""
            changed(.accountReady); return try view()
        } catch { changed(.unavailable); throw error }
    }
    private func retireAccountDriver() async throws {
        guard let driver else { return }
        driver.retire()
        let end = ContinuousClock.now.advanced(by: .seconds(15))
        while driver.hasUnsettledOperations {
            try Task.checkCancellation()
            guard ContinuousClock.now < end else { throw NativePracticeProfileError.busy }
            try await Task.sleep(for: .milliseconds(20))
        }
    }
    private func retireCandidateRuntime() async throws {
        guard let pendingCandidate else { return }
        pendingCandidate.retire()
        let end = ContinuousClock.now.advanced(by: .seconds(15))
        while !pendingCandidate.resources.isIdle || pendingCandidate.auth.hasUnsettledOperations {
            try Task.checkCancellation()
            guard ContinuousClock.now < end else { throw NativePracticeProfileError.busy }
            try await Task.sleep(for: .milliseconds(20))
        }
        try await pendingCandidate.resources.close()
        self.pendingCandidate = nil
    }
    private func freshToken(for expected: NativeAccountIdentity) async throws -> String {
        if let registered {
            let state = registered.auth.state()
            guard currentAccount() == expected, state.phase == .ready else { throw NativePracticeProfileError.sessionChanged }
            return try await registered.auth.token(expectedRevision: state.revision)
        }
        guard let driver else { throw NativePracticeProfileError.unavailable }
        return try await driver.token(expected: expected)
    }
    public func accountToken(expectedRevision: String) async throws -> String {
        guard let captured = try expect(expectedRevision) else { throw NativePracticeProfileError.sessionChanged }
        let token = try await freshToken(for: captured)
        guard revision == expectedRevision, currentAccount() == captured else { throw NativePracticeProfileError.sessionChanged }
        return token
    }
    private func request(_ operation: NativePracticeAccountRequest, captured: NativeAccountIdentity?,
                         body: Data? = nil, key: String? = nil) async throws -> NativePracticeEnrollmentReply {
        guard let wire else { throw NativePracticeProfileError.unavailable }
        let token: String?
        if let captured { token = try await freshToken(for: captured) } else { token = nil }
        let result = try await wire.send(operation, token: token, body: body, idempotencyKey: key)
        try Task.checkCancellation()
        if let captured { guard currentAccount() == captured else { throw NativePracticeProfileError.sessionChanged } }
        return result
    }
    private func successfulObject(_ reply: NativePracticeEnrollmentReply) throws -> [String: Any] {
        guard (200...299).contains(reply.status), let object = try JSONSerialization.jsonObject(with: reply.body) as? [String: Any] else {
            throw NativePracticeProfileError.unavailable
        }
        return object
    }
    private func registry(for captured: NativeAccountIdentity) async throws -> (NativeRegisteredPracticeReceipt, [String: Any]) {
        let value = try successfulObject(await request(.enrollment(.status), captured: captured))
        guard value["contract_version"] as? String == "enrollment.v1",
              let number = value["revision"] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue >= 0, number.doubleValue < 2_147_483_648, number.doubleValue.rounded(.down) == number.doubleValue,
              let practice = value["practice"] as? [String: Any], let id = practice["id"] as? String,
              let practiceID = UUID(uuidString: id), practiceID.uuidString.lowercased() == id,
              let workspace = value["workspace"] as? [String: Any], let org = workspace["organization_id"] as? String,
              let box = workspace["box_id"] as? String, let boxID = UUID(uuidString: box), boxID.uuidString.lowercased() == box else {
            throw NativePracticeProfileError.unavailable
        }
        return (try .init(account: captured, practiceID: practiceID, organizationID: org, boxID: boxID, registryRevision: number.intValue), value)
    }
    public func activatePracticeOrganization(expectedRevision: String) async throws -> NativePracticeOrganizationToken {
        guard let captured = try expect(expectedRevision), let configuration, let driver else { throw NativePracticeProfileError.unavailable }
        transition = true; defer { transition = false }
        let (receipt, _) = try await registry(for: captured)
        let service = RegistryService(binding: configuration.binding, receipt: receipt)
        let resolver = try NativePracticeProfileResolver(binding: configuration.binding, service: service, currentAccount: { [weak self] in self?.currentAccount() })
        let selection = try await resolver.registeredOrganization()
        try await driver.activateOrganization(selection)
        let token = try await driver.workspaceConfirmationToken(selection)
        guard revision == expectedRevision, currentAccount() == captured else { throw NativePracticeProfileError.sessionChanged }
        return try .init(token: token, revision: expectedRevision)
    }
    private func qualifiedProfile(captured: NativeAccountIdentity, known: NativePracticeSelectionMarker? = nil) async throws -> NativePracticeProfile {
        guard let configuration else { throw NativePracticeProfileError.unavailable }
        let (receipt, status) = try await registry(for: captured)
        guard status["stage"] as? String == "ready", let workspace = status["workspace"] as? [String: Any],
              let address = workspace["url"] as? String, let parsed = URLComponents(string: address), parsed.scheme == "https",
              let host = parsed.host, parsed.user == nil, parsed.password == nil, parsed.port == nil, parsed.query == nil, parsed.fragment == nil else {
            throw NativePracticeProfileError.unavailable
        }
        let api = "https://" + (host == "app.cosmas.ai" ? "api.cosmas.ai" : "api." + host)
        guard configuration.binding.allowsAPI(api, practiceID: receipt.practiceID) else { throw NativePracticeProfileError.invalidBinding }
        if let known {
            try known.validate(binding: configuration.binding)
            guard known.userID == captured.userID, known.practiceID == receipt.practiceID,
                  known.organizationID == receipt.organizationID, known.boxID == receipt.boxID, known.apiOrigin == api else {
                throw NativePracticeProfileError.invalidBinding
            }
        }
        let expected = try NativePracticeConnectionExpectation(selectionID: receipt.practiceID, nonce: UUID(), account: captured,
            organizationID: receipt.organizationID, boxID: receipt.boxID, apiOrigin: api)
        let body = try JSONSerialization.data(withJSONObject: ["client": "apple", "nonce": expected.nonce.uuidString.lowercased(), "expected_revision": receipt.registryRevision])
        let reply = try await request(.workspaceProfile, captured: captured, body: body)
        guard reply.status == 200 else { throw NativePracticeProfileError.unavailable }
        let bootstrap = try NativePracticeWorkspaceBootstrap.decode(reply.body, expectation: expected, binding: configuration.binding)
        let service = RegistryService(binding: configuration.binding, receipt: receipt,
            profileReceipt: .init(expectation: expected, expiresAt: bootstrap.expiresAt, bootstrap: bootstrap))
        return try await NativePracticeProfileResolver(binding: configuration.binding, service: service,
            currentAccount: { [weak self] in self?.currentAccount() }).resolve(expected)
    }
    private func makeAndAdmit(_ profile: NativePracticeProfile) async throws -> NativePracticeRuntime {
        guard let driver else { throw NativePracticeProfileError.unavailable }
        let workspaceDriver = try driver.adoptWorkspace(profile)
        let runtime = try CosmasWorkspaceAuthPlugin.makeRegisteredPracticeRuntime(profile: profile, driver: workspaceDriver)
        pendingCandidate = runtime
        do {
            let state = runtime.auth.state()
            guard state.phase == .ready else { throw NativePracticeProfileError.unavailable }
            let checked = try await CosmasWorkspaceAuthPlugin.admitRegisteredPractice(runtime: runtime, expectedRevision: state.revision)
            guard checked.boxID == profile.boxID, runtime.auth.state() == state else { throw NativePracticeProfileError.invalidBinding }
            return runtime
        } catch { runtime.retire(); throw error }
    }
    public func activateRegisteredPractice(expectedRevision: String) async throws -> NativePracticeActiveWorkspaceSnapshot {
        guard let captured = try expect(expectedRevision) else { throw NativePracticeProfileError.sessionChanged }
        transition = true; defer { transition = false }
        do {
            let profile = try await qualifiedProfile(captured: captured)
            let runtime = try await makeAndAdmit(profile)
            registered = runtime; pendingCandidate = nil; marker = .init(profile: profile)
            account = captured; changed(.accountReady)
            try store.write(marker!)
            try CosmasWorkspaceAuthPlugin.installRegisteredPracticeRuntime(runtime)
            let snapshot = try NativePracticeActiveWorkspaceSnapshot(runtime: runtime)
            try await scene.replaceRenderer(snapshot)
            return snapshot
        } catch { registered?.retire(); changed(.unavailable); throw error }
    }
    public func currentSnapshot() async throws -> NativePracticeActiveWorkspaceSnapshot? {
        guard let marker else { return nil }
        guard let configuration else { throw NativePracticeProfileError.unavailable }
        guard !transition else { throw NativePracticeProfileError.busy }
        transition = true; defer { transition = false }
        try marker.validate(binding: configuration.binding)
        if registered == nil {
            // Only marked startup chooses this realm before default plugin load.
            enteredRealm = true
            try CosmasWorkspaceAuthPlugin.holdProcessForAccountSetup()
            let block = try KeychainAccessBlock(bundleIdentifier: configuration.binding.realm.bundleIdentifier,
                profile: configuration.binding.realm.profile, profileNamespace: configuration.binding.realm.storageNamespace)
            accountBlock = block
            guard try !block.isBlocked() else { throw NativeAuthError.signOutPending }
            driver = try ClerkKitAccountDriver.configured(configuration: configuration.binding.realm, audience: configuration.binding.audience)
            let end = ContinuousClock.now.advanced(by: .seconds(15))
            while driver?.loaded != true {
                try Task.checkCancellation(); guard ContinuousClock.now < end else { throw NativePracticeProfileError.unavailable }
                try await Task.sleep(for: .milliseconds(20))
            }
            guard let current = driver?.identity, current.userID == marker.userID else { throw NativePracticeProfileError.unavailable }
            enteredRealm = true; account = current; email = driver?.email ?? ""; displayName = driver?.displayName ?? ""
            changed(.accountReady)
            let (receipt, _) = try await registry(for: current)
            let selection = try await NativePracticeProfileResolver(binding: configuration.binding,
                service: RegistryService(binding: configuration.binding, receipt: receipt),
                currentAccount: { [weak self] in self?.currentAccount() }).registeredOrganization()
            try await driver!.activateOrganization(selection)
            let profile = try await qualifiedProfile(captured: current, known: marker)
            registered = try await makeAndAdmit(profile)
            pendingCandidate = nil
            try CosmasWorkspaceAuthPlugin.installRegisteredPracticeRuntime(registered!)
        } else {
            guard let current = currentAccount(), current.userID == marker.userID else { throw NativePracticeProfileError.unavailable }
            if account != current { account = current; changed(.accountReady) }
            let fresh = try await qualifiedProfile(captured: current, known: marker)
            let old = registered!
            registered = try NativePracticeRuntime(profile: fresh, auth: old.auth, resources: old.resources)
        }
        return try NativePracticeActiveWorkspaceSnapshot(runtime: registered!)
    }
    /// Existing selected-workspace login keeps its immutable fixed Org/realm,
    /// but a new SID/revision requires a fresh server profile and new document.
    /// Normal beta sign-in does not call this native-only method.
    public func revalidateRegisteredSignIn(expectedRevision: String) async throws {
        guard !transition, let registered, registered.auth.state().phase == .ready,
              registered.auth.state().revision == expectedRevision else {
            throw NativePracticeProfileError.sessionChanged
        }
        guard let snapshot = try await currentSnapshot(), snapshot.revision == expectedRevision,
              registered.auth.state().revision == expectedRevision else {
            throw NativePracticeProfileError.sessionChanged
        }
        transition = true; defer { transition = false }
        try await scene.replaceRenderer(snapshot)
    }
    public func returnToBeta(expectedRevision: String) async throws {
        _ = try expect(expectedRevision, ready: false)
        guard enteredRealm || isRegisteredPracticeActive else { return } // Cancel-before-sign-in is SDK/graph inert.
        transition = true; defer { transition = false }
        destinations.removeAll(); account = nil; changed(.unavailable)
        try await scene.prepareAccountRealm(); registered?.retire(); try await retireCandidateRuntime(); try await retireAccountDriver()
        try await CosmasWorkspaceAuthPlugin.restoreCompiledBetaRuntime()
        try store.clear(); marker = nil; registered = nil; driver = nil; enteredRealm = false
        changed(.signedOut); try await scene.replaceRenderer(nil)
    }
    public func signOut(expectedRevision: String) async throws -> NativePracticeAccountView {
        _ = try expect(expectedRevision); transition = true; defer { transition = false }
        destinations.removeAll(); account = nil; changed(.unavailable)
        if let registered { _ = try await registered.auth.signOut() }
        else if let driver { try accountBlock?.setBlocked(true); try await driver.signOut(); try accountBlock?.setBlocked(false) }
        changed(.signedOut); return try view()
    }
    public func enrollmentRequest(_ request: NativePracticeEnrollmentRequest) async throws -> NativePracticeEnrollmentReply {
        let captured = try expect(request.expectedRevision, ready: request.operation != .config)
        transition = true; defer { transition = false }
        let destination: NativePracticeEnrollmentDestination? = request.operation == .checkout ? .checkout : (request.operation == .portal ? .portal : nil)
        var priorPractice: UUID?
        if let destination, let captured {
            destinations.removeValue(forKey: destination)
            priorPractice = try await registry(for: captured).0.practiceID
        }
        let result = try await self.request(.enrollment(request.operation), captured: captured, body: request.body, key: request.idempotencyKey)
        guard revision == request.expectedRevision else { throw NativePracticeProfileError.sessionChanged }
        if request.operation == .selectPractice || request.operation == .join || request.operation == .practice { destinations.removeAll() }
        if let destination, let captured, let priorPractice, (200...299).contains(result.status) {
            let object = try successfulObject(result)
            if let url = object["url"] as? String {
                let (receipt, _) = try await registry(for: captured)
                guard receipt.practiceID == priorPractice else { throw NativePracticeProfileError.sessionChanged }
                if destination == .checkout {
                    guard object["status"] as? String == "open", let enrollment = object["enrollment"] as? [String: Any],
                          let practice = enrollment["practice"] as? [String: Any],
                          practice["id"] as? String == priorPractice.uuidString.lowercased() else {
                        throw NativePracticeProfileError.invalidBinding
                    }
                }
                guard let reviewed = URL(string: url), reviewed.scheme == "https", reviewed.port == nil,
                      reviewed.user == nil, reviewed.password == nil, url.utf8.count <= 8192,
                      reviewed.host == (destination == .checkout ? "checkout.stripe.com" : "billing.stripe.com") else {
                    throw NativePracticeProfileError.invalidBinding
                }
                destinations[destination] = (captured, receipt.practiceID, reviewed)
            }
        }
        return result
    }
    public func openEnrollmentDestination(expectedRevision: String, destination: NativePracticeEnrollmentDestination) async throws {
        guard let captured = try expect(expectedRevision), let reviewed = destinations[destination], reviewed.account == captured else {
            throw NativePracticeProfileError.invalidBinding
        }
        transition = true; defer { transition = false }
        let (receipt, _) = try await registry(for: captured)
        guard receipt.practiceID == reviewed.practice, revision == expectedRevision else { throw NativePracticeProfileError.sessionChanged }
        try await browser.open(reviewed.url)
    }
}

/// Returned values are exclusively from the authenticated fixed wire above.
/// Native resolver still validates nonce/session/practice/Org/Box/API/expiry.
@MainActor private final class RegistryService: NativePracticeAccountService {
    let binding: NativePracticeAccountServiceBinding
    let receipt: NativeRegisteredPracticeReceipt
    let profileReceipt: NativePracticeAccountServiceReceipt?
    init(binding: NativePracticeAccountServiceBinding, receipt: NativeRegisteredPracticeReceipt,
         profileReceipt: NativePracticeAccountServiceReceipt? = nil) {
        self.binding = binding; self.receipt = receipt; self.profileReceipt = profileReceipt
    }
    func registeredPractice(account: NativeAccountIdentity) async throws -> NativeRegisteredPracticeReceipt {
        guard receipt.account == account else { throw NativePracticeProfileError.sessionChanged }; return receipt
    }
    func resolve(_ expectation: NativePracticeConnectionExpectation) async throws -> NativePracticeAccountServiceReceipt {
        guard let profileReceipt, profileReceipt.expectation == expectation else { throw NativePracticeProfileError.invalidBinding }
        return profileReceipt
    }
}
