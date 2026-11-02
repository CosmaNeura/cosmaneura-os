"""Single deployed scope/custody checks; no vendor or hosted qualification."""
from __future__ import annotations

import base64
import json
import stat
from uuid import uuid5

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from cosmas_os.enrollment import private_clock_hosted as hosted
from cosmas_os.enrollment import private_clock_runner as runner
from cosmas_os.enrollment.config import EnrollmentSettings
from cosmas_os.enrollment.domain import EnrollmentError
from cosmas_os.enrollment.private_clock_lab import BOX_NAMESPACE, binding_value


@pytest.fixture
def inputs():
    issuer = "https://invented-instance.clerk.accounts.dev"
    bindings = {}
    for slot, suffix in (("a", "1"), ("b", "2")):
        practice = "00000000-0000-4000-8000-00000000000" + suffix
        bindings[slot] = {
            "contract_version": "enrollment-private-stripe-clock.v1", "synthetic_only": True,
            "practice_id": practice, "box_id": str(uuid5(BOX_NAMESPACE, practice)),
            "organization_id": "org_invented" + slot, "owner_subject": "user_invented" + slot,
            "issuer": issuer, "app_origin": runner.APP_ORIGIN, "api_origin": runner.API_ORIGIN,
            "workspace_url": f"https://practice-{slot}.staging.cosmas.ai/chief",
            "workspace_api_origin": f"https://api.practice-{slot}.staging.cosmas.ai",
            "source_commit": "1" * 40, "image_sha256": "2" * 64,
            "stripe_account_id": "acct_invented", "stripe_base_price_id": "price_inventedbase",
            "stripe_additional_price_id": "price_inventedadditional",
            "stripe_portal_configuration_id": "bpc_invented", "stripe_api_version": "2025-09-30.clover",
            "customer_id": "cus_invented" + slot, "clock_id": "clock_invented" + slot,
            "initial_frozen_time": 1_800_000_000,
            "journal_host": "psql-cbot-clock-stg-abc12345.postgres.database.azure.com",
            "journal_port": 5432, "journal_database": "cosmabot_enrollment_clock_lab"}
    settings = {name: (field.default.get_secret_value() if isinstance(field.default, SecretStr) else field.default)
                for name, field in EnrollmentSettings.model_fields.items()}
    settings.update(
        enabled=True, data_mode="synthetic", provisioning_enabled=True,
        public_app_origin=runner.APP_ORIGIN, allowed_origins=[runner.APP_ORIGIN],
        allowed_workspace_origins=["https://practice-a.staging.cosmas.ai"],
        clerk_publishable_key="pk_test_" + base64.b64encode(b"invented-instance.clerk.accounts.dev$").decode(),
        clerk_secret_key="sk_test_invented", clerk_issuer=issuer, clerk_authorized_parties=[runner.APP_ORIGIN],
        clerk_audience="invented-audience", clerk_methods_verified=True,
        stripe_integration_enabled=True, stripe_acquisition_enabled=True,
        commercial_terms_verified=True, activation_available=True,
        stripe_secret_key="sk_test_invented", stripe_webhook_secret="whsec_invented",
        stripe_account_id="acct_invented", stripe_base_price_id="price_inventedbase",
        stripe_additional_price_id="price_inventedadditional", stripe_portal_configuration_id="bpc_invented",
        database_url="postgresql+psycopg://enrollment_runtime:invented@psql-cosmabot-enrollment-staging-abc12345.postgres.database.azure.com/cosmabot_enrollment?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt",
    )
    environment = {"ENROLLMENT_" + name.upper(): json.dumps(value) if isinstance(value, (bool, list)) else value
                   for name, value in settings.items()}
    environment[hosted.BINDINGS_ENV] = json.dumps({"contract_version": "enrollment-private-clock-setup.v1",
                                                  "synthetic_only": True, "bindings": bindings})
    environment[hosted.JOURNAL_ENV] = "postgresql+psycopg://clock_journal_a:invented@psql-cbot-clock-stg-abc12345.postgres.database.azure.com/cosmabot_enrollment_clock_lab?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt\n"
    return environment, bindings


def forbid_engines(monkeypatch):
    def denied(*_args, **_kwargs):
        pytest.fail("unsafe composition reached database/vendor work")
    monkeypatch.setattr(runner, "create_engine", denied)


@pytest.mark.parametrize("change", ["missing_setting", "extra_setting", "production", "live_key", "production_flag",
                                   "wrong_hash", "wrong_role", "foreign_journal", "shared_customer", "duplicate_json"])
def test_unqualified_or_mixed_scope_refused_before_database_work(inputs, monkeypatch, change):
    environment, bindings = inputs
    digest = binding_value(bindings["a"]).sha256
    if change == "missing_setting":
        environment.pop("ENROLLMENT_CLERK_SESSION_POLICY")
        monkeypatch.setenv("ENROLLMENT_CLERK_SESSION_POLICY", "default_session")
    elif change == "extra_setting":
        environment["ENROLLMENT_CLOCK_CHOOSER"] = "true"
    elif change == "production":
        environment["ENROLLMENT_DATA_MODE"] = "production"
    elif change == "live_key":
        environment["ENROLLMENT_STRIPE_SECRET_KEY"] = "sk_live_invented"
    elif change == "production_flag":
        environment["ENROLLMENT_PRODUCTION_QUALIFIED"] = "true"
    elif change == "wrong_hash":
        digest = "f" * 64
    elif change == "wrong_role":
        environment[hosted.JOURNAL_ENV] = environment[hosted.JOURNAL_ENV].replace("clock_journal_a", "clock_journal_b")
    elif change == "foreign_journal":
        environment[hosted.JOURNAL_ENV] = environment[hosted.JOURNAL_ENV].replace("psql-cbot-clock-stg-abc12345.postgres.database.azure.com", "foreign.example")
    elif change == "shared_customer":
        bindings["b"]["customer_id"] = bindings["a"]["customer_id"]
        environment[hosted.BINDINGS_ENV] = json.dumps({"contract_version": "enrollment-private-clock-setup.v1",
                                                      "synthetic_only": True, "bindings": bindings})
    else:
        environment[hosted.BINDINGS_ENV] = '{"synthetic_only":true,"synthetic_only":false}'
    forbid_engines(monkeypatch)
    with pytest.raises((ValueError, EnrollmentError)):
        hosted.create_environment_app(slot="a", binding_sha256=digest, environment=environment)


@pytest.mark.parametrize("slot", ["a", "b"])
def test_sequential_selection_passes_only_exact_scope_to_existing_factory(inputs, monkeypatch, slot):
    environment, bindings = inputs
    environment["ENROLLMENT_ALLOWED_WORKSPACE_ORIGINS"] = json.dumps([f"https://practice-{slot}.staging.cosmas.ai"])
    environment[hosted.JOURNAL_ENV] = environment[hosted.JOURNAL_ENV].replace("clock_journal_a", "clock_journal_" + slot)
    digest = binding_value(bindings[slot]).sha256
    captured = []
    app = FastAPI()

    def existing_factory(**paths):
        root = paths["configuration_path"].parent
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in paths.values())
        configuration = json.loads(paths["configuration_path"].read_text())
        assert configuration["binding_sha256"] == digest
        assert configuration["journal_role"] == "clock_journal_" + slot
        assert configuration["enrollment"]["clerk_audience"] == "invented-audience"
        assert set(configuration["enrollment"]) == set(EnrollmentSettings.model_fields)
        assert json.loads(paths["binding_path"].read_text()) == bindings[slot]
        assert paths["journal_url_path"].read_text() == environment[hosted.JOURNAL_ENV]
        captured.append(root)
        return app

    monkeypatch.setattr(hosted, "create_explicit_app", existing_factory)
    assert hosted.create_environment_app(slot=slot, binding_sha256=digest, environment=environment) is app
    assert len(captured) == 1 and not captured[0].exists()
    assert bindings[slot]["initial_frozen_time"] == 1_800_000_000


def test_explicit_cli_has_fixed_listener_and_no_default_app(inputs, monkeypatch):
    environment, bindings = inputs
    digest = binding_value(bindings["a"]).sha256
    app = FastAPI()
    invoked = []
    monkeypatch.setattr(hosted, "create_environment_app", lambda **kwargs: invoked.append(kwargs) or app)
    import uvicorn
    served = []
    monkeypatch.setattr(uvicorn, "run", lambda value, **kwargs: served.append((value, kwargs)))
    monkeypatch.setattr("sys.argv", ["hosted-clock", "--slot", "a", "--binding-sha256", digest,
                                    "--intent", hosted.INTENT])
    monkeypatch.setattr(hosted.os, "environ", environment)
    assert hosted.main() == 0
    assert invoked == [{"slot": "a", "binding_sha256": digest, "environment": environment}]
    assert served == [(app, {"host": "0.0.0.0", "port": 8000, "access_log": False, "log_level": "warning"})]
    assert "app" not in vars(hosted)
    monkeypatch.setattr("sys.argv", ["hosted-clock"])
    with pytest.raises(SystemExit):
        hosted.main()
