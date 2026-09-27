import CosmasNativeAuth
import Foundation

// Real account parser/runtime with invented identities and in-memory transport.
// No SDK, Keychain, audio device or external service is used.
@MainActor enum CheckNativeRecordingAccount {
  private struct Failed: Error { let line: UInt }
  private static func check(_ value: Bool, line: UInt = #line) throws {
    if !value { throw Failed(line: line) }
  }
  private static func rejects(_ operation: () async throws -> Void, line: UInt = #line) async throws {
    do { try await operation() } catch { return }
    throw Failed(line: line)
  }
  final class Driver: NativeAuthDriver {
    var loaded = true
    var identity: NativeAuthIdentity? = try! NativeAuthIdentity(
      userID: "user_offline", sessionID: "sess_offline", organizationID: "org_offline")
    func signIn() async throws {}
    func signOut() async throws { identity = nil }
    func freshToken() async throws -> String? {
      guard let identity else { return nil }
      func encode(_ value: [String: Any]) throws -> String {
        try JSONSerialization.data(withJSONObject: value).base64EncodedString()
          .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
          .replacingOccurrences(of: "=", with: "")
      }
      let now = Int(Date().timeIntervalSince1970)
      return try encode(["alg": "RS256", "kid": "synthetic"]) + "." + encode([
        "iss": "https://identity.clerk.accounts.dev", "aud": "offline-provider",
        "azp": "capacitor://localhost", "sub": identity.userID, "sid": identity.sessionID,
        "org_id": identity.organizationID, "exp": now + 60, "iat": now, "nbf": now,
      ]) + ".c3ludGhldGlj"
    }
  }
  private final class Block: NativeAuthAccessBlock {
    func isBlocked() throws -> Bool { false }
    func setBlocked(_ blocked: Bool) throws {}
  }
  private final class Journal: NativeSourceJournalBacking {
    var data: Data?
    func read() -> Data? { data }
    func write(_ data: Data) { self.data = data }
  }
  private actor Wire: ProviderNativeWire {
    var fault: String
    var calls = 0
    var pending: CheckedContinuation<Void, Never>?
    init(_ fault: String = "") { self.fault = fault }
    func release() { fault = ""; pending?.resume(); pending = nil }
    func send(_ request: ProviderNativeRequest, token: String) async throws -> ProviderNativeReply {
      calls += 1
      precondition(request.action == .recordingAccount && request.body == Data("{}".utf8))
      if fault == "hold" { await withCheckedContinuation { pending = $0 } }
      var value: [String: Any] = ["contract_version": 1,
        "box_id": "00000000-0000-4000-8000-000000000101",
        "actor_id": "00000000-0000-4000-8000-000000000102",
        "recovery_scope": String(repeating: "a", count: 64)]
      switch fault {
      case "boolean": value["contract_version"] = true
      case "fraction": value["contract_version"] = 1.1
      case "version": value["contract_version"] = 2
      case "string_version": value["contract_version"] = "1"
      case "missing": value.removeValue(forKey: "actor_id")
      case "extra": value["key"] = "must-not-cross"
      case "box": value["box_id"] = "not-a-uuid"
      case "actor": value["actor_id"] = "not-a-uuid"
      case "uppercase_uuid": value["actor_id"] = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
      case "uppercase_scope": value["recovery_scope"] = String(repeating: "A", count: 64)
      case "short_scope": value["recovery_scope"] = String(repeating: "a", count: 63)
      case "different_scope": value["recovery_scope"] = String(repeating: "b", count: 64)
      default: break
      }
      if fault == "oversize" { return ProviderNativeReply(status: 200, body: Data(repeating: 32, count: 1025)) }
      return ProviderNativeReply(status: Int(fault) ?? 200,
        body: try JSONSerialization.data(withJSONObject: value))
    }
  }
  static func makeAuth() throws -> (NativeWorkspaceAuth, Driver) {
    let driver = Driver()
    let policy = try NativeTokenPolicy(issuer: "https://identity.clerk.accounts.dev", audience: "offline-provider")
    return (NativeWorkspaceAuth(enabled: true, organizationID: "org_offline", tokenPolicy: policy,
      driver: { driver }, accessBlock: { Block() }), driver)
  }
  private static func wait(_ condition: () async -> Bool) async throws {
    for _ in 0..<2000 {
      if await condition() { return }
      try await Task.sleep(for: .milliseconds(1))
    }
    throw Failed(line: #line)
  }
  static func run() async throws -> Int {
    var checks = 0
    let (auth, driver) = try makeAuth()
    let wire = Wire(), connection = NativeProviderConnection(auth: auth, wire: wire)
    let first = try await connection.recordingAccount(revision: auth.state().revision)
    // Golden vector independently computed with Python JSON/SHA-256/UUID.
    try check(first.accountDigest == "4b2ebeba9f538548558a897a8cac152ff6a53e019f4df9904acdac1b2d522aae")
    try check(first.recoveryScope.uuidString.lowercased() == "852f42b5-517c-8594-9b60-fb09cee7438f")
    driver.identity = try NativeAuthIdentity(userID: "user_offline", sessionID: "sess_renewed", organizationID: "org_offline")
    let renewed = try await connection.recordingAccount(revision: auth.state().revision)
    try check(first == renewed)
    driver.identity = try NativeAuthIdentity(userID: "user_other", sessionID: "sess_other", organizationID: "org_offline")
    let other = try await connection.recordingAccount(revision: auth.state().revision)
    try check(first.recoveryScope != other.recoveryScope)
    let changedScope = NativeProviderConnection(auth: auth, wire: Wire("different_scope"))
    let remapped = try await changedScope.recordingAccount(revision: auth.state().revision)
    try check(remapped.recoveryScope != other.recoveryScope)
    checks += 5
    for fault in ["boolean", "fraction", "version", "string_version", "missing", "extra", "box", "actor",
                  "uppercase_uuid", "uppercase_scope", "short_scope", "oversize", "401", "403", "404", "405",
                  "409", "422", "426", "503", "504"] {
      let failed = NativeProviderConnection(auth: auth, wire: Wire(fault))
      try await rejects { _ = try await failed.recordingAccount(revision: auth.state().revision) }
      checks += 1
    }
    let transport = try WorkspaceSourceTransport(settings: ["enabled": true, "apiOrigin": "https://api.example.invalid"])
    let request = try ProviderNativeRequest(recordingAccountID: UUID(), revision: auth.state().revision)
    let wireRequest = try transport.makeRequest(request, token: "synthetic-token")
    try check(wireRequest.url?.absoluteString == "https://api.example.invalid/provider-team/identity")
    try check(wireRequest.httpMethod == "GET" && wireRequest.httpBody == nil && wireRequest.url?.query == nil)
    try check(wireRequest.value(forHTTPHeaderField: "X-Cosmas-Team-Contract") == "2")
    try check(wireRequest.value(forHTTPHeaderField: "X-Cosmas-Draft-Recovery") == "2")
    try await rejects {
      _ = try ProviderNativeRequest(id: UUID().uuidString.lowercased(), revision: auth.state().revision,
        action: "native-recording-account", key: "synthetic-key", body: "{}")
    }
    checks += 5
    for mode in ["cancel", "auth_change", "timeout"] {
      let (current, changed) = try makeAuth()
      let stalled = Wire("hold"), connection = NativeProviderConnection(auth: current, wire: stalled)
      let revision = current.state().revision
      let started = ContinuousClock.now
      let operation = Task { try await connection.recordingAccount(revision: revision) }
      try await wait { await stalled.pending != nil }
      if mode == "cancel" { operation.cancel() }
      if mode == "auth_change" {
        changed.identity = nil
        connection.authChanged(current.state())
        await stalled.release()
      }
      try await rejects { _ = try await operation.value }
      try check(started.duration(to: .now) < .seconds(mode == "timeout" ? 18 : 2))
      await stalled.release()
      checks += 1
    }
    // A replacement renderer receives the same auth and recovery objects.
    let (retainedAuth, retainedDriver) = try makeAuth()
    let retainedConnection = NativeProviderConnection(auth: retainedAuth, wire: Wire())
    let recovery = NativeSourceRecovery(journal: try NativeSourceProofJournal(platform: .ios, backing: Journal()))
    var constructions = 0, firstEvents = 0, secondEvents = 0
    let runtime = NativeProviderRecordingRuntime(auth: retainedAuth) { _ in
      constructions += 1; return (retainedConnection, recovery)
    }
    let old = UUID(), replacement = UUID()
    runtime.attach(old) { _ in firstEvents += 1 }
    _ = retainedAuth.state()
    runtime.attach(replacement) { _ in secondEvents += 1 }
    runtime.detach(old) // A stale detach must not remove the new observer.
    retainedDriver.identity = nil
    _ = retainedAuth.state()
    try check(firstEvents == 1 && secondEvents == 1)
    let a = try runtime.resources(), b = try runtime.resources()
    try check(constructions == 1 && a.connection === b.connection && a.recovery === b.recovery)
    try runtime.claimRendererSource(old)
    try await rejects { try runtime.claimRendererSource(old) }
    try await rejects { try runtime.claimRendererSource(replacement) }
    runtime.releaseRendererSource(old)
    try await rejects { try runtime.requireNativeAvailable() }
    runtime.finishRendererOperation(old, retainingSource: true)
    try await rejects { try runtime.requireNativeAvailable() }
    runtime.releaseRendererSource(old)
    try runtime.requireNativeAvailable()
    checks += 7
    return checks
  }
}
