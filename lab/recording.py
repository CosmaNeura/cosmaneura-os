"""Run the actual Scribe recording qualification without model or account setup."""

import argparse
import html
import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from lab.capture_checks import run_capture_suites
from lab.runner import REPO


def render(output, report):
    rows = "".join("<tr><th scope=row>" + html.escape(row["name"].replace("_", " "))
        + "</th><td>" + ("Passed" if row["passed"] else "Failed")
        + f"</td><td>{row.get('tests', 0)}</td><td>" + html.escape(row["scope"]) + "</td></tr>"
        for row in report["suites"])
    limits = "".join("<li>" + html.escape(value) + "</li>" for value in report["limits"])
    status = "Passed" if report["passed"] else "Needs attention"
    (output / "report.html").write_text(f"""<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<meta http-equiv=Content-Security-Policy content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Scribe recording qualification</title><style>body{{font:16px system-ui;margin:32px auto;padding:0 24px;max-width:1000px;color:#18263a}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #ccd5df}}code{{overflow-wrap:anywhere}}.scroll{{overflow:auto}}</style>
<h1>🎙️ Scribe recording qualification · {status}</h1><p>Generated audio only · no microphone or phone required.</p>
<p>Source commit: <code>{html.escape(report['commit'])}</code> · source unchanged: {report['source_unchanged']}</p>
<div class=scroll><table><thead><tr><th>Suite</th><th>Result</th><th>Tests</th><th>Scope</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Evidence limits</h2><ul>{limits}</ul><p>Exact commands, source hashes and scenario events are saved alongside this report.</p></html>""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New empty directory outside the repository")
    parser.add_argument("--stress", action="store_true", help="Also run one-hour capture and three-hour native PCM qualification")
    args = parser.parse_args()
    if (REPO / ".env").exists() or (REPO / ".env").is_symlink():
        parser.error("Use a checkout without .env")
    node = shutil.which("node")
    if not node:
        parser.error("Node 24 or newer is required; reuse the pinned dependencies")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 24:
        parser.error("Node 24 or newer is required; put the bundled runtime first in PATH")
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix="cosmabot-recording-"))
    if output.is_relative_to(REPO) or output.exists() and any(output.iterdir()):
        parser.error("Use a new empty output directory outside the repository")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    report = run_capture_suites(output / "capture-checks", stress=args.stress)
    report.update(schema="cosmabot-recording-lab.v1", synthetic_only=True, model_calls=0,
        finished_at=datetime.now(UTC).isoformat(), node_version=version,
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip())
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    render(output, report)
    print(f"Recording report: {output / 'report.html'}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
