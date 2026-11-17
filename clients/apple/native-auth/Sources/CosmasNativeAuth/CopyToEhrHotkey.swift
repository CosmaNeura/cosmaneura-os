import CoreFoundation
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// Clipboard paste for one reviewed Copy to EHR draft.
/// The clinician presses Paste. This type never types into another app.
public enum CopyToEhrCopyKind: Equatable, Sendable {
    case nextSection
    case fullNote
}

public enum CopyToEhrCopyRefusal: Equatable, Error, Sendable {
    case flagOff
    case expired
    case stale
    case unavailable
}

public enum CopyToEhrCopyMessages {
    public static let needsDraft = "Open a Copy to EHR draft first."
    public static let hotkeyUnavailable = "Copy to EHR hotkey is unavailable."

    public static func confirmation(copiedName: String, notSent: Bool) -> String {
        let lead = notSent ? "This note was not sent. " : ""
        return lead + "Copied \(copiedName). Press Paste in the chart yourself."
    }

    public static func refusal(_ refusal: CopyToEhrCopyRefusal) -> String {
        switch refusal {
        case .flagOff:
            return ""
        case .expired:
            return "This copy session expired. Reopen Copy to EHR."
        case .stale:
            return "This draft changed. Reopen Copy to EHR."
        case .unavailable:
            return "Copy to EHR is unavailable."
        }
    }
}

public enum CopyToEhrWording {
    /// Clinician-facing copy stays copy and paste. Whole-word check only.
    public static func isCopyOnly(_ text: String) -> Bool {
        let folded = text.lowercased()
        if folded.contains("integration") || folded.contains("auto-entry") || folded.contains("auto entry") {
            return false
        }
        return folded.range(of: #"\bsync\b"#, options: .regularExpression) == nil
    }

    /// A server label that fails the copy-only check is not shown. Position is 1-based.
    public static func sectionDisplayName(label: String, position: Int) -> String {
        guard isCopyOnly(label) else { return "Section \(position)" }
        return label
    }
}

public struct CopyToEhrSection: Equatable, Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    public var key: String
    public var label: String
    public var text: String

    public init(key: String, label: String, text: String) {
        self.key = key
        self.label = label
        self.text = text
    }

    public var description: String { "CopyToEhrSection(key: \(key), bytes: \(text.utf8.count))" }
    public var debugDescription: String { description }
}

public struct CopyToEhrPackage: Equatable, Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    public var profileID: String
    public var draftID: String
    public var draftRevision: String
    public var payloadHash: String
    public var sections: [CopyToEhrSection]
    public var extras: [CopyToEhrSection]
    public var fullNote: String
    public var sectionNotes: [String: String]
    public var createdAt: Date
    public var expiresAt: Date
    public var reviewState: String
    public var visitStatus: String

    public var notSent: Bool { visitStatus == "not_sent_copy_instead" }

    public var description: String {
        "CopyToEhrPackage(draftID: \(draftID), sections: \(sections.count), bytes: \(fullNote.utf8.count))"
    }
    public var debugDescription: String { description }

    public static func parse(_ data: Data) -> CopyToEhrPackage? {
        guard data.count <= 2_000_000,
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == packageKeys,
              let profileID = bounded(object["profile_id"], limit: 64),
              let draftID = bounded(object["draft_id"], limit: 200),
              let draftRevision = bounded(object["draft_revision"], limit: 200),
              let payloadHash = object["payload_hash"] as? String, isLowerHex(payloadHash, count: 64),
              let sectionRows = object["sections"] as? [Any], (1...100).contains(sectionRows.count),
              let extraRows = object["extras"] as? [Any], extraRows.count <= 20,
              let fullNote = object["full_note"] as? String, fullNote.utf8.count <= 1_048_576,
              !hasHashLine(fullNote),
              let noteObject = object["section_notes"] as? [String: Any],
              let createdAt = timestamp(object["created_at"]),
              let expiresAt = timestamp(object["expires_at"]),
              let reviewState = bounded(object["review_state"], limit: 64),
              let visitStatus = object["visit_copy_to_ehr_status"] as? String,
              visitStatus == "unset" || visitStatus == "not_sent_copy_instead" else { return nil }

        var seen: Set<String> = []
        var sections: [CopyToEhrSection] = []
        for row in sectionRows {
            guard let section = parseSection(row, extra: false), seen.insert(section.key).inserted else { return nil }
            sections.append(section)
        }
        var extras: [CopyToEhrSection] = []
        for row in extraRows {
            guard let section = parseSection(row, extra: true), seen.insert(section.key).inserted else { return nil }
            extras.append(section)
        }
        var sectionNotes: [String: String] = [:]
        for section in sections {
            guard let note = noteObject[section.key] as? String, note.utf8.count <= 262_144, !hasHashLine(note) else {
                return nil
            }
            sectionNotes[section.key] = note
        }
        guard noteObject.count == sections.count else { return nil }
        return CopyToEhrPackage(
            profileID: profileID, draftID: draftID, draftRevision: draftRevision, payloadHash: payloadHash,
            sections: sections, extras: extras, fullNote: fullNote, sectionNotes: sectionNotes,
            createdAt: createdAt, expiresAt: expiresAt, reviewState: reviewState, visitStatus: visitStatus)
    }

    private static let packageKeys: Set<String> = [
        "profile_id", "draft_id", "draft_revision", "payload_hash", "sections", "extras",
        "created_at", "expires_at", "review_state", "visit_copy_to_ehr_status", "full_note", "section_notes",
    ]
    private static let extraKeys: Set<String> = ["patient_instructions", "orders"]

    private static func parseSection(_ row: Any, extra: Bool) -> CopyToEhrSection? {
        guard let object = row as? [String: Any], Set(object.keys) == ["key", "label", "text"],
              let key = bounded(object["key"], limit: 200),
              let label = bounded(object["label"], limit: 200),
              !label.contains("\n"), !label.contains("\r"), !label.hasPrefix("#"),
              let text = object["text"] as? String, text.utf8.count <= 262_144, !hasHashLine(text) else { return nil }
        let isExtra = extraKeys.contains(key)
        guard isExtra == extra else { return nil }
        return CopyToEhrSection(key: key, label: label, text: text)
    }

    private static func bounded(_ value: Any?, limit: Int) -> String? {
        guard let text = value as? String, !text.isEmpty, text.utf8.count <= limit else { return nil }
        return text
    }

    private static func hasHashLine(_ text: String) -> Bool {
        if text.hasPrefix("#") { return true }
        return text.split(separator: "\n", omittingEmptySubsequences: false).contains { $0.hasPrefix("#") }
    }

    private static func isLowerHex(_ text: String, count: Int) -> Bool {
        guard text.count == count else { return false }
        return text.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }

    private static func timestamp(_ value: Any?) -> Date? {
        guard let text = value as? String, text.count <= 64 else { return nil }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime]
        if let date = parser.date(from: text) { return date }
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return parser.date(from: text)
    }
}

public struct CopyToEhrPasteboardItem: Equatable, Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    public static let stringType = "public.utf8-plain-text"
    public static let concealedType = "org.nspasteboard.ConcealedType"
    public static let transientType = "org.nspasteboard.TransientType"
    public static let markerType = "com.cosmasos.copy-to-ehr.marker"

    public var text: String
    public var marker: String
    public var localOnly: Bool
    public var stringType: String
    public var concealedType: String
    public var transientType: String
    public var markerType: String

    public static func make(text: String, marker: String) -> CopyToEhrPasteboardItem {
        CopyToEhrPasteboardItem(
            text: text, marker: marker, localOnly: true,
            stringType: stringType, concealedType: concealedType,
            transientType: transientType, markerType: markerType)
    }

    public var matchesRequiredFlags: Bool {
        localOnly && stringType == Self.stringType && concealedType == Self.concealedType
            && transientType == Self.transientType && markerType == Self.markerType && !marker.isEmpty
    }

    public var description: String { "CopyToEhrPasteboardItem(localOnly: \(localOnly), bytes: \(text.utf8.count))" }
    public var debugDescription: String { description }
}

/// Local-only pasteboard values. Concealed and transient types are present and empty.
public struct CopyToEhrPasteboardPayload: Equatable, Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    public var localOnly: Bool
    public var values: [String: String]

    public static func make(_ item: CopyToEhrPasteboardItem) -> CopyToEhrPasteboardPayload? {
        guard item.matchesRequiredFlags else { return nil }
        return CopyToEhrPasteboardPayload(localOnly: true, values: [
            item.stringType: item.text,
            item.concealedType: "",
            item.transientType: "",
            item.markerType: item.marker,
        ])
    }

    public var description: String {
        let bytes = values[CopyToEhrPasteboardItem.stringType]?.utf8.count ?? 0
        let concealed = values[CopyToEhrPasteboardItem.concealedType] != nil
        let transient = values[CopyToEhrPasteboardItem.transientType] != nil
        return "CopyToEhrPasteboardPayload(localOnly: \(localOnly), bytes: \(bytes), concealed: \(concealed), transient: \(transient))"
    }
    public var debugDescription: String { description }
}

public struct CopyToEhrPasteboardObservation: Equatable, Sendable {
    public var changeCount: Int
    public var marker: String?
    public var text: String?

    public init(changeCount: Int, marker: String?, text: String?) {
        self.changeCount = changeCount
        self.marker = marker
        self.text = text
    }
}

public struct CopyToEhrClipboardReceipt: Equatable, Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    public var marker: String
    public var text: String
    public var changeCount: Int

    public init(marker: String, text: String, changeCount: Int) {
        self.marker = marker
        self.text = text
        self.changeCount = changeCount
    }

    public var description: String { "CopyToEhrClipboardReceipt(changeCount: \(changeCount), bytes: \(text.utf8.count))" }
    public var debugDescription: String { description }
}

public enum CopyToEhrClearDecision: Equatable, Sendable {
    case clear
    case keep

    /// Clear only while the pasteboard still holds the text we wrote.
    public static func decide(receipt: CopyToEhrClipboardReceipt, observed: CopyToEhrPasteboardObservation) -> CopyToEhrClearDecision {
        guard observed.changeCount == receipt.changeCount, observed.marker == receipt.marker, observed.text == receipt.text else {
            return .keep
        }
        return .clear
    }
}

public protocol CopyToEhrPasteboardPort: AnyObject {
    func writeLocalOnly(_ payload: CopyToEhrPasteboardPayload) -> Int?
    func observe() -> CopyToEhrPasteboardObservation
    func clearLocalOnly()
}

public final class CopyToEhrPasteboardWriter {
    private let port: any CopyToEhrPasteboardPort

    public init(port: any CopyToEhrPasteboardPort) { self.port = port }

    public func write(_ item: CopyToEhrPasteboardItem) -> CopyToEhrClipboardReceipt? {
        guard let payload = CopyToEhrPasteboardPayload.make(item), payload.localOnly,
              let changeCount = port.writeLocalOnly(payload) else { return nil }
        return CopyToEhrClipboardReceipt(marker: item.marker, text: item.text, changeCount: changeCount)
    }

    public func clearIfStillOurs(_ receipt: CopyToEhrClipboardReceipt) {
        guard CopyToEhrClearDecision.decide(receipt: receipt, observed: port.observe()) == .clear else { return }
        port.clearLocalOnly()
    }
}

public struct CopyToEhrCopyOutcome: Equatable, Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    public var confirmation: String
    public var copiedName: String
    public var item: CopyToEhrPasteboardItem
    public var highlightIndex: Int

    public var description: String { "CopyToEhrCopyOutcome(highlight: \(highlightIndex), bytes: \(item.text.utf8.count))" }
    public var debugDescription: String { description }
}

public struct CopyToEhrCopyPlan: Equatable, Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    public var outcome: CopyToEhrCopyOutcome
    public var nextIndex: Int
    public var payloadHash: String

    public var description: String { "CopyToEhrCopyPlan(highlight: \(nextIndex))" }
    public var debugDescription: String { description }
}

public struct CopyToEhrHotkeySession: Equatable, Sendable {
    public private(set) var highlightIndex: Int
    public private(set) var payloadHash: String?

    public init() {
        highlightIndex = 0
        payloadHash = nil
    }

    public func highlightedKey(in package: CopyToEhrPackage) -> String? {
        let index = resolvedIndex(in: package)
        guard package.sections.indices.contains(index) else { return nil }
        return package.sections[index].key
    }

    /// Plans a copy without moving the highlight. Commit after the pasteboard write succeeds.
    public func plan(
        _ kind: CopyToEhrCopyKind, package: CopyToEhrPackage, enabled: Bool,
        expectedRevision: String?, now: Date, marker: String
    ) -> Result<CopyToEhrCopyPlan, CopyToEhrCopyRefusal> {
        guard enabled else { return .failure(.flagOff) }
        guard !marker.isEmpty, !package.sections.isEmpty else { return .failure(.unavailable) }
        guard now < package.expiresAt else { return .failure(.expired) }
        if let expectedRevision, expectedRevision != package.draftRevision { return .failure(.stale) }
        let index = resolvedIndex(in: package)
        switch kind {
        case .nextSection:
            let section = package.sections[index]
            guard let note = package.sectionNotes[section.key] else { return .failure(.unavailable) }
            let next = (index + 1) % package.sections.count
            let name = CopyToEhrWording.sectionDisplayName(label: section.label, position: index + 1)
            return .success(makePlan(
                name: name, text: note, notSent: package.notSent, nextIndex: next,
                hash: package.payloadHash, marker: marker))
        case .fullNote:
            return .success(makePlan(
                name: "Full note", text: package.fullNote, notSent: package.notSent, nextIndex: index,
                hash: package.payloadHash, marker: marker))
        }
    }

    public mutating func commit(_ plan: CopyToEhrCopyPlan) {
        highlightIndex = plan.nextIndex
        payloadHash = plan.payloadHash
    }

    private func resolvedIndex(in package: CopyToEhrPackage) -> Int {
        let start = payloadHash == package.payloadHash ? highlightIndex : 0
        return package.sections.indices.contains(start) ? start : 0
    }

    private func makePlan(
        name: String, text: String, notSent: Bool, nextIndex: Int, hash: String, marker: String
    ) -> CopyToEhrCopyPlan {
        let outcome = CopyToEhrCopyOutcome(
            confirmation: CopyToEhrCopyMessages.confirmation(copiedName: name, notSent: notSent),
            copiedName: name, item: .make(text: text, marker: marker), highlightIndex: nextIndex)
        return CopyToEhrCopyPlan(outcome: outcome, nextIndex: nextIndex, payloadHash: hash)
    }
}

/// Carbon modifier masks from HIToolbox Events.h. These are not NSEvent flags.
public enum CopyToEhrCarbonModifiers {
    public static let command: UInt32 = 256
    public static let shift: UInt32 = 512
    public static let option: UInt32 = 2048
    public static let control: UInt32 = 4096
}

public enum CopyToEhrCarbonHotkey {
    public static let signature: UInt32 = 0x4345484B
    public static let nextID: UInt32 = 1
    public static let fullNoteID: UInt32 = 2

    public static func fourCharCode(_ value: String) -> UInt32? {
        let units = Array(value.utf8)
        guard units.count == 4 else { return nil }
        return units.reduce(UInt32(0)) { ($0 << 8) + UInt32($1) }
    }
}

public struct CopyToEhrCarbonHotkeySpec: Equatable, Sendable {
    public var keyCode: UInt32
    public var modifiers: UInt32
}

public struct CopyToEhrHotkeyChord: Equatable, Sendable {
    public var key: Character
    public var control: Bool
    public var option: Bool
    public var shift: Bool
    public var command: Bool

    /// Control-Option-Shift-C. Avoids Command-C.
    public static let nextSection = CopyToEhrHotkeyChord(key: "c", control: true, option: true, shift: true, command: false)
    /// Control-Option-Shift-N. Avoids Command-C and the section chord.
    public static let fullNote = CopyToEhrHotkeyChord(key: "n", control: true, option: true, shift: true, command: false)

    public init(key: Character, control: Bool, option: Bool, shift: Bool, command: Bool) {
        self.key = key
        self.control = control
        self.option = option
        self.shift = shift
        self.command = command
    }

    /// Command is refused even when Control or Option is also held.
    public var isUsable: Bool {
        !command && (control || option) && Self.virtualKeyCode(for: key) != nil
    }

    public static func parse(_ stored: String) -> CopyToEhrHotkeyChord? {
        let parts = stored.lowercased().split(separator: "+").map {
            $0.trimmingCharacters(in: .whitespacesAndNewlines)
        }.filter { !$0.isEmpty }
        guard let rawKey = parts.last, rawKey.count == 1, let key = rawKey.first else { return nil }
        var control = false, option = false, shift = false, command = false
        for part in parts.dropLast() {
            switch part {
            case "ctrl", "control": control = true
            case "opt", "option", "alt": option = true
            case "shift": shift = true
            case "cmd", "command": command = true
            default: return nil
            }
        }
        let chord = CopyToEhrHotkeyChord(key: key, control: control, option: option, shift: shift, command: command)
        return chord.isUsable ? chord : nil
    }

    public static func resolved(storedNext: String?, storedFull: String?) -> (next: CopyToEhrHotkeyChord, full: CopyToEhrHotkeyChord) {
        let next = storedNext.flatMap(parse) ?? .nextSection
        var full = storedFull.flatMap(parse) ?? .fullNote
        if full == next { full = next == .fullNote ? .nextSection : .fullNote }
        if full == next {
            full = CopyToEhrHotkeyChord(key: next.key == "n" ? "c" : "n", control: true, option: true, shift: true, command: false)
        }
        return (next, full)
    }

    public func carbonSpec() -> CopyToEhrCarbonHotkeySpec? {
        guard let code = Self.virtualKeyCode(for: key), isUsable else { return nil }
        var modifiers: UInt32 = 0
        if control { modifiers |= CopyToEhrCarbonModifiers.control }
        if option { modifiers |= CopyToEhrCarbonModifiers.option }
        if shift { modifiers |= CopyToEhrCarbonModifiers.shift }
        if command { modifiers |= CopyToEhrCarbonModifiers.command }
        return CopyToEhrCarbonHotkeySpec(keyCode: code, modifiers: modifiers)
    }

    /// ANSI virtual key codes from HIToolbox Events.h.
    public static func virtualKeyCode(for key: Character) -> UInt32? {
        switch key.lowercased().first {
        case "a": return 0x00
        case "s": return 0x01
        case "d": return 0x02
        case "f": return 0x03
        case "h": return 0x04
        case "g": return 0x05
        case "z": return 0x06
        case "x": return 0x07
        case "c": return 0x08
        case "v": return 0x09
        case "b": return 0x0B
        case "q": return 0x0C
        case "w": return 0x0D
        case "e": return 0x0E
        case "r": return 0x0F
        case "y": return 0x10
        case "t": return 0x11
        case "1": return 0x12
        case "2": return 0x13
        case "3": return 0x14
        case "4": return 0x15
        case "6": return 0x16
        case "5": return 0x17
        case "9": return 0x19
        case "7": return 0x1A
        case "8": return 0x1C
        case "0": return 0x1D
        case "o": return 0x1F
        case "u": return 0x20
        case "i": return 0x22
        case "p": return 0x23
        case "l": return 0x25
        case "j": return 0x26
        case "k": return 0x28
        case "n": return 0x2D
        case "m": return 0x2E
        default: return nil
        }
    }
}

public enum CopyToEhrHotkeyDefaults {
    public static let infoKey = "CosmasCopyToEhrHotkey"
    public static let enabled = "CosmasCopyToEhrHotkeyEnabled"
    public static let draftID = "CosmasCopyToEhrDraftID"
    public static let profile = "CosmasCopyToEhrProfile"
    public static let revision = "CosmasCopyToEhrRevision"
    public static let apiOrigin = "CosmasCopyToEhrAPIOrigin"
    public static let nextHotkey = "CosmasCopyToEhrNextSectionHotkey"
    public static let fullHotkey = "CosmasCopyToEhrFullNoteHotkey"
    public static let clearSeconds = "CosmasCopyToEhrClearSeconds"
    public static let storedKeys = [enabled, draftID, profile, revision, apiOrigin, nextHotkey, fullHotkey, clearSeconds]
}

public struct CopyToEhrArm: Equatable, Sendable {
    public var draftID: String
    public var profile: String
    public var revision: String?
    public var origin: URL

    public init(draftID: String, profile: String, revision: String?, origin: URL) {
        self.draftID = draftID
        self.profile = profile
        self.revision = revision
        self.origin = origin
    }
}

public struct CopyToEhrHotkeySettings: Equatable, Sendable {
    public var infoEnabled: Bool
    public var defaultsEnabled: Bool
    public var draftID: String?
    public var profile: String?
    public var revision: String?
    public var storedOrigin: String?
    public var configuredOrigin: String?
    public var nextChord: String?
    public var fullChord: String?
    public var clearSeconds: Int?

    public init(
        infoEnabled: Bool = false, defaultsEnabled: Bool = false, draftID: String? = nil, profile: String? = nil,
        revision: String? = nil, storedOrigin: String? = nil, configuredOrigin: String? = nil,
        nextChord: String? = nil, fullChord: String? = nil, clearSeconds: Int? = nil
    ) {
        self.infoEnabled = infoEnabled
        self.defaultsEnabled = defaultsEnabled
        self.draftID = draftID
        self.profile = profile
        self.revision = revision
        self.storedOrigin = storedOrigin
        self.configuredOrigin = configuredOrigin
        self.nextChord = nextChord
        self.fullChord = fullChord
        self.clearSeconds = clearSeconds
    }

    public init(info: [String: Any]?, values: [String: Any]) {
        let infoDict = Self.nested(info?[CopyToEhrHotkeyDefaults.infoKey])
        infoEnabled = Self.bool(infoDict?["enabled"])
        defaultsEnabled = Self.bool(values[CopyToEhrHotkeyDefaults.enabled])
        draftID = Self.shortString(values[CopyToEhrHotkeyDefaults.draftID], limit: 200)
        profile = Self.shortString(values[CopyToEhrHotkeyDefaults.profile], limit: 64)
        revision = Self.shortString(values[CopyToEhrHotkeyDefaults.revision], limit: 200)
        storedOrigin = Self.shortString(values[CopyToEhrHotkeyDefaults.apiOrigin], limit: 253)
        nextChord = Self.shortString(values[CopyToEhrHotkeyDefaults.nextHotkey], limit: 80)
        fullChord = Self.shortString(values[CopyToEhrHotkeyDefaults.fullHotkey], limit: 80)
        clearSeconds = Self.wholeNumber(values[CopyToEhrHotkeyDefaults.clearSeconds])
        configuredOrigin = Self.configuredAPIOrigin(info)
    }

    public static func read(info: [String: Any]?, defaults: UserDefaults) -> CopyToEhrHotkeySettings {
        var values: [String: Any] = [:]
        for key in CopyToEhrHotkeyDefaults.storedKeys {
            if let value = defaults.object(forKey: key) { values[key] = value }
        }
        return CopyToEhrHotkeySettings(info: info, values: values)
    }

    public var isEnabled: Bool { infoEnabled || defaultsEnabled }

    /// Missing timer uses 60 seconds. Zero turns the timer off. Values outside 1...900 use 60.
    public var clearDelaySeconds: Int? {
        guard let clearSeconds else { return 60 }
        if clearSeconds == 0 { return nil }
        if clearSeconds < 0 || clearSeconds > 900 { return 60 }
        return clearSeconds
    }

    public func chords() -> (next: CopyToEhrHotkeyChord, full: CopyToEhrHotkeyChord) {
        CopyToEhrHotkeyChord.resolved(storedNext: nextChord, storedFull: fullChord)
    }

    public func arm() -> CopyToEhrArm? {
        guard let draftID else { return nil }
        let chosen = profile ?? "generic"
        guard let origin = resolvedOrigin(),
              CopyToEhrDraftEndpoint.accepts(draftID: draftID, profile: chosen, revision: revision) else { return nil }
        return CopyToEhrArm(draftID: draftID, profile: chosen, revision: revision, origin: origin)
    }

    public func resolvedOrigin() -> URL? {
        if let configuredOrigin, let url = CopyToEhrDraftEndpoint.allowedOrigin(configuredOrigin) { return url }
        if let storedOrigin, let url = CopyToEhrDraftEndpoint.allowedOrigin(storedOrigin) { return url }
        return nil
    }

    private static func configuredAPIOrigin(_ info: [String: Any]?) -> String? {
        guard let capture = nested(info?["CosmasConfiguredCapture"]), bool(capture["enabled"]),
              let origin = capture["apiOrigin"] as? String else { return nil }
        return shortString(origin, limit: 253)
    }

    private static func nested(_ value: Any?) -> [String: Any]? {
        if let dict = value as? [String: Any] { return dict }
        guard let object = value as? NSDictionary else { return nil }
        var result: [String: Any] = [:]
        for (key, item) in object {
            guard let key = key as? String else { return nil }
            result[key] = item
        }
        return result
    }

    private static func bool(_ value: Any?) -> Bool {
        guard let value else { return false }
        if type(of: value) == Bool.self, let flag = value as? Bool { return flag }
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { return false }
        return number.boolValue
    }

    private static func wholeNumber(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
        let whole = number.intValue
        guard number.doubleValue == Double(whole) else { return nil }
        return whole
    }

    private static func shortString(_ value: Any?, limit: Int) -> String? {
        guard let text = value as? String else { return nil }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.utf8.count <= limit else { return nil }
        return trimmed
    }
}

public enum CopyToEhrDraftEndpoint {
    public static func allowedOrigin(_ value: String) -> URL? {
        guard let url = URL(string: value), url.absoluteString == value,
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              url.path.isEmpty || url.path == "/", let host = url.host, !host.isEmpty else { return nil }
        if url.scheme == "https" { return url }
        if url.scheme == "http", host == "127.0.0.1", url.port != nil { return url }
        return nil
    }

    public static func accepts(draftID: String, profile: String, revision: String?) -> Bool {
        guard token(draftID, limit: 200), token(profile, limit: 64) else { return false }
        if let revision { return token(revision, limit: 200) }
        return true
    }

    public static func request(origin: URL, draftID: String, profile: String, revision: String?, bearer: String?) -> URLRequest? {
        guard allowedOrigin(origin.absoluteString) != nil,
              accepts(draftID: draftID, profile: profile, revision: revision),
              var components = URLComponents(url: origin, resolvingAgainstBaseURL: false) else { return nil }
        components.path = "/api/copy-to-ehr/drafts/" + draftID
        var query = [URLQueryItem(name: "profile", value: profile)]
        if let revision { query.append(URLQueryItem(name: "revision", value: revision)) }
        components.queryItems = query
        guard let url = components.url else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        request.timeoutInterval = 20
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        request.setValue("app://cosmas", forHTTPHeaderField: "Origin")
        if let bearer, !bearer.isEmpty {
            guard bearer.utf8.count <= 8192,
                  bearer.unicodeScalars.allSatisfy({ $0.isASCII && $0.value >= 33 && $0.value < 127 }) else { return nil }
            request.setValue("Bearer " + bearer, forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private static func token(_ value: String, limit: Int) -> Bool {
        guard !value.isEmpty, value.utf8.count <= limit else { return false }
        return value.unicodeScalars.allSatisfy { scalar in
            CharacterSet.alphanumerics.contains(scalar) || scalar == "-" || scalar == "_" || scalar == "."
        }
    }
}
