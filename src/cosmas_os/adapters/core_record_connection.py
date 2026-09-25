"""Location-only bounded transport; existing capture adapters are unchanged."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from azure.core.pipeline.transport import HttpResponse, HttpTransport
from azure.identity import ManagedIdentityCredential

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.application.core_record_deadline import RecordDeadline
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable

MAX_BYTES = 16_384
MAX_HEADERS = 16_384
PATHS = frozenset(
    {
        "/embed/v1/context-tokens/exchange",
        "/service/v1/agent/mount-context/resolve",
        "/service/v1/agent/scribe/capture-bindings/resolve",
    }
)


class _BoundedHTTP:
    def __init__(self, budget: RecordDeadline, transport_factory=None, *, max_bytes=MAX_BYTES):
        if type(max_bytes) is not int or not 1 <= max_bytes <= 65_536:
            raise ValueError("invalid_record_capacity")
        self.budget = budget
        self.max_bytes = max_bytes
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
        remaining = self.budget.check()
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
                    or len(length) > 5
                    or int(length) > self.max_bytes
                ):
                    raise ConnectorUnavailable("core_capture_receipt_invalid")
                body = bytearray()
                if response.is_stream_consumed:
                    # An in-process fixture may already own a bounded response.
                    if len(response.content) > self.max_bytes:
                        raise ConnectorUnavailable("core_capture_receipt_invalid")
                    body.extend(response.content)
                else:
                    async for chunk in response.aiter_raw():
                        self.budget.check()
                        if len(body) + len(chunk) > self.max_bytes:
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
    def __init__(self, origin, http):
        self.origin, self.http = origin, http

    @contextmanager
    def stream(self, method, url, *, headers, json=None, **kwargs):
        if method != "POST" or url not in {self.origin + p for p in PATHS} or kwargs:
            raise ConnectorUnavailable("core_capture_request_unconfirmed")
        response = self.http.request(method, url, headers=headers, json=json)
        try:
            yield response
        finally:
            response.close()

    def close(self):
        self.http.close()


class BoundedCoreRecordConnection(HttpCoreCaptureAdmission):
    """Reuse exact inherited context/binding validators with no capture routes."""

    def __init__(
        self,
        origin,
        workload_token: Callable[[], str],
        budget: RecordDeadline,
        *,
        transport_factory=None,
        now=lambda: datetime.now(UTC),
    ):
        budget.check()

        def token():
            budget.check()
            value = workload_token()
            budget.check()
            return value

        super().__init__(origin, token, now=now)
        self._client.close()
        self._client = _CoreClient(self._origin, _BoundedHTTP(budget, transport_factory))


class _TokenResponse(HttpResponse):
    def __init__(self, request, response: httpx.Response):
        super().__init__(request, None)
        self.status_code = response.status_code
        self.headers = response.headers
        self.reason = ""
        self.content_type = self.headers.get("content-type")
        self._body = response.content

    def body(self):
        return self._body

    def stream_download(self, pipeline, **kwargs):
        yield self._body


class BoundedIdentityTransport(HttpTransport):
    """Public SDK seam; the selected MI determines its existing token endpoint."""

    def __init__(self, budget, *, transport_factory=None):
        self.http = _BoundedHTTP(budget, transport_factory)

    def open(self):
        self.http.budget.check()

    def close(self):
        self.http.close()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    def sleep(self, duration):
        # SDK retry/backoff must not start a hidden second token attempt.
        raise ConnectorUnavailable("core_capture_identity_unavailable")

    def send(self, request, **kwargs):
        self.http.budget.check()
        parsed = urlsplit(request.url)
        body = request.data
        if isinstance(body, str):
            body = body.encode("utf-8")
        if (
            request.method not in {"GET", "POST"}
            or parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or body is not None
            and (not isinstance(body, bytes) or len(body) > 8192)
        ):
            raise ConnectorUnavailable("core_capture_identity_unavailable")
        response = self.http.request(
            request.method, request.url, headers=dict(request.headers), content=body
        )
        # Never feed untrusted provider error text or redirects into SDK errors.
        if response.status_code >= 300:
            raise ConnectorUnavailable("core_capture_identity_unavailable")
        return _TokenResponse(request, response)


@contextmanager
def record_connection(
    settings: Any, budget: RecordDeadline
) -> Iterator[BoundedCoreRecordConnection]:
    """Construct and close all resources inside the one location worker."""
    budget.check()
    if not settings.workspace_capture_available:
        raise ConnectorUnavailable("core_capture_request_unconfirmed")
    # A mutable settings object cannot change the selected token scope mid-read.
    scope = settings.core_capture_scope
    transport = BoundedIdentityTransport(budget)
    try:
        credential = ManagedIdentityCredential(
            client_id=settings.core_capture_managed_identity_client_id,
            transport=transport,
            retry_total=0,
            retry_connect=0,
            retry_read=0,
            retry_status=0,
        )
        try:
            connection = BoundedCoreRecordConnection(
                settings.core_capture_origin,
                lambda: credential.get_token(scope).token,
                budget,
            )
            try:
                yield connection
            finally:
                connection.close()
        finally:
            credential.close()
    finally:
        transport.close()
