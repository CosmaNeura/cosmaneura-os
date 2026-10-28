import AppKit
import CosmasNativeAuth
import Darwin
import Foundation

/// One private, fixed-field status file per helper process; never record SDK errors,
/// identities, Keychain values, tokens, URLs, or request payloads.
@MainActor private final class AuthDiagnostics {
    enum Phase: String {
        case starting, backgroundReady, backgroundLoading, backgroundSignedOut, backgroundUnavailable
        case backgroundSignOutPending, secureStorageApprovalRequired, interactiveWindowVisible
        case interactiveStorageCheck, signingIn, signingOut, operationComplete
        case operationUnavailable, configurationUnavailable, sourceRecoveryUnavailable
    }
    private let descriptor: Int32
    private var last: Phase?

    init() {
        let directory = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true).resolvingSymlinksInPath()
        let path = directory.appendingPathComponent("cosmabot-desktop-auth-\(getpid()).status.json").path
        descriptor = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
        if descriptor >= 0 { _ = fchmod(descriptor, 0o600) }
        record(.starting)
    }

    func record(_ phase: Phase) {
        guard descriptor >= 0, phase != last else { return }
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0, metadata.st_uid == getuid(), metadata.st_nlink == 1,
              metadata.st_mode & S_IFMT == S_IFREG, metadata.st_mode & 0o777 == 0o600,
              let data = try? JSONSerialization.data(withJSONObject: [
                "schema": "cosmabot-desktop-auth-status/v1", "phase": phase.rawValue,
              ], options: [.sortedKeys]), data.count < 512 else { return }
        let written = data.withUnsafeBytes { bytes in pwrite(descriptor, bytes.baseAddress, bytes.count, 0) }
        guard written == data.count, ftruncate(descriptor, off_t(data.count)) == 0 else { return }
        last = phase
    }

    deinit { if descriptor >= 0 { close(descriptor) } }
}

/// The system authentication session needs a visible window in this helper's
/// process; the Electron window belongs to a different process.
@MainActor private final class SignInWindow: NSObject, NSWindowDelegate {
    private let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 170),
        styleMask: [.titled, .closable], backing: .buffered, defer: false)
    private var onCancel: (() -> Void)?

    override init() {
        super.init()
        window.title = "CosmaBot secure account"
        window.isReleasedWhenClosed = false
        window.delegate = self
        let message = NSTextField(wrappingLabelWithString:
            "Complete the secure account prompt. If macOS requests approval, use that prompt. You can cancel and return to CosmaBot.")
        message.frame = NSRect(x: 24, y: 77, width: 392, height: 65)
        window.contentView?.addSubview(message)
        let cancel = NSButton(title: "Cancel", target: self, action: #selector(cancelSignIn))
        cancel.bezelStyle = .rounded
        cancel.frame = NSRect(x: 266, y: 24, width: 150, height: 32)
        window.contentView?.addSubview(cancel)
    }

    func show(onCancel: @escaping () -> Void) {
        self.onCancel = onCancel
        // Activation starts in response to the owner's Sign in action. Give
        // this separate helper a normal foreground app while it owns the UI.
        NSApplication.shared.setActivationPolicy(.regular)
        window.center()
        window.makeKeyAndOrderFront(nil)
        window.displayIfNeeded()
        NSApplication.shared.activate()
    }

    func dismiss() {
        onCancel = nil
        window.orderOut(nil)
        NSApplication.shared.setActivationPolicy(.accessory)
    }

    @objc private func cancelSignIn() {
        onCancel?()
        dismiss()
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        cancelSignIn()
        return false
    }
}

/// Only the spawning Electron main process receives these pipe responses.
@MainActor private final class Helper {
    private var auth: NativeWorkspaceAuth
    private let makeAuth: @MainActor () -> NativeWorkspaceAuth
    private let accessBlock: KeychainAccessBlock?
    private let diagnostics = AuthDiagnostics()
    private var active: [String: Task<Void, Never>] = [:]
    private var recent: [String] = []
    private var signInWindow: SignInWindow?
    private var sourceHost: DesktopSourceHost?

    init() {
        let settings = Bundle.main.object(forInfoDictionaryKey: "CosmasNativeAuth") as? [String: Any] ?? [:]
        if settings["enabled"] as? Bool != true {
            let factory: @MainActor () -> NativeWorkspaceAuth = {
                NativeWorkspaceAuth(enabled: false, organizationID: "",
                    driver: { throw NativeAuthError.unavailable }, accessBlock: { throw NativeAuthError.unavailable })
            }
            makeAuth = factory
            accessBlock = nil
            auth = factory()
        } else {
            do {
                guard let key = settings["publishableKey"] as? String,
                      let origin = settings["frontendOrigin"] as? String,
                      let organization = settings["organizationId"] as? String,
                      let audience = settings["audience"] as? String,
                      let profile = NativeIdentityProfile(rawValue: settings["profile"] as? String ?? "synthetic"),
                      let bundle = Bundle.main.bundleIdentifier else { throw NativeAuthError.unavailable }
                let configuration = try NativeClerkConfiguration(publishableKey: key, frontendOrigin: origin,
                    organizationID: organization, bundleIdentifier: bundle, workspaceOrigin: .desktopApp, profile: profile)
                let policy = try NativeTokenPolicy(issuer: origin, audience: audience,
                    authorizedParty: NativeWorkspaceOrigin.desktopApp.rawValue,
                    nativeSessionWithoutOrigin: profile != .synthetic,
                    sharedStagingSession: profile == .operationalStaging)
                let block = try KeychainAccessBlock(bundleIdentifier: bundle, profile: profile,
                    allowsAuthenticationUI: false)
                var cachedDriver: ClerkKitWorkspaceDriver?
                let factory: @MainActor () -> NativeWorkspaceAuth = {
                    NativeWorkspaceAuth(enabled: true, organizationID: organization, tokenPolicy: policy,
                        driver: {
                            if let cachedDriver { return cachedDriver }
                            let created = try ClerkKitWorkspaceDriver(configuration: configuration)
                            cachedDriver = created
                            return created
                        }, accessBlock: { block })
                }
                makeAuth = factory
                accessBlock = block
                auth = factory()
            } catch {
                let factory: @MainActor () -> NativeWorkspaceAuth = {
                    NativeWorkspaceAuth(enabled: true, organizationID: "",
                        driver: { throw NativeAuthError.unavailable }, accessBlock: { throw NativeAuthError.unavailable })
                }
                makeAuth = factory
                accessBlock = nil
                auth = factory()
            }
        }
        attachAuth()
    }

    private func attachAuth() {
        auth.onChange = { [weak self] state in
            self?.sourceHost?.authChanged(state)
            Self.send(["event": "authStateChanged", "state": NativeAuthPayload.state(state)])
        }
    }

    func run() async {
        Self.send(["event": "ready", "version": 1])
        var frames = DesktopAuthFrames()
        do {
            for try await byte in FileHandle.standardInput.bytes {
                if let request = try frames.append(byte) { receive(request) }
            }
            stop(code: frames.hasPartialFrame ? 64 : 0)
        } catch { stop(code: 64) }
    }

    private func receive(_ request: DesktopAuthRequest) {
        guard active.count < 32, active[request.id] == nil, !recent.contains(request.id) else { stop(code: 64) }
        recent.append(request.id)
        if recent.count > 128 { recent.removeFirst() }
        active[request.id] = Task { @MainActor in
            defer { active.removeValue(forKey: request.id) }
            do {
                let result: Any
                switch request.method {
                case .getState:
                    let state = auth.state()
                    if signInWindow == nil {
                        switch state.phase {
                        case .ready: diagnostics.record(.backgroundReady)
                        case .loading: diagnostics.record(.backgroundLoading)
                        case .signedOut: diagnostics.record(.backgroundSignedOut)
                        case .signOutPending: diagnostics.record(.backgroundSignOutPending)
                        case .unavailable:
                            diagnostics.record(accessBlock?.availability == .interactionRequired
                                ? .secureStorageApprovalRequired : .backgroundUnavailable)
                        default: break
                        }
                    }
                    result = NativeAuthPayload.state(state)
                case .signIn: result = NativeAuthPayload.state(try await interactive(requestID: request.id, signingIn: true))
                case .signOut: result = NativeAuthPayload.state(try await interactive(requestID: request.id, signingIn: false))
                case .getToken:
                    guard let revision = request.revision else { throw NativeAuthError.unavailable }
                    result = ["token": try await auth.token(expectedRevision: revision), "revision": revision]
                case .sourceIdle, .sourcePrepare, .sourceAuthorize, .sourceExtend, .sourceRelease, .sourceStopped, .sourcePreparationRelease:
                    guard let payload = request.payload else { throw NativeAuthError.unavailable }
                    if sourceHost == nil { sourceHost = try DesktopSourceHost(auth: auth) }
                    guard let sourceHost else { throw NativeAuthError.unavailable }
                    result = try await sourceHost.dispatch(request.method.rawValue, payload: payload)
                }
                try Task.checkCancellation()
                Self.send(["id": request.id, "ok": true, "result": result])
            } catch {
                Self.send(["id": request.id, "ok": false, "error": NativeAuthError.unavailable.rawValue])
            }
        }
    }

    private func interactive(requestID: String, signingIn: Bool) async throws -> NativeAuthState {
        guard signInWindow == nil else { throw NativeAuthError.unavailable }
        let window = SignInWindow()
        signInWindow = window
        window.show { [weak self] in self?.active[requestID]?.cancel() }
        diagnostics.record(.interactiveWindowVisible)
        defer {
            window.dismiss()
            signInWindow = nil
        }
        // Let Cocoa display/activate the owned window before an OS approval can
        // synchronously wait. Background state/token checks retain fail-closed UI.
        await Task.yield()
        do {
            try Task.checkCancellation()
            guard let accessBlock else {
                diagnostics.record(.configurationUnavailable)
                throw NativeAuthError.unavailable
            }
            return try await accessBlock.withAuthenticationUI {
                diagnostics.record(.interactiveStorageCheck)
                _ = auth.state()
                if auth.allowsStorageRecovery {
                    // Never replace a coordinator retained by a source host or
                    // with pending SDK work; either could outlive this request.
                    guard sourceHost == nil else {
                        diagnostics.record(.sourceRecoveryUnavailable)
                        throw NativeAuthError.unavailable
                    }
                    auth.onChange = nil
                    auth = makeAuth()
                    attachAuth()
                }
                try Task.checkCancellation()
                diagnostics.record(signingIn ? .signingIn : .signingOut)
                let state = signingIn ? try await auth.signIn() : try await auth.signOut()
                diagnostics.record(.operationComplete)
                return state
            }
        } catch {
            diagnostics.record(.operationUnavailable)
            throw error
        }
    }

    private static func send(_ payload: [String: Any]) {
        guard var data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
              data.count < 16384 else { exit(70) }
        data.append(10)
        do { try FileHandle.standardOutput.write(contentsOf: data) }
        catch { exit(74) }
    }

    private func stop(code: Int32) -> Never {
        for task in active.values { task.cancel() }
        sourceHost?.close()
        exit(code)
    }
}

let application = NSApplication.shared
application.setActivationPolicy(.accessory)
private let helper = Helper()
Task { @MainActor in await helper.run() }
application.run()
