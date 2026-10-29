"""Closed sandbox configuration and startup: no vendor calls or account activation."""

import asyncio
from dataclasses import replace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from tests.unit.test_managed_service_configuration import (
    install,
    no_network,
    no_session,
    secret_ref,
)
from tests.unit.test_scheduling_runtime import configuration as configuration

from cosmas_os.adapters.elation_read import ElationReadError
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.adapters.managed_service_configuration import load_managed_profile
from cosmas_os.adapters.managed_services import ManagedServices, managed_services_lifespan

__all__ = ["no_network"]


def document(settings) -> dict[str, Any]:
    return dict(version=1, box_id=settings.beta_box_id, elation_sandbox=[dict(
        id=str(uuid4()), owner_id=str(uuid4()), account_id=str(uuid4()),
        connection_id=str(uuid4()), credential_generation=str(uuid4()), practice_id="913",
        practice_name="Invented practice", timezone="America/New_York",
        environment="sandbox", data_classification="synthetic_only",
        client_id=secret_ref("ELATION_ID", "invented-client"),
        client_secret=secret_ref("ELATION_SECRET", "invented-secret"))])


def test_loading_and_startup_need_no_secrets_database_or_network(tmp_path, configuration, monkeypatch):
    install(tmp_path, configuration, document(configuration))
    profile = load_managed_profile(configuration)
    definition = profile.elation_sandbox[0]
    app = FastAPI()
    assert configuration.workspace_elation_sandbox_enabled is False
    with managed_services_lifespan(app, configuration, no_session):
        port = app.state.ehr_reads
        assert port.available() is False and port.current(definition.scope) is False
        configuration.workspace_ehr_read_enabled = configuration.workspace_elation_sandbox_enabled = True
        assert port.available() is True and port.current(definition.scope) is False
        monkeypatch.setenv("COSMAS_MANAGED_SECRET_ELATION_ID", "invented-client")
        monkeypatch.setenv("COSMAS_MANAGED_SECRET_ELATION_SECRET", "invented-secret")
        assert port.current(definition.scope) is True
        assert port.timezone_for(definition.scope) == "America/New_York"
        assert profile.elation_credentials is not None
        async def acquire():
            assert profile.elation_credentials is not None
            return await profile.elation_credentials(definition.scope)
        credentials = asyncio.run(acquire())
        assert credentials.scope_sha256 == definition.scope.commitment()
        assert "invented-secret" not in repr(credentials)
        monkeypatch.setenv("COSMAS_MANAGED_SECRET_ELATION_SECRET", "changed-invented-secret")
        assert port.current(definition.scope) is False
        for field in ("box_id", "owner_id", "connection_id", "credential_generation"):
            assert port.current(replace(definition.scope, **{field: uuid4()})) is False
    assert app.state.ehr_reads is None and port.available() is False


@pytest.mark.parametrize("fault", ["production", "real_data", "missing_classification", "raw_secret",
    "url", "duplicate", "conflicting_secret", "invalid_timezone", "control_label", "large_id"])
def test_invalid_or_non_synthetic_installation_is_rejected(tmp_path, configuration, fault):
    doc = document(configuration)
    item = doc["elation_sandbox"][0]
    if fault == "production":
        item["environment"] = "production"
    elif fault == "real_data":
        item["data_classification"] = "phi"
    elif fault == "missing_classification":
        item.pop("data_classification")
    elif fault == "raw_secret":
        item["client_secret"] = "not-accepted"
    elif fault == "url":
        item["base_url"] = "https://example.invalid"
    elif fault == "duplicate":
        doc["elation_sandbox"].append(item.copy())
    elif fault == "conflicting_secret":
        item["client_secret"] = {**item["client_id"], "sha256": "f" * 64}
    elif fault == "invalid_timezone":
        item["timezone"] = "Invented/Timezone"
    elif fault == "control_label":
        item["practice_name"] = "Invented\npractice"
    else:
        item["practice_id"] = str(2**63)
    install(tmp_path, configuration, doc)
    with pytest.raises(ValueError, match="^Managed service configuration is invalid or unavailable$"):
        load_managed_profile(configuration)


def test_lifespan_refuses_ambiguous_mock_and_managed_runtime(tmp_path, configuration):
    install(tmp_path, configuration, document(configuration))
    profile = load_managed_profile(configuration)
    mock = SyntheticElationReads((profile.elation_sandbox[0].scope,),
        httpx.MockTransport(lambda _: pytest.fail("no provider I/O")), enabled=lambda: True)
    app = FastAPI()
    app.state.ehr_reads = mock
    with pytest.raises(ValueError, match="Mock and managed EHR runtimes cannot be combined"):
        with managed_services_lifespan(app, configuration, no_session):
            pytest.fail("ambiguous runtime entered lifespan")
    assert app.state.ehr_reads is mock


def test_disabled_runtime_cannot_dispatch_even_with_invented_exact_secrets(tmp_path, configuration, monkeypatch):
    install(tmp_path, configuration, document(configuration))
    profile = load_managed_profile(configuration)
    monkeypatch.setenv("COSMAS_MANAGED_SECRET_ELATION_ID", "invented-client")
    monkeypatch.setenv("COSMAS_MANAGED_SECRET_ELATION_SECRET", "invented-secret")
    runtime = ManagedServices(configuration, profile, no_session)
    port = runtime.ehr_reads
    assert port is not None
    with pytest.raises(ElationReadError, match="connection_changed"):
        port._adapter(profile.elation_sandbox[0].scope, lambda: True)
    runtime.close()
