"""Bounded HTTP adapter with invented protocol rows and no network."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.core_encounters import PATH, CoreEncounterConnection
from cosmas_os.application.core_record_deadline import RecordDeadline
from cosmas_os.config import Settings
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_encounters import (
    ConnectionContent,
    ConnectionRequest,
    ConnectionSnapshot,
    DiscoveryResponse,
    digest,
)


def fixture():
    suffix = "00000000000000000000000001"
    request = ConnectionRequest(
        expected_tenant_ref="authority_tenant_" + suffix, request_nonce=uuid4()
    )
    content = ConnectionContent(
        actor_ref="authority_actor_" + suffix,
        tenant_ref=request.expected_tenant_ref,
        provider_link_ref="scribe_provider_link_" + suffix,
        practice_ref="practice_" + suffix,
        practice_label="Invented practice",
        review_sha256="1" * 64,
    )
    data = content.model_dump(mode="json")
    response = DiscoveryResponse(
        action="connection",
        request_nonce=request.request_nonce,
        checked_at=datetime.now(UTC),
        connection=ConnectionSnapshot(**data, connection_sha256=digest(data)),
        encounters=(),
        next_cursor=None,
    )
    return request, response


def test_trusted_origin_and_fresh_bearer_are_the_only_destination_and_identity():
    request, expected = fixture()

    def handler(incoming):
        assert str(incoming.url) == "https://core.example.invalid" + PATH
        assert incoming.headers["authorization"] == "Bearer invented-fresh-session"
        assert json.loads(incoming.content) == request.model_dump(mode="json")
        assert "cookie" not in incoming.headers
        return httpx.Response(
            200,
            content=expected.model_dump_json(),
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "X-Cosmaneura-Record-Version": "1",
            },
        )

    port = CoreEncounterConnection(
        "https://core.example.invalid",
        RecordDeadline(),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    try:
        assert port.read(request, SecretStr("invented-fresh-session")) == expected
    finally:
        port.close()


@pytest.mark.parametrize("fault", ["nonce", "redirect", "oversize"])
def test_unmatched_or_unbounded_response_is_not_a_connection(fault):
    request, expected = fixture()

    def handler(incoming):
        data = expected.model_dump(mode="json")
        if fault == "nonce":
            data["request_nonce"] = str(uuid4())
        return httpx.Response(
            302 if fault == "redirect" else 200,
            content="x" * 65_537 if fault == "oversize" else json.dumps(data),
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "X-Cosmaneura-Record-Version": "1",
            },
        )

    port = CoreEncounterConnection(
        "https://core.example.invalid",
        RecordDeadline(),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ConnectorUnavailable):
            port.read(request, SecretStr("invented-session"))
    finally:
        port.close()


def test_connection_gate_needs_a_complete_reviewed_scope_without_recursing():
    baseline = dict(
        _env_file=None,
        workspace_enabled=True,
        workspace_authenticated_enabled=True,
        synth_seed=False,
        auth_mode="clerk_jwt",
        database_url="postgresql+psycopg://synthetic@127.0.0.1/w1a_synthetic",
        clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="synthetic",
        clerk_organization_id="org_synthetic",
        clerk_authorized_parties="http://localhost:5173",
        beta_box_id=str(uuid4()),
        cors_allowed_origins="http://localhost:5173",
    )
    disabled = Settings(**baseline)
    assert not disabled.workspace_core_connection_available
    enabled = Settings(
        **baseline,
        workspace_core_connection_enabled=True,
        core_capture_origin="https://core.example.invalid",
        core_connection_tenant_ref="authority_tenant_00000000000000000000000001",
    )
    assert (
        enabled.workspace_core_connection_available and not enabled.runtime_configuration_errors()
    )
    missing = Settings(**baseline, workspace_core_connection_enabled=True)
    assert (
        not missing.workspace_core_connection_available and missing.runtime_configuration_errors()
    )
