"""Self-contained result dashboard and an allowlisted loopback-only viewer."""

import html
import json
import statistics
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _text(value):
    return html.escape(str(value))


def _outcomes(rows, title):
    if not rows:
        return ""
    content = ""
    for row in rows:
        name = row.get("role", row.get("capability", "Review")).replace("_", " ").title()
        scenario = row.get("scenario", row.get("name", "Scenario")).replace("_", " ")
        result = "Passed" if row.get("passed") else "Needs work"
        checks = "".join("<li>" + ("✓ " if ok else "✕ ") + _text(key.replace("_", " ")) + "</li>"
                         for key, ok in row.get("checks", {}).items())
        limits = "".join("<li>" + _text(limit) + "</li>" for limit in row.get("limits", []))
        feedback = ("<p class=draft>" + _text(row["feedback"]) + "</p>") if row.get("feedback") else ""
        content += ("<details><summary>" + _text(result + " · " + name + " · " + scenario) + "</summary>"
                    + "<p class=meta>" + _text(row.get("evidence_level", "See the exact saved checks below.")) + "</p>"
                    + feedback + "<ul>" + checks + "</ul>"
                    + ("<p><strong>Evidence limits</strong></p><ul>" + limits + "</ul>" if limits else "") + "</details>")
    return "<section class=scenario-matrix><h3>" + _text(title) + "</h3>" + content + "</section>"


def _review_flow(graph, prefix):
    """Static, keyboard-accessible graph with the same links in a text list."""
    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    if not nodes:
        return ""
    edges = [edge for edge in graph.get("edges", []) if edge["from"] in nodes and edge["to"] in nodes]
    ranks, remaining = {}, set(nodes)
    while remaining:
        ready = [key for key in nodes if key in remaining and all(
            edge["from"] in ranks for edge in edges if edge["to"] == key)]
        if not ready:
            ready = [key for key in nodes if key in remaining]
        for key in ready:
            ranks[key] = 1 + max((ranks.get(edge["from"], -1) for edge in edges if edge["to"] == key), default=-1)
            remaining.remove(key)
    ordered = sorted(nodes, key=lambda key: ranks[key])
    anchors = {key: prefix + "-node-" + str(index) for index, key in enumerate(ordered)}
    labels = {key: node.get("display_label") or node["role"].replace("_", " ").title() + " · " + node["kind"].replace("_", " ")
              for key, node in nodes.items()}
    states = {"draft": "Awaiting simulated review", "edits_requested": "Edits requested",
              "signed_off": "Accepted by simulated reviewer"}
    def state_label(node):
        return states.get(node.get("review_state", "draft"), node.get("review_state", "draft")) if node["kind"] == "material" else "Saved application evidence"

    positions, counts = {}, {}
    for key in ordered:
        rank = ranks[key]
        positions[key] = (20 + rank * 280, 24 + counts.get(rank, 0) * 116)
        counts[rank] = counts.get(rank, 0) + 1
    width, height = 280 * (max(ranks.values()) + 1), max(counts.values()) * 116 + 24
    diagram = (f'<svg role="img" aria-labelledby="{prefix}-title {prefix}-description" '
               f'viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
               f'<title id="{prefix}-title">Saved materials and review revisions</title>'
               f'<desc id="{prefix}-description">Arrows connect saved dependencies. Dashed arrows mark a revision after feedback. '
               'Every node links to its exact material and reviewer feedback below.</desc>'
               f'<defs><marker id="{prefix}-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">'
               '<path d="M0,0 L6,3 L0,6" fill="#557369"/></marker></defs>')
    for edge in edges:
        if edge["relation"] != "revised_after_feedback" and any(
            other["from"] == edge["from"] and other["to"] == edge["to"] and other["relation"] == "revised_after_feedback"
            for other in edges
        ):
            continue
        x, y = positions[edge["from"]]
        target_x, target_y = positions[edge["to"]]
        revised = edge["relation"] == "revised_after_feedback"
        diagram += (f'<path class="flow-edge {"revision-edge" if revised else ""}" '
                    f'd="M{x + 234},{y + 40} H{x + 253} V{target_y + 40} H{target_x}" '
                    f'marker-end="url(#{prefix}-arrow)"/>')
    for key in ordered:
        node, (x, y) = nodes[key], positions[key]
        state = node.get("review_state", "draft")
        role = node["role"].replace("_", " ").title()
        diagram += (f'<a href="#{anchors[key]}" aria-label="{_text(labels[key])}: {_text(state_label(node))}">'
                    f'<rect x="{x}" y="{y}" width="234" height="80" rx="8" class="flow-node {_text(state)}"/>'
                    f'<text x="{x + 12}" y="{y + 24}" class="flow-label">{_text(role)}</text>'
                    f'<text x="{x + 12}" y="{y + 44}">{_text(node["kind"].replace("_", " "))}</text>'
                    f'<text x="{x + 12}" y="{y + 65}">{_text(state_label(node))}</text></a>')
    diagram += "</svg>"
    materials = ""
    personas = {"provider": "Family practice doctor", "nurse": "Nurse practitioner", "pa": "Physician assistant"}
    for key in ordered:
        node = nodes[key]
        links = "".join('<li>' + ("Revised after feedback on " if edge["relation"] == "revised_after_feedback" else "Uses saved material from ")
                        + f'<a href="#{anchors[edge["from"]]}">{_text(labels[edge["from"]])}</a></li>'
                        for edge in edges if edge["to"] == key)
        decisions = ""
        for decision in node.get("decisions", []):
            choice = "Requested edits" if decision["choice"] == "request_edits" else "Accepted this exact version"
            decisions += ("<div class=review-feedback><p><strong>" + _text(personas.get(decision["persona"], decision["persona"]))
                          + " · simulated reviewer agent</strong><br>" + _text(choice) + "</p>"
                          + "<blockquote class=draft>" + _text(decision["feedback"]) + "</blockquote>"
                          + "<p class=meta>Reviewed material SHA-256: " + _text(decision["material_sha256"]) + "</p></div>")
        receipt = node.get("application_receipt")
        receipt_text = ("<details><summary>Saved application evidence</summary><pre>"
                        + _text(json.dumps(receipt, indent=2, ensure_ascii=False)) + "</pre></details>") if receipt else ""
        materials += (f'<li id="{anchors[key]}"><h4>{_text(labels[key])}</h4><p class=meta>'
                      + _text(state_label(node)) + "</p>"
                      + ("<ul class=material-links>" + links + "</ul>" if links else "")
                      + "<details><summary>Read exact material</summary><p class=draft>" + _text(node["body"])
                      + "</p><p class=meta>Material SHA-256: " + _text(node["sha256"]) + "</p></details>"
                      + decisions + receipt_text + "</li>")
    state = "Latest materials accepted by simulated reviewers" if graph.get("complete") else "Simulated review is still in progress"
    return ("<section class=review-process><h3>Review and revision workflow</h3><p><strong>" + state + "</strong></p>"
            + "<p class=notice>These are simulated reviewer agent sign-offs for test materials, not clinical approvals or permission to send, sign or change a patient record.</p>"
            + "<p class=meta>Solid arrows: saved dependencies. Dashed arrows: revised after feedback. Scroll the diagram horizontally if needed, or use the linked materials below.</p>"
            + '<div class="table-scroll flow-scroll" tabindex="0" role="region" aria-label="Review workflow diagram">'
            + diagram + '</div><ol class=review-materials>' + materials + "</ol></section>")


def render(root, report):
    episodes = report["episodes"]
    passed = sum(e["passed"] for e in episodes)
    durations = sorted(e["duration_ms"] / 1000 for e in episodes)
    median = statistics.median(durations) if durations else 0
    cards = []
    for episode_index, episode in enumerate(episodes):
        failures = ", ".join(k.replace("_", " ") for k, ok in episode["checks"].items() if not ok)
        receipts = episode.get("handoff_receipts", [])
        timing = episode.get("timing", {})
        phase_times = ("<details><summary>Time spent</summary><ul>" + "".join(
            "<li>" + html.escape(name.replace("_", " ").title()) + f": {ms / 1000:.1f}s</li>"
            for name, ms in timing.get("phase_ms", {}).items()) + "</ul><p>Longest measured handoff wait: "
            + (f'{max(timing["recipient_queue_ms"].values()) / 1000:.2f}s' if timing.get("recipient_queue_ms") else "Not measured")
            + "</p></details>") if timing else ""
        handoffs = ("<p><strong>Assigned drafts</strong> · human review outstanding</p><ul>"
            + "".join("<li>" + html.escape(r["recipient_name"]) + " · "
                + ("Draft saved" if r["status"] == "completed" else html.escape(r["status"]))
                + "</li>" for r in receipts) + "</ul>") if receipts else ""
        artifacts = "".join(
            f'<details><summary>{html.escape(a.get("display_label") or a["role"].replace("_", " ").title() + " · saved draft")}</summary>'
            f'<p class="draft">{html.escape(a["body"])}</p><p class="meta">Artifact {a["sha256"][:16]} · '
            f'{len(a.get("dependencies", []))} exact dependencies</p></details>' for a in episode["artifacts"])
        capabilities = _outcomes(episode.get("capability_scenarios", []), "Capability scenarios")
        reviews = _outcomes(episode.get("review_scenarios", []), "Review scenario checks")
        graph = _review_flow(episode.get("review_graph", {}), "episode-" + str(episode_index))
        scenarios = episode.get("connector_scenarios", [])
        matrix = ("<details open><summary>Connector scenarios</summary><ul>" + "".join(
            "<li>" + ("✓ " if r["passed"] else "✕ ") + html.escape(r["provider"].title() + " · " + r["scenario"].replace("_", " "))
            + f' · {r["duration_ms"]} ms</li>' for r in scenarios) + "</ul></details>") if scenarios else ""
        lessons = episode.get("shared_lessons", [])
        shared = ("<details><summary>Lessons shared between provider teams</summary><ul>" + "".join(
            "<li>" + html.escape(lesson["finding"]) + "<p class=meta>Scenario checks: "
            + html.escape(", ".join(("Passed: " if s["passed"] else "Needs work: ") + s["scenario"].replace("_", " ") for s in lesson["tested_scenarios"]) or
                          "Setup validation is covered by the separate application tests.")
            + "</p></li>" for lesson in lessons) + "</ul></details>"
            + "<p class=meta>" + html.escape(episode["evidence_level"])
            + " Timings measure local replay, not provider delivery speed.</p>") if lessons else ""
        phases = episode.get("phases", [])
        stages = ("<details open><summary>Encounter stages</summary><ul>" + "".join(
            "<li>" + ("✓ " if r["passed"] else "✕ ") + html.escape(r["name"]) + "</li>" for r in phases)
            + "</ul><p class=meta>Approvals and provider replies use synthetic test actors.</p></details>") if phases else ""
        incoming = ""
        if episode.get("inbound_scenarios"):
            incoming = "<details open><summary>Incoming work evaluation</summary>"
            for row in episode["inbound_scenarios"]:
                metrics = row.get("metrics", {})
                incoming += "<p><strong>" + html.escape(row["provider"].title()) + "</strong> · " + ("Passed" if row["passed"] else "Needs work") + "</p>"
                if metrics:
                    incoming += (f'<p>First useful Chief plan: {metrics["time_to_first_useful_result_ms"] / 1000:.2f}s · '
                        f'Handoffs correct: {metrics["handoff_correct"]}/{metrics["handoff_total"]} · '
                        f'Duplicate actions: {metrics["duplicate_actions"]} · '
                        f'Longest handoff wait: {metrics["max_handoff_wait_ms"] / 1000:.2f}s · '
                        f'Recovered responses: {metrics["recovered_lost_responses"]}</p>'
                        f'<p>{metrics["persona_task_steps"]} scripted provider steps; browser clicks and real usability are unmeasured.</p>')
            incoming += "<p class=meta>" + html.escape(" ".join(episode.get("limits", []))) + "</p></details>"
            incoming += "<details><summary>Fax submission and delivery receipts</summary><ul>"
            for fax in episode.get("fax_receipts", []):
                incoming += "<li>" + html.escape(fax["provider"].title() + " · " + fax["scenario"].replace("_", " "))
                incoming += "<ul>" + "".join("<li>" + html.escape(stage["stage"].replace("_", " "))
                    + f' · {stage["submit_calls"]} submit call · ' + html.escape(stage["acceptance"] + " · " + stage["transport"])
                    + "</li>" for stage in fax["receipt_stages"]) + "</ul></li>"
            incoming += "</ul><p class=meta>Provider acceptance is separate from delivery and human completion. All HTTP is simulated.</p></details>"
        cards.append(f'''<article class="episode {'has-review' if graph else ''}" data-case="{html.escape(episode['case'])}">
<div class="episode-head"><div><p class="eyebrow">{html.escape(episode['id'])}</p><h2>{html.escape(episode['title'])}</h2></div>
<span class="badge {'pass' if episode['passed'] else 'fail'}">{'Passed' if episode['passed'] else 'Needs work'}</span></div>
<p>{episode['duration_ms'] / 1000:.1f}s · {episode['tool_calls']} tool calls · application: {html.escape(episode['application']['status'])}</p>
{handoffs}
{phase_times}
{matrix}{shared}{stages}{incoming}{graph}{reviews}{capabilities}
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
    capture = report.get("capture_checks", {})
    capture_panel = ("<section class=panel><h2>Recorder qualification</h2><ul>" + "".join(
        "<li>" + ("✓ " if s["passed"] else "✕ ") + html.escape(s["name"].replace("_", " ").title())
        + f' · {s.get("tests", 0)} tests<p class=meta>' + html.escape(s["scope"]) + "</p></li>" for s in capture["suites"])
        + "</ul><p>" + html.escape(" ".join(capture["limits"])) + "</p></section>") if capture else ""
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
.episode{{min-width:0}}.has-review{{grid-column:1/-1}}.scenario-matrix,.review-process{{margin-top:24px}}h3{{font-size:17px;margin:0 0 8px}}h4{{font-size:15px;margin:0}}.review-materials{{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,290px),1fr));gap:16px}}.review-materials>li{{border:1px solid #dce4df;border-radius:8px;padding:16px;min-width:0;scroll-margin-top:16px}}.review-materials>li:target{{outline:3px solid #568978;outline-offset:2px}}.review-feedback{{border-left:3px solid #568978;padding-left:12px;margin-top:14px}}blockquote{{margin:8px 0}}.meta,.draft,pre,a{{overflow-wrap:anywhere}}pre{{white-space:pre-wrap;font-size:12px}}a{{color:#195f47}}a:focus-visible,.flow-scroll:focus-visible{{outline:3px solid #568978;outline-offset:3px}}.flow-scroll{{border:1px solid #e5ebe7;border-radius:8px;background:#f8faf7}}svg{{display:block}}.flow-edge{{fill:none;stroke:#557369;stroke-width:1.5}}.revision-edge{{stroke:#916012;stroke-dasharray:5 4;stroke-width:2}}.flow-node{{fill:white;stroke:#a4b9ae;stroke-width:1.5}}.flow-node.edits_requested{{fill:#fff3dd;stroke:#99701c}}.flow-node.signed_off{{fill:#e3f3e8;stroke:#39795a}}svg text{{font-family:ui-sans-serif,system-ui,sans-serif;font-size:11px;fill:#18362e}}svg .flow-label{{font-weight:650;font-size:14px}}
@media(max-width:650px){{main{{padding:18px 14px 50px}}h1{{font-size:28px}}.stats{{grid-template-columns:1fr 1fr}}.grid{{grid-template-columns:1fr}}.stat,.episode,.panel{{padding:16px}}.badge{{font-size:11px}}.review-materials{{grid-template-columns:1fr}}}}
</style></head><body><main><header><p class="eyebrow">CosmaBot / Synthetic development environment</p><h1>Agent laboratory</h1>
<p class="intro">Watch the team use tools, exchange saved drafts, and test the application. Each result below is backed by an execution trace and explicit checks.</p>
<p><span class="badge {'pass' if report['status']=='passed' else 'fail'}">{html.escape(report['status'].title())}</span> · {html.escape(report['model'])} · {report['concurrency']} workers · fault: {html.escape(report['fault'])}</p></header>
<div class="stats"><div class="stat"><strong>{passed}/{len(episodes)}</strong><span>Episodes passed</span></div><div class="stat"><strong>{median:.1f}s</strong><span>Median episode · n={len(episodes)}</span></div><div class="stat"><strong>{sum(e['tool_calls'] for e in episodes)}</strong><span>Executed tool calls</span></div><div class="stat"><strong>{usage.get('tokens',0):,}</strong><span>Model tokens · {usage.get('model_calls',0)} calls</span></div></div>
<div class="notice">{'Real GPT‑4.1 tool decisions with synthetic data.' if report['mode']=='azure' else 'Deterministic replay: tools execute, but no model is called.'} Human approvals are performed by a separate synthetic test actor. External effects: zero.</div>
{performance}<div class="grid">{''.join(cards)}</div>{capture_panel}<section class="panel"><h2>Workflow coverage</h2><p class="meta">Agent episodes and existing application contract suites are separate evidence levels. An unrun workflow stays visible.</p><div class="table-scroll"><table><thead><tr><th>Workflow</th><th>Passes / runs</th><th>Application contracts</th></tr></thead><tbody>{coverage}</tbody></table></div></section>
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
