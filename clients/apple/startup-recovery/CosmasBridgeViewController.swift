import UIKit
import WebKit
import Capacitor
import CosmaneuraIOSPCMCapacitor
import AVFAudio
#if canImport(CosmasWorkspaceAuthPlugin)
import CosmasWorkspaceAuthPlugin
#endif
#if canImport(CosmasNativeAuth)
import CosmasNativeAuth
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
    private var messagesPresentation = false
    private var lastFeedbackAt: TimeInterval = 0
    private var sendFeedback: UIImpactFeedbackGenerator?
    private var selectionFeedback: UISelectionFeedbackGenerator?
    private var notificationFeedback: UINotificationFeedbackGenerator?
    private(set) var capturePlugin: IOSPCMCapacitorPlugin?
    #if canImport(CosmasWorkspaceAuthPlugin)
    private var authPlugin: CosmasWorkspaceAuthPlugin?
    private var speechPlugin: CosmasPrivateSpeechPlugin?
    #endif
    private(set) var startedNavigation = false
    private var selectedDocumentAssets: WorkspaceRegisteredDocumentAssets?
    #if canImport(CosmasNativeAuth)
    private var registeredPracticeSnapshot: NativePracticeActiveWorkspaceSnapshot?
    private var accountEntry = false
    #endif

    init(generation: String) {
        workspaceGeneration = generation
        super.init(nibName: nil, bundle: nil)
        lifecycleHandler.owner = self
    }

    required init?(coder: NSCoder) { fatalError("Use the native workspace container") }

    override func capacitorDidLoad() {
        super.capacitorDidLoad()
        #if canImport(CosmasWorkspaceAuthPlugin)
        // Registration is not activation. The retained beta graph remains the
        // default; no account service or alternative issuer is contacted here.
        // The plugin advertises availability=false until native startup installs
        // a complete pinned account/enrollment/runtime/navigation host.
        bridge?.registerPluginInstance(CosmasNativePracticeConnectionPlugin())
        #endif
    }

    override func instanceDescriptor() -> InstanceDescriptor {
        // Capacitor 8.5.0 otherwise installs a scroll delegate that disables
        // the pinch recognizer when zooming begins. Keep WebKit's zoom behavior.
        let descriptor = super.instanceDescriptor()
        descriptor.zoomingEnabled = true
        // InstanceDescriptor's documented appLocation affects local assets,
        // not the fixed capacitor://localhost origin or native API authority.
        if let selectedDocumentAssets { descriptor.appLocation = selectedDocumentAssets.location }
        return descriptor
    }

    #if canImport(CosmasNativeAuth)
    /// Typed native admission only, before construction/loading of this document.
    func prepareRegisteredPractice(_ snapshot: NativePracticeActiveWorkspaceSnapshot) throws {
        guard !isViewLoaded, !startedNavigation, registeredPracticeSnapshot == nil,
              !accountEntry else { throw NativePracticeProfileError.sessionChanged }
        try snapshot.validateCurrentBinding()
        guard let native = snapshot.bootstrap.rendererProfile["nativeIdentity"] as? [String: Any],
              let api = native["apiOrigin"] as? String else { throw NativePracticeProfileError.invalidBinding }
        selectedDocumentAssets = try WorkspaceRegisteredDocumentAssets(apiOrigin: api)
        try snapshot.validateCurrentBinding()
        registeredPracticeSnapshot = snapshot
    }
    func prepareAccountEntry() throws {
        guard !isViewLoaded, !startedNavigation, registeredPracticeSnapshot == nil else {
            throw NativePracticeProfileError.sessionChanged
        }
        accountEntry = true
    }
    #endif

    private func installLifecycle(on webView: WKWebView) throws {
        // Capacitor replaces the configuration's content controller while building
        // the WebView, so install on the finished instance before loadWebView.
        let content = webView.configuration.userContentController
        content.add(lifecycleHandler, name: "cosmasWorkspaceLifecycle")
        content.add(lifecycleHandler, name: "cosmasPresentation")
        // UUID-generated value contains no user input or credentials.
        let source = "Object.defineProperty(window, '__cosmasWorkspaceGeneration', {value: '\(workspaceGeneration)', writable: false, configurable: false});"
        content.addUserScript(WKUserScript(
            source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        #if canImport(CosmasNativeAuth)
        if accountEntry {
            // Resumes only a transition the native host already owns. This
            // presentation snapshot grants no account, Org or workspace access.
            let entry = "Object.defineProperty(window,'__cosmasNativePracticeEntry',{value:Object.freeze({contract_version:'cosmabot.native-practice-entry.v1',entry:'account'}),writable:false,configurable:false});"
            content.addUserScript(WKUserScript(source: entry, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        if let snapshot = registeredPracticeSnapshot {
            try snapshot.validateCurrentBinding()
            let data = try JSONSerialization.data(withJSONObject: snapshot.payload, options: [.sortedKeys, .withoutEscapingSlashes])
            guard let encoded = String(data: data, encoding: .utf8) else { throw NativePracticeProfileError.invalidBinding }
            // Freeze every nested public field before any renderer code executes.
            // No token, arbitrary URL, local-storage flag or JS installer exists.
            let script = """
            (()=>{const freeze=value=>{if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;};Object.defineProperty(window,'__cosmasRegisteredWorkspace',{value:freeze(\(encoded)),writable:false,configurable:false});})();
            """
            content.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        #endif
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
            speechPlugin = bridge?.plugin(withName: "CosmasPrivateSpeech") as? CosmasPrivateSpeechPlugin
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
        do { try installLifecycle(on: webView) }
        catch { quarantine(); onFailure?(); return }
        startedNavigation = true
        super.viewDidLoad()
        #if DEBUG
        // Synthetic Simulator XCUITest only: after the real IOSPCM plugin path is
        // loaded, optionally request mic permission the same way plugin start does.
        // Never compiled into Release/TestFlight.
        if Bundle.main.bundleIdentifier == "com.cosmasos.synthetic",
           ProcessInfo.processInfo.arguments.contains("-COSMAS_UI_TEST_START_CAPTURE"),
           capturePlugin != nil {
            Task { _ = await AVAudioApplication.requestRecordPermission() }
        }
        #endif
    }

    fileprivate func receive(_ message: WKScriptMessage) {
        if message.name == "cosmasPresentation" { receivePresentation(message); return }
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

    private func receivePresentation(_ message: WKScriptMessage) {
        guard !quarantined, message.webView === webView, message.frameInfo.isMainFrame,
              let body = message.body as? [String: Any], Set(body.keys) == ["kind", "value", "generation"],
              body["generation"] as? String == workspaceGeneration,
              let kind = body["kind"] as? String, let value = body["value"] as? String else { return }
        let origin = message.frameInfo.securityOrigin
        guard origin.protocol == "capacitor", origin.host == "localhost", origin.port == 0 else { return }
        if kind == "mode", ["messages", "workspace"].contains(value) {
            messagesPresentation = value == "messages"
            // Existing route history and its navigation guards remain authoritative.
            webView?.allowsBackForwardNavigationGestures = messagesPresentation
            if messagesPresentation { preparePresentationFeedback() }
            return
        }
        guard kind == "feedback", messagesPresentation,
              webView?.window?.windowScene?.activationState == .foregroundActive,
              IOSPCMCapacitorPlugin.confirmProcessCaptureIdle(),
              ["send", "selection", "success", "warning"].contains(value) else { return }
        let now = ProcessInfo.processInfo.systemUptime
        guard now - lastFeedbackAt >= 0.08 else { return }
        lastFeedbackAt = now
        preparePresentationFeedback()
        switch value {
        case "send": sendFeedback?.impactOccurred()
        case "selection": selectionFeedback?.selectionChanged()
        case "success": notificationFeedback?.notificationOccurred(.success)
        case "warning": notificationFeedback?.notificationOccurred(.warning)
        default: break
        }
    }

    private func preparePresentationFeedback() {
        guard let webView else { return }
        // Modern UIKit routes feedback through the active view's interaction.
        // Retain the generators rather than creating and dropping one per event.
        if sendFeedback == nil {
            if #available(iOS 17.5, *) {
                sendFeedback = UIImpactFeedbackGenerator(style: .light, view: webView)
                selectionFeedback = UISelectionFeedbackGenerator(view: webView)
                notificationFeedback = UINotificationFeedbackGenerator(view: webView)
            } else {
                sendFeedback = UIImpactFeedbackGenerator(style: .light)
                selectionFeedback = UISelectionFeedbackGenerator()
                notificationFeedback = UINotificationFeedbackGenerator()
            }
        }
        sendFeedback?.prepare()
        selectionFeedback?.prepare()
        notificationFeedback?.prepare()
    }

    /// A foreground hint requires this current scene's live, local document.
    /// JavaScript owns fresh authentication before any work observation.
    func notifySceneState(active: Bool, generation: String) -> Bool {
        guard !quarantined, startedNavigation, isViewLoaded,
              generation == workspaceGeneration,
              let webView, let scene = webView.window?.windowScene, let url = webView.url,
              url.scheme == "capacitor", url.host == "localhost", url.port == nil,
              url.user == nil, url.password == nil,
              !active || scene.activationState == .foregroundActive,
              let source = WorkspaceSceneSignalState.script(generation: generation, active: active) else { return false }
        webView.evaluateJavaScript(source, in: nil, in: .page) { _ in }
        return true
    }

    func quarantine() {
        guard !quarantined else { return }
        quarantined = true
        #if canImport(CosmasWorkspaceAuthPlugin)
        authPlugin?.fenceForRendererLoss()
        speechPlugin?.fenceForRendererLoss()
        #endif
        webView?.stopLoading()
        webView?.isUserInteractionEnabled = false
        webView?.isHidden = true
        // Stop future bridge messages as well as document input. Durable stores remain intact.
        webView?.configuration.userContentController.removeAllScriptMessageHandlers()
        selectedDocumentAssets = nil
    }

    /// Account setup retires clinical native resources but keeps its explicit
    /// EnrollmentEntry document interactive. Only final replacement quarantines.
    func stopForPracticeConnection() async throws -> Bool {
        guard startedNavigation, let capturePlugin else { return false }
        #if canImport(CosmasWorkspaceAuthPlugin)
        guard let authPlugin else { return false }
        speechPlugin?.fenceForRendererLoss()
        try await authPlugin.closeForRendererLoss(
            stopCapture: { try await capturePlugin.fenceAndStopForRendererLoss() },
            captureIsIdle: { IOSPCMCapacitorPlugin.confirmProcessCaptureIdle() })
        return IOSPCMCapacitorPlugin.confirmProcessCaptureIdle()
        #else
        return false
        #endif
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

/// Fresh app-private static assets for one admitted renderer. No patient data,
/// credential or renderer-provided URL enters this directory. The bundle is
/// read-only; default Beta and explicit account-only setup use it unchanged.
private final class WorkspaceRegisteredDocumentAssets {
    let location: URL
    init(apiOrigin: String) throws {
        let manager = FileManager.default
        guard let resources = Bundle.main.resourceURL else { throw WorkspaceRegisteredDocumentPolicy.Invalid.document }
        let bundled = resources.appendingPathComponent("public", isDirectory: true)
        let keys: [URLResourceKey] = [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]
        guard let files = manager.enumerator(at: bundled, includingPropertiesForKeys: keys) else {
            throw WorkspaceRegisteredDocumentPolicy.Invalid.document
        }
        var count = 0, bytes = 0
        for case let file as URL in files {
            let value = try file.resourceValues(forKeys: Set(keys))
            count += 1; bytes += value.fileSize ?? 0
            guard count <= 4096, bytes <= 134_217_728, value.isSymbolicLink != true,
                  value.isDirectory == true || value.isRegularFile == true else {
                throw WorkspaceRegisteredDocumentPolicy.Invalid.document
            }
        }
        let source = try String(contentsOf: bundled.appendingPathComponent("index.html"), encoding: .utf8)
        let selected = try WorkspaceRegisteredDocumentPolicy.selectedHTML(source, apiOrigin: apiOrigin)
        let destination = manager.temporaryDirectory.appendingPathComponent("cosmas-native-document-" + UUID().uuidString, isDirectory: true)
        do {
            try manager.copyItem(at: bundled, to: destination)
            try selected.write(to: destination.appendingPathComponent("index.html"), atomically: true, encoding: .utf8)
        } catch { try? manager.removeItem(at: destination); throw error }
        location = destination
    }
    deinit { try? FileManager.default.removeItem(at: location) }
}
