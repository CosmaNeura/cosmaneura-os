@preconcurrency import Capacitor
import CosmasNativeAuth
import AuthenticationServices
import UIKit

/// Apple supplies a credential to the already mounted browser Clerk client.
/// The renderer receives it only in memory and never via URL, storage or logs.
@objc(CosmasAppleSignInPlugin)
@MainActor public final class CosmasAppleSignInPlugin: CAPPlugin, @preconcurrency CAPBridgedPlugin, @unchecked Sendable {
    public let identifier = "CosmasAppleSignInPlugin"
    public let jsName = "CosmasAppleSignIn"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "environment", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "mount", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "unmount", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "credential", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "finish", returnType: CAPPluginReturnPromise),
    ]
    private var button: ASAuthorizationAppleIDButton?
    private var admittedKey: String?
    private var state = NativeAppleButtonState()
    private var environmentEpoch = 0

    @objc nonisolated public func environment(_ call: CAPPluginCall) {
        Task { @MainActor in
            self.environmentEpoch += 1
            let epoch = self.environmentEpoch
            self.admittedKey = nil
            self.removeButton()
            do {
                // Use the app's existing profile validator, never a renderer URL.
                let values = Bundle.main.object(forInfoDictionaryKey: "CosmasNativeIdentity") as? [String: Any] ?? [:]
                let configuration = try NativeAppleSignIn.configuration(values: values,
                    browserKey: call.getString("publishableKey"), bundleIdentifier: Bundle.main.bundleIdentifier)
                var request = URLRequest(url: URL(string: configuration.frontendOrigin + "/v1/environment")!)
                request.timeoutInterval = 10
                request.cachePolicy = .reloadIgnoringLocalCacheData
                try configuration.prepareFrontendRequest(&request)
                // No persisted browser/native credentials are needed for this public read.
                let session = URLSession(configuration: .ephemeral)
                defer { session.invalidateAndCancel() }
                let (data, response) = try await session.data(for: request)
                let enabled = NativeAppleSignIn.enabled(environment: data, response: response, requestedURL: request.url!)
                guard epoch == self.environmentEpoch else { call.resolve(["enabled": false]); return }
                self.admittedKey = enabled ? configuration.publishableKey : nil
                call.resolve(["enabled": enabled])
            } catch { call.resolve(["enabled": false]) }
        }
    }

    @objc nonisolated public func mount(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard self.admittedKey != nil,
                  let webView = self.bridge?.webView, webView.window != nil,
                  let id = call.getString("id"), !id.isEmpty,
                  let x = call.getDouble("x"), let y = call.getDouble("y"),
                  let width = call.getDouble("width"), let height = call.getDouble("height"),
                  [x,y,width,height].allSatisfy({ $0.isFinite }), width >= 140, height >= 30 else {
                self.removeButton(); call.reject("Apple sign-in unavailable"); return
            }
            guard self.state.mount(id) else { call.reject("Apple sign-in busy"); return }
            let frame = CGRect(x: x, y: y, width: width, height: height)
            guard webView.bounds.contains(frame) else { self.button?.isHidden = true; call.resolve(); return }
            if self.button == nil {
                let button = ASAuthorizationAppleIDButton(type: .signIn, style: .black)
                button.accessibilityIdentifier = "cosmas.apple.signin"
                button.addTarget(self, action: #selector(self.tapped), for: .touchUpInside)
                webView.addSubview(button)
                self.button = button
            }
            self.button?.frame = frame
            self.button?.isHidden = false
            self.button?.isEnabled = !self.state.busy
            call.resolve()
        }
    }

    @objc private func tapped() {
        guard admittedKey != nil, let id = state.tap() else { return }
        button?.isEnabled = false
        notifyListeners("appleTapped", data: ["id": id])
    }

    @objc nonisolated public func credential(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard self.admittedKey != nil, let id = call.getString("id"), self.state.beginCredential(id)
            else { call.reject("Apple sign-in unavailable"); return }
            defer { self.state.endCredential(id) }
            do {
                let token = try await NativeAppleSignIn.identityToken()
                guard self.state.id == id else { call.resolve(["status": "dismissed"]); return }
                call.resolve(["status": "credential", "token": token])
            } catch { call.resolve(["status": NativeAppleSignIn.failureStatus(error)]) }
        }
    }

    @objc nonisolated public func finish(_ call: CAPPluginCall) {
        Task { @MainActor in
            if let id = call.getString("id") { self.state.finish(id) }
            self.button?.isEnabled = !self.state.busy
            call.resolve()
        }
    }

    @objc nonisolated public func unmount(_ call: CAPPluginCall) {
        Task { @MainActor in
            if call.getString("id") == self.state.id { self.removeButton() }
            call.resolve()
        }
    }

    private func removeButton() {
        button?.removeFromSuperview(); button = nil; state.unmount()
    }
}
