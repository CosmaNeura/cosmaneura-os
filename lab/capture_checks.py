"""Reuse the actual recorder tests as an explicit, repeatable lab qualification tier."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager

CAPTURE_TESTS = [
    "src/audio/pcm-capture-worklet.test.ts", "src/audio/browser-microphone-source.test.ts",
    "src/audio/renewable-pcm.test.ts", "src/flow/continuous-controller.test.ts",
    "src/flow/encrypted-store.test.ts", "src/configured/flow/controller.integration.test.ts",
    "src/configured/flow/automatic-controller.test.ts", "src/configured/native/continuous-source.test.ts",
    "src/storage/encrypted-indexeddb.test.ts", "src/queue/capture-queue.test.ts",
    "src/configured/native/nurse-operational-recording.test.ts",
    "src/bff/recovery-contracts.test.ts", "src/flow/recovery-exchange.test.ts",
    "src/bff/source-contracts.test.ts",
]


@contextmanager
def dependencies(cwd, shared):
    """Reuse the pinned capture tools for desktop tests without an installation."""
    if not shared.is_dir():
        raise FileNotFoundError("Install the pinned capture test dependencies first")
    target = cwd / "node_modules"
    created = not target.exists() and not target.is_symlink()
    if created:
        target.symlink_to(shared, target_is_directory=True)
    try:
        yield
    finally:
        if created and target.is_symlink() and target.resolve() == shared.resolve():
            target.unlink()


def run_capture_checks(args):
    from lab.runner import write_report

    report = json.loads((args.output / "report.json").read_text())
    episodes_passed = report["status"] == "passed"
    report["status"] = "running"
    write_report(args.output, report)
    evidence = run_capture_suites(args.output / "capture-checks",
        stress=getattr(args, "capture_stress_checks", False))
    report = json.loads((args.output / "report.json").read_text())
    report["capture_checks"] = {"suites": evidence["suites"], "limits": evidence["limits"]}
    passed = evidence["passed"]
    report["status"] = "passed" if passed and episodes_passed else "failed"
    write_report(args.output, report)
    return 0 if passed else 1


def source_files():
    from lab.runner import REPO

    paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard",
        "clients/capture", "clients/desktop", "web", "lab/capture_checks.py", "lab/recording.py"],
        cwd=REPO, text=True).splitlines()
    return {path: hashlib.sha256((REPO / path).read_bytes()).hexdigest()
        for path in sorted(set(paths)) if (REPO / path).is_file()}


def run_capture_suites(root, *, stress=False):
    """Qualify recording separately, without a typed-note encounter or model call."""
    from lab.runner import REPO, run_owned_child

    root.mkdir(parents=True, exist_ok=False)
    before = source_files()
    node = shutil.which("node")
    env = {name: os.environ[name] for name in ("HOME", "USER", "LOGNAME", "TMPDIR", "PATH", "DEVELOPER_DIR") if name in os.environ}
    env.update(CI="true", LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8", NSUnbufferedIO="YES")
    env["COSMABOT_RECORDING_EVIDENCE_DIR"] = str(root / "operational")
    suites = [
        ("capture_pipeline", REPO / "clients/capture", CAPTURE_TESTS,
         "Generated PCM, encrypted queue, interrupted upload, renewal and restoration; synthetic receiver."),
        ("desktop_recorder", REPO / "clients/desktop", ["recorder"],
         "Actual mounted React recording buttons and desktop recorder lifecycle; synthetic native input, admission and custody protector."),
        ("recording_ui", REPO / "web", ["src/CapturePanel.test.tsx", "src/native-capture-runtime.test.ts",
         "src/EncounterCaptureLifecycle.test.tsx", "src/CaptureTranscriptEditor.test.tsx"],
         "Mounted product recording controls, optional DOB, consent, recovery, and transcript review; synthetic service/runtime boundaries."),
    ]
    if stress:
        suites.append(("capture_endurance", REPO / "clients/capture",
                       ["src/configured/flow/automatic-controller.test.ts"],
                       "Full one-hour PCM in both capture modes; twenty-minute offline storage reopen, lost receipt, missing/duplicate chunks."))
    results = []
    for name, cwd, selectors, scope in suites:
        result_file = root / (name + ".json")
        command = [node or "node-unavailable", str(cwd / "node_modules/vitest/vitest.mjs"), "run", *selectors,
                   "--reporter=json", "--outputFile", str(result_file)]
        command += ["--testNamePattern", "stress:" if name == "capture_endurance" else "^(?!.*stress:)"]
        with (root / (name + ".log")).open("w") as log:
            try:
                with dependencies(cwd, REPO / "clients/capture/node_modules"):
                    code = run_owned_child(command, env=env, log=log, timeout=300 if name == "capture_endurance" else 180, cwd=cwd)
                data = json.loads(result_file.read_text()) if result_file.exists() else {}
                count = data.get("numPassedTests", 0) + data.get("numFailedTests", 0)
                passed = code == 0 and data.get("success") is True and count > 0 and data.get("numFailedTests") == 0
                row = {"name": name, "passed": passed, "tests": count,
                       "skipped": data.get("numPendingTests", 0), "exit_code": code, "scope": scope,
                       "command": command, "cwd": str(cwd)}
            except (OSError, subprocess.TimeoutExpired, ValueError) as error:
                row = {"name": name, "passed": False, "error": type(error).__name__, "scope": scope}
        results.append(row)
        print(f"{name}: {'passed' if row['passed'] else 'FAILED'} ({row.get('tests', 0)} tests)", flush=True)
    native = [("native_audio", "clients/desktop/native-audio",
               "AlignedMeetingPCMTests|ContinuousCaptureWindowTests|AudioDeliveryTests", 240,
               "Real Swift PCM alignment/mixing and buffer boundaries using generated signals; no OS microphone or meeting capture.")]
    if stress:
        native.append(("native_endurance", "clients/capture/native-recording-pcm",
                       "LongSourceWindowTests|NativeInputFrameLimitTests|NativeRecordingPCMSinkTests|NativeRecordingContinuationTests", 900,
                       "Three-hour generated PCM through native encryption and fourteen leases; accelerated-clock input, route/background interruption and storage failures."))
    # File-provider metadata in Desktop build products can prevent ad-hoc signing.
    # Use owned temporary build storage; keep all logs and results in the evidence.
    scratch = tempfile.TemporaryDirectory(prefix="cosmabot-recording-swift-")
    try:
        for name, package, selector, timeout, scope in native:
            results.append(run_native_suite(root, scratch.name, name, package, selector, timeout, scope, env))
    finally:
        scratch.cleanup()
    after = source_files()
    operational = []
    for path in sorted((root / "operational").rglob("*.json")):
        operational.append({"path": str(path.relative_to(root)), "scenario": json.loads(path.read_text())})
    evidence = {"suites": results, "source_files": before, "source_unchanged": before == after,
        "operational_scenarios": operational,
        "passed": before == after and all(row["passed"] for row in results),
        "limits": ["No physical microphone, real-time endurance, OS audio routing or speech-recognition accuracy is proven.",
                   "Service admission, native audio input and upload receivers are synthetic; product controllers, encryption and queues execute.",
                   "These recorder checks are separate from the typed-note agent encounter."]}
    if before != after:
        evidence["source_after"] = after
    (root / "summary.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence


def run_native_suite(root, scratch, name, package, selector, timeout, scope, env):
    from pathlib import Path

    from lab.runner import REPO, run_owned_child

    command = ["/usr/bin/swift", "test", "--package-path", str(REPO / package),
               "--scratch-path", str(Path(scratch) / (name + "-build")), "--filter", selector]
    with (root / (name + ".log")).open("w") as log:
        try:
            code = run_owned_child(command, env=env, log=log, timeout=timeout)
            count, failures = swift_counts((root / (name + ".log")).read_text())
            row = {"name": name, "passed": code == 0 and count > 0 and failures == 0,
                   "tests": count, "exit_code": code, "scope": scope, "command": command}
        except (OSError, subprocess.TimeoutExpired) as error:
            row = {"name": name, "passed": False, "error": type(error).__name__, "scope": scope,
                   "command": command}
    print(f"{name}: {'passed' if row['passed'] else 'FAILED'} ({row.get('tests', 0)} tests)", flush=True)
    return row


def swift_counts(output):
    """Swift packages can run both XCTest and Swift Testing in one invocation."""
    classic = re.findall(r"Executed (\d+) tests?, with (\d+) failures?", output)
    modern = re.findall(r"Test run with (\d+) tests?(?: in \d+ suites?)? passed", output)
    count, failures = map(int, classic[-1]) if classic else (0, 0)
    return count + (int(modern[-1]) if modern else 0), failures
