import UIKit
import WebKit
import Capacitor
import CosmaneuraIOSPCMCapacitor
#if canImport(CosmasWorkspaceAuthPlugin)
import CosmasWorkspaceAuthPlugin
#endif

/// Keeps Capacitor's policy, authentication, and navigation handling intact.
/// Terminal failures are consumed: Capacitor 8.5.0 reloads on process death and
/// may load an error page or print private diagnostics on navigation failure.
@MainActor final class WorkspaceNavigationDelegate: NSObject, WKNavigationDelegate {
    private let downstream: WKNavigationDelegate
    private let failed: () -> Void

    init(downstream: WKNavigationDelegate, failed: @escaping () -> Void) {
        self.downstream = downstream
        self.failed = failed
        super.init()
    }

    override func responds(to selector: Selector!) -> Bool {
        super.responds(to: selector) || downstream.responds(to: selector)
    }

    override func forwardingTarget(for selector: Selector!) -> Any? {
        downstream.responds(to: selector) ? downstream : super.forwardingTarget(for: selector)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { failed() }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if Self.isCancellation(error) {
            downstream.webView?(webView, didFail: navigation, withError: error)
        } else { failed() }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        // Cancellation belongs to a replaced navigation, not a broken workspace.
        if Self.isCancellation(error) {
            downstream.webView?(webView, didFailProvisionalNavigation: navigation, withError: error)
        } else { failed() }
    }

    private static func isCancellation(_ error: Error) -> Bool {
        let value = error as NSError
        return value.domain == NSURLErrorDomain && value.code == NSURLErrorCancelled
    }
}

@MainActor private final class WorkspaceLifecycleHandler: NSObject, WKScriptMessageHandler {
    weak var owner: CosmasBridgeViewController?
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        owner?.receive(message)
    }
}

@MainActor final class CosmasBridgeViewController: CAPBridgeViewController {
    let workspaceGeneration: String
    var onSignal: ((WorkspaceRecoveryState.Signal, String, Bool, Bool) -> Void)?
    var onFailure: (() -> Void)?
    private var navigationProxy: WorkspaceNavigationDelegate?
    private let lifecycleHandler = WorkspaceLifecycleHandler()
    private var quarantined = false
    private(set) var capturePlugin: IOSPCMCapacitorPlugin?
    #if canImport(CosmasWorkspaceAuthPlugin)
    private var authPlugin: CosmasWorkspaceAuthPlugin?
    #endif
    private(set) var startedNavigation = false

    init(generation: String) {
        workspaceGeneration = generation
        super.init(nibName: nil, bundle: nil)
        lifecycleHandler.owner = self
    }

    required init?(coder: NSCoder) { fatalError("Use the native workspace container") }

    private func installLifecycle(on webView: WKWebView) {
        // Capacitor replaces the configuration's content controller while building
        // the WebView, so install on the finished instance before loadWebView.
        let content = webView.configuration.userContentController
        content.add(lifecycleHandler, name: "cosmasWorkspaceLifecycle")
        // UUID-generated value contains no user input or credentials.
        let source = "Object.defineProperty(window, '__cosmasWorkspaceGeneration', {value: '\(workspaceGeneration)', writable: false, configurable: false});"
        content.addUserScript(WKUserScript(
            source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true))
    }

    override func viewDidLoad() {
        // In the pinned 8.5.0 binary, CAPBridgeViewController.viewDidLoad starts
        // loadWebView. Install before super so the first navigation is protected.
        guard !quarantined, let webView, let downstream = webView.navigationDelegate,
              let plugin = bridge?.plugin(withName: "IOSPCM") as? IOSPCMCapacitorPlugin else {
            quarantine()
            onFailure?()
            return
        }
        capturePlugin = plugin
        #if canImport(CosmasWorkspaceAuthPlugin)
        do {
            guard let auth = bridge?.plugin(withName: "CosmasWorkspaceAuth") as? CosmasWorkspaceAuthPlugin else {
                throw NSError(domain: "CosmasWorkspace", code: 1)
            }
            authPlugin = auth
            try auth.prepareCosmaneuraNavigation(on: webView)
        } catch {
            quarantine()
            onFailure?()
            return
        }
        #endif
        let proxy = WorkspaceNavigationDelegate(downstream: downstream) { [weak self] in self?.onFailure?() }
        navigationProxy = proxy
        webView.navigationDelegate = proxy
        installLifecycle(on: webView)
        startedNavigation = true
        super.viewDidLoad()
    }

    fileprivate func receive(_ message: WKScriptMessage) {
        guard !quarantined, message.name == "cosmasWorkspaceLifecycle",
              message.webView === webView,
              let body = message.body as? [String: Any], Set(body.keys) == ["kind", "generation"],
              let kind = body["kind"] as? String, let signal = WorkspaceRecoveryState.Signal(rawValue: kind),
              let generation = body["generation"] as? String else { return }
        let origin = message.frameInfo.securityOrigin
        // The compositor fixes the local origin. Never accept a remote page's readiness.
        let sameOrigin = origin.protocol == "capacitor" && origin.host == "localhost" && origin.port == 0
        onSignal?(signal, generation, message.frameInfo.isMainFrame, sameOrigin)
    }

    func quarantine() {
        guard !quarantined else { return }
        quarantined = true
        #if canImport(CosmasWorkspaceAuthPlugin)
        authPlugin?.fenceForRendererLoss()
        #endif
        webView?.stopLoading()
        webView?.isUserInteractionEnabled = false
        webView?.isHidden = true
        // Stop future bridge messages as well as document input. Durable stores remain intact.
        webView?.configuration.userContentController.removeAllScriptMessageHandlers()
    }

    /// Retains both old plugins until physical and configured-owner closure finish.
    func stopForRendererLoss() async throws -> Bool {
        quarantine()
        guard let capturePlugin else {
            return !startedNavigation && IOSPCMCapacitorPlugin.confirmProcessCaptureIdle()
        }
        #if canImport(CosmasWorkspaceAuthPlugin)
        if let authPlugin {
            try await authPlugin.closeForRendererLoss(
                stopCapture: { try await capturePlugin.fenceAndStopForRendererLoss() },
                captureIsIdle: { IOSPCMCapacitorPlugin.confirmProcessCaptureIdle() })
        } else {
            guard !startedNavigation else { return false }
            try await capturePlugin.fenceAndStopForRendererLoss()
        }
        #else
        try await capturePlugin.fenceAndStopForRendererLoss()
        #endif
        return IOSPCMCapacitorPlugin.confirmProcessCaptureIdle()
    }
}
