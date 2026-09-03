from __future__ import annotations

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cosmas_os.api.app import _identity, app
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.application.seed import SYNTH_CSV
from cosmas_os.cli import app as cli_app
from cosmas_os.config import settings


def test_health():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "env": "synth_os"}


def test_readiness_requires_current_database_schema(engine):
    response = TestClient(app).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "env": "synth_os"}


def test_health_reports_configured_environment(monkeypatch):
    monkeypatch.setattr(settings, "cosmas_env", "configured_test_env")
    response = TestClient(app).get("/health")
    assert response.json() == {"status": "ok", "env": "configured_test_env"}


def test_info_does_not_print_database_credentials(monkeypatch):
    secret_url = "postgresql+psycopg://user:secret@example.invalid/cosmas_os"
    monkeypatch.setattr(settings, "database_url", secret_url)
    result = CliRunner().invoke(cli_app, ["info"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "env=synth_os database_configured=True"
    assert secret_url not in result.stdout


def test_api_happy_path_requires_db(engine):
    # engine fixture ensures schema; API uses its own session factory bound to settings URL
    client = TestClient(app)
    seed = client.post("/synth/seed")
    assert seed.status_code == 200
    data = seed.json()
    headers = {"X-Box-Id": data["box_id"], "X-Actor-Principal-Id": data["owner_id"]}
    imp = client.post("/schedule/import", headers=headers, json={"csv_text": SYNTH_CSV})
    assert imp.status_code == 200
    appt_id = imp.json()["appointment_ids"][0]
    link = client.post(
        "/patient-links/attest",
        headers=headers,
        json={"source_pair_key": "csv:jordan-lee", "label": "Jordan Lee"},
    )
    assert link.status_code == 200
    chase = client.post(
        f"/chase/open?appointment_id={appt_id}&patient_link_id={link.json()['id']}&chaser_id={data['agents']['chaser']}",
        headers=headers,
    )
    assert chase.status_code == 200
    ticket_id = chase.json()["ticket_id"]
    dec = client.post(
        f"/tickets/{ticket_id}/decide",
        headers=headers,
        json={"kind": "approve"},
    )
    assert dec.status_code == 200
    q = client.get("/queue", headers=headers)
    assert q.status_code == 200
    assert any(i["id"] == ticket_id for i in q.json())


def test_synth_demo_queue_is_ready_for_human_review(engine):
    client = TestClient(app)
    seeded = client.post("/synth/demo-queue")
    assert seeded.status_code == 200
    data = seeded.json()
    headers = {
        "X-Box-Id": data["box_id"],
        "X-Actor-Principal-Id": data["owner_id"],
    }
    queue = client.get("/queue", headers=headers)
    assert queue.status_code == 200
    assert any(
        item["id"] == data["ticket_id"] and item["state"] == "pending_approval"
        for item in queue.json()
    )


def test_queue_requires_both_synthetic_identity_headers(engine):
    client = TestClient(app)
    seeded = client.post("/synth/seed").json()
    response = client.get("/queue", headers={"X-Box-Id": seeded["box_id"]})
    assert response.status_code == 401


def test_synth_seed_routes_are_hidden_outside_synth(monkeypatch, engine):
    monkeypatch.setattr(settings, "cosmas_env", "early_adopter_beta")
    response = TestClient(app).post("/synth/demo-queue")
    assert response.status_code == 404


def test_synthetic_beta_allows_seeded_message_edit_but_blocks_new_ingest(monkeypatch, engine):
    client = TestClient(app)
    seeded = client.post("/synth/demo-queue").json()
    headers = {
        "X-Box-Id": seeded["box_id"],
        "X-Actor-Principal-Id": seeded["owner_id"],
    }
    item = next(
        row for row in client.get("/queue", headers=headers).json()
        if row["id"] == seeded["ticket_id"]
    )

    monkeypatch.setattr(settings, "cosmas_env", "early_adopter_beta")
    monkeypatch.setattr(settings, "data_mode", "synthetic")
    identity = RequestIdentity(
        box_id=seeded["box_id"],
        principal_id=seeded["owner_id"],
        auth_mode="clerk_jwt",
        organization_id="org_test_beta",
    )
    app.dependency_overrides[_identity] = lambda: identity
    try:
        edited = client.post(
            f"/tickets/{seeded['ticket_id']}/edit",
            json={"body": "Invented beta-lab message only."},
        )
        imported = client.post("/schedule/import", json={"csv_text": SYNTH_CSV})
    finally:
        app.dependency_overrides.pop(_identity, None)

    assert item["state"] == "pending_approval"
    assert edited.status_code == 200
    assert imported.status_code == 403
    assert imported.json()["detail"] == "data entry is disabled until separate PHI authorization"
