from __future__ import annotations

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cosmas_os.api.app import app
from cosmas_os.application.seed import SYNTH_CSV
from cosmas_os.cli import app as cli_app
from cosmas_os.config import settings


def test_health():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "env": "synth_os"}


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
