"""Installed read grants remain separate from account setup and provider I/O."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.unit.test_managed_service_configuration import document, install
from tests.unit.test_managed_services import no_session, profile
from tests.unit.test_scheduling_runtime import configuration as configuration
from tests.unit.test_spruce_inbox import binding

from cosmas_os.adapters import managed_service_configuration as configured
from cosmas_os.adapters.managed_services import ManagedServices
from cosmas_os.application import inbox_work


def test_actual_main_app_hook_reads_current_installed_registry_and_closed_fallback(monkeypatch):
    application = import_module("cosmas_os.api.app")
    installed = object()
    monkeypatch.setattr(application, "managed_services", lambda app: SimpleNamespace(inbox_registry=lambda: installed))
    assert application._inbox_registry()() is installed
    monkeypatch.setattr(application, "managed_services", lambda app: None)
    assert application._inbox_registry()() is inbox_work.EMPTY_REGISTRY


def grant(selected):
    source = binding().model_copy(update={"selection": selected})
    now = datetime.now(UTC)
    return inbox_work.InboxReadGrant(
        grant_id=uuid4(), binding=source, label="Invented selected Spruce item",
        reviewed_by=selected.owner_id, review_reference="invented-owner-read-review",
        reviewed_inbox_read=True, reviewed_at=now-timedelta(minutes=1),
        expires_at=now+timedelta(hours=1), correspondence_public_sha256="a"*64,
    )


def test_host_registry_reuses_exact_installed_account_without_credentials_or_database(configuration):
    installed = profile()
    selected = next(x.selection for x in installed.vendor_catalog.installations.values() if x.selection.vendor == "spruce")
    reviewed = grant(selected.model_copy(update={"connection_id": uuid4()}))
    runtime = ManagedServices(configuration, replace(installed, inbox_grants=(reviewed,)), no_session)
    assert runtime.inbox_registry() is inbox_work.EMPTY_REGISTRY
    configuration.inbox_work_enabled = True
    assert runtime.inbox_registry().grants[str(reviewed.grant_id)] == reviewed
    assert not runtime.has_credentials
    assert not configuration.vendor_io_enabled  # Outgoing I/O is independently disabled.
    with pytest.raises(TypeError):
        runtime.inbox_registry().grants["new"] = reviewed
    configuration.inbox_work_enabled = False
    assert runtime.inbox_registry() is inbox_work.EMPTY_REGISTRY
    configuration.inbox_work_enabled = True
    runtime.close()
    assert runtime.inbox_registry() is inbox_work.EMPTY_REGISTRY


@pytest.mark.parametrize("fault", ["installation_id", "foreign_owner", "changed_account", "duplicate", "not_tuple"])
def test_registry_refuses_grants_not_bound_to_exact_reviewed_account(configuration, fault):
    installed = profile()
    selected = next(x.selection for x in installed.vendor_catalog.installations.values() if x.selection.vendor == "spruce")
    selected = selected.model_copy(update={"connection_id": uuid4()})
    if fault == "installation_id":
        selected = next(x.selection for x in installed.vendor_catalog.installations.values() if x.selection.vendor == "spruce")
    elif fault == "foreign_owner":
        selected = selected.model_copy(update={"owner_id": uuid4()})
    elif fault == "changed_account":
        selected = selected.model_copy(update={"remote_account_id": "entity_OtherAccount"})
    reviewed = grant(selected)
    values = [reviewed] if fault == "not_tuple" else (reviewed, reviewed) if fault == "duplicate" else (reviewed,)
    with pytest.raises(ValueError):
        ManagedServices(configuration, replace(installed, inbox_grants=values), no_session)


def test_protected_configuration_installs_independent_grants_without_reading_secrets(tmp_path, configuration, monkeypatch):
    doc = document(configuration, "spruce")
    selected = configured.ConnectionSelection.model_validate(doc["delivery"][0]["selection"])
    reviewed = grant(selected.model_copy(update={"connection_id": uuid4()}))
    doc["inbox_grants"] = [reviewed.model_dump(mode="json")]
    install(tmp_path, configuration, doc)
    calls = []
    def secret(_):
        calls.append("secret")
        return "PRIVATE_invented"
    monkeypatch.setattr(configured, "_secret", secret)
    supplied = configured.load_managed_profile(configuration)
    assert supplied.inbox_grants == (reviewed,) and calls == []
    provider = supplied.credentials
    assert provider is not None
    credential = asyncio.run(provider(reviewed.binding.selection))
    assert credential.selection_sha256 == reviewed.binding.selection.commitment()
    assert calls == ["secret"]
    configuration.inbox_work_enabled = True
    runtime = ManagedServices(configuration, supplied, no_session)
    assert runtime.inbox_registry().grants[str(reviewed.grant_id)] == reviewed


@pytest.mark.parametrize("fault", ["foreign_box", "installation_id", "changed_configuration", "duplicate", "extra_authority"])
def test_protected_registry_configuration_refuses_unreviewed_scope(tmp_path, configuration, fault):
    doc = document(configuration, "spruce", credential=False)
    selected = configured.ConnectionSelection.model_validate(doc["delivery"][0]["selection"])
    reviewed = grant(selected.model_copy(update={"connection_id": uuid4()})).model_dump(mode="json")
    if fault == "foreign_box":
        reviewed["binding"]["selection"]["box_id"] = str(uuid4())
    elif fault == "installation_id":
        reviewed["binding"]["selection"]["connection_id"] = str(selected.connection_id)
    elif fault == "changed_configuration":
        reviewed["binding"]["selection"]["configuration_sha256"] = "b"*64
    elif fault == "extra_authority":
        reviewed["approve_reply"] = True
    doc["inbox_grants"] = [reviewed, reviewed] if fault == "duplicate" else [reviewed]
    install(tmp_path, configuration, doc)
    with pytest.raises(ValueError, match="Managed service configuration"):
        configured.load_managed_profile(configuration)
