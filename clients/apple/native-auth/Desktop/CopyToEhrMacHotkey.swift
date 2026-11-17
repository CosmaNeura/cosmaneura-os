import AppKit
import Carbon
import CosmasNativeAuth
import Foundation

/// Carbon hotkey for Copy to EHR. RegisterEventHotKey does not ask for
/// Accessibility or Input Monitoring. Do not replace it with an NSEvent monitor.
@MainActor final class CopyToEhrMacHotkey {
    private let settings: CopyToEhrHotkeySettings
    private let tokenProvider: @MainActor () async throws -> String?
    private let writer = CopyToEhrPasteboardWriter(port: CopyToEhrGeneralPasteboard())
    private let panel = CopyToEhrConfirmationPanel()
    private var session = CopyToEhrHotkeySession()
    private var busy = false
    private var clearTask: Task<Void, Never>?

    init(settings: CopyToEhrHotkeySettings, token: @escaping @MainActor () async throws -> String?) {
        self.settings = settings
        self.tokenProvider = token
    }

    func install() -> Bool {
        let chords = settings.chords()
        guard let next = chords.next.carbonSpec(), let full = chords.full.carbonSpec() else { return false }
        return CopyToEhrCarbonHotkeys.install(owner: self, next: next, full: full)
    }

    func stop() {
        clearTask?.cancel()
        panel.close()
        CopyToEhrCarbonHotkeys.stop(owner: self)
    }

    func present(_ confirmation: String) { panel.show(confirmation) }

    fileprivate func handleHotkey(id: UInt32) {
        let kind: CopyToEhrCopyKind
        switch id {
        case CopyToEhrCarbonHotkey.nextID: kind = .nextSection
        case CopyToEhrCarbonHotkey.fullNoteID: kind = .fullNote
        default: return
        }
        guard !busy else { return }
        busy = true
        Task { @MainActor in
            defer { self.busy = false }
            await self.perform(kind)
        }
    }

    private func perform(_ kind: CopyToEhrCopyKind) async {
        guard settings.isEnabled else { return }
        guard let arm = settings.arm() else {
            panel.show(CopyToEhrCopyMessages.needsDraft)
            return
        }
        let bearer: String?
        do { bearer = try await tokenProvider() }
        catch {
            panel.show(CopyToEhrCopyMessages.refusal(.unavailable))
            return
        }
        guard let request = CopyToEhrDraftEndpoint.request(
            origin: arm.origin, draftID: arm.draftID, profile: arm.profile, revision: arm.revision, bearer: bearer
        ) else {
            panel.show(CopyToEhrCopyMessages.refusal(.unavailable))
            return
        }
        let loaded = await CopyToEhrDraftFetcher.load(request)
        let planned: Result<CopyToEhrCopyPlan, CopyToEhrCopyRefusal>
        switch loaded {
        case .stale:
            planned = .failure(.stale)
        case .unavailable:
            planned = .failure(.unavailable)
        case .data(let data):
            guard let package = CopyToEhrPackage.parse(data) else {
                planned = .failure(.unavailable)
                break
            }
            planned = session.plan(
                kind, package: package, enabled: true, expectedRevision: arm.revision,
                now: Date(), marker: UUID().uuidString.lowercased())
        }
        switch planned {
        case .failure(let refusal):
            let message = CopyToEhrCopyMessages.refusal(refusal)
            if !message.isEmpty { panel.show(message) }
        case .success(let plan):
            guard let receipt = writer.write(plan.outcome.item) else {
                panel.show(CopyToEhrCopyMessages.refusal(.unavailable))
                return
            }
            session.commit(plan)
            panel.show(plan.outcome.confirmation)
            scheduleClear(receipt)
        }
    }

    private func scheduleClear(_ receipt: CopyToEhrClipboardReceipt) {
        clearTask?.cancel()
        guard let seconds = settings.clearDelaySeconds else { return }
        clearTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(seconds))
            guard !Task.isCancelled else { return }
            self.writer.clearIfStillOurs(receipt)
        }
    }
}

private enum CopyToEhrCarbonHotkeys {
    nonisolated(unsafe) private static var eventHandler: EventHandlerRef?
    nonisolated(unsafe) private static var refs: [UInt32: EventHotKeyRef] = [:]
    nonisolated(unsafe) private static weak var owner: CopyToEhrMacHotkey?

    static func install(owner: CopyToEhrMacHotkey, next: CopyToEhrCarbonHotkeySpec, full: CopyToEhrCarbonHotkeySpec) -> Bool {
        stop(owner: owner)
        self.owner = owner
        guard installHandler(),
              register(id: CopyToEhrCarbonHotkey.nextID, spec: next),
              register(id: CopyToEhrCarbonHotkey.fullNoteID, spec: full) else {
            stop(owner: owner)
            return false
        }
        return true
    }

    static func stop(owner: CopyToEhrMacHotkey) {
        guard self.owner == nil || self.owner === owner else { return }
        for ref in refs.values { UnregisterEventHotKey(ref) }
        refs.removeAll()
        if let eventHandler {
            RemoveEventHandler(eventHandler)
            self.eventHandler = nil
        }
        self.owner = nil
    }

    static func deliver(_ id: UInt32) {
        // Carbon delivers this on the thread running the application event loop.
        MainActor.assumeIsolated { owner?.handleHotkey(id: id) }
    }

    private static func installHandler() -> Bool {
        if eventHandler != nil { return true }
        let specs = [EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))]
        let status = InstallEventHandler(GetEventDispatcherTarget(), copyToEhrHotkeyEventHandler, 1, specs, nil, &eventHandler)
        return status == noErr && eventHandler != nil
    }

    private static func register(id: UInt32, spec: CopyToEhrCarbonHotkeySpec) -> Bool {
        var ref: EventHotKeyRef?
        let hotKeyID = EventHotKeyID(signature: CopyToEhrCarbonHotkey.signature, id: id)
        let status = RegisterEventHotKey(spec.keyCode, spec.modifiers, hotKeyID, GetEventDispatcherTarget(), 0, &ref)
        guard status == noErr, let ref else { return false }
        refs[id] = ref
        return true
    }
}

private func copyToEhrHotkeyEventHandler(
    _: EventHandlerCallRef?, event: EventRef?, _: UnsafeMutableRawPointer?
) -> OSStatus {
    guard let event else { return OSStatus(eventNotHandledErr) }
    var hotKeyID = EventHotKeyID()
    let error = GetEventParameter(
        event, UInt32(kEventParamDirectObject), UInt32(typeEventHotKeyID), nil,
        MemoryLayout<EventHotKeyID>.size, nil, &hotKeyID)
    if error != noErr { return error }
    guard hotKeyID.signature == CopyToEhrCarbonHotkey.signature else { return OSStatus(eventNotHandledErr) }
    CopyToEhrCarbonHotkeys.deliver(hotKeyID.id)
    return noErr
}

private final class CopyToEhrGeneralPasteboard: CopyToEhrPasteboardPort {
    func writeLocalOnly(_ payload: CopyToEhrPasteboardPayload) -> Int? {
        guard payload.localOnly,
              payload.values[CopyToEhrPasteboardItem.concealedType] != nil,
              payload.values[CopyToEhrPasteboardItem.transientType] != nil else { return nil }
        let board = NSPasteboard.general
        // currentHostOnly keeps this paste on this Mac. No Universal Clipboard.
        board.prepareForNewContents(with: .currentHostOnly)
        let item = NSPasteboardItem()
        for type in [
            CopyToEhrPasteboardItem.stringType, CopyToEhrPasteboardItem.concealedType,
            CopyToEhrPasteboardItem.transientType, CopyToEhrPasteboardItem.markerType,
        ] {
            guard let value = payload.values[type] else { return nil }
            item.setString(value, forType: NSPasteboard.PasteboardType(type))
        }
        guard board.writeObjects([item]) else { return nil }
        return board.changeCount
    }

    func observe() -> CopyToEhrPasteboardObservation {
        let board = NSPasteboard.general
        return CopyToEhrPasteboardObservation(
            changeCount: board.changeCount,
            marker: board.string(forType: NSPasteboard.PasteboardType(CopyToEhrPasteboardItem.markerType)),
            text: board.string(forType: .string))
    }

    func clearLocalOnly() {
        let board = NSPasteboard.general
        board.prepareForNewContents(with: .currentHostOnly)
        board.clearContents()
    }
}

private enum CopyToEhrFetchBody {
    case data(Data)
    case stale
    case unavailable
}

private final class CopyToEhrNoRedirect: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(
        _ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

private enum CopyToEhrDraftFetcher {
    static func load(_ request: URLRequest) async -> CopyToEhrFetchBody {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCredentialStorage = nil
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        configuration.timeoutIntervalForRequest = 20
        configuration.timeoutIntervalForResource = 20
        let session = URLSession(configuration: configuration, delegate: CopyToEhrNoRedirect(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse, http.url == request.url else { return .unavailable }
            switch http.statusCode {
            case 200:
                guard data.count <= 2_000_000, let mime = http.mimeType, mime.hasPrefix("application/json") else {
                    return .unavailable
                }
                return .data(data)
            case 409:
                return .stale
            default:
                return .unavailable
            }
        } catch {
            return .unavailable
        }
    }
}

@MainActor private final class CopyToEhrConfirmationPanel: NSObject {
    private let panel = NSPanel(
        contentRect: NSRect(x: 0, y: 0, width: 460, height: 120),
        styleMask: [.titled, .nonactivatingPanel], backing: .buffered, defer: false)
    private let label = NSTextField(wrappingLabelWithString: " ")
    private var dismiss: Task<Void, Never>?

    override init() {
        super.init()
        panel.title = "Copy to EHR"
        panel.isFloatingPanel = true
        panel.level = .statusBar
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        label.frame = NSRect(x: 20, y: 18, width: 420, height: 72)
        panel.contentView?.addSubview(label)
    }

    func show(_ confirmation: String) {
        guard !confirmation.isEmpty else { return }
        label.stringValue = confirmation
        panel.center()
        panel.orderFrontRegardless()
        dismiss?.cancel()
        dismiss = Task { @MainActor in
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled else { return }
            self.panel.orderOut(nil)
        }
    }

    func close() {
        dismiss?.cancel()
        panel.orderOut(nil)
    }
}
