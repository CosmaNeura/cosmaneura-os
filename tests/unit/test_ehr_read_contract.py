"""Closed synthetic EHR commands and authentication boundaries without a database."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cosmas_os.adapters.elation_read import ElationReadScope
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.api.ehr_read_routes import router
from cosmas_os.api.ehr_read_schemas import EHR_COMMAND, ReviewEhr
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.config import Settings


def command():
    start = datetime(2026, 10, 25, 12, tzinfo=UTC)
    return dict(action="observe", connection_id=str(uuid4()), binding_sha256="a" * 64,
        starts_at=start.isoformat(), ends_at=(start + timedelta(days=1)).isoformat(),
        idempotency_key="ehr-observe-1")


@pytest.mark.parametrize("change", [
    {"cursor": "next"}, {"offset": 25}, {"patient_id": "930"},
    {"url": "https://example.invalid"}, {"practice_id": "910"},
    {"action": "search"}, {"starts_at": "2026-10-25T12:00:00"},
    {"ends_at": "2026-11-25T12:00:00Z"}, {"connection_id": "bad-id"},
    {"binding_sha256": "bad-hash"}, {"idempotency_key": "short"},
])
def test_browser_cannot_supply_provider_ids_pages_or_unbounded_requests(change):
    with pytest.raises(ValidationError):
        EHR_COMMAND.validate_python({**command(), **change})


@pytest.mark.parametrize("field", ["reviewed_visit", "reviewed_patient_identity", "reviewed_exact_snapshot", "reviewed_untrusted_source"])
@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_review_accepts_only_explicit_true(field, value):
    body = dict(expected_revision=1, idempotency_key="ehr-review-1", observation_id=str(uuid4()),
        observation_sha256="a" * 64, item_handle=str(uuid4()), item_sha256="b" * 64,
        reviewed_visit=True, reviewed_patient_identity=True, reviewed_exact_snapshot=True, reviewed_untrusted_source=True)
    body[field] = value
    with pytest.raises(ValidationError):
        ReviewEhr.model_validate(body)


def test_feature_is_default_off_and_cannot_enable_in_a_hosted_environment():
    assert not Settings().workspace_ehr_read_enabled
    configured = Settings(workspace_enabled=True, workspace_authenticated_enabled=True, auth_mode="clerk_jwt",
        workspace_ehr_read_enabled=True, synth_seed=False,
        database_url="postgresql+psycopg://invented@127.0.0.1:54329/w1a_ehr_runtime",
        clerk_issuer="https://clerk.example.invalid", clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="synthetic-test", clerk_organization_id="org_invented",
        clerk_authorized_parties="http://localhost:5173", beta_box_id="00000000-0000-4000-8000-000000000001")
    assert configured.workspace_ehr_read_available
    configured.workspace_hosted_enabled = True
    assert not configured.workspace_ehr_read_available


def test_runtime_requires_exact_mock_transport_and_keeps_disabled_scope_unavailable():
    scope = ElationReadScope(uuid4(), uuid4(), uuid4(), uuid4(), 910, "Invented Elation Clinic")
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    port = SyntheticElationReads((scope,), transport, enabled=lambda: False)
    assert not port.current(scope)
    class UnsupportedTransport(httpx.MockTransport):
        pass
    # Only the exact fixture transport is admitted, even when explicitly enabled.
    with pytest.raises(ValueError, match="explicit_synthetic_ehr_installation_required"):
        SyntheticElationReads((scope,), UnsupportedTransport(lambda _: httpx.Response(200)), enabled=lambda: True)


def isolated_route(identity):
    app = FastAPI()
    calls = []

    def fence(*_):
        calls.append("fence")

    @app.exception_handler(WorkspaceError)
    async def closed_error(_request, exc):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    app.include_router(router(runtime=lambda: None,
        configuration=lambda: SimpleNamespace(workspace_ehr_read_available=False),
        identity_dependency=lambda: identity, session_dependency=lambda: object(),
        workspace_gate=lambda: None, fence=fence))
    return TestClient(app), calls


def test_unsupported_identity_returns_closed_unavailable_before_body_or_database_work():
    client, calls = isolated_route(SimpleNamespace(auth_mode="desktop_native", external_identity_id=None))
    with client:
        result = client.post("/connections/ehr/reads", headers={"X-Cosmas-Desktop-Session": "synthetic-session"},
            content="not-json")
    assert result.status_code == 404 and result.json() == {"detail": "ehr_read_unavailable"}
    assert calls == []


@pytest.mark.parametrize("headers,body", [
    ({"Authorization": "Bearer synthetic"}, {"action": "status"}),
    ({"X-Cosmas-Ehr-Read": "1"}, {"action": "status"}),
    ({"Authorization": "Bearer synthetic", "X-Cosmas-Ehr-Read": "2"}, {"action": "status"}),
    ({"Authorization": "Bearer synthetic", "X-Cosmas-Ehr-Read": "1"}, {"action": "status", "cursor": "next"}),
])
def test_missing_or_wrong_protocol_headers_and_extra_fields_fail_before_execution(headers, body):
    identity = SimpleNamespace(auth_mode="clerk_jwt", external_identity_id=str(uuid4()),
        box_id=str(uuid4()), principal_id=str(uuid4()))
    client, calls = isolated_route(identity)
    with client:
        result = client.post("/connections/ehr/reads", headers=headers, json=body)
    assert result.status_code == 422 and result.json() == {"detail": "invalid_ehr_read_request"}
    assert calls == []
