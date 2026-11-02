import Foundation
import Testing
@testable import CosmasNativeAuth

@Suite struct NativePracticeConnectionContractTests {
    @Test func accountContractNeverExposesOrganizationOrWorkspaceGrant() throws {
        let revision = UUID().uuidString.lowercased()
        let account = try NativeAccountIdentity(issuer: "https://invented.clerk.accounts.dev", userID: "user_one", sessionID: "sess_one")
        let identity = try NativePracticeAccountView.Identity(account: account, email: "invented@example.invalid", displayName: "Synthetic Owner")
        let ready = try NativePracticeAccountView(phase: .accountReady, revision: revision, identity: identity)
        let object = ready.payload["identity"] as! [String: Any]
        #expect(Set(object.keys) == ["userId", "sessionId", "email", "displayName"])
        let out = try NativePracticeAccountView(phase: .signedOut, revision: revision, identity: nil)
        #expect(out.payload["identity"] is NSNull)
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeAccountView(phase: .accountReady, revision: revision, identity: nil)
        }
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeAccountView(phase: .signedOut, revision: revision, identity: identity)
        }
    }

    @Test func enrollmentContractAcceptsFixedOperationsAndRejectsURLHeaderOrGETBodyInjection() throws {
        let revision = UUID().uuidString.lowercased(), body = Data("{\"expected_revision\":1}".utf8)
        let request = try NativePracticeEnrollmentRequest(expectedRevision: revision, operation: .practice,
            body: body, idempotencyKey: UUID().uuidString.lowercased())
        #expect(request.operation.method == "PUT" && request.operation.path == "/enrollment/v1/native/practice")
        #expect(NativePracticeEnrollmentOperation(rawValue: "https://other.invalid") == nil)
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeEnrollmentRequest(expectedRevision: revision, operation: .status, body: body, idempotencyKey: nil)
        }
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeEnrollmentRequest(expectedRevision: revision, operation: .practice, body: body, idempotencyKey: "safe\nAuthorization: injected")
        }
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeEnrollmentRequest(expectedRevision: "browser-owned", operation: .config, body: nil, idempotencyKey: nil)
        }
    }

    @Test func enrollmentRepliesPreserveActualErrorStatusAndBoundBodies() throws {
        let reply = try NativePracticeEnrollmentReply(status: 503, body: Data("{\"detail\":{\"code\":\"native_workspace_unqualified\"}}".utf8))
        #expect(reply.payload["status"] as? Int == 503)
        #expect((reply.payload["body"] as? [String: Any])?["detail"] != nil)
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeEnrollmentReply(status: 200, body: Data(repeating: 32, count: 524_289))
        }
    }
}
