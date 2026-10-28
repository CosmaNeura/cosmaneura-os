"""Managed sandbox installation and shared quota using invented HTTP responses only."""

import asyncio
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker
from tests.integration.test_ehr_reads import (
    action,
    ehr_case,
    observe_body,
    observed,
    review,
    signed_workspace,
    verified,
)

from cosmas_os.adapters.elation_read import ElationReadError
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.adapters.managed_service_configuration import load_managed_profile
from cosmas_os.adapters.managed_services import ManagedServices
from cosmas_os.api import app as api_module
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import CaptureBudget, capture_budget
from cosmas_os.application.elation_sandbox_quota import ElationSandboxQuotaBudget
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ehr_read_models import EhrReadBinding, EhrReadRequest, EhrReadSnapshot
from cosmas_os.elation_sandbox_models import (
    ElationSandboxInstallationReceipt,
    ElationSandboxQuota,
    ElationSandboxQuotaMinute,
)

__all__ = ["ehr_case", "signed_workspace"]


def secret_ref(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    return dict(environment=name, sha256=hashlib.sha256(value.encode()).hexdigest())


@pytest.fixture
def sandbox(ehr_case, engine, monkeypatch):
    f = ehr_case
    monkeypatch.setattr(f.configuration, "workspace_elation_sandbox_enabled", True)
    monkeypatch.setattr(f.configuration, "beta_box_id", f.box)
    definition = dict(id=str(uuid4()), owner_id=f.owner, account_id=f.account,
        connection_id=str(uuid4()), credential_generation=str(uuid4()),
        practice_id="910", practice_name="Invented Elation Clinic", timezone="UTC",
        environment="sandbox", data_classification="synthetic_only",
        client_id=secret_ref(monkeypatch, "COSMAS_MANAGED_SECRET_ELATION_ID", "invented-client-id"),
        client_secret=secret_ref(monkeypatch, "COSMAS_MANAGED_SECRET_ELATION_SECRET", "invented-client-secret"))
    config = dict(version=1, box_id=f.box, elation_sandbox=[definition])
    raw = json.dumps(config)
    monkeypatch.setattr(f.configuration, "managed_services_config_json", SecretStr(raw))
    monkeypatch.setattr(f.configuration, "managed_services_config_path", "")
    monkeypatch.setattr(f.configuration, "managed_services_config_sha256", hashlib.sha256(raw.encode()).hexdigest())
    profile = load_managed_profile(f.configuration)
    profile = replace(profile, transport_factory=lambda: httpx.MockTransport(f.provider))
    runtime = ManagedServices(f.configuration, profile, sessionmaker(bind=engine))
    port = runtime.ehr_reads
    assert port is not None
    monkeypatch.setattr(api_module.app.state, "ehr_reads", port)
    f.port, f.scope = port, profile.elation_sandbox[0].scope
    f.definition, f.profile, f.engine = definition, profile, engine
    with ehr.install_runtime_reader(lambda: port):
        yield f
    runtime.close()


def install_body(f, key="install-sandbox-1"):
    installation = f.profile.elation_sandbox[0]
    return dict(action="install", installation_id=str(installation.id),
        installation_sha256=installation.commitment(), idempotency_key=key)


def installed(f):
    body = install_body(f)
    result = action(f, body)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "installed"
    assert result.json()["request_sha256"] == payload_hash(body)
    return result.json()


def test_explicit_installation_is_no_io_exactly_recoverable_and_separately_gated(sandbox):
    f = sandbox
    f.configuration.workspace_elation_sandbox_enabled = False
    assert action(f, {"action": "status"}).json()["status"] == "not_enabled"
    assert action(f, install_body(f)).status_code == 404
    f.configuration.workspace_elation_sandbox_enabled = True
    status = action(f, {"action": "status"}).json()
    assert status["status"] == "setup_required" and status["transport"] == "vendor_sandbox"
    assert status["connection_id"] is None and status["binding_sha256"] is None
    assert status["installation"] == {"id": f.definition["id"], "sha256": install_body(f)["installation_sha256"]}
    result = installed(f)
    assert action(f, install_body(f)).json() == result
    assert action(f, {"action": "resolve", "idempotency_key": "install-sandbox-1"}).json() == result
    assert action(f, {"action": "status"}).json()["status"] == "ready"
    assert f.s.get(EhrReadBinding, f.binding_id).state == "revoked"
    assert f.provider.calls == []
    assert f.s.scalar(select(func.count()).select_from(ElationSandboxInstallationReceipt)) == 1
    assert action(f, {**install_body(f), "installation_sha256": "0" * 64}).status_code == 409
    assert action(f, observe_body(f, key="install-sandbox-1")).status_code == 409
    assert f.provider.calls == []


def test_managed_sandbox_read_review_recovery_keeps_immutable_transport(sandbox):
    f = sandbox
    installed(f)
    window = observed(f)
    visit = verified(f, window)
    assert window["transport"] == visit["transport"] == "vendor_sandbox"
    assert window["observation"]["mode"] == "synthetic"
    saved = review(f, visit)
    assert saved.status_code == 200, saved.text
    assert saved.json()["transport"] == "vendor_sandbox" and saved.json()["source_withheld"] is False
    assert action(f, {"action": "resolve", "idempotency_key": visit["observation_key"]}).json() == visit
    read = f.s.get(EhrReadRequest, visit["observation_id"])
    snapshot = f.s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == read.id))
    assert read.transport == snapshot.payload["private"]["transport"] == "vendor_sandbox"
    assert snapshot.payload_sha256 == payload_hash(snapshot.payload)
    assert f.s.scalar(select(func.sum(ElationSandboxQuotaMinute.requests))) == len(f.provider.calls) == 6


def test_secret_rotation_withholds_saved_content_and_old_installation_receipt(sandbox, monkeypatch):
    f = sandbox
    original = installed(f)
    window = observed(f)
    visit = verified(f, window)
    assert review(f, visit).status_code == 200
    calls = len(f.provider.calls)
    monkeypatch.setenv("COSMAS_MANAGED_SECRET_ELATION_SECRET", "changed-invented-secret")
    result = action(f, {"action": "resolve", "idempotency_key": "install-sandbox-1"}).json()
    assert result == {**original, "status": "unavailable"}
    assert action(f, {"action": "inspect", "observation_id": visit["observation_id"]}).status_code == 409
    replay = review(f, visit)
    assert replay.status_code == 200 and replay.json()["source_withheld"] is True
    assert "Alex" not in json.dumps(replay.json()["workspace"])
    assert len(f.provider.calls) == calls


def test_changed_or_foreign_installation_never_creates_binding(sandbox):
    f = sandbox
    before = f.s.scalar(select(func.count()).select_from(EhrReadBinding))
    assert action(f, {**install_body(f), "installation_id": str(uuid4())}).status_code == 409
    assert action(f, {**install_body(f), "installation_sha256": "0" * 64}).status_code == 409
    assert action(f, {**install_body(f), "client_secret": "not-accepted"}).status_code == 422
    assert f.s.scalar(select(func.count()).select_from(EhrReadBinding)) == before
    assert f.provider.calls == []


def test_quota_is_shared_across_instances_and_conservative_at_day_edge(engine):
    factory = sessionmaker(bind=engine)
    a, b = ElationSandboxQuotaBudget(factory), ElationSandboxQuotaBudget(factory)
    key = "c" * 64
    assert a.reserve(key) == 0
    assert 0 < b.reserve(key) <= 0.51
    with factory() as s:
        q = s.get(ElationSandboxQuota, key)
        assert q is not None
        q.last_permitted_at = datetime.now(UTC) - timedelta(seconds=1)
        minute = s.scalar(select(ElationSandboxQuotaMinute).where(ElationSandboxQuotaMinute.credential_key == key))
        assert minute is not None
        minute.requests = 149_999
        s.commit()
    with pytest.raises(ElationReadError, match="rate_limited"):
        b.reserve(key)
    with factory() as s:
        minute = s.scalar(select(ElationSandboxQuotaMinute).where(ElationSandboxQuotaMinute.credential_key == key))
        assert minute is not None
        minute.minute -= timedelta(days=1, minutes=1)
        s.commit()
    assert b.reserve(key) == 0
    with factory() as s:
        assert s.scalar(select(func.sum(ElationSandboxQuotaMinute.requests))) == 1


@pytest.mark.parametrize("inside_request", [False, True])
def test_quota_contention_is_bounded_by_postgres_not_async_timeout(engine, inside_request):
    factory = sessionmaker(bind=engine)
    key = "d" * 64
    with factory() as s:
        s.add(ElationSandboxQuota(credential_key=key))
        s.commit()
    budget = ElationSandboxQuotaBudget(factory)
    with engine.begin() as holder:
        holder.execute(text("SELECT credential_key FROM elation_sandbox_quotas WHERE credential_key=:key FOR UPDATE"), {"key": key})
        began = time.monotonic()
        def contested():
            if inside_request:
                with capture_budget(CaptureBudget(45)):
                    return asyncio.run(budget.permit(key))
            return asyncio.run(budget.permit(key))
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(contested)
            with pytest.raises(ElationReadError, match="rate_limited"):
                future.result(timeout=4)
        assert time.monotonic() - began < 3
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(ElationSandboxQuotaMinute)) == 0
    assert budget.reserve(key) == 0


@pytest.mark.parametrize("transport", ["mock", None, "production", "missing"])
def test_self_consistent_transport_substitution_is_rejected_in_python_and_sql(sandbox, transport):
    f = sandbox
    installed(f)
    window = observed(f)
    read = f.s.get(EhrReadRequest, window["observation_id"])
    snap = f.s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == read.id))
    original = deepcopy(snap.payload)
    corrupt = deepcopy(original)
    if transport == "missing":
        corrupt["private"].pop("transport")
    else:
        corrupt["private"]["transport"] = transport
    # Even recomputing both outer digests cannot relabel an immutable request.
    assert f.s.scalar(text("SELECT public.ehr_read_payload_valid(CAST(:payload AS jsonb), r) "
        "FROM ehr_read_requests r WHERE r.id=:id"), {"payload": json.dumps(corrupt), "id": read.id}) is False
    with f.s.no_autoflush:
        snap.payload = corrupt
        snap.payload_sha256 = payload_hash(corrupt)
        snap.source_sha256 = ehr._commitment(read, snap.payload_sha256)
        with pytest.raises(ws.WorkspaceError, match="ehr_read_source_invalid"):
            ehr._snapshot(f.s, read)
    f.s.rollback()
    assert action(f, {"action": "inspect", "observation_id": read.id}).json() == window


def test_saved_vendor_receipt_is_not_relabelled_after_runtime_becomes_mock(sandbox, monkeypatch):
    f = sandbox
    installed(f)
    window = observed(f)
    visit = verified(f, window)
    assert review(f, visit).status_code == 200
    calls = len(f.provider.calls)
    mock = SyntheticElationReads((f.scope,), httpx.MockTransport(f.provider), enabled=lambda: True)
    monkeypatch.setattr(api_module.app.state, "ehr_reads", mock)
    with ehr.install_runtime_reader(lambda: mock):
        for command in ({"action": "inspect", "observation_id": visit["observation_id"]},
                        {"action": "resolve", "idempotency_key": visit["observation_key"]}):
            result = action(f, command)
            assert result.status_code == 409 and "Alex" not in result.text
        replay = review(f, visit)
        assert replay.status_code == 200 and replay.json()["source_withheld"] is True
        assert replay.json()["transport"] == "vendor_sandbox"
    assert len(f.provider.calls) == calls
