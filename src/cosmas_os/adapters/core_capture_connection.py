"""Capture-specific owned transport with the retained adapter's exact protocols."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
from azure.identity import ManagedIdentityCredential

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.adapters.core_record_connection import BoundedIdentityTransport
from cosmas_os.application.capture_deadline import CaptureBudget
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_source import MAX_CAPTURE_SOURCE_BYTES

MAX_HEADERS = 16_384
PATH_LIMITS = {
    "/embed/v1/context-tokens/exchange": 16_384,
    "/service/v1/agent/mount-context/resolve": 16_384,
    "/service/v1/agent/scribe/capture-bindings/resolve": 16_384,
    "/service/v1/agent/scribe/encounter-context": 262_144,
    "/service/v1/agent/scribe/capture-admissions": 16_384,
    "/service/v1/agent/scribe/capture-notes": 1_052_672,
    "/service/v1/agent/scribe/capture-operations": MAX_CAPTURE_SOURCE_BYTES + 4096,
}


class _CaptureHTTP:
    def __init__(self, budget: CaptureBudget, maximum, phase_seconds, transport_factory=None):
        self.budget = budget
        self.maximum = maximum
        self.phase_seconds = phase_seconds
        self.transport_factory = transport_factory
        self.closed = False

    def close(self):
        self.closed = True

    def request(self, method: str, url: str, *, headers, content=None, json=None):
        if self.closed:
            raise ConnectorUnavailable("core_capture_request_unconfirmed")
        self.budget.check()
        return self.budget.run(
            lambda: self._request(method, url, headers=headers, content=content, json=json)
        )

    async def _request(self, method, url, *, headers, content, json):
        remaining = min(self.phase_seconds, self.budget.check())
        transport = (
            self.transport_factory()
            if self.transport_factory
            else httpx.AsyncHTTPTransport(
                retries=0,
                trust_env=False,
                http1=True,
                http2=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            )
        )
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(remaining, connect=min(5, remaining)),
        ) as client:
            self.budget.check()
            async with client.stream(
                method,
                url,
                headers={**headers, "Accept-Encoding": "identity"},
                content=content,
                json=json,
            ) as response:
                self.budget.check()
                if (
                    sum(len(k) + len(v) for k, v in response.headers.raw) > MAX_HEADERS
                    or response.headers.get("content-encoding", "identity") != "identity"
                    or len(response.headers.get_list("content-length")) > 1
                ):
                    raise ConnectorUnavailable("core_capture_receipt_invalid")
                length = response.headers.get("content-length")
                if length is not None and (
                    not length.isascii()
                    or not length.isdigit()
                    or len(length) > 9
                    or int(length) > self.maximum
                ):
                    raise ConnectorUnavailable("core_capture_receipt_invalid")
                body = bytearray()
                if response.is_stream_consumed:
                    # An in-process fixture may already own a bounded response.
                    if len(response.content) > self.maximum:
                        raise ConnectorUnavailable("core_capture_receipt_invalid")
                    body.extend(response.content)
                else:
                    async for chunk in response.aiter_raw():
                        self.budget.check()
                        if len(body) + len(chunk) > self.maximum:
                            raise ConnectorUnavailable("core_capture_receipt_invalid")
                        body.extend(chunk)
                self.budget.check()
                if length is not None and len(body) != int(length):
                    raise ConnectorUnavailable("core_capture_receipt_invalid")
                return httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    content=bytes(body),
                    request=response.request,
                )


class _CoreClient:
    def __init__(self, origin, budget, transport_factory, *, path_limits=None):
        self.origin, self.budget, self.transport_factory = origin, budget, transport_factory
        self.path_limits = dict(PATH_LIMITS if path_limits is None else path_limits)
        self.closed = False

    @contextmanager
    def stream(self, method, url, *, headers, json=None, timeout=None):
        self.budget.check()
        path = url.removeprefix(self.origin)
        if (self.closed or method != "POST" or url != self.origin + path
            or path not in self.path_limits or timeout not in {None, 30, 100}):
            raise ConnectorUnavailable("core_capture_request_unconfirmed")
        transport = _CaptureHTTP(
            self.budget, self.path_limits[path], timeout or 10, self.transport_factory
        )
        try:
            response = transport.request(method, url, headers=headers, json=json)
            try:
                self.budget.check()
                yield response
                self.budget.check()
            finally:
                response.close()
        finally:
            transport.close()

    def close(self):
        self.closed = True


class BoundedCoreCaptureConnection(HttpCoreCaptureAdmission):
    def __init__(self, origin, workload_token: Callable[[], str], budget: CaptureBudget,
                 *, transport_factory=None, now=lambda: datetime.now(UTC)):
        budget.check()

        def token():
            budget.check()
            value = workload_token()
            budget.check()
            return value

        super().__init__(origin, token, now=now)
        self._client.close()
        self._client = _CoreClient(self._origin, budget, transport_factory)


@contextmanager
def capture_connection(settings: Any, budget: CaptureBudget) -> Iterator[BoundedCoreCaptureConnection]:
    budget.check()
    if not settings.workspace_capture_available:
        raise ConnectorUnavailable("core_capture_request_unconfirmed")
    scope = settings.core_capture_scope
    transport = BoundedIdentityTransport(budget)
    try:
        credential = ManagedIdentityCredential(
            client_id=settings.core_capture_managed_identity_client_id,
            transport=transport, retry_total=0, retry_connect=0, retry_read=0, retry_status=0,
        )
        try:
            connection = BoundedCoreCaptureConnection(
                settings.core_capture_origin, lambda: credential.get_token(scope).token, budget,
            )
            try:
                yield connection
            finally:
                connection.close()
        finally:
            credential.close()
    finally:
        transport.close()
