import Foundation
import Testing
@testable import CosmasNativeAuth

@Suite struct CopyToEhrHotkeyTests {
    @Test func sectionHotkeyFollowsServerOrderAndSkipsExtras() throws {
        let package = try samplePackage()
        #expect(package.sections.map(\.key) == ["subjective", "objective", "plan"])
        #expect(package.extras.map(\.key) == ["orders"])
        var session = CopyToEhrHotkeySession()
        let now = try timestamp("2026-11-10T12:05:00Z")
        var copied: [String] = []
        for expected in ["subjective", "objective", "plan"] {
            let before = session
            let plan = try session.plan(
                .nextSection, package: package, enabled: true, expectedRevision: package.draftRevision,
                now: now, marker: "marker-\(expected)").get()
            let section = try #require(package.sections.first { $0.key == expected })
            #expect(session == before)
            #expect(plan.outcome.copiedName == section.label)
            #expect(plan.outcome.item.text == package.sectionNotes[expected])
            #expect(plan.outcome.item.text != section.text)
            #expect(!plan.outcome.item.text.contains("INVENTED-ORDER-LINE"))
            #expect(!plan.outcome.confirmation.contains("INVENTED-ORDER-LINE"))
            #expect(!plan.outcome.confirmation.contains("Invented stiffness."))
            #expect(CopyToEhrWording.isCopyOnly(plan.outcome.confirmation))
            session.commit(plan)
            copied.append(plan.outcome.copiedName)
        }
        #expect(copied == ["Subjective", "Objective", "Plan"])
        #expect(session.highlightIndex == 0)
        #expect(session.highlightedKey(in: package) == "subjective")
        let again = try session.plan(
            .nextSection, package: package, enabled: true, expectedRevision: package.draftRevision,
            now: now, marker: "marker-again").get()
        #expect(again.outcome.copiedName == "Subjective")
    }

    @Test func fullNoteUsesRenderedNoteAndLeavesTheSectionHighlight() throws {
        let package = try samplePackage()
        var session = CopyToEhrHotkeySession()
        let now = try timestamp("2026-11-10T12:05:00Z")
        let first = try session.plan(
            .nextSection, package: package, enabled: true, expectedRevision: nil, now: now, marker: "m1").get()
        session.commit(first)
        #expect(session.highlightIndex == 1)
        let full = try session.plan(
            .fullNote, package: package, enabled: true, expectedRevision: nil, now: now, marker: "m2").get()
        #expect(full.outcome.copiedName == "Full note")
        #expect(full.outcome.item.text == package.fullNote)
        #expect(!full.outcome.item.text.contains("INVENTED-ORDER-LINE"))
        #expect(full.outcome.confirmation.contains("Full note"))
        #expect(!full.outcome.confirmation.contains("Invented rest."))
        #expect(full.nextIndex == 1)
        session.commit(full)
        #expect(session.highlightIndex == 1)
        #expect(session.highlightedKey(in: package) == "objective")
    }

    @Test func changedPackageStartsTheHighlightOver() throws {
        let package = try samplePackage()
        var session = CopyToEhrHotkeySession()
        let now = try timestamp("2026-11-10T12:05:00Z")
        for marker in ["m1", "m2"] {
            let plan = try session.plan(
                .nextSection, package: package, enabled: true, expectedRevision: nil, now: now, marker: marker).get()
            session.commit(plan)
        }
        #expect(session.highlightIndex == 2)
        let data = try packageJSON(hash: String(repeating: "cd", count: 32))
        let revised = try #require(CopyToEhrPackage.parse(data))
        let plan = try session.plan(
            .nextSection, package: revised, enabled: true, expectedRevision: nil, now: now, marker: "m3").get()
        #expect(plan.outcome.copiedName == "Subjective")
        #expect(plan.nextIndex == 1)
    }

    @Test func flagOffExpiredAndStaleDoNotMoveTheHighlight() throws {
        let package = try samplePackage()
        let session = CopyToEhrHotkeySession()
        let ready = try timestamp("2026-11-10T12:05:00Z")
        let expired = try timestamp("2026-11-10T12:15:00Z")
        let before = session
        #expect(session.plan(.nextSection, package: package, enabled: false, expectedRevision: nil, now: ready, marker: "m")
            == .failure(.flagOff))
        #expect(CopyToEhrCopyMessages.refusal(.flagOff).isEmpty)
        #expect(session.plan(.fullNote, package: package, enabled: true, expectedRevision: "rev-other", now: ready, marker: "m")
            == .failure(.stale))
        #expect(session.plan(.nextSection, package: package, enabled: true, expectedRevision: nil, now: expired, marker: "m")
            == .failure(.expired))
        #expect(session == before)
        for refusal in [CopyToEhrCopyRefusal.expired, .stale, .unavailable] {
            let message = CopyToEhrCopyMessages.refusal(refusal)
            #expect(CopyToEhrWording.isCopyOnly(message))
            #expect(!message.contains("Invented"))
        }
        #expect(CopyToEhrWording.isCopyOnly(CopyToEhrCopyMessages.needsDraft))
        #expect(CopyToEhrWording.isCopyOnly(CopyToEhrCopyMessages.hotkeyUnavailable))
    }

    @Test func notSentConfirmationNamesTheSectionOnly() throws {
        var package = try samplePackage()
        package.visitStatus = "not_sent_copy_instead"
        let session = CopyToEhrHotkeySession()
        let plan = try session.plan(
            .nextSection, package: package, enabled: true, expectedRevision: nil,
            now: try timestamp("2026-11-10T12:05:00Z"), marker: "m").get()
        #expect(plan.outcome.confirmation == "This note was not sent. Copied Subjective. Press Paste in the chart yourself.")
        #expect(!plan.outcome.confirmation.contains("Invented stiffness."))
    }

    @Test func clipboardWriteIsLocalConcealedAndTransient() throws {
        let package = try samplePackage()
        let session = CopyToEhrHotkeySession()
        let plan = try session.plan(
            .nextSection, package: package, enabled: true, expectedRevision: nil,
            now: try timestamp("2026-11-10T12:05:00Z"), marker: "marker-1").get()
        let payload = try #require(CopyToEhrPasteboardPayload.make(plan.outcome.item))
        #expect(payload.localOnly)
        #expect(payload.values[CopyToEhrPasteboardItem.stringType] == "Subjective\nInvented stiffness.")
        #expect(payload.values[CopyToEhrPasteboardItem.concealedType] == "")
        #expect(payload.values[CopyToEhrPasteboardItem.transientType] == "")
        #expect(payload.values[CopyToEhrPasteboardItem.markerType] == "marker-1")
        var tampered = plan.outcome.item
        tampered.localOnly = false
        #expect(CopyToEhrPasteboardPayload.make(tampered) == nil)
        let board = FakePasteboard()
        let writer = CopyToEhrPasteboardWriter(port: board)
        #expect(writer.write(tampered) == nil)
        #expect(board.writes.isEmpty)
        let receipt = try #require(writer.write(plan.outcome.item))
        #expect(board.writes.count == 1)
        #expect(board.writes[0].localOnly)
        #expect(board.writes[0].values[CopyToEhrPasteboardItem.concealedType] == "")
        #expect(board.writes[0].values[CopyToEhrPasteboardItem.transientType] == "")
        #expect(receipt.changeCount == 1)
        #expect(receipt.text == plan.outcome.item.text)
    }

    @Test func timedClearRunsOnlyWhileTheClipboardStillHoldsOurText() throws {
        let board = FakePasteboard()
        let writer = CopyToEhrPasteboardWriter(port: board)
        let item = CopyToEhrPasteboardItem.make(text: "Subjective\nInvented stiffness.", marker: "marker-1")
        let receipt = try #require(writer.write(item))
        writer.clearIfStillOurs(receipt)
        #expect(board.clears == 1)
        board.observation = CopyToEhrPasteboardObservation(
            changeCount: receipt.changeCount, marker: receipt.marker, text: receipt.text)
        writer.clearIfStillOurs(receipt)
        #expect(board.clears == 2)
        board.observation = CopyToEhrPasteboardObservation(
            changeCount: receipt.changeCount, marker: receipt.marker, text: "clinician copied something else")
        writer.clearIfStillOurs(receipt)
        #expect(board.clears == 2)
        board.observation = CopyToEhrPasteboardObservation(changeCount: receipt.changeCount, marker: "other-marker", text: receipt.text)
        writer.clearIfStillOurs(receipt)
        #expect(board.clears == 2)
        board.observation = CopyToEhrPasteboardObservation(changeCount: receipt.changeCount + 4, marker: receipt.marker, text: receipt.text)
        writer.clearIfStillOurs(receipt)
        #expect(board.clears == 2)
        #expect(CopyToEhrHotkeySettings().clearDelaySeconds == 60)
        #expect(CopyToEhrHotkeySettings(clearSeconds: 0).clearDelaySeconds == nil)
        #expect(CopyToEhrHotkeySettings(clearSeconds: 30).clearDelaySeconds == 30)
        #expect(CopyToEhrHotkeySettings(clearSeconds: 5_000).clearDelaySeconds == 60)
    }

    @Test func hotkeyDefaultsOffAndDoesNotUseCommandC() {
        #expect(!CopyToEhrHotkeySettings().isEnabled)
        let nested: [String: Any] = ["enabled": false]
        let info: [String: Any] = [CopyToEhrHotkeyDefaults.infoKey: nested]
        #expect(!CopyToEhrHotkeySettings(info: info, values: [:]).isEnabled)
        let turnedOn: [String: Any] = ["enabled": true]
        let enabledInfo: [String: Any] = [CopyToEhrHotkeyDefaults.infoKey: turnedOn]
        #expect(CopyToEhrHotkeySettings(info: enabledInfo, values: [:]).isEnabled)
        let defaultsOn: [String: Any] = [CopyToEhrHotkeyDefaults.enabled: NSNumber(value: true)]
        #expect(CopyToEhrHotkeySettings(info: nil, values: defaultsOn).isEnabled)
        let integer: [String: Any] = [CopyToEhrHotkeyDefaults.enabled: NSNumber(value: 1)]
        #expect(!CopyToEhrHotkeySettings(info: nil, values: integer).isEnabled)

        let section = CopyToEhrHotkeyChord.nextSection.carbonSpec()
        #expect(section?.keyCode == 0x08)
        #expect(section?.modifiers == CopyToEhrCarbonModifiers.control | CopyToEhrCarbonModifiers.option | CopyToEhrCarbonModifiers.shift)
        #expect((section?.modifiers ?? 0) & CopyToEhrCarbonModifiers.command == 0)
        #expect(CopyToEhrHotkeyChord.fullNote.carbonSpec()?.keyCode == 0x2D)
        #expect(CopyToEhrHotkeyChord.nextSection != CopyToEhrHotkeyChord.fullNote)
        #expect(CopyToEhrHotkeyChord.parse("cmd+c") == nil)
        #expect(CopyToEhrHotkeyChord.parse("command+v") == nil)
        #expect(CopyToEhrHotkeyChord.parse("c") == nil)
        let resolved = CopyToEhrHotkeyChord.resolved(storedNext: "cmd+c", storedFull: "ctrl+opt+k")
        #expect(resolved.next == .nextSection)
        #expect(resolved.full.carbonSpec()?.keyCode == 0x28)
        #expect(resolved.full != resolved.next)
        #expect(CopyToEhrCarbonHotkey.fourCharCode("CEHK") == CopyToEhrCarbonHotkey.signature)
        #expect(CopyToEhrCarbonHotkey.nextID != CopyToEhrCarbonHotkey.fullNoteID)
    }

    @Test func commandChordIsRefusedEvenWithOtherModifiers() {
        for stored in [
            "ctrl+cmd+c", "control+command+c", "opt+cmd+shift+n",
            "ctrl+opt+command+k", "cmd+ctrl+c", "option+alt+cmd+v",
        ] {
            #expect(CopyToEhrHotkeyChord.parse(stored) == nil)
        }
        let entered = CopyToEhrHotkeyChord(key: "c", control: true, option: true, shift: true, command: true)
        #expect(!entered.isUsable)
        #expect(entered.carbonSpec() == nil)
        let bothRefused = CopyToEhrHotkeyChord.resolved(storedNext: "ctrl+cmd+c", storedFull: "opt+command+n")
        #expect(bothRefused.next == .nextSection)
        #expect(bothRefused.full == .fullNote)
        let oneRefused = CopyToEhrHotkeyChord.resolved(storedNext: "ctrl+opt+cmd+c", storedFull: "ctrl+opt+shift+k")
        #expect(oneRefused.next == .nextSection)
        #expect(oneRefused.full.carbonSpec()?.keyCode == 0x28)
        let nextModifiers = oneRefused.next.carbonSpec()?.modifiers ?? 0
        let fullModifiers = oneRefused.full.carbonSpec()?.modifiers ?? 0
        #expect(nextModifiers & CopyToEhrCarbonModifiers.command == 0)
        #expect(fullModifiers & CopyToEhrCarbonModifiers.command == 0)
    }

    @Test func unsafeSectionLabelShowsSectionNumberNotTheLabel() throws {
        var package = try samplePackage()
        package.sections[0].label = "Assessment sync"
        package.sections[1].label = "Objective integration"
        package.visitStatus = "not_sent_copy_instead"
        var session = CopyToEhrHotkeySession()
        let now = try timestamp("2026-11-10T12:05:00Z")
        let first = try session.plan(
            .nextSection, package: package, enabled: true, expectedRevision: nil, now: now, marker: "m1").get()
        #expect(first.outcome.copiedName == "Section 1")
        #expect(first.outcome.confirmation == "This note was not sent. Copied Section 1. Press Paste in the chart yourself.")
        #expect(!first.outcome.confirmation.contains("sync"))
        #expect(!first.outcome.confirmation.contains("Invented stiffness."))
        #expect(first.outcome.item.text == package.sectionNotes["subjective"])
        #expect(CopyToEhrWording.isCopyOnly(first.outcome.confirmation))
        session.commit(first)
        let second = try session.plan(
            .nextSection, package: package, enabled: true, expectedRevision: nil, now: now, marker: "m2").get()
        #expect(second.outcome.copiedName == "Section 2")
        #expect(!second.outcome.confirmation.contains("integration"))
        #expect(!second.outcome.confirmation.contains("Invented range."))
        #expect(second.outcome.item.text == package.sectionNotes["objective"])
        session.commit(second)
        package.sections[2].label = "Plan auto-entry"
        let third = try session.plan(
            .nextSection, package: package, enabled: true, expectedRevision: nil, now: now, marker: "m3").get()
        #expect(third.outcome.copiedName == "Section 3")
        #expect(!third.outcome.confirmation.contains("auto-entry"))
        #expect(!third.outcome.confirmation.contains("auto entry"))
        #expect(!third.outcome.confirmation.contains("Invented rest."))
        let full = try session.plan(
            .fullNote, package: package, enabled: true, expectedRevision: nil, now: now, marker: "m4").get()
        #expect(full.outcome.copiedName == "Full note")
        #expect(!full.outcome.confirmation.contains("Section"))
        #expect(!full.outcome.confirmation.contains("Invented rest."))
    }

    @Test func draftRequestUsesTheCopyRouteAndKeepsTheTokenOutOfTheURL() throws {
        let origin = try #require(URL(string: "https://api.staging.example"))
        let request = try #require(CopyToEhrDraftEndpoint.request(
            origin: origin, draftID: "draft-synth-100", profile: "generic", revision: "rev-synth-1", bearer: "synth-token"))
        let url = try #require(request.url)
        let parts = try #require(URLComponents(url: url, resolvingAgainstBaseURL: false))
        #expect(request.httpMethod == "GET")
        #expect(request.cachePolicy == .reloadIgnoringLocalAndRemoteCacheData)
        #expect(parts.path == "/api/copy-to-ehr/drafts/draft-synth-100")
        #expect(parts.queryItems == [
            URLQueryItem(name: "profile", value: "generic"),
            URLQueryItem(name: "revision", value: "rev-synth-1"),
        ])
        #expect(request.url?.absoluteString.contains("synth-token") == false)
        #expect(request.value(forHTTPHeaderField: "Authorization") == "Bearer synth-token")
        #expect(CopyToEhrDraftEndpoint.request(
            origin: try #require(URL(string: "http://evil.example")), draftID: "draft-synth-100",
            profile: "generic", revision: nil, bearer: nil) == nil)
        #expect(CopyToEhrDraftEndpoint.allowedOrigin("http://127.0.0.1:8046") != nil)
        let noteID = "visit_note_01synth" + String(repeating: "0", count: 18)
        #expect(CopyToEhrDraftEndpoint.accepts(draftID: noteID, profile: "atlas_md", revision: "rev-synth-1"))
        #expect(!CopyToEhrDraftEndpoint.accepts(draftID: "draft/synth", profile: "generic", revision: nil))
    }

    @Test func armUsesTheConfiguredOriginAndStaysOffWithoutADraft() throws {
        let capture: [String: Any] = ["enabled": true, "apiOrigin": "https://api.configured.example"]
        let info: [String: Any] = ["CosmasConfiguredCapture": capture]
        let values: [String: Any] = [
            CopyToEhrHotkeyDefaults.draftID: "draft-synth-100",
            CopyToEhrHotkeyDefaults.apiOrigin: "http://127.0.0.1:8046",
            CopyToEhrHotkeyDefaults.profile: "atlas_md",
        ]
        let settings = CopyToEhrHotkeySettings(info: info, values: values)
        let arm = try #require(settings.arm())
        #expect(arm.origin.absoluteString == "https://api.configured.example")
        #expect(arm.profile == "atlas_md")
        #expect(CopyToEhrHotkeySettings().arm() == nil)
        let blocked: [String: Any] = [
            CopyToEhrHotkeyDefaults.draftID: "draft-synth-100",
            CopyToEhrHotkeyDefaults.apiOrigin: "http://evil.example",
        ]
        #expect(CopyToEhrHotkeySettings(info: nil, values: blocked).arm() == nil)
        let local: [String: Any] = [
            CopyToEhrHotkeyDefaults.draftID: "draft-synth-100",
            CopyToEhrHotkeyDefaults.apiOrigin: "http://127.0.0.1:8046",
        ]
        #expect(CopyToEhrHotkeySettings(info: nil, values: local).arm()?.profile == "generic")
    }

    @Test func parserRejectsHashLinesExtrasInTheNoteAndUnknownKeys() throws {
        #expect(CopyToEhrPackage.parse(try packageJSON(hash: "abc")) == nil)
        var hashed = jsonObject()
        hashed["full_note"] = "Subjective\n# Invented heading"
        #expect(CopyToEhrPackage.parse(try JSONSerialization.data(withJSONObject: hashed)) == nil)
        var misplaced = jsonObject()
        misplaced["sections"] = [["key": "orders", "label": "Orders", "text": "INVENTED-ORDER-LINE"]]
        misplaced["section_notes"] = ["orders": "Orders\nINVENTED-ORDER-LINE"]
        #expect(CopyToEhrPackage.parse(try JSONSerialization.data(withJSONObject: misplaced)) == nil)
        var extraKey = jsonObject()
        extraKey["note_text"] = "Invented stiffness."
        #expect(CopyToEhrPackage.parse(try JSONSerialization.data(withJSONObject: extraKey)) == nil)
    }
}

private final class FakePasteboard: CopyToEhrPasteboardPort {
    var writes: [CopyToEhrPasteboardPayload] = []
    var clears = 0
    var observation = CopyToEhrPasteboardObservation(changeCount: 0, marker: nil, text: nil)

    func writeLocalOnly(_ payload: CopyToEhrPasteboardPayload) -> Int? {
        guard payload.localOnly else { return nil }
        writes.append(payload)
        observation = CopyToEhrPasteboardObservation(
            changeCount: writes.count,
            marker: payload.values[CopyToEhrPasteboardItem.markerType],
            text: payload.values[CopyToEhrPasteboardItem.stringType])
        return observation.changeCount
    }

    func observe() -> CopyToEhrPasteboardObservation { observation }
    func clearLocalOnly() {
        clears += 1
        observation = CopyToEhrPasteboardObservation(changeCount: observation.changeCount + 1, marker: nil, text: nil)
    }
}

private func timestamp(_ value: String) throws -> Date {
    let parser = ISO8601DateFormatter()
    parser.formatOptions = [.withInternetDateTime]
    return try #require(parser.date(from: value))
}

private func samplePackage() throws -> CopyToEhrPackage {
    try #require(CopyToEhrPackage.parse(try packageJSON(hash: String(repeating: "ab", count: 32))))
}

private func packageJSON(hash: String) throws -> Data {
    var object = jsonObject()
    object["payload_hash"] = hash
    return try JSONSerialization.data(withJSONObject: object)
}

private func jsonObject() -> [String: Any] {
    [
        "profile_id": "generic",
        "draft_id": "draft-synth-100",
        "draft_revision": "rev-synth-1",
        "payload_hash": String(repeating: "ab", count: 32),
        "sections": [
            ["key": "subjective", "label": "Subjective", "text": "Invented stiffness."],
            ["key": "objective", "label": "Objective", "text": "Invented range."],
            ["key": "plan", "label": "Plan", "text": "Invented rest."],
        ],
        "extras": [
            ["key": "orders", "label": "Orders", "text": "INVENTED-ORDER-LINE"],
        ],
        "created_at": "2026-11-10T12:00:00Z",
        "expires_at": "2026-11-10T12:15:00Z",
        "review_state": "reviewed",
        "visit_copy_to_ehr_status": "unset",
        "full_note": "Subjective\nInvented stiffness.\n\nObjective\nInvented range.\n\nPlan\nInvented rest.",
        "section_notes": [
            "plan": "Plan\nInvented rest.",
            "subjective": "Subjective\nInvented stiffness.",
            "objective": "Objective\nInvented range.",
        ],
    ]
}
