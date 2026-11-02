"""Exercise the actual owned Foundation-only native CSP transformation."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def native_policy_check(tmp_path_factory):
    folder = tmp_path_factory.mktemp("native-selected-document-policy")
    runner = folder / "PolicyChecks.swift"
    runner.write_text(r'''
import Foundation
@main struct PolicyChecks {
    static let api = "https://api.a.staging.cosmas.ai"
    static let other = "https://api.123e4567-e89b-42d3-a456-426614174000.staging.cosmas.ai"
    static let policy = "default-src &#x27;none&#x27;; script-src &#x27;self&#x27;; connect-src &#x27;self&#x27; https://api.staging.cosmas.ai; object-src &#x27;none&#x27;; frame-src blob:"
    static func document(_ content: String = policy) -> String {
        "<!doctype html><html><head>\n<meta http-equiv=\"Content-Security-Policy\" content=\"" + content + "\" /><script src=\"/assets/app.js\"></script></head><body></body></html>"
    }
    static func rejected(_ source: String, _ api: String = api) {
        do { _ = try WorkspaceRegisteredDocumentPolicy.selectedHTML(source, apiOrigin: api); fatalError("Invalid policy accepted") }
        catch { }
    }
    static func main() throws {
        switch CommandLine.arguments[1] {
        case "selected":
            let source = document()
            let result = try WorkspaceRegisteredDocumentPolicy.selectedHTML(source, apiOrigin: api)
            precondition(result == source.replacingOccurrences(of: "https://api.staging.cosmas.ai;", with: "https://api.staging.cosmas.ai " + api + ";"))
            let uuidResult = try WorkspaceRegisteredDocumentPolicy.selectedHTML(document(), apiOrigin: other)
            precondition(uuidResult.contains(other))
        case "unchanged":
            let source = document(policy.replacingOccurrences(of: "https://api.staging.cosmas.ai", with: api))
            let result = try WorkspaceRegisteredDocumentPolicy.selectedHTML(source, apiOrigin: api)
            precondition(result == source)
        case "malformed":
            rejected(document().replacingOccurrences(of: "<head>", with: "<head><script src=\"early.js\"></script>"))
            rejected(document().replacingOccurrences(of: "</head>", with: "<meta http-equiv='Content-Security-Policy' content=\"connect-src *\" /></head>"))
            rejected("<html><head></head><body></body></html>")
            rejected(document(policy + "; connect-src &#x27;self&#x27;"))
        case "origins":
            for value in ["https://evil.example", "https://api.a.staging.cosmas.ai/path", "https://api.a.staging.cosmas.ai:443", "https://api.a.staging.cosmas.ai?next=x", "https://api.a.staging.cosmas.ai#fragment", "https://user@api.a.staging.cosmas.ai", "https://api.*.staging.cosmas.ai", "http://api.a.staging.cosmas.ai"] { rejected(document(), value) }
        case "compiled-policy":
            rejected(document(policy.replacingOccurrences(of: "https://api.staging.cosmas.ai", with: "https://*.staging.cosmas.ai")))
            rejected(document(policy.replacingOccurrences(of: "https://api.staging.cosmas.ai", with: "https://api.staging.cosmas.ai/path")))
            rejected(document(policy.replacingOccurrences(of: "connect-src &#x27;self&#x27;", with: "connect-src *")))
        default: fatalError("Unknown case")
        }
    }
}
''', encoding="utf-8")
    executable = folder / "policy-check"
    compiler = shutil.which("swiftc")
    assert compiler is not None, "The native document policy check requires a Swift compiler on PATH."
    command = [compiler, "-swift-version", "6", "-module-cache-path", str(folder / "module-cache"), str(ROOT / "clients/apple/startup-recovery/WorkspaceRecoveryState.swift"), str(runner), "-o", str(executable)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


@pytest.mark.parametrize("case", ["selected", "unchanged", "malformed", "origins", "compiled-policy"])
def test_native_selected_document_retains_closed_compiled_policy(native_policy_check, case):
    result = subprocess.run([str(native_policy_check), case], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
