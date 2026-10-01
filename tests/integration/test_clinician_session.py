"""The clinician browser bridge uses actual durable services, not canned replies."""

import pytest
from fastapi.testclient import TestClient
from lab.clinician_session import INTAKE, TRANSCRIPT, Rehearsal, build_api


@pytest.fixture(params=[False, True], ids=["baseline", "optimized"])
def rehearsal(engine, tmp_path, monkeypatch, request):
    from cosmas_os.config import settings

    for name in ("workspace_llm_backend", "workspace_llm_api_key", "workspace_capture_backend", "workspace_enabled"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    lab = Rehearsal(tmp_path, engine, "replay", optimized=request.param)
    lab.prepare()
    with TestClient(build_api(lab), base_url="http://127.0.0.1:5195") as client:
        yield lab, client


def test_clinician_input_reaches_three_real_saved_recipients_and_recovers(rehearsal):
    lab, client = rehearsal
    base = "/lab-api/provider/1"
    opened = client.get(base + "/open")
    assert opened.status_code == 200, opened.text
    assert opened.json()["team"]["llm"]["enabled"] is True
    workspace = opened.json()["workspace"]
    appended = client.post(base + "/entries", json={"expected_revision": workspace["revision"],
        "idempotency_key": "clinician-notebook", "kind": "scratchpad", "content": TRANSCRIPT + INTAKE})
    assert appended.status_code == 200, appended.text
    assert appended.json()["workspace"]["label"] == workspace["label"] == "Jordan Cypress · invented visit"
    command = {"expected_revision": appended.json()["workspace"]["revision"], "team_revision": 1,
               "idempotency_key": "clinician-chief-request", "role": "chief", "content": "Prepare team drafts from these notes."}
    result = client.post(base + "/ask", json=command)
    assert result.status_code == 200 and result.json()["outcome"] == "saved", result.text
    status = client.get(base + "/status").json()["result"]
    assert status["passed"], status
    assert len(status["handoff_receipts"]) == 3
    expected_roles = {"visit_prep", "research", "follow_up"} if lab.optimized else {"scribe", "research", "follow_up"}
    assert {row["recipient_role"] for row in status["handoff_receipts"]} == expected_roles
    assert len(status["artifacts"]) == 5 and status["application"]["external_effects"] == 0
    current = client.get(base + "/workspace").json()
    conversations = [entry for entry in current["entries"] if entry["kind"] == "conversation"]
    assert len(conversations) == (1 if lab.optimized else 2)
    assert conversations[0]["content"] == command["content"]
    for route in ("ask", "resolve"):
        assert client.post(base + "/" + route, json=command).json() == result.json()
    again = client.get(base + "/workspace").json()
    assert again["revision"] == current["revision"] and len(again["handoffs"]) == 3
    assert lab.budget.calls == 0


def test_persona_and_round_isolation_and_remote_origin_rejection(rehearsal):
    _lab, client = rehearsal
    views = [client.get(f"/lab-api/{persona}/{round_number}/open").json()
             for persona, round_number in (("provider", 1), ("nurse", 1), ("provider", 2))]
    assert len({view["workspace"]["id"] for view in views}) == 3
    assert len({view["team"]["recovery_scope"] for view in views}) == 3
    assert client.get("/lab-api/provider/1/open", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.get("/lab-api/provider/1/open", headers={"Authorization": "Bearer synthetic"}).status_code == 403
    assert client.get("/lab-api/other/1/open").status_code == 404
    assert client.get("/lab-api/provider/3/open").status_code == 404
    assert client.post("/lab-api/other/1/ask", json={}).status_code == 404
    assert client.post("/lab-api/provider/3/notes", json={}).status_code == 404


def test_no_arbitrary_clinical_context_or_actor_command(rehearsal):
    _lab, client = rehearsal
    client.get("/lab-api/provider/1/open")
    command = {"expected_revision": 2, "team_revision": 1, "idempotency_key": "invalid-chief-request",
               "role": "chief", "content": "Invented question", "research_analysis": None}
    assert client.post("/lab-api/provider/1/ask", json=command).status_code == 422
    assert client.post("/lab-api/provider/1/entries", json={"expected_revision": 2,
        "idempotency_key": "invalid-transcript-entry", "kind": "conversation", "content": "Invented"}).status_code == 422
