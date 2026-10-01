import json

import httpx
import pytest
from lab.clinician_benchmark import capture, read_inputs, sha
from lab.clinician_session import PERSONAS, TRANSCRIPT


@pytest.mark.parametrize("bad", [None, "packet_changed", "request_changed", "baseline_failed", "duplicate_case"])
def test_benchmark_requires_exact_six_completed_ui_inputs(tmp_path, monkeypatch, bad):
    packet = TRANSCRIPT + "\nSCRIBE SUMMARY — unreviewed generated draft\nInvented source summary.\n"
    request = "Prepare three private drafts from the supplied synthetic notes."
    (tmp_path / "scribe-packet.txt").write_text(packet)
    for persona in PERSONAS:
        for number in (1, 2):
            (tmp_path / f"{persona}-{number}.json").write_text(json.dumps({
                "passed": bad != "baseline_failed", "checks": {"saved": True},
                "request_sha256": sha(request), "duration_ms": 1000}))

    def respond(incoming):
        assert incoming.url.host == "127.0.0.1" and incoming.url.port == 5195
        assert incoming.method == "GET" and not incoming.headers.get("authorization")
        return httpx.Response(200, json={"entries": [
            {"kind": "scratchpad", "content": "changed" if bad == "packet_changed" else packet.strip()},
            {"kind": "conversation", "content": "changed" if bad == "request_changed" else request},
            {"kind": "conversation", "content": "Legacy test-only verification request, not the original clinician input."}]})

    client = httpx.Client
    monkeypatch.setattr("lab.clinician_benchmark.httpx.Client",
                        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    if bad in {"packet_changed", "request_changed", "baseline_failed"}:
        with pytest.raises(ValueError):
            capture(tmp_path)
        assert not (tmp_path / "benchmark-input.json").exists()
        return
    captured = capture(tmp_path)
    path = tmp_path / "benchmark-input.json"
    assert read_inputs(path) == captured
    assert len(captured["rows"]) == 6 and captured["packet_sha256"] == sha(packet)
    if bad == "duplicate_case":
        captured["rows"][-1] = captured["rows"][0]
        path.write_text(json.dumps(captured))
        with pytest.raises(ValueError, match="distinct"):
            read_inputs(path)


def test_summary_uses_actual_selected_recipients_and_does_not_claim_usability(tmp_path):
    from lab.clinician_report import write

    (tmp_path / "events.jsonl").write_text("")
    roles = ["visit_prep", "research", "follow_up"]
    artifacts = [{"role": "chief_plan", "structured_plan": {"tasks": [{"owner": role} for role in roles]}},
                 *({"role": role} for role in roles), {"role": "chief"}]
    (tmp_path / "provider-1.json").write_text(json.dumps({"passed": True, "checks": {"saved": True},
        "handoff_receipts": [{"recipient_role": role, "status": "completed", "result_entry_id": role,
                               "attempt_count": 1} for role in roles], "artifacts": artifacts,
        "application": {"external_effects": 0}, "duration_ms": 100,
        "timing": {"phase_ms": {}, "recipient_queue_ms": {}, "recipient_execution_ms": {}},
        "tool_calls": 5, "failures": []}))
    result = write(tmp_path)
    assert not result["complete"] and result["rows"][0]["status"] == "passed"
    assert "separate from clinician usability acceptance" in (tmp_path / "run-summary.html").read_text()


def test_saved_drafts_alone_do_not_pass_the_observed_clinician_regressions():
    from lab.clinician_benchmark import quality_checks

    result = {"handoff_receipts": [{"recipient_role": role} for role in ("scribe", "research", "follow_up")],
              "artifacts": [{"role": "follow_up", "body": "Staff should clarify permission and collect the medication list."}]}
    checks = quality_checks(result, "Have Visit Prep prepare questions and Research investigate.")
    assert checks["research_and_follow_up_saved"] and checks["medication_gap_retained"]
    for key in ("requested_visit_prep_honored", "birth_date_retained_in_follow_up",
                "human_role_and_review_for_each_suggested_task", "contact_time_conflict_retained"):
        assert checks[key] is False


@pytest.mark.parametrize("text,expected", [
    ("No external actions or requests have been completed.", False),
    ("No requests were completed.", False),
    ("No requests are documented as completed.", True),
    ("No external actions or requests are confirmed as completed.", True),
    ("No tasks are documented to have been completed.", True),
    ("Completion of planned requests is not documented.", True),
])
@pytest.mark.parametrize("location", ["receipt", "source_draft"])
def test_benchmark_independently_checks_saved_draft_negative_completion_claims(text, expected, location):
    from lab.clinician_benchmark import quality_checks

    result = {"handoff_receipts": [{"recipient_role": "follow_up", "draft_text": text if location == "receipt" else "Draft saved."}],
              "artifacts": [{"role": "follow_up", "body": "Draft saved.", "structured_draft": {
                  "body": text if location == "source_draft" else "Draft saved.", "human_tasks": []}}]}
    assert quality_checks(result, "Prepare drafts.")["no_unsupported_negative_completion_claim"] is expected


@pytest.mark.parametrize("explicit_conflict_word", [False, True])
def test_clinician_case_check_preserves_both_contact_preferences_before_publication(explicit_conflict_word):
    from types import SimpleNamespace

    from lab.clinician_session import INTAKE, TRANSCRIPT, check_clinician_draft
    from lab.store import LabError

    source = "SYNTHETIC conflict: morning on intake versus after 15:00 in the transcript." if explicit_conflict_word else TRANSCRIPT + INTAKE
    if not explicit_conflict_word:
        assert "conflict" not in source.lower()
    sources = [{"content": source}]
    draft = SimpleNamespace(body="Contact preferences conflict and permission is unresolved.", unresolved=[], human_tasks=[])
    with pytest.raises(LabError, match="both documented"):
        check_clinician_draft("follow_up", draft, sources)
    draft.unresolved = ["Clarify morning versus after 15:00 with the patient; neither is confirmed."]
    check_clinician_draft("follow_up", draft, sources)
    check_clinician_draft("follow_up", SimpleNamespace(body="Unconfirmed preference.", unresolved=[], human_tasks=[]),
                          [{"content": "No contact time was supplied."}])


@pytest.mark.parametrize("worker_status", [0, 7])
def test_owned_launcher_preserves_worker_failure_and_always_records_cleanup(tmp_path, monkeypatch, worker_status):
    from lab import clinician_session

    output = tmp_path / "owned-run"
    closed = []

    class Cluster:
        url = "postgresql+psycopg://synthetic:synthetic@127.0.0.1:1/owned"

        def __init__(self, *_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            closed.append(True)

    def child(argv, **kwargs):
        assert "--worker" in argv and "--optimized" in argv
        assert kwargs["env"]["COSMABOT_CLINICIAN_CHILD"] == "owned-synthetic-cluster"
        return worker_status

    monkeypatch.setattr(clinician_session, "OwnedPostgres", Cluster)
    monkeypatch.setattr(clinician_session, "run_owned_child", child)
    monkeypatch.setattr("sys.argv", ["clinician-session", "--output", str(output)])
    if worker_status:
        with pytest.raises(SystemExit) as error:
            clinician_session.main()
        assert error.value.code == worker_status
    else:
        clinician_session.main()
    assert closed == [True]
    assert json.loads((output / "cleanup.json").read_text()) == {
        "owned_postgres_stopped": True, "temporary_password_file_removed": True}
