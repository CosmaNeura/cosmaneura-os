import asyncio
import time
from threading import Event, Thread
from types import SimpleNamespace

import httpx
import pytest
from azure.identity import ManagedIdentityCredential
from pydantic import SecretStr
from tests.unit.test_core_capture_admission import NOW, core_handler, selection

from cosmas_os.adapters import core_record_connection as module
from cosmas_os.application.core_record_deadline import RecordDeadline, RecordDeadlineExceeded
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable


def test_inherited_exact_three_phase_validators_and_location_only_allowlist():
    selected, calls = selection(), []
    port = module.BoundedCoreRecordConnection(
        "https://core.example.invalid",
        lambda: "synthetic_PRIVATE_workload",
        RecordDeadline(),
        now=lambda: NOW,
        transport_factory=lambda: httpx.MockTransport(core_handler(selected, calls)),
    )
    try:
        token = port.exchange_context(selected, SecretStr("synthetic_PRIVATE_jwt"))
        credential = port.resolve_context(selected, token)
        binding = port.resolve_binding(selected, credential)
        assert binding.appointment_ref == selected.appointment_ref
        assert len(calls) == 3
        with pytest.raises(ConnectorUnavailable):
            port.admit_capture(binding, credential, None, "forbidden-admission")
        assert len(calls) == 3
    finally:
        port.close()


@pytest.mark.parametrize("late_phase", ["resolve", "binding"])
def test_late_token_never_starts_following_core_send(late_phase):
    selected, calls, token_calls = selection(), [], []
    budget = RecordDeadline(0.15)

    def workload():
        token_calls.append(1)
        if len(token_calls) == (1 if late_phase == "resolve" else 2):
            budget.when = time.monotonic() - 1
        return "synthetic_PRIVATE_workload"

    port = module.BoundedCoreRecordConnection(
        "https://core.example.invalid",
        workload,
        budget,
        now=lambda: NOW,
        transport_factory=lambda: httpx.MockTransport(core_handler(selected, calls)),
    )
    try:
        token = port.exchange_context(selected, SecretStr("synthetic_PRIVATE_jwt"))
        with pytest.raises(ConnectorUnavailable):
            credential = port.resolve_context(selected, token)
            port.resolve_binding(selected, credential)
        assert len(calls) == (1 if late_phase == "resolve" else 2)
    finally:
        port.close()


class SlowBody(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False
        self.chunks = 0

    async def __aiter__(self):
        for _ in range(100):
            await asyncio.sleep(0.01)
            self.chunks += 1
            yield b" "

    async def aclose(self):
        self.closed = True


def test_trickled_response_uses_total_deadline_and_worker_closes_stream():
    body, calls = SlowBody(), []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            201,
            stream=body,
            headers={
                "content-type": "application/json",
                "cache-control": "no-store",
                "X-Cosmaneura-Embed-Version": "1.0",
            },
        )

    port = module.BoundedCoreRecordConnection(
        "https://core.example.invalid",
        lambda: "token",
        RecordDeadline(0.06),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    started = time.monotonic()
    try:
        with pytest.raises(RecordDeadlineExceeded):
            port.exchange_context(selection(), SecretStr("invented"))
        assert time.monotonic() - started < 0.5
        assert body.closed and 0 < body.chunks < 100 and len(calls) == 1
    finally:
        port.close()


@pytest.mark.parametrize(
    "fault", ["body", "headers", "encoding", "redirect", "length", "duplicates"]
)
def test_transport_bounds_and_no_redirect_retry(fault):
    calls = []

    def handler(request):
        calls.append(request)
        headers = {
            "cache-control": "no-store",
            "content-type": "application/json",
            "X-Cosmaneura-Embed-Version": "1.0",
        }
        body = b"{}"
        status = 201
        if fault == "body":
            body = b" " * (module.MAX_BYTES + 1)
        if fault == "headers":
            headers["invented"] = "a" * (module.MAX_HEADERS + 1)
        if fault == "encoding":
            headers["content-encoding"] = "gzip"
        if fault == "redirect":
            status = 307
            headers["location"] = "https://elsewhere.invalid"
        if fault == "length":
            headers["content-length"] = "7"
        if fault == "duplicates":
            headers = [*headers.items(), ("content-length", "2"), ("content-length", "2")]
        return httpx.Response(status, headers=headers, content=body)

    port = module.BoundedCoreRecordConnection(
        "https://core.example.invalid",
        lambda: "token",
        RecordDeadline(),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ConnectorUnavailable):
            port.exchange_context(selection(), SecretStr("invented"))
        assert len(calls) == 1
    finally:
        port.close()


def test_cancellation_signals_worker_loop_without_foreign_thread_close():
    budget, entered, finished = RecordDeadline(), Event(), Event()
    threads, errors = [], []

    async def operation():
        try:
            entered.set()
            await asyncio.sleep(30)
        finally:
            from threading import get_ident

            threads.append(get_ident())

    def worker():
        from threading import get_ident

        threads.append(get_ident())
        try:
            budget.run(operation)
        except RecordDeadlineExceeded:
            errors.append("cancelled")
        finally:
            finished.set()

    thread = Thread(target=worker)
    thread.start()
    assert entered.wait(1)
    budget.cancel()
    assert finished.wait(1)
    thread.join()
    assert errors == ["cancelled"] and len(threads) == 2 and threads[0] == threads[1]


def test_actual_managed_identity_sdk_uses_bounded_public_transport(monkeypatch):
    # Select the installed SDK's IMDS branch without contacting that endpoint.
    for name in (
        "IDENTITY_ENDPOINT",
        "IDENTITY_HEADER",
        "MSI_ENDPOINT",
        "MSI_SECRET",
        "AZURE_POD_IDENTITY_AUTHORITY_HOST",
        "IMDS_ENDPOINT",
        "IDENTITY_SERVER_THUMBPRINT",
    ):
        monkeypatch.delenv(name, raising=False)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "169.254.169.254"
        assert request.url.params["client_id"] == "00000000-0000-4000-8000-000000000001"
        return httpx.Response(
            200,
            json={
                "access_token": "invented-workload-token",
                "expires_in": 3600,
                "token_type": "Bearer",
                "resource": "api://invented",
            },
        )

    transport = module.BoundedIdentityTransport(
        RecordDeadline(), transport_factory=lambda: httpx.MockTransport(handler)
    )
    credential = ManagedIdentityCredential(
        client_id="00000000-0000-4000-8000-000000000001",
        transport=transport,
        retry_total=0,
        retry_connect=0,
        retry_read=0,
        retry_status=0,
    )
    try:
        assert credential.get_token("api://invented/.default").token == "invented-workload-token"
        assert len(calls) == 1
    finally:
        credential.close()
        transport.close()


def test_selected_factory_owns_close_after_use_and_disables_sdk_retries(monkeypatch):
    events = []

    class Credential:
        def __init__(self, **kwargs):
            assert kwargs["client_id"] == "selected-only"
            assert all(
                kwargs[key] == 0
                for key in ("retry_total", "retry_connect", "retry_read", "retry_status")
            )
            assert isinstance(kwargs["transport"], module.BoundedIdentityTransport)
            events.append("created")

        def get_token(self, scope):
            assert scope == "exact-scope"
            return SimpleNamespace(token="invented")

        def close(self):
            events.append("closed")

    monkeypatch.setattr(module, "ManagedIdentityCredential", Credential)
    configuration = SimpleNamespace(
        workspace_capture_available=True,
        core_capture_managed_identity_client_id="selected-only",
        core_capture_origin="https://core.example.invalid",
        core_capture_scope="exact-scope",
    )
    with module.record_connection(configuration, RecordDeadline()) as port:
        configuration.core_capture_scope = "changed-scope-must-not-be-used"
        assert port._workload_token() == "invented"
        assert events == ["created"]
    assert events == ["created", "closed"]


@pytest.mark.parametrize("status", [429, 500, 307])
def test_actual_identity_sdk_error_is_one_attempt_without_private_error_body(monkeypatch, status):
    for name in (
        "IDENTITY_ENDPOINT",
        "IDENTITY_HEADER",
        "MSI_ENDPOINT",
        "MSI_SECRET",
        "AZURE_POD_IDENTITY_AUTHORITY_HOST",
        "IMDS_ENDPOINT",
        "IDENTITY_SERVER_THUMBPRINT",
    ):
        monkeypatch.delenv(name, raising=False)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"error_description": "PRIVATE_DO_NOT_DISCLOSE"},
            headers={"location": "https://elsewhere.invalid"},
        )

    transport = module.BoundedIdentityTransport(
        RecordDeadline(), transport_factory=lambda: httpx.MockTransport(handler)
    )
    credential = ManagedIdentityCredential(
        client_id="00000000-0000-4000-8000-000000000001",
        transport=transport,
        retry_total=0,
        retry_connect=0,
        retry_read=0,
        retry_status=0,
    )
    try:
        with pytest.raises(Exception) as caught:
            credential.get_token("api://invented/.default")
        assert "PRIVATE" not in str(caught.value)
        assert len(calls) == 1
    finally:
        credential.close()
        transport.close()


def test_failed_identity_constructor_still_closes_owned_transport(monkeypatch):
    transports = []

    def fail(**kwargs):
        transports.append(kwargs["transport"])
        raise ValueError("invented failure")

    monkeypatch.setattr(module, "ManagedIdentityCredential", fail)
    configuration = SimpleNamespace(
        workspace_capture_available=True,
        core_capture_managed_identity_client_id="selected-only",
        core_capture_scope="exact-scope",
    )
    with pytest.raises(ValueError, match="invented failure"):
        with module.record_connection(configuration, RecordDeadline()):
            pytest.fail("not admitted")
    assert len(transports) == 1 and transports[0].http.closed
