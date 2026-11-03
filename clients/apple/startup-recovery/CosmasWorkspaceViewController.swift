import UIKit
import CosmaneuraIOSPCMCapacitor
#if canImport(CosmasWorkspaceAuthPlugin)
import CosmasWorkspaceAuthPlugin
#endif
#if canImport(CosmasNativeAuth)
import CosmasNativeAuth
#endif

/// A native surface stays available even when JavaScript or the WebView fails.
@MainActor final class CosmasWorkspaceViewController: UIViewController {
    private var recovery = WorkspaceRecoveryState()
    private var sceneSignal: WorkspaceSceneSignalState?
    private var workspace: CosmasBridgeViewController?
    private var sceneActive = false
    private var sceneDisconnected = false
    private var timer: Timer?
    private var stopTask: Task<Void, Never>?
    private var practiceTransitionPending = false
    private var practiceSourcesClosed = false
    #if canImport(CosmasNativeAuth)
    private var registeredPracticeActive = false
    private var registeredPracticeSnapshot: NativePracticeActiveWorkspaceSnapshot?
    private var resumeAccountEntry = false
    #endif
    #if canImport(CosmasWorkspaceAuthPlugin) && canImport(CosmasNativeAuth)
    private var practiceHost: NativePracticeConnectionController?
    private var practiceHydration: Task<Void, Never>?
    private var practiceStartupFailed = false
    #endif
    private var keyboardBottom: NSLayoutConstraint?
    private var restingBottom: NSLayoutConstraint?
    private let keyboardDismissBar = UIView()
    private let keyboardDoneButton = UIButton(type: .system)
    private var keyboardDismissHeight: NSLayoutConstraint?
    private let panel = UIView()
    private let titleLabel = UILabel()
    private let explanationLabel = UILabel()
    private let statusLabel = UILabel()
    private let reopenButton = UIButton(type: .system)
    private let retryButton = UIButton(type: .system)
    private let returnToBetaButton = UIButton(type: .system)
    private let practiceSignInButton = UIButton(type: .system)

    // The shipped workspace header is light in both layouts. A future dark
    // palette must change its status style together with its surface tokens.
    override var preferredStatusBarStyle: UIStatusBarStyle { .darkContent }

    override func viewDidLoad() {
        super.viewDidLoad()
        overrideUserInterfaceStyle = .light
        view.backgroundColor = .systemBackground
        // Debug synthetic Simulator only: local invented demo rows (no network,
        // no sign-in). Compiled out of Release/TestFlight (DEBUG condition only).
        #if DEBUG
        if CosmasSyntheticDemoSurface.isEnabled {
            let surface = CosmasSyntheticDemoSurface()
            addChild(surface)
            surface.view.frame = view.bounds
            surface.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
            view.addSubview(surface.view)
            surface.didMove(toParent: self)
            return
        }
        #endif
        buildPanel()
        buildKeyboardDismissal()
        NotificationCenter.default.addObserver(self, selector: #selector(keyboardWillShow(_:)),
            name: UIResponder.keyboardWillShowNotification, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(keyboardDidHide(_:)),
            name: UIResponder.keyboardDidHideNotification, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(updateKeyboardDismissalSize),
            name: UIContentSizeCategory.didChangeNotification, object: nil)
        openInitialWorkspace()
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
        keyboardDismissBar.isHidden = false
        updateKeyboardDismissalSize()
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
        keyboardDismissBar.isHidden = true
        updateKeyboardDismissalSize()
        keyboardBottom?.isActive = false
        restingBottom?.isActive = true
    }

    private func buildKeyboardDismissal() {
        // WebKit's system accessory is not consistently available on the phone.
        // Keep one explicit native dismissal action beside the existing resize owner.
        keyboardDismissBar.translatesAutoresizingMaskIntoConstraints = false
        keyboardDismissBar.backgroundColor = .systemBackground
        keyboardDismissBar.isHidden = true
        view.addSubview(keyboardDismissBar)
        keyboardDoneButton.translatesAutoresizingMaskIntoConstraints = false
        keyboardDoneButton.setTitle("Done", for: .normal)
        keyboardDoneButton.accessibilityIdentifier = "cosmas.keyboard.done"
        keyboardDoneButton.accessibilityHint = "Hides the keyboard. Your draft is kept."
        keyboardDoneButton.titleLabel?.adjustsFontForContentSizeCategory = true
        keyboardDoneButton.addTarget(self, action: #selector(dismissKeyboard), for: .touchUpInside)
        keyboardDismissBar.addSubview(keyboardDoneButton)
        let separator = UIView()
        separator.translatesAutoresizingMaskIntoConstraints = false
        separator.backgroundColor = .separator
        keyboardDismissBar.addSubview(separator)
        keyboardDismissHeight = keyboardDismissBar.heightAnchor.constraint(equalToConstant: 0)
        NSLayoutConstraint.activate([
            keyboardDismissBar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            keyboardDismissBar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            keyboardDismissBar.bottomAnchor.constraint(equalTo: view.keyboardLayoutGuide.topAnchor),
            keyboardDismissHeight!,
            keyboardDoneButton.trailingAnchor.constraint(equalTo: keyboardDismissBar.safeAreaLayoutGuide.trailingAnchor, constant: -12),
            keyboardDoneButton.topAnchor.constraint(equalTo: keyboardDismissBar.topAnchor),
            keyboardDoneButton.bottomAnchor.constraint(equalTo: keyboardDismissBar.bottomAnchor),
            keyboardDoneButton.widthAnchor.constraint(greaterThanOrEqualToConstant: 64),
            separator.leadingAnchor.constraint(equalTo: keyboardDismissBar.leadingAnchor),
            separator.trailingAnchor.constraint(equalTo: keyboardDismissBar.trailingAnchor),
            separator.topAnchor.constraint(equalTo: keyboardDismissBar.topAnchor),
            separator.heightAnchor.constraint(equalToConstant: 1 / traitCollection.displayScale),
        ])
        updateKeyboardDismissalSize()
    }

    @objc private func updateKeyboardDismissalSize() {
        let font = UIFont.preferredFont(forTextStyle: .body)
        keyboardDoneButton.titleLabel?.font = font
        keyboardDismissHeight?.constant = keyboardDismissBar.isHidden ? 0 : max(44, ceil(font.lineHeight + 16))
    }

    @objc private func dismissKeyboard() {
        // Resigning focus preserves the current draft and never submits the form.
        view.endEditing(true)
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
        #if canImport(CosmasWorkspaceAuthPlugin) && canImport(CosmasNativeAuth)
        practiceHydration?.cancel()
        #endif
        fail()
    }

    private func tick() {
        if recovery.tick(now: ProcessInfo.processInfo.systemUptime, sceneActive: sceneActive) { showFailure() }
    }

    private func openInitialWorkspace() {
        #if canImport(CosmasWorkspaceAuthPlugin) && canImport(CosmasNativeAuth)
        do {
            let scene = NativePracticeSceneTransition(prepareAccountRealm: { [weak self] in
                guard let self else { throw NativePracticeProfileError.unavailable }
                try await self.prepareAccountRealm()
            }, replaceRenderer: { [weak self] snapshot in
                guard let self else { throw NativePracticeProfileError.unavailable }
                try await self.replaceRenderer(snapshot)
            })
            let host: NativePracticeConnectionController
            if let installed = CosmasNativePracticeConnectionPlugin.installedHost {
                guard let current = installed as? NativePracticeConnectionController else {
                    throw NativePracticeProfileError.invalidBinding
                }
                practiceHost = current
                try current.rebindScene(scene); host = current
            } else {
                // Invalid optional setup configuration cannot wall marker-free
                // beta users. The controller still checks its new encrypted
                // selection item; a marked user never falls back to Beta.
                let configuration = try? NativePracticeBundleConfiguration.load(bundle: .main)
                host = try NativePracticeConnectionController(configuration: configuration, scene: scene)
                try CosmasNativePracticeConnectionPlugin.install(host: host)
                practiceHost = host
            }
            practiceStartupFailed = false
            if host.shouldResumeAccountSetup {
                resumeAccountEntry = true; registeredPracticeActive = false
                openWorkspace(); return
            }
            if host.isRegisteredPracticeActive {
                registeredPracticeActive = true
                hydratePractice(replacing: false); return
            }
        } catch { practiceStartupFailed = true; fail(); return }
        #endif
        openWorkspace()
    }

    #if canImport(CosmasWorkspaceAuthPlugin) && canImport(CosmasNativeAuth)
    private func hydratePractice(replacing: Bool) {
        guard practiceHydration == nil, !sceneDisconnected, let host = practiceHost else { return }
        let expectedWorkspace = workspace
        let generation = recovery.generation
        let phase = recovery.phase
        practiceHydration = Task { [weak self, host, expectedWorkspace] in
            guard let self else { return }
            defer { self.practiceHydration = nil; self.renderPanel() }
            do {
                let snapshot = try await host.currentSnapshot()
                guard !self.sceneDisconnected, self.workspace === expectedWorkspace,
                      self.recovery.generation == generation, self.recovery.phase == phase,
                      host.isRegisteredPracticeActive, let snapshot else {
                    throw NativePracticeProfileError.unavailable
                }
                try snapshot.validateCurrentBinding()
                self.registeredPracticeSnapshot = snapshot
                self.registeredPracticeActive = true; self.resumeAccountEntry = false
                if replacing { self.discardWorkspace() }
                self.openWorkspace()
            } catch {
                if !self.sceneDisconnected, self.workspace === expectedWorkspace, self.recovery.generation == generation { self.fail() }
            }
        }
        renderPanel()
    }
    #endif

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
        #if canImport(CosmasNativeAuth)
        if resumeAccountEntry {
            do { try next.prepareAccountEntry() }
            catch { fail(); return }
        } else if registeredPracticeActive {
            // A registered practice never reopens with the compiled beta graph.
            guard let snapshot = registeredPracticeSnapshot else { fail(); return }
            do { try next.prepareRegisteredPractice(snapshot) }
            catch { fail(); return }
        }
        #endif
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
        keyboardBottom = next.view.bottomAnchor.constraint(equalTo: keyboardDismissBar.topAnchor)
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

    #if canImport(CosmasNativeAuth)
    /// Called only by the complete native host after the actual account sign-in
    /// action. Its scene callback closes original sources without disabling the
    /// account-only document. The host retires/reconfigures SDK ownership after.
    func prepareAccountRealm() async throws {
        guard !sceneDisconnected, !practiceTransitionPending, stopTask == nil else { throw NativePracticeProfileError.busy }
        if practiceSourcesClosed { return }
        guard let selected = workspace else {
            // Marked startup recovery may need an explicit Beta return before
            // any renderer exists. The host separately checks process custody.
            guard IOSPCMCapacitorPlugin.confirmProcessCaptureIdle() else { throw NativePracticeProfileError.busy }
            practiceSourcesClosed = true; return
        }
        practiceTransitionPending = true
        defer { practiceTransitionPending = false }
        let generation = recovery.generation
        guard try await selected.stopForPracticeConnection(), !sceneDisconnected,
              workspace === selected, recovery.generation == generation,
              IOSPCMCapacitorPlugin.confirmProcessCaptureIdle() else {
            throw NativePracticeProfileError.unavailable
        }
        practiceSourcesClosed = true
    }

    /// The host already installed/admitted the immutable graph. Replace only
    /// this scene's renderer; no URL or renderer-provided profile is accepted.
    func replaceRenderer(_ snapshot: NativePracticeActiveWorkspaceSnapshot?) async throws {
        guard !sceneDisconnected, !practiceTransitionPending, stopTask == nil else {
            throw NativePracticeProfileError.busy
        }
        practiceTransitionPending = true
        defer { practiceTransitionPending = false }
        let retained = workspace
        if let retained {
            guard try await retained.stopForRendererLoss(), !sceneDisconnected,
                  workspace === retained else { throw NativePracticeProfileError.unavailable }
        }
        guard IOSPCMCapacitorPlugin.confirmProcessCaptureIdle() else { throw NativePracticeProfileError.busy }
        // Source closure can suspend. A late sign-out or SID/revision change
        // cannot inject a formerly valid profile into a replacement document.
        try snapshot?.validateCurrentBinding()
        sceneSignal?.close()
        keyboardBottom?.isActive = false; restingBottom?.isActive = false
        retained?.onFailure = nil; retained?.onSignal = nil
        retained?.willMove(toParent: nil); retained?.view.removeFromSuperview(); retained?.removeFromParent()
        workspace = nil
        registeredPracticeActive = snapshot != nil
        registeredPracticeSnapshot = snapshot
        resumeAccountEntry = false
        practiceSourcesClosed = false
        openWorkspace()
        guard workspace != nil, recovery.phase != .failed else { throw NativePracticeProfileError.unavailable }
    }
    #endif

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
        #if canImport(CosmasWorkspaceAuthPlugin) && canImport(CosmasNativeAuth)
        if practiceStartupFailed { discardWorkspace(); openInitialWorkspace(); return }
        if let host = practiceHost {
            if host.shouldResumeAccountSetup {
                discardWorkspace(); resumeAccountEntry = true; registeredPracticeActive = false
                openWorkspace(); return
            }
            if host.isRegisteredPracticeActive { hydratePractice(replacing: true); return }
        }
        #endif
        discardWorkspace()
        openWorkspace()
    }

    private func discardWorkspace() {
        workspace?.onFailure = nil; workspace?.onSignal = nil
        workspace?.willMove(toParent: nil); workspace?.view.removeFromSuperview(); workspace?.removeFromParent()
        workspace = nil
    }

    @objc private func returnToExistingBeta() {
        #if canImport(CosmasWorkspaceAuthPlugin) && canImport(CosmasNativeAuth)
        guard !sceneDisconnected, practiceHydration == nil, let host = practiceHost else { return }
        practiceHydration = Task { [weak self, host] in
            guard let self else { return }
            defer { self.practiceHydration = nil; self.renderPanel() }
            do {
                let state = try await host.accountStatus()
                try await host.returnToBeta(expectedRevision: state.revision)
            } catch { self.fail() }
        }
        renderPanel()
        #endif
    }

    @objc private func signInToSavedPractice() {
        #if canImport(CosmasWorkspaceAuthPlugin) && canImport(CosmasNativeAuth)
        guard !sceneDisconnected, practiceHydration == nil, let host = practiceHost, host.available else { return }
        practiceHydration = Task { [weak self, host] in
            guard let self else { return }
            defer { self.practiceHydration = nil; self.renderPanel() }
            do {
                let account = try await host.beginAccountSignIn()
                guard !self.sceneDisconnected, account.phase == .accountReady else {
                    throw NativePracticeProfileError.unavailable
                }
                self.discardWorkspace()
                self.resumeAccountEntry = true; self.registeredPracticeActive = false
                self.openWorkspace()
            } catch { self.fail() }
        }
        renderPanel()
        #endif
    }

    private func buildPanel() {
        panel.backgroundColor = .systemBackground
        panel.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(panel)
        let scroll = UIScrollView()
        scroll.translatesAutoresizingMaskIntoConstraints = false
        panel.addSubview(scroll)
        let stack = UIStackView(arrangedSubviews: [titleLabel, explanationLabel, statusLabel, reopenButton, retryButton, practiceSignInButton, returnToBetaButton])
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
        returnToBetaButton.setTitle("Return to existing workspace", for: .normal)
        returnToBetaButton.isHidden = true
        practiceSignInButton.setTitle("Sign in to this practice", for: .normal)
        practiceSignInButton.isHidden = true
        reopenButton.addTarget(self, action: #selector(reopen), for: .touchUpInside)
        retryButton.addTarget(self, action: #selector(retryStop), for: .touchUpInside)
        returnToBetaButton.addTarget(self, action: #selector(returnToExistingBeta), for: .touchUpInside)
        practiceSignInButton.addTarget(self, action: #selector(signInToSavedPractice), for: .touchUpInside)
        for button in [reopenButton, retryButton, returnToBetaButton, practiceSignInButton] {
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
        #if canImport(CosmasWorkspaceAuthPlugin) && canImport(CosmasNativeAuth)
        let practiceRecovery = practiceHost.map { $0.isRegisteredPracticeActive || $0.shouldResumeAccountSetup } ?? false
        let practiceBusy = practiceHydration != nil
        returnToBetaButton.isHidden = !failed || !practiceRecovery
        returnToBetaButton.isEnabled = !sceneDisconnected && !practiceBusy && stopTask == nil
        practiceSignInButton.isHidden = !failed || !practiceRecovery || practiceHost?.available != true
        practiceSignInButton.isEnabled = !sceneDisconnected && !practiceBusy && stopTask == nil
        reopenButton.isEnabled = reopenButton.isEnabled && !practiceBusy
        if practiceRecovery {
            titleLabel.text = practiceBusy ? "Reconnecting your practice" : failed ? "Your practice needs a connection" : "Opening your practice"
            explanationLabel.text = "Your saved local work is kept. Reconnect this practice or return to your existing workspace."
            if practiceBusy { statusLabel.text = "Checking your secure practice connection…" }
        }
        #endif
    }
}

#if DEBUG
/// Debug + `com.cosmasos.synthetic` only. Local invented Chief rows and visit
/// timer — no network, no secrets, no sign-in. Entire type is compiled out of
/// Release so TestFlight/production binaries cannot reach it.
@MainActor final class CosmasSyntheticDemoSurface: UIViewController {
    /// Optional XCUITest opt-in; Debug synthetic also enables without it.
    static let launchArgument = "-COSMAS_UI_TEST_FIXTURES"

    static var isEnabled: Bool {
        Bundle.main.bundleIdentifier == "com.cosmasos.synthetic"
    }

    /// Proof hook for unit tests: this type exists only under DEBUG.
    static let isCompiledIntoThisBinary = true

    private let elapsedLabel = UILabel()
    private let startButton = UIButton(type: .system)
    private let stopButton = UIButton(type: .system)
    private let chiefList = UIStackView()
    private var visitTimer: Timer?
    private var startedAt: TimeInterval?
    private var frozenElapsed: TimeInterval = 0

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        view.accessibilityIdentifier = "cosmas.uiTest.surface"

        let title = UILabel()
        title.text = "Synthetic demo"
        title.font = .preferredFont(forTextStyle: .title2)
        title.adjustsFontForContentSizeCategory = true

        elapsedLabel.font = .monospacedDigitSystemFont(ofSize: 28, weight: .semibold)
        elapsedLabel.text = format(0)
        elapsedLabel.accessibilityIdentifier = "cosmas.visit.timer.elapsed"
        // Visible text is the a11y label so XCUITest can assert elapsed time.
        elapsedLabel.isAccessibilityElement = true

        startButton.setTitle("Start visit timer", for: .normal)
        startButton.accessibilityIdentifier = "cosmas.visit.timer.start"
        startButton.addTarget(self, action: #selector(startTimer), for: .touchUpInside)
        stopButton.setTitle("Stop visit timer", for: .normal)
        stopButton.accessibilityIdentifier = "cosmas.visit.timer.stop"
        stopButton.isEnabled = false
        stopButton.addTarget(self, action: #selector(stopTimer), for: .touchUpInside)
        for button in [startButton, stopButton] {
            button.titleLabel?.font = .preferredFont(forTextStyle: .headline)
            button.titleLabel?.adjustsFontForContentSizeCategory = true
            button.heightAnchor.constraint(greaterThanOrEqualToConstant: 48).isActive = true
        }

        let chiefHeading = UILabel()
        chiefHeading.text = "Chief"
        chiefHeading.font = .preferredFont(forTextStyle: .headline)
        chiefHeading.adjustsFontForContentSizeCategory = true
        chiefHeading.accessibilityIdentifier = "cosmas.messages.chief.group"

        chiefList.axis = .vertical
        chiefList.spacing = 8
        chiefList.accessibilityIdentifier = "cosmas.messages.chief.list"
        // Invented patient-chat engagements under the Chief group.
        for label in ["Invented sleep notebook", "Invented annual visit"] {
            chiefList.addArrangedSubview(makeChiefRow(context: label))
        }

        let stack = UIStackView(arrangedSubviews: [
            title, elapsedLabel, startButton, stopButton, chiefHeading, chiefList,
        ])
        stack.axis = .vertical
        stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 32),
        ])
    }

    private func makeChiefRow(context: String) -> UIView {
        let row = UIStackView()
        row.axis = .horizontal
        row.spacing = 12
        row.alignment = .center
        row.accessibilityIdentifier = "cosmas.messages.chief.row"

        let icon = UIImageView(image: UIImage(systemName: "person.crop.circle.fill"))
        icon.tintColor = .systemGreen
        icon.accessibilityIdentifier = "cosmas.messages.chief.icon"
        icon.accessibilityLabel = "Chief of Staff"
        icon.isAccessibilityElement = true
        icon.widthAnchor.constraint(equalToConstant: 36).isActive = true
        icon.heightAnchor.constraint(equalToConstant: 36).isActive = true

        let text = UILabel()
        text.text = context
        text.font = .preferredFont(forTextStyle: .body)
        text.adjustsFontForContentSizeCategory = true
        text.numberOfLines = 0

        // Exactly one Chief icon per row — no duplicate name badge beside it.
        row.addArrangedSubview(icon)
        row.addArrangedSubview(text)
        return row
    }

    @objc private func startTimer() {
        guard startedAt == nil else { return }
        frozenElapsed = 0
        startedAt = ProcessInfo.processInfo.systemUptime
        startButton.isEnabled = false
        stopButton.isEnabled = true
        visitTimer?.invalidate()
        visitTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.renderElapsed() }
        }
        renderElapsed()
    }

    @objc private func stopTimer() {
        guard let startedAt else { return }
        frozenElapsed = ProcessInfo.processInfo.systemUptime - startedAt
        self.startedAt = nil
        visitTimer?.invalidate()
        visitTimer = nil
        startButton.isEnabled = true
        stopButton.isEnabled = false
        elapsedLabel.text = format(frozenElapsed)
    }

    private func renderElapsed() {
        guard let startedAt else { return }
        elapsedLabel.text = format(ProcessInfo.processInfo.systemUptime - startedAt)
    }

    private func format(_ value: TimeInterval) -> String {
        let total = max(0, Int(value))
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    deinit {
        visitTimer?.invalidate()
    }
}
#else
/// Release/TestFlight: demo surface is not compiled in. Keep a named hook so
/// source audits and tests can prove the Debug-only gate without shipping UI.
enum CosmasSyntheticDemoSurface {
    static let isCompiledIntoThisBinary = false
    static var isEnabled: Bool { false }
}
#endif
