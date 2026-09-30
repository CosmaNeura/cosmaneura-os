"""Reuse the actual recorder tests as an explicit, repeatable lab qualification tier."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager

CAPTURE_TESTS = [
    "src/audio/pcm-capture-worklet.test.ts", "src/audio/browser-microphone-source.test.ts",
    "src/audio/renewable-pcm.test.ts", "src/flow/continuous-controller.test.ts",
    "src/flow/encrypted-store.test.ts", "src/configured/flow/controller.integration.test.ts",
    "src/configured/flow/automatic-controller.test.ts", "src/configured/native/continuous-source.test.ts",
    "src/storage/encrypted-indexeddb.test.ts", "src/queue/capture-queue.test.ts",
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
    from lab.runner import REPO, run_owned_child, write_report

    root = args.output / "capture-checks"
    root.mkdir()
    report = json.loads((args.output / "report.json").read_text())
    episodes_passed = report["status"] == "passed"
    report["status"] = "running"
    write_report(args.output, report)
    node = shutil.which("node")
    env = {name: os.environ[name] for name in ("HOME", "USER", "LOGNAME", "TMPDIR", "PATH", "DEVELOPER_DIR") if name in os.environ}
    env.update(CI="true", LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")
    suites = [
        ("capture_pipeline", REPO / "clients/capture", CAPTURE_TESTS,
         "Generated PCM, encrypted queue, interrupted upload, renewal and restoration; synthetic receiver."),
        ("desktop_recorder", REPO / "clients/desktop", ["recorder"],
         "Actual desktop recorder lifecycle with synthetic native bridge and storage."),
    ]
    results = []
    for name, cwd, selectors, scope in suites:
        result_file = root / (name + ".json")
        command = [node or "node-unavailable", str(cwd / "node_modules/vitest/vitest.mjs"), "run", *selectors,
                   "--reporter=json", "--outputFile", str(result_file)]
        with (root / (name + ".log")).open("w") as log:
            try:
                with dependencies(cwd, REPO / "clients/capture/node_modules"):
                    code = run_owned_child(command, env=env, log=log, timeout=180, cwd=cwd)
                data = json.loads(result_file.read_text()) if result_file.exists() else {}
                count = data.get("numTotalTests", 0)
                passed = code == 0 and data.get("success") is True and count > 0 and data.get("numFailedTests") == 0
                row = {"name": name, "passed": passed, "tests": count, "exit_code": code, "scope": scope}
            except (OSError, subprocess.TimeoutExpired, ValueError) as error:
                row = {"name": name, "passed": False, "error": type(error).__name__, "scope": scope}
        results.append(row)
    native_scope = "Real Swift PCM alignment/mixing and buffer boundaries using generated signals; no OS microphone or meeting capture."
    command = ["/usr/bin/swift", "test", "--package-path", str(REPO / "clients/desktop/native-audio"),
        "--scratch-path", str(root / "swift-build"), "--filter",
        "AlignedMeetingPCMTests|ContinuousCaptureWindowTests|AudioDeliveryTests"]
    with (root / "native_audio.log").open("w") as log:
        try:
            code = run_owned_child(command, env=env, log=log, timeout=240)
            output = (root / "native_audio.log").read_text()
            counts = re.findall(r"Executed (\d+) tests?, with (\d+) failures?", output)
            modern = re.findall(r"Test run with (\d+) tests? in \d+ suites? passed", output)
            count, failures = (int(modern[-1]), 0) if modern else (map(int, counts[-1]) if counts else (0, 1))
            results.append({"name": "native_audio", "passed": code == 0 and count > 0 and failures == 0,
                            "tests": count, "exit_code": code, "scope": native_scope})
        except (OSError, subprocess.TimeoutExpired) as error:
            results.append({"name": "native_audio", "passed": False, "error": type(error).__name__, "scope": native_scope})
    paths = subprocess.check_output(["git", "ls-files", "clients/capture", "clients/desktop"], cwd=REPO, text=True).splitlines()
    hashes = {path: hashlib.sha256((REPO / path).read_bytes()).hexdigest() for path in paths if (REPO / path).is_file()}
    evidence = {"suites": results, "source_files": hashes,
        "limits": ["No physical microphone, real-time endurance, OS audio routing or speech-recognition accuracy is proven.",
                   "These recorder checks are separate from the typed-note agent encounter."]}
    (root / "summary.json").write_text(json.dumps(evidence, indent=2) + "\n")
    report = json.loads((args.output / "report.json").read_text())
    report["capture_checks"] = {"suites": results, "limits": evidence["limits"]}
    passed = all(row["passed"] for row in results)
    report["status"] = "passed" if passed and episodes_passed else "failed"
    write_report(args.output, report)
    return 0 if passed else 1
