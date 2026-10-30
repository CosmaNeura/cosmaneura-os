import Foundation
import UIKit
import WebKit
import CosmasNativeAuth

/// The handler exists only in WebKit's isolated client world. Page scripts
/// cannot post to it; the bundled listener requires a trusted button click.
@MainActor final class CosmaneuraNavigationHandler: NSObject, WKScriptMessageHandlerWithReply {
    private weak var webView: WKWebView?
    private let policy: CosmaneuraRecordNavigation
    private let currentState: () -> NativeAuthState?
    private var consumed: [String] = []
    private var pending = false
    private static let channel = "cosmasCosmaneuraNavigation"

    init(webView: WKWebView, policy: CosmaneuraRecordNavigation, currentState: @escaping () -> NativeAuthState?) {
        self.webView = webView
        self.policy = policy
        self.currentState = currentState
        super.init()
    }

    func install() throws {
        guard let webView, let resource = Bundle.module.url(forResource: "cosmaneura-navigation-dom", withExtension: "js") else {
            throw CosmaneuraNavigationError.unavailable
        }
        let common = try String(contentsOf: resource, encoding: .utf8)
        let enabled = policy.origin == nil ? "false" : "true"
        let schedulingEnabled = policy.scheduling.enabled ? "true" : "false"
        let googleEnabled = policy.google.enabled ? "true" : "false"
        let microsoftEnabled = policy.microsoft.enabled ? "true" : "false"
        let anyEnabled = policy.origin != nil || policy.scheduling.enabled || policy.microsoft.enabled || policy.google.enabled ? "true" : "false"
        let capability = "Object.defineProperty(window, 'cosmasGoogleNavigation', {value:Object.freeze({version:1,available:\(googleEnabled),mode:'trusted-click'}),writable:false,configurable:false});Object.defineProperty(window, 'cosmasMicrosoftNavigation', {value:Object.freeze({version:1,available:\(microsoftEnabled),mode:'trusted-click'}),writable:false,configurable:false});Object.defineProperty(window, 'cosmasCosmaneuraNavigation', {value:Object.freeze({version:1,available:\(enabled),mode:'trusted-click'}),writable:false,configurable:false});Object.defineProperty(window, 'cosmasSchedulingNavigation', {value:Object.freeze({version:1,available:\(schedulingEnabled),mode:'trusted-click'}),writable:false,configurable:false});"
        let script = "(() => {\n\(common)\ninstallCosmaneuraTrustedClicks(\(anyEnabled), request => window.webkit.messageHandlers.\(Self.channel).postMessage(request));\n})();"
        let content = webView.configuration.userContentController
        content.addScriptMessageHandler(self, contentWorld: .defaultClient, name: Self.channel)
        content.addUserScript(WKUserScript(source: capability, injectionTime: .atDocumentStart, forMainFrameOnly: true, in: .page))
        content.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: true, in: .defaultClient))
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping @MainActor @Sendable (Any?, String?) -> Void) {
        do {
            guard !pending, message.name == Self.channel, let webView,
                  message.webView === webView, userContentController === webView.configuration.userContentController,
                  webView.isUserInteractionEnabled, webView.window != nil,
                  UIApplication.shared.applicationState == .active else { throw CosmaneuraNavigationError.unavailable }
            let origin = message.frameInfo.securityOrigin
            guard CosmaneuraRecordNavigation.currentAppleDocument(webView.url?.absoluteString,
                  frameDocument: message.frameInfo.request.url?.absoluteString, mainFrame: message.frameInfo.isMainFrame,
                  scheme: origin.protocol, host: origin.host, port: origin.port),
                  let payload = message.body as? [String: Any] else { throw CosmaneuraNavigationError.unavailable }
            let request = try policy.request(payload)
            guard !consumed.contains(request.requestID), let state = currentState(), state.phase == .ready,
                  state.identity != nil, state.revision == request.expectedRevision else { throw CosmaneuraNavigationError.unavailable }
            consumed.append(request.requestID)
            if consumed.count > 128 { consumed.removeFirst() }
            pending = true
            var replied = false
            let timeout = Task { @MainActor in
                try? await Task.sleep(for: .seconds(12))
                guard !Task.isCancelled, !replied else { return }
                replied = true
                // The OS may have accepted an open whose callback is missing.
                // Keep the pending gate until that exact callback settles.
                replyHandler(nil, "Cosmaneura navigation unavailable")
            }
            // No suspension occurs between session/frame validation and dispatch.
            // A successful callback does not prove the browser loaded the record.
            UIApplication.shared.open(request.url, options: [:]) { [weak self] accepted in
                self?.pending = false
                timeout.cancel()
                guard !replied else { return }
                replied = true
                if accepted { replyHandler(["schemaVersion": 1, "requestId": request.requestID, "status": "opened"], nil) }
                else { replyHandler(nil, "Cosmaneura navigation unavailable") }
            }
        } catch { replyHandler(nil, "Cosmaneura navigation unavailable") }
    }
}
