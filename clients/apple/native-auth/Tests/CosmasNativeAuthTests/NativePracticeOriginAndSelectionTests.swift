import Foundation
import Testing
@testable import CosmasNativeAuth

private func originBinding(dynamic: Bool = false, origins: Set<String> = ["https://api.a.staging.cosmas.ai", "https://api.b.staging.cosmas.ai"]) throws -> NativePracticeAccountServiceBinding {
    let host = "invented.clerk.accounts.dev"
    let realm = try NativeClerkAccountConfiguration(publishableKey: "pk_test_" + Data((host + "$").utf8).base64EncodedString(),
        frontendOrigin: "https://" + host, bundleIdentifier: "com.cosmasos.beta.ios",
        profile: .operationalStaging, storageNamespace: String(repeating: "b", count: 64))
    return try .init(accountOrigin: NativePracticeAccountServiceBinding.stagingAccountOrigin, realm: realm, audience: "",
        allowedAPIOrigins: origins, registeredPracticeOrigins: dynamic ? .syntheticPracticeUUIDStaging : .exact)
}

@Suite struct NativePracticeOriginAndSelectionTests {
    @Test func exactOriginDefaultPreservesReviewedPracticesAndRejectsNewPractice() throws {
        let binding = try originBinding(), practice = UUID()
        #expect(binding.allowsAPI("https://api.a.staging.cosmas.ai", practiceID: practice))
        #expect(binding.allowsAPI("https://api.b.staging.cosmas.ai", practiceID: practice))
        #expect(!binding.allowsAPI("https://api." + practice.uuidString.lowercased() + ".staging.cosmas.ai", practiceID: practice))
        #expect(throws: NativePracticeProfileError.invalidBinding) { try originBinding(origins: []) }
    }
    @Test func registeredOriginRequiresExactServerPracticeUUIDAndKeepsReservedOriginsClosed() throws {
        let binding = try originBinding(dynamic: true, origins: []), practice = UUID()
        let exact = "https://api." + practice.uuidString.lowercased() + ".staging.cosmas.ai"
        #expect(binding.allowsAPI(exact, practiceID: practice))
        for origin in [exact.uppercased(), exact + "/", exact + "?url=other", exact + ".attacker.invalid",
                       exact.replacingOccurrences(of: "https://", with: "http://"),
                       "https://api." + UUID().uuidString.lowercased() + ".staging.cosmas.ai",
                       "https://api.staging.cosmas.ai", "https://api.accounts.staging.cosmas.ai",
                       "https://api.app.cosmas.ai", "https://api.cosmas.ai", "https://api.some-slug.staging.cosmas.ai"] {
            #expect(!binding.allowsAPI(origin, practiceID: practice))
        }
    }
    @Test func enablingRegisteredPolicyDoesNotWidenReviewedExactOrigins() throws {
        let practice = UUID(), binding = try originBinding(dynamic: true)
        #expect(binding.allowsAPI("https://api.a.staging.cosmas.ai", practiceID: practice))
        #expect(binding.allowsAPI("https://api." + practice.uuidString.lowercased() + ".staging.cosmas.ai", practiceID: practice))
        #expect(!binding.allowsAPI("https://api.c.staging.cosmas.ai", practiceID: practice))
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try originBinding(dynamic: true, origins: Set((0..<33).map { "https://api.\($0).example.invalid" }))
        }
    }
    @Test func persistedSelectionIsBoundedMetadataAndRequiresPinnedRealmAndPractice() throws {
        let binding = try originBinding(dynamic: true, origins: []), practice = UUID(), box = UUID()
        let value: [String: Any] = ["version": 1, "userID": "user_synthetic", "issuer": binding.realm.frontendOrigin,
            "practiceID": practice.uuidString, "organizationID": "org_synthetic", "boxID": box.uuidString,
            "apiOrigin": "https://api." + practice.uuidString.lowercased() + ".staging.cosmas.ai"]
        let encoded = try JSONSerialization.data(withJSONObject: value)
        let marker = try NativePracticeSelectionMarker.decode(encoded)
        try marker.validate(binding: binding)
        #expect(marker.practiceID == practice && marker.boxID == box)
        #expect(try NativePracticeSelectionMarker.decode(JSONEncoder().encode(marker)) == marker)
        for (key, replacement) in [("issuer", "https://other.clerk.accounts.dev"), ("userID", "user bad"),
                                   ("organizationID", "org bad"), ("apiOrigin", "https://api." + UUID().uuidString.lowercased() + ".staging.cosmas.ai")] {
            var altered = value; altered[key] = replacement
            let decoded = try NativePracticeSelectionMarker.decode(JSONSerialization.data(withJSONObject: altered))
            #expect(throws: NativePracticeProfileError.invalidBinding) { try decoded.validate(binding: binding) }
        }
        var extra = value; extra["token"] = "synthetic-untrusted-value"
        #expect(throws: NativePracticeProfileError.invalidBinding) { try NativePracticeSelectionMarker.decode(JSONSerialization.data(withJSONObject: extra)) }
        #expect(throws: NativePracticeProfileError.invalidBinding) { try NativePracticeSelectionMarker.decode(Data(repeating: 32, count: 4097)) }
        // This metadata has no session, JWT or qualification proof; the concrete
        // host still obtains a fresh authenticated profile before any admission.
        #expect(Set(value.keys).isDisjoint(with: ["sessionID", "token", "nativeIdentity", "workspace_proof_sha256"]))
    }
}
