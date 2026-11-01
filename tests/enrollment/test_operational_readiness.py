"""Closed registration stays reachable; database loss still withdraws readiness."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from cosmas_os.enrollment import api
from cosmas_os.enrollment.config import EnrollmentSettings


def test_closed_registration_can_serve_config_when_database_is_ready(monkeypatch):
    monkeypatch.setattr(api, "schema_ready", lambda _engine: True)
    engine = create_engine("sqlite://")
    try:
        with TestClient(api.create_app(EnrollmentSettings(enabled=False), engine=engine)) as client:
            assert client.get("/operational-ready").status_code == 200
            assert client.get("/enrollment/v1/config").json()["enabled"] is False
            assert client.get("/ready").status_code == 503
            assert client.get("/enrollment/v1/status").status_code == 503
    finally:
        engine.dispose()


def test_database_loss_withdraws_operational_readiness_without_opening_registration(monkeypatch):
    monkeypatch.setattr(api, "schema_ready", lambda _engine: True)
    engine = create_engine("sqlite://")
    try:
        app = api.create_app(EnrollmentSettings(enabled=False), engine=engine)
        monkeypatch.setattr(api, "schema_ready", lambda _engine: False)
        with TestClient(app) as client:
            response = client.get("/operational-ready")
            assert response.status_code == 503
            assert response.json()["operational_ready"] is False
            assert client.get("/health").status_code == 200
            assert client.get("/enrollment/v1/config").json()["enabled"] is False
    finally:
        engine.dispose()
