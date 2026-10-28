"""Provider selection and runtime gates use only in-process invented SOAP traffic."""

from dataclasses import replace
from typing import cast
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from tests.unit.test_tebra_read import END, PRACTICE_ROW, START, envelope

from cosmas_os.adapters.ehr_read_runtime import EhrReadRuntimes, select_runtime
from cosmas_os.adapters.tebra_read import TebraReadError
from cosmas_os.adapters.tebra_read_runtime import SyntheticTebraReads, TebraWorkspaceScope
from cosmas_os.api.ehr_read_schemas import EHR_COMMAND
from cosmas_os.ports.ehr_reads import SnapshotPayload, TebraPrivateSnapshot

SCOPE = TebraWorkspaceScope(uuid4(), uuid4(), uuid4(), uuid4(), 900, 901, "Invented & Independent Clinic", "America/New_York")


def test_only_exact_mock_transport_and_explicit_scopes_can_install_tebra():
    for transport in (None, httpx.HTTPTransport()):
        with pytest.raises(ValueError, match="explicit_synthetic"):
            SyntheticTebraReads((SCOPE,), cast(httpx.MockTransport, transport), enabled=lambda: True)
        if transport is not None:
            transport.close()
    with pytest.raises(ValueError):
        SyntheticTebraReads((), httpx.MockTransport(lambda _: pytest.fail("no IO")), enabled=lambda: True)
    port = SyntheticTebraReads((SCOPE,), httpx.MockTransport(lambda _: pytest.fail("no IO")), enabled=lambda: True)
    assert select_runtime(EhrReadRuntimes(tebra=port), "elation") is None
    assert select_runtime(EhrReadRuntimes(tebra=port), "tebra") is port
    assert not port.current(replace(SCOPE, credential_generation=uuid4()))
    assert replace(SCOPE, timezone="UTC").commitment() != SCOPE.commitment()


def test_runtime_checks_current_human_scope_after_each_wire_read():
    current = True
    calls = []
    def handler(request):
        nonlocal current
        calls.append(request)
        current = False
        return httpx.Response(200, stream=httpx.ByteStream(envelope("GetPractices", PRACTICE_ROW)), headers={"Content-Type": "text/xml"})
    port = SyntheticTebraReads((SCOPE,), httpx.MockTransport(handler), enabled=lambda: current)
    with pytest.raises(TebraReadError, match="access_denied"):
        port.window(SCOPE, START, END, authorize=lambda: True)
    assert len(calls) == 1


@pytest.mark.parametrize("body", [
    {"action": "status", "provider": None},
    {"action": "status", "provider": "other"},
    {"action": "install", "provider": "tebra", "installation_id": str(uuid4()), "installation_sha256": "a"*64, "idempotency_key": "tebra-install-1"},
])
def test_provider_selector_has_no_null_or_live_install_fallback(body):
    with pytest.raises(ValidationError):
        EHR_COMMAND.validate_python(body)


def test_empty_tebra_observation_retains_closed_tebra_private_shape():
    payload = {"public": {"provider": "tebra", "mode": "synthetic", "kind": "window",
        "practice": {"label": "Invented Clinic", "timezone": "UTC"}, "observed_at": START.isoformat(),
        "window": {"starts_at": START.isoformat(), "ends_at": END.isoformat()}, "coverage": "returned_rows_only", "items": []},
        "private": {"transport": "mock", "binding_sha256": "a"*64, "request_sha256": "b"*64, "items": [], "provider_sources": ["c"*64]}}
    assert isinstance(SnapshotPayload.model_validate(payload).private, TebraPrivateSnapshot)
    payload["private"]["transport"] = "vendor_sandbox"
    with pytest.raises(ValidationError):
        SnapshotPayload.model_validate(payload)
