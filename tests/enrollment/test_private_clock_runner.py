"""Explicit runner custody/authority wiring; no hosted or vendor qualification."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from tests.enrollment.test_private_clock_lab import (
    lab as lab,
)
from tests.enrollment.test_private_clock_lab import (
    postgres_journal as postgres_journal,
)
from tests.enrollment.test_private_clock_lab import (
    start_trial,
)

from cosmas_os.enrollment import private_clock_runner as runner
from cosmas_os.enrollment.config import EnrollmentSettings
from cosmas_os.enrollment.domain import EnrollmentError
from cosmas_os.enrollment.private_clock_lab import PostgresClockJournal, create_clock_lab_app


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value))
    path.chmod(0o600)


@pytest.fixture
def runner_files(lab, postgres_journal, tmp_path):
    # Reuse the provider/identity fixture with this runner's fixed central API
    # origin. Its canonical binding and journal row remain synthetic test data.
    binding = lab.binding.model_copy(update={"api_origin": runner.API_ORIGIN})
    save(lab.paths["binding_path"], binding.model_dump())
    lab.binding = binding
    lab.commerce.binding = binding
    lab.commerce.journal = PostgresClockJournal.prepare_database(postgres_journal.engine, binding)
    values = {name: (getattr(lab.settings, name).get_secret_value()
                    if isinstance(getattr(lab.settings, name), SecretStr)
                    else getattr(lab.settings, name)) for name in EnrollmentSettings.model_fields}
    central = postgres_journal.engine.url.set(username="enrollment_runtime", database="cosmabot_enrollment")
    values["database_url"] = central.render_as_string(hide_password=False)
    configuration = {"contract_version": runner.CONTRACT, "synthetic_only": True,
                     "binding_sha256": lab.binding.sha256, "journal_role": "clock_journal_a", "enrollment": values}
    config = tmp_path / "runner.json"
    journal = tmp_path / "journal.url"
    save(config, configuration)
    journal.write_text(postgres_journal.engine.url.set(username="clock_journal_a").render_as_string(hide_password=False) + "\n")
    journal.chmod(0o600)
    return configuration, {"configuration_path": config, "binding_path": lab.paths["binding_path"],
                           "journal_url_path": journal}


def no_engines(monkeypatch):
    def denied(*_args, **_kwargs):
        pytest.fail("invalid inputs reached engine creation")
    monkeypatch.setattr(runner, "create_engine", denied)


@pytest.mark.parametrize("field", ["binding_path", "journal_url_path"])
def test_missing_protected_input_stops_before_engine_work(runner_files, monkeypatch, field):
    _, paths = runner_files
    paths[field] = paths[field].with_name("absent")
    no_engines(monkeypatch)
    with pytest.raises((ValueError, EnrollmentError, OSError)):
        runner.create_explicit_app(**paths)


@pytest.mark.parametrize("change", ["production", "missing_field", "unknown_field", "wrong_hash"])
def test_production_ambient_and_unknown_configuration_refused(runner_files, monkeypatch, change):
    configuration, paths = runner_files
    if change == "production":
        configuration["enrollment"]["data_mode"] = "production"
    elif change == "missing_field":
        configuration["enrollment"].pop("production_qualified")
        monkeypatch.setenv("ENROLLMENT_PRODUCTION_QUALIFIED", "false")
    elif change == "unknown_field":
        configuration["enrollment"]["private_ingress_approved"] = True
    else:
        configuration["binding_sha256"] = "f" * 64
    save(paths["configuration_path"], configuration)
    no_engines(monkeypatch)
    with pytest.raises((ValueError, EnrollmentError)):
        runner.create_explicit_app(**paths)


def test_wrong_binding_and_unprotected_credential_refused(runner_files, monkeypatch):
    _, paths = runner_files
    binding = json.loads(paths["binding_path"].read_text())
    original_binding = dict(binding)
    binding["organization_id"] = "org_wrong"
    save(paths["binding_path"], binding)
    no_engines(monkeypatch)
    with pytest.raises((ValueError, EnrollmentError)):
        runner.create_explicit_app(**paths)
    save(paths["binding_path"], original_binding)
    paths["journal_url_path"].chmod(0o644)
    with pytest.raises((ValueError, EnrollmentError)):
        runner.create_explicit_app(**paths)


@pytest.mark.parametrize("change", ["wrong_role", "shared_database", "foreign_journal"])
def test_journal_scope_or_shared_database_refused(runner_files, monkeypatch, change):
    configuration, paths = runner_files
    if change == "shared_database":
        configuration["enrollment"]["database_url"] = paths["journal_url_path"].read_text().strip()
        save(paths["configuration_path"], configuration)
    elif change == "wrong_role":
        paths["journal_url_path"].write_text(paths["journal_url_path"].read_text().replace("clock_journal_a", "clock_journal_b"))
    else:
        paths["journal_url_path"].write_text(paths["journal_url_path"].read_text().replace("127.0.0.1", "foreign.example"))
    no_engines(monkeypatch)
    with pytest.raises((ValueError, EnrollmentError)):
        runner.create_explicit_app(**paths)


def wire_fixture(lab, postgres_journal, monkeypatch):
    engines = []

    def engine(url, **kwargs):
        assert kwargs["hide_parameters"] is True
        assert kwargs["connect_args"] == {"connect_timeout": 10}
        engines.append(url)
        # Reuse the fixture's migrated registry and real private PostgreSQL
        # journal. Only the engine construction boundary uses fixture stores.
        return lab.engine if url.database == "cosmabot_enrollment" else postgres_journal.engine

    def factory(settings, **kwargs):
        assert "workspace_confirmer" not in kwargs
        return create_clock_lab_app(settings, **kwargs, **lab.ports)

    monkeypatch.setattr(runner, "create_engine", engine)
    monkeypatch.setattr(runner, "create_clock_lab_app", factory)
    return engines


@pytest.mark.parametrize("audience", ["", "invented-enrollment-session"])
def test_explicit_real_factory_wiring_keeps_original_trial_and_ignores_ambient(runner_files, lab, postgres_journal, monkeypatch, audience):
    _, paths = runner_files
    configuration = json.loads(paths["configuration_path"].read_text())
    configuration["enrollment"]["clerk_audience"] = audience
    paths["configuration_path"].write_text(json.dumps(configuration))
    start_trial(lab)
    before = PostgresClockJournal(postgres_journal.engine, lab.binding).read()
    engines = wire_fixture(lab, postgres_journal, monkeypatch)
    monkeypatch.setenv("ENROLLMENT_PRODUCTION_QUALIFIED", "true")
    monkeypatch.setenv("ENROLLMENT_STRIPE_LIVE_MODE", "true")
    monkeypatch.setenv("ENROLLMENT_CLERK_AUDIENCE", "untrusted-ambient-audience")
    app = runner.create_explicit_app(**paths)
    with TestClient(app) as client:
        response = client.get("/enrollment/v1/config")
        assert response.status_code == 200 and response.json()["workspace_confirmation_configured"] is True
        assert app.state.enrollment_service.settings.stripe_live_mode is False
        assert app.state.enrollment_service.settings.production_qualified is False
        assert app.state.enrollment_service.settings.clerk_audience == audience
        assert client.put("/enrollment/v1/practice", json={}).status_code == 503
    assert len(engines) == 2 and engines[0].database != engines[1].database
    assert PostgresClockJournal(postgres_journal.engine, lab.binding).read() == before


def test_pending_clock_startup_failure_preserves_journal(runner_files, lab, postgres_journal, monkeypatch):
    _, paths = runner_files
    start_trial(lab)
    journal = PostgresClockJournal(postgres_journal.engine, lab.binding)
    journal.target("before")
    before = journal.read()
    wire_fixture(lab, postgres_journal, monkeypatch)
    with pytest.raises(EnrollmentError):
        runner.create_explicit_app(**paths)
    assert journal.read() == before


def test_runner_has_no_public_listener_or_zero_argument_factory(monkeypatch):
    monkeypatch.setattr("sys.argv", ["clock-runner"])
    with pytest.raises(SystemExit):
        runner.main()
    monkeypatch.setattr("sys.argv", ["clock-runner", "--configuration", "/absent/config", "--binding", "/absent/binding",
                                    "--journal-url-file", "/absent/journal", "--listen-host", "0.0.0.0",
                                    "--listen-port", "8061", "--intent", "RUN_PRIVATE_SYNTHETIC_CLOCK"])
    with pytest.raises(SystemExit):
        runner.main()


@pytest.mark.parametrize("ambient_mode", ["synthetic", "production"])
def test_fresh_factory_import_never_initializes_ambient_app(runner_files, tmp_path, ambient_mode):
    configuration, _ = runner_files
    values = configuration["enrollment"]
    ambient = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
               "PYTHONDONTWRITEBYTECODE": "1"}
    for name, value in values.items():
        ambient["ENROLLMENT_" + name.upper()] = (json.dumps(value) if isinstance(value, (bool, list)) else str(value))
    ambient["ENROLLMENT_DATA_MODE"] = ambient_mode
    ambient["ENROLLMENT_STRIPE_LIVE_MODE"] = "true"
    ambient["ENROLLMENT_PRODUCTION_QUALIFIED"] = "true"
    ambient["ENROLLMENT_STRIPE_SECRET_KEY"] = "sk_live_invented_fixture_only"
    program = r'''
import importlib,json,sys
from types import SimpleNamespace
import httpx,sqlalchemy
from cosmas_os.enrollment import auth,config,stripe
Settings=config.EnrollmentSettings
settings_init=Settings.__init__
calls=[]
def forbidden(*args,**kwargs):
    calls.append("ambient_operation")
    raise AssertionError("ambient initialization before explicit ASGI request")
config.EnrollmentSettings.__init__=forbidden
sqlalchemy.create_engine=forbidden
auth.ClerkEnrollmentVerifier.__init__=forbidden
stripe.StripeCommerce.__init__=forbidden
httpx.Client.__init__=forbidden
api=importlib.import_module("cosmas_os.enrollment.api")
importlib.import_module("cosmas_os.enrollment.private_clock_runner")
assert "app" not in vars(api) and not calls
assert callable(api.create_app)
Settings.__init__=settings_init
explicit=json.load(sys.stdin)
explicit.update(enabled=False,data_mode="synthetic",database_url="",clerk_methods_verified=False,
                stripe_integration_enabled=False,stripe_live_mode=False,production_qualified=False)
application=api.create_app(Settings.model_validate(explicit,strict=True),commerce=SimpleNamespace())
assert application.state.enrollment_settings.data_mode=="synthetic" and not calls and "app" not in vars(api)
default_calls=[]
def create_default():
    default_calls.append("requested")
    return application
api.create_app=create_default
from uvicorn.importer import import_from_string
assert import_from_string("cosmas_os.enrollment.api:app") is application
assert import_from_string("cosmas_os.enrollment.api:app") is application
assert default_calls==["requested"] and not calls
import uvicorn
served=[]
uvicorn.run=lambda app,**kwargs: served.append((app,kwargs))
sys.argv=["enrollment-api","--host","127.0.0.1","--port","8061"]
api.main()
assert served[0][0] is application and served[0][1]=={"host":"127.0.0.1","port":8061}
assert default_calls==["requested"] and not calls
print(json.dumps({"factory_import_side_effect_free":True,"explicit_asgi_cached_once":True,"cli_uses_cached_app":True}))
'''
    result = subprocess.run([sys.executable, "-c", program], input=json.dumps(values), text=True,
                            capture_output=True, cwd=tmp_path, env=ambient, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"factory_import_side_effect_free": True,
                                        "explicit_asgi_cached_once": True, "cli_uses_cached_app": True}
