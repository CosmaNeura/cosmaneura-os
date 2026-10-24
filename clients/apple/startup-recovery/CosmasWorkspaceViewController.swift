import UIKit
import CosmaneuraIOSPCMCapacitor

/// A native surface stays available even when JavaScript or the WebView fails.
@MainActor final class CosmasWorkspaceViewController: UIViewController {
    private var recovery = WorkspaceRecoveryState()
    private var sceneSignal: WorkspaceSceneSignalState?
    private var workspace: CosmasBridgeViewController?
    private var sceneActive = false
    private var sceneDisconnected = false
    private var timer: Timer?
    private var stopTask: Task<Void, Never>?
    private var keyboardBottom: NSLayoutConstraint?
    private var restingBottom: NSLayoutConstraint?
    private let panel = UIView()
    private let titleLabel = UILabel()
    private let explanationLabel = UILabel()
    private let statusLabel = UILabel()
    private let reopenButton = UIButton(type: .system)
    private let retryButton = UIButton(type: .system)

    // The shipped workspace header is light in both layouts. A future dark
    // palette must change its status style together with its surface tokens.
    override var preferredStatusBarStyle: UIStatusBarStyle { .darkContent }

    override func viewDidLoad() {
        super.viewDidLoad()
        overrideUserInterfaceStyle = .light
        view.backgroundColor = .systemBackground
        buildPanel()
        NotificationCenter.default.addObserver(self, selector: #selector(keyboardWillShow(_:)),
            name: UIResponder.keyboardWillShowNotification, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(keyboardDidHide(_:)),
            name: UIResponder.keyboardDidHideNotification, object: nil)
        openWorkspace()
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] timer in
            MainActor.assumeIsolated {
                guard let self else { timer.invalidate(); return }
                self.tick()
            }
        }
    }

    @objc private func keyboardWillShow(_ notification: Notification) {
        // Keyboard notifications are process-wide. Only this active key window
        // may opt into its own keyboard guide.
        guard let window = view.window, window.isKeyWindow,
              window.windowScene?.activationState == .foregroundActive,
              notification.userInfo?[UIResponder.keyboardIsLocalUserInfoKey] as? Bool != false,
              workspace != nil else { return }
        restingBottom?.isActive = false
        keyboardBottom?.isActive = true
        // Commit the native resize before WebKit reacts to the same keyboard
        // transition, so it does not also pan a full-height document.
        view.layoutIfNeeded()
    }

    @objc private func keyboardDidHide(_ notification: Notification) {
        // Some UIKit versions retain the dismissed accessory's height in the
        // guide. Once UIKit confirms dismissal, the viewport is the full view.
        // Interactive dismissal continues to follow the guide until didHide.
        guard notification.userInfo?[UIResponder.keyboardIsLocalUserInfoKey] as? Bool != false else { return }
        keyboardBottom?.isActive = false
        restingBottom?.isActive = true
    }

    func setSceneActive(_ active: Bool) {
        sceneActive = active
        sceneSignal?.setSceneActive(active)
        tick()
        dispatchSceneSignal()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        dispatchSceneSignal()
    }

    func sceneDidDisconnect() {
        setSceneActive(false)
        sceneDisconnected = true
        sceneActive = false
        sceneSignal?.close()
        timer?.invalidate()
        timer = nil
        fail()
    }

    private func tick() {
        if recovery.tick(now: ProcessInfo.processInfo.systemUptime, sceneActive: sceneActive) { showFailure() }
    }

    private func openWorkspace() {
        guard !sceneDisconnected else { return }
        recovery = WorkspaceRecoveryState()
        sceneSignal = WorkspaceSceneSignalState(generation: recovery.generation)
        sceneSignal?.setSceneActive(sceneActive)
        _ = recovery.tick(now: ProcessInfo.processInfo.systemUptime, sceneActive: sceneActive)
        renderPanel()
        // A disconnected scene may still own a pending or failed native stop.
        // Gate initial construction as well as explicit reopen; this container
        // must neither create a new bridge nor stop another container's owner.
        guard IOSPCMCapacitorPlugin.confirmProcessCaptureIdle() else {
            fail()
            return
        }
        guard let resources = Bundle.main.resourceURL,
              FileManager.default.fileExists(atPath: resources.appendingPathComponent("public/index.html").path) else {
            fail()
            return
        }
        let next = CosmasBridgeViewController(generation: recovery.generation)
        workspace = next
        next.onFailure = { [weak self, weak next] in
            guard let self, let next, self.workspace === next else { return }
            self.fail()
        }
        next.onSignal = { [weak self, weak next] signal, generation, mainFrame, sameOrigin in
            guard let self, let next, self.workspace === next,
                  self.recovery.receive(signal, generation: generation, mainFrame: mainFrame, sameOrigin: sameOrigin) else { return }
            if signal == .failed { self.showFailure() } else {
                self.sceneSignal?.ready(generation: generation, mainFrame: mainFrame, sameOrigin: sameOrigin)
                self.renderPanel()
                self.dispatchSceneSignal()
            }
        }
        addChild(next)
        next.view.translatesAutoresizingMaskIntoConstraints = false
        view.insertSubview(next.view, belowSubview: panel)
        // UIKit owns keyboard geometry. Resize the WebView once instead of
        // letting a document composer and the keyboard pan each other.
        let keyboard = view.keyboardLayoutGuide
        keyboard.followsUndockedKeyboard = false
        keyboard.usesBottomSafeArea = false
        keyboardBottom = next.view.bottomAnchor.constraint(equalTo: keyboard.topAnchor)
        restingBottom = next.view.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        NSLayoutConstraint.activate([
            next.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            next.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            next.view.topAnchor.constraint(equalTo: view.topAnchor),
            // Keep the guide attached from first layout so WebKit cannot also
            // pan the document while UIKit begins the first keyboard resize.
            keyboardBottom!,
        ])
        next.didMove(toParent: self)
    }

    private func fail() {
        guard recovery.fail() else { return }
        showFailure()
    }

    private func showFailure() {
        sceneSignal?.close()
        workspace?.quarantine()
        renderPanel()
        checkStop()
    }

    private func dispatchSceneSignal() {
        guard !sceneDisconnected, recovery.phase == .active,
              let active = sceneSignal?.pending, let workspace,
              workspace.notifySceneState(active: active, generation: recovery.generation) else { return }
        sceneSignal?.didDispatch(active, generation: recovery.generation)
    }

    private func checkStop() {
        guard recovery.beginStopCheck() else { return }
        renderPanel()
        // Retain both old plugins through physical stop and original source-proof closure.
        let retainedWorkspace = workspace
        let generation = recovery.generation
        stopTask = Task { [self, retainedWorkspace] in
            var verified = false
            do {
                if let retainedWorkspace {
                    verified = try await retainedWorkspace.stopForRendererLoss()
                } else {
                    // No workspace was constructed by this container.
                    verified = IOSPCMCapacitorPlugin.confirmProcessCaptureIdle()
                }
            } catch { verified = false }
            guard recovery.generation == generation else { return }
            recovery.finishStopCheck(idle: verified)
            stopTask = nil
            renderPanel()
        }
    }

    @objc private func retryStop() { checkStop() }

    @objc private func reopen() {
        guard !sceneDisconnected, recovery.canReopen else { return }
        // Another scene may have started capture since the earlier check.
        guard IOSPCMCapacitorPlugin.confirmProcessCaptureIdle() else {
            checkStop()
            return
        }
        workspace?.onFailure = nil
        workspace?.onSignal = nil
        workspace?.willMove(toParent: nil)
        workspace?.view.removeFromSuperview()
        workspace?.removeFromParent()
        workspace = nil
        openWorkspace()
    }

    private func buildPanel() {
        panel.backgroundColor = .systemBackground
        panel.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(panel)
        let scroll = UIScrollView()
        scroll.translatesAutoresizingMaskIntoConstraints = false
        panel.addSubview(scroll)
        let stack = UIStackView(arrangedSubviews: [titleLabel, explanationLabel, statusLabel, reopenButton, retryButton])
        stack.axis = .vertical
        stack.spacing = 20
        stack.translatesAutoresizingMaskIntoConstraints = false
        scroll.addSubview(stack)
        titleLabel.font = .preferredFont(forTextStyle: .title1)
        titleLabel.accessibilityTraits = .header
        for label in [titleLabel, explanationLabel, statusLabel] {
            label.numberOfLines = 0
            label.adjustsFontForContentSizeCategory = true
        }
        explanationLabel.font = .preferredFont(forTextStyle: .body)
        statusLabel.font = .preferredFont(forTextStyle: .body)
        reopenButton.setTitle("Reopen workspace", for: .normal)
        retryButton.setTitle("Check recording stopped", for: .normal)
        reopenButton.addTarget(self, action: #selector(reopen), for: .touchUpInside)
        retryButton.addTarget(self, action: #selector(retryStop), for: .touchUpInside)
        for button in [reopenButton, retryButton] {
            button.titleLabel?.font = .preferredFont(forTextStyle: .headline)
            button.titleLabel?.adjustsFontForContentSizeCategory = true
            button.titleLabel?.numberOfLines = 0
            button.heightAnchor.constraint(greaterThanOrEqualToConstant: 48).isActive = true
        }
        NSLayoutConstraint.activate([
            panel.leadingAnchor.constraint(equalTo: view.leadingAnchor), panel.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            panel.topAnchor.constraint(equalTo: view.topAnchor), panel.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            scroll.leadingAnchor.constraint(equalTo: panel.safeAreaLayoutGuide.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: panel.safeAreaLayoutGuide.trailingAnchor),
            scroll.topAnchor.constraint(equalTo: panel.safeAreaLayoutGuide.topAnchor),
            scroll.bottomAnchor.constraint(equalTo: panel.safeAreaLayoutGuide.bottomAnchor),
            stack.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 48),
            stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor, constant: -32),
            stack.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor, constant: -48),
        ])
    }

    private func renderPanel() {
        panel.isHidden = recovery.phase == .active
        guard recovery.phase != .active else { return }
        let failed = recovery.phase == .failed
        titleLabel.text = failed ? "Your workspace could not continue" : "Opening your workspace"
        explanationLabel.text = failed
            ? "Review any unconfirmed requests after reopening. Submitted work may still finish. Unsaved changes or the last part of a recording may be missing. Do not delete app data. If this keeps happening, close the app and contact your beta administrator."
            : "CosmasOS is opening your private workspace. Your local work has not been reset."
        switch recovery.stopState {
        case .unchecked: statusLabel.text = nil
        case .checking: statusLabel.text = "Checking that recording has stopped…"
        case .blocked: statusLabel.text = "Recording stop could not be confirmed. Stop recording in any other CosmasOS window, then check again. If it remains blocked, close the app."
        case .idle: statusLabel.text = "Recording is stopped. Reopen when you are ready, then review the capture for any gap."
        }
        reopenButton.isHidden = !failed
        reopenButton.isEnabled = recovery.canReopen && !sceneDisconnected
        retryButton.isHidden = recovery.stopState != .blocked
    }
}
