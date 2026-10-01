"""Review reports preserve exact feedback, authority and safe local navigation."""

from html.parser import HTMLParser

from lab.report import render
from lab.review_graph import ReviewGraph


def fixture(tmp_path):
    graph = ReviewGraph(tmp_path)
    source = graph.add("source", kind="source", scope="invented", role="scribe", body="Invented source.")
    original = graph.add("draft-1", kind="material", scope="invented", role="scribe",
        body="Draft <script>do not execute</script>", dependencies=(source["id"],),
        application_receipt={"note_id": "actual-note-id", "content_hash": "exact-hash"})
    graph.decide(original["id"], persona="provider", scope="invented", expected_sha256=original["sha256"],
        choice="request_edits", feedback='Keep "records not reviewed". <img src="https://invalid.example/secret">', request_id="first")
    revised = graph.add("draft-2", kind="material", scope="invented", role="scribe",
        body="Revised draft: records not reviewed; request is planned.", dependencies=(original["id"],))
    graph.supersede(original["id"], revised["id"])
    graph.decide(revised["id"], persona="provider", scope="invented", expected_sha256=revised["sha256"],
        choice="sign_off", feedback="This exact revision preserves the uncertainty.", request_id="second")
    episode = {"id": "synthetic-review", "case": "review_loops", "title": "Invented review loop",
        "passed": True, "duration_ms": 125, "tool_calls": 2, "application": {"status": "synthetic"},
        "checks": {"revision_saved": True}, "review_graph": graph.snapshot(),
        "review_scenarios": [{"scenario": "changed_material", "passed": True, "checks": {"old_review_refused": True}}],
        "capability_scenarios": [{"role": "scribe", "scenario": "source_revision", "passed": False,
            "checks": {"source_kept": False}, "evidence_level": "Actual local source service; invented transcript.",
            "limits": ["No audio or transcription model was run."]}],
        "artifacts": [{"role": "scribe", "display_label": "Scribe · source evidence", "body": "Original source.", "sha256": source["sha256"]}]}
    return {"episodes": [episode], "coverage": [], "limits": ["Synthetic only."], "mode": "replay", "model": "none",
        "concurrency": 1, "fault": "none", "status": "passed", "started_at": "2026-10-01",
        "source": {"commit": "invented-commit", "source_sha256": "invented-source-hash"}}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.targets, self.tags = [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a":
            self.targets.append(attrs["href"])


def test_report_preserves_exact_feedback_and_separates_simulated_acceptance(tmp_path):
    report = fixture(tmp_path)
    render(tmp_path, report)
    page = (tmp_path / "report.html").read_text()
    parser = Links()
    parser.feed(page)
    assert "script" not in parser.tags and "img" not in parser.tags
    assert 'Keep &quot;records not reviewed&quot;. &lt;img src=' in page
    assert "This exact revision preserves the uncertainty." in page
    assert "simulated reviewer agent sign-offs for test materials, not clinical approvals" in page
    assert "Revised after feedback on" in page and "Uses saved material from" in page
    assert "actual-note-id" in page and "exact-hash" in page
    assert "Scribe · source evidence</summary>" in page and "0 exact dependencies" in page
    assert "Needs work · Scribe · source revision" in page
    assert "No audio or transcription model was run." in page
    for node in report["episodes"][0]["review_graph"]["nodes"]:
        assert node["sha256"] in page


def test_multiple_episode_graph_links_are_unique_local_and_accessible(tmp_path):
    report = fixture(tmp_path)
    report["episodes"].append(report["episodes"][0])
    render(tmp_path, report)
    page = (tmp_path / "report.html").read_text()
    parser = Links()
    parser.feed(page)
    assert len(parser.ids) == len(set(parser.ids))
    assert parser.targets and all(target.startswith("#") and target[1:] in parser.ids for target in parser.targets)
    assert 'aria-label="Review workflow diagram"' in page
    assert "Deterministic replay: tools execute, but no model is called." in page


def test_legacy_episode_and_model_mode_remain_supported(tmp_path):
    report = fixture(tmp_path)
    episode = report["episodes"][0]
    for field in ("review_graph", "review_scenarios", "capability_scenarios"):
        episode.pop(field)
    episode["artifacts"][0].pop("display_label")
    episode["artifacts"][0]["dependencies"] = []
    report["mode"] = "azure"
    render(tmp_path, report)
    page = (tmp_path / "report.html").read_text()
    assert "Review and revision workflow" not in page
    assert "Scribe · saved draft" in page
    assert "Real GPT‑4.1 tool decisions with synthetic data." in page
