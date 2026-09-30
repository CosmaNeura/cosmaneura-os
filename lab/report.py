"""Self-contained result dashboard and an allowlisted loopback-only viewer."""

import html
import json
import statistics
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def render(root, report):
    episodes = report["episodes"]
    passed = sum(e["passed"] for e in episodes)
    durations = sorted(e["duration_ms"] / 1000 for e in episodes)
    median = statistics.median(durations) if durations else 0
    cards = []
    for episode in episodes:
        failures = ", ".join(k.replace("_", " ") for k, ok in episode["checks"].items() if not ok)
        receipts = episode.get("handoff_receipts", [])
        timing = episode.get("timing", {})
        phase_times = ("<details><summary>Time spent</summary><ul>" + "".join(
            "<li>" + html.escape(name.replace("_", " ").title()) + f": {ms / 1000:.1f}s</li>"
            for name, ms in timing.get("phase_ms", {}).items()) + "</ul><p>Longest wait for an agent to start: "
            + f'{max(timing.get("recipient_queue_ms", {}).values(), default=0) / 1000:.2f}s'
            + "</p></details>") if timing else ""
        handoffs = ("<p><strong>Assigned drafts</strong> · human review outstanding</p><ul>"
            + "".join("<li>" + html.escape(r["recipient_name"]) + " · "
                + ("Draft saved" if r["status"] == "completed" else html.escape(r["status"]))
                + "</li>" for r in receipts) + "</ul>") if receipts else ""
        artifacts = "".join(
            f'<details><summary>{html.escape(a["role"].replace("_", " ").title())} · saved draft</summary>'
            f'<p class="draft">{html.escape(a["body"])}</p><p class="meta">Artifact {a["sha256"][:16]} · '
            f'{len(a["dependencies"])} exact dependencies</p></details>' for a in episode["artifacts"])
        cards.append(f'''<article class="episode" data-case="{episode['case']}">
<div class="episode-head"><div><p class="eyebrow">{html.escape(episode['id'])}</p><h2>{html.escape(episode['title'])}</h2></div>
<span class="badge {'pass' if episode['passed'] else 'fail'}">{'Passed' if episode['passed'] else 'Needs work'}</span></div>
<p>{episode['duration_ms'] / 1000:.1f}s · {episode['tool_calls']} tool calls · application: {html.escape(episode['application']['status'])}</p>
{handoffs}
{phase_times}
{('<p class="error">'+html.escape(failures)+'</p>') if failures else ''}
<details><summary>What was checked</summary><ul>{''.join('<li>'+('✓ ' if ok else '✕ ')+html.escape(k.replace('_',' '))+'</li>' for k,ok in episode['checks'].items())}</ul></details>
{artifacts}</article>''')
    coverage = "".join(f'<tr><th scope="row">{html.escape(row["title"])}</th><td>{row["agent_passes"]}/{row["agent_episodes"]}</td>'
                       f'<td>{html.escape(row["application_contracts"].replace("_", " "))}</td></tr>' for row in report["coverage"])
    events = []
    if (root / "events.jsonl").exists():
        events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines() if line]
    timeline = "".join(f'<tr><td>{e["elapsed_ms"]/1000:.1f}s</td><td>{html.escape(e["episode"])}</td>'
                       f'<td>{html.escape(e["role"])}</td><td>{html.escape(e.get("tool", e["kind"]))}</td>'
                       f'<td>{html.escape(e.get("error", "OK"))}</td></tr>' for e in events[-300:])
    usage = report.get("usage", {})
    limits = "".join(f"<li>{html.escape(item)}</li>" for item in report["limits"])
    comparison = report.get("performance_comparison")
    performance = (f'''<section class="panel"><h2>Waiting time comparison</h2>
<p>{comparison['samples_each']} synthetic trials per configuration; same source, model and task.</p>
<div class="table-scroll"><table><thead><tr><th>Measure</th><th>Previous flow</th><th>Optimized flow</th></tr></thead><tbody>
<tr><th scope="row">Median completion</th><td>{comparison['baseline_median_ms']/1000:.1f}s</td><td>{comparison['candidate_median_ms']/1000:.1f}s</td></tr>
<tr><th scope="row">Median longest queue wait</th><td>{(comparison.get('baseline_max_queue_median_ms') or 0)/1000:.2f}s</td><td>{(comparison.get('candidate_max_queue_median_ms') or 0)/1000:.2f}s</td></tr>
<tr><th scope="row">Model calls across trials</th><td>{comparison['baseline_model_calls']}</td><td>{comparison['candidate_model_calls']}</td></tr>
</tbody></table></div><p>{comparison['observed_reduction_percent']}% observed reduction in completion time. Small synthetic sample; production performance is unmeasured.</p></section>''') if comparison else ""
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>CosmaBot · Agent laboratory</title><style>
:root{{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;color:#18362e;background:#f4f6f3;line-height:1.5}}*{{box-sizing:border-box}}
body{{margin:0}}main{{max-width:1140px;margin:auto;padding:32px 24px 80px}}header{{padding:24px 0}}.eyebrow{{font-size:12px;font-weight:650;letter-spacing:.09em;text-transform:uppercase;color:#557369;margin:0 0 6px}}
h1{{font-size:34px;font-weight:650;line-height:1.15;letter-spacing:-.03em;margin:6px 0 12px}}h2{{font-size:19px;margin:0}}p{{margin:10px 0}}.intro{{max-width:720px;color:#456056}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0 24px}}
.stat,.episode,.panel{{background:#fff;border:1px solid #dce4df;border-radius:12px;padding:20px}}.stat strong{{display:block;font-size:26px;letter-spacing:-.03em}}.stat span,.meta{{font-size:12px;color:#567166}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.episode-head{{display:flex;justify-content:space-between;align-items:start;gap:12px}}
.badge{{display:inline-block;white-space:nowrap;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:650}}.pass{{background:#e3f3e8;color:#185c3b}}.fail{{background:#fff0d7;color:#795313}}.error{{color:#90451b;background:#fff5e8;padding:10px;border-radius:6px}}
details{{border-top:1px solid #e5ebe7;margin-top:10px}}summary{{cursor:pointer;padding:12px 0;min-height:44px;font-weight:550;font-size:14px}}summary:focus-visible{{outline:3px solid #568978;outline-offset:3px}}.draft{{white-space:pre-wrap;font-size:14px}}.panel{{margin-top:24px}}.table-scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px;margin:12px 0}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #e5ebe7;vertical-align:top}}thead{{color:#456056}}.notice{{background:#e7efe9;border-left:3px solid #4d7861;padding:12px 16px;font-size:14px;margin:20px 0}}ul{{padding-left:20px}}footer{{font-size:12px;color:#567166;margin-top:24px;overflow-wrap:anywhere}}
@media(max-width:650px){{main{{padding:18px 14px 50px}}h1{{font-size:28px}}.stats{{grid-template-columns:1fr 1fr}}.grid{{grid-template-columns:1fr}}.stat,.episode,.panel{{padding:16px}}.badge{{font-size:11px}}}}
</style></head><body><main><header><p class="eyebrow">CosmaBot / Synthetic development environment</p><h1>Agent laboratory</h1>
<p class="intro">Watch the team use tools, exchange saved drafts, and test the application. Each result below is backed by an execution trace and explicit checks.</p>
<p><span class="badge {'pass' if report['status']=='passed' else 'fail'}">{html.escape(report['status'].title())}</span> · {html.escape(report['model'])} · {report['concurrency']} workers · fault: {html.escape(report['fault'])}</p></header>
<div class="stats"><div class="stat"><strong>{passed}/{len(episodes)}</strong><span>Episodes passed</span></div><div class="stat"><strong>{median:.1f}s</strong><span>Median episode · n={len(episodes)}</span></div><div class="stat"><strong>{sum(e['tool_calls'] for e in episodes)}</strong><span>Executed tool calls</span></div><div class="stat"><strong>{usage.get('tokens',0):,}</strong><span>Model tokens · {usage.get('model_calls',0)} calls</span></div></div>
<div class="notice">{'Real GPT‑4.1 tool decisions with synthetic data.' if report['mode']=='azure' else 'Deterministic replay: tools execute, but no model is called.'} Human approvals are performed by a separate synthetic test actor. External effects: zero.</div>
{performance}<div class="grid">{''.join(cards)}</div><section class="panel"><h2>Workflow coverage</h2><p class="meta">Agent episodes and existing application contract suites are separate evidence levels. An unrun workflow stays visible.</p><div class="table-scroll"><table><thead><tr><th>Workflow</th><th>Agent passes / runs</th><th>Application contracts</th></tr></thead><tbody>{coverage}</tbody></table></div></section>
<section class="panel"><details><summary>Execution timeline · {len(events)} events (latest 300 shown)</summary><div class="table-scroll"><table><thead><tr><th>Time</th><th>Episode</th><th>Actor</th><th>Step</th><th>Result</th></tr></thead><tbody>{timeline}</tbody></table></div></details><details><summary>Scope and evidence limits</summary><ul>{limits}</ul></details></section>
<footer>Started {html.escape(report['started_at'])}<br>Source commit {html.escape(report['source']['commit'])}<br>Checked file-set SHA-256 {report['source']['source_sha256']}<br>Reload this page to see newly saved results. Full data: report.json and events.jsonl in the run directory.</footer></main></body></html>'''
    temporary = root / "report.next.html"
    temporary.write_text(page)
    temporary.replace(root / "report.html")


def serve(root, port=5190):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            choices = {"/": ("report.html", "text/html"), "/report.json": ("report.json", "application/json"),
                       "/events.jsonl": ("events.jsonl", "application/x-ndjson")}
            if self.path not in choices:
                self.send_error(404)
                return
            name, content_type = choices[self.path]
            path = root / name
            if not path.is_file():
                self.send_error(404)
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    print(f"Read-only dashboard: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
