import AppKit
import CosmasNativeAuth
import Foundation

/// The system authentication session needs a visible window in this helper's
/// process; the Electron window belongs to a different process.
@MainActor private final class SignInWindow: NSObject, NSWindowDelegate {
    private let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 170),
        styleMask: [.titled, .closable], backing: .buffered, defer: false)
    private var onCancel: (() -> Void)?

    override init() {
        super.init()
        window.title = "Sign in to Cosmas"
        window.isReleasedWhenClosed = false
        window.delegate = self
        let message = NSTextField(wrappingLabelWithString:
            "Complete sign-in in the secure browser window. You can cancel and return to Cosmas.")
        message.frame = NSRect(x: 24, y: 77, width: 392, height: 65)
        window.contentView?.addSubview(message)
        let cancel = NSButton(title: "Cancel sign-in", target: self, action: #selector(cancelSignIn))
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
    private let auth: NativeWorkspaceAuth
    private var active: [String: Task<Void, Never>] = [:]
    private var recent: [String] = []
    private var signInWindow: SignInWindow?
    private var sourceHost: DesktopSourceHost?

    init() {
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
                    organizationID: organization, bundleIdentifier: bundle, workspaceOrigin: .desktopApp, profile: profile)
                let policy = try NativeTokenPolicy(issuer: origin, audience: audience,
                    authorizedParty: NativeWorkspaceOrigin.desktopApp.rawValue,
                    nativeSessionWithoutOrigin: profile == .operationalBeta)
                auth = NativeWorkspaceAuth(enabled: true, organizationID: organization, tokenPolicy: policy,
                    driver: { try ClerkKitWorkspaceDriver(configuration: configuration) },
                    accessBlock: { try KeychainAccessBlock(bundleIdentifier: bundle, profile: profile) })
            } catch {
                auth = NativeWorkspaceAuth(enabled: true, organizationID: "",
                    driver: { throw NativeAuthError.unavailable }, accessBlock: { throw NativeAuthError.unavailable })
            }
        }
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
                case .getState: result = NativeAuthPayload.state(auth.state())
                case .signIn: result = NativeAuthPayload.state(try await signIn(requestID: request.id))
                case .signOut: result = NativeAuthPayload.state(try await auth.signOut())
                case .getToken:
                    guard let revision = request.revision else { throw NativeAuthError.unavailable }
                    result = ["token": try await auth.token(expectedRevision: revision), "revision": revision]
                case .sourcePrepare, .sourceAuthorize, .sourceExtend, .sourceRelease, .sourceStopped, .sourcePreparationRelease:
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

    private func signIn(requestID: String) async throws -> NativeAuthState {
        guard signInWindow == nil else { throw NativeAuthError.unavailable }
        let window = SignInWindow()
        signInWindow = window
        window.show { [weak self] in self?.active[requestID]?.cancel() }
        defer {
            window.dismiss()
            signInWindow = nil
        }
        return try await auth.signIn()
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
