"""Bounded Azure custody transport using only public SDK transport interfaces.

The application supplies the account, private container and selected credential.
This synchronous store belongs in an API worker thread; the application still
owns its earlier auth/body deadline and durable ingestion generation fence.
"""

import asyncio
import math
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import httpx
from azure.core.credentials import AccessToken, AzureNamedKeyCredential, AzureSasCredential
from azure.core.pipeline.transport import HttpResponse, HttpTransport
from azure.storage.blob import ContainerClient

from cosmas_os.ports.vendor_artifacts import ArtifactStoreError
from cosmas_os.ports.vendor_connectors import MAX_DOCUMENT_BYTES

_RAW_CHUNK_BYTES = 65_536
_HEADER_BYTES = 16_384
_SAS_FIELDS = frozenset({"sv", "ss", "srt", "sp", "se", "st", "spr", "sip", "si", "sr",
    "sig", "skoid", "sktid", "skt", "ske", "sks", "skv", "saoid", "suoid", "scid", "ses",
    "rscc", "rscd", "rsce", "rscl", "rsct"})


@dataclass(frozen=True, repr=False)
class AcquiredAzureArtifactToken:
    """An already-acquired token from the explicitly selected managed identity.

    Acquiring/refreshing the token belongs to the authorized runtime, before this
    bounded store operation. This value cannot discover identities or refresh a
    token. The factory binds it to its exact storage origin and expiry.
    """

    token: str
    expires_on: int
    account_url: str
    selected_identity_client_id: UUID

    def __repr__(self):
        return "AcquiredAzureArtifactToken(<protected>)"


class _AcquiredCredential:
    def __init__(self, value: AcquiredAzureArtifactToken):
        self._value = value

    def get_token(self, *scopes: str, **kwargs) -> AccessToken:
        if (scopes != ("https://storage.azure.com/.default",)
                or self._value.expires_on <= time.time()):
            raise ArtifactStoreError("storage_unavailable")
        return AccessToken(self._value.token, self._value.expires_on)


@dataclass
class _Operation:
    url: str
    length: int
    deadline: float
    methods: list[str]


class _Body:
    def __init__(self, response: HttpResponse, data: bytes):
        self.response = response
        self.content_length = len(data)
        self._data = data

    def __iter__(self):
        data, self._data = self._data, b""
        if data:
            yield data


class _Response(HttpResponse):
    def __init__(self, request, status: int, headers: dict[str, str], body: bytes):
        super().__init__(request, None)
        self.status_code = status
        self.headers = httpx.Headers(headers)
        self.reason = ""
        self.content_type = self.headers.get("content-type")
        self._body = body

    def body(self) -> bytes:
        return self._body

    def stream_download(self, pipeline, **kwargs):
        return _Body(self, self._body)


class _Transport(HttpTransport):
    def __init__(self, query: tuple[tuple[str, str], ...], expires_on: int | None):
        self.operation: ContextVar[_Operation | None] = ContextVar("vendor_artifact_io", default=None)
        self._query = sorted((*query, ("timeout", "30")))
        self._expires_on = expires_on

    def open(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, request, **kwargs):
        operation = self.operation.get()
        if operation is None or not operation.methods:
            raise ArtifactStoreError("storage_unavailable")
        target = urlsplit(request.url)
        expected = urlsplit(operation.url)
        try:
            query = sorted(parse_qsl(target.query, strict_parsing=True, max_num_fields=33))
        except ValueError:
            raise ArtifactStoreError("storage_unavailable") from None
        if ((target.scheme, target.netloc, target.path) !=
                (expected.scheme, expected.netloc, expected.path)
                or target.fragment or request.method != operation.methods[0]
                or query != self._query):
            raise ArtifactStoreError("storage_unavailable")
        # Spend the request before I/O. SDK-level retries cannot send it again.
        operation.methods.pop(0)
        if request.method == "GET":
            if (request.headers.get("x-ms-range") != f"bytes=0-{operation.length}"
                    or not request.headers.get("If-Match") or request.data is not None):
                raise ArtifactStoreError("storage_unavailable")
        if request.method == "HEAD" and request.data is not None:
            raise ArtifactStoreError("storage_unavailable")
        if request.method == "PUT":
            if (request.headers.get("If-None-Match") != "*"
                    or type(request.data) is not bytes or len(request.data) != operation.length):
                raise ArtifactStoreError("storage_unavailable")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            # Never block an application's event loop or create an unowned worker.
            raise ArtifactStoreError("storage_unavailable")
        try:
            if self._expires_on is not None:
                operation.deadline = min(operation.deadline,
                    time.monotonic() + self._expires_on - time.time())
            return asyncio.run(self._send(request, operation))
        except ArtifactStoreError:
            raise
        except Exception:
            # Do not expose URLs, selected credentials or SDK/provider text.
            raise ArtifactStoreError("storage_unavailable") from None

    @staticmethod
    async def _send(request, operation: _Operation) -> HttpResponse:
        remaining = operation.deadline - time.monotonic()
        if remaining <= 0:
            raise ArtifactStoreError("storage_unavailable")
        async with asyncio.timeout(remaining):
            # No ambient proxies, redirects, implicit identity or transport retries.
            transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False,
                http1=True, http2=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0))
            async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(remaining, connect=min(5, remaining)),
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=0)) as client:
                request_headers = dict(request.headers)
                request_headers["Accept-Encoding"] = "identity"
                async with client.stream(request.method, request.url,
                        headers=request_headers, content=request.data) as response:
                    if sum(len(key) + len(value) for key, value in response.headers.raw) > _HEADER_BYTES:
                        raise ArtifactStoreError("storage_unavailable")
                    status, headers = response.status_code, dict(response.headers)
                    if 300 <= status < 400:
                        raise ArtifactStoreError("storage_unavailable")
                    # Error codes are in headers. Never feed a provider error body
                    # into the SDK's unbounded XML/error-body reader.
                    if status >= 400:
                        return _Response(request, status, headers, b"")
                    if request.method == "PUT":
                        if status != 201:
                            raise ArtifactStoreError("storage_unavailable")
                        return _Response(request, status, headers, b"")
                    if request.method == "HEAD":
                        if status != 200:
                            raise ArtifactStoreError("storage_unavailable")
                        if (headers.get("content-length") != str(operation.length)
                                or headers.get("x-ms-blob-type") != "BlockBlob"
                                or not headers.get("etag")):
                            raise ArtifactStoreError("artifact_changed")
                        return _Response(request, status, headers, b"")
                    if (status != 206
                            or headers.get("content-range") !=
                                f"bytes 0-{operation.length - 1}/{operation.length}"
                            or headers.get("etag") != request.headers.get("If-Match")
                            or headers.get("content-encoding", "identity") != "identity"
                            or headers.get("x-ms-blob-type") != "BlockBlob"):
                        raise ArtifactStoreError("artifact_changed")
                    length = headers.get("content-length")
                    if length is not None and length != str(operation.length):
                        raise ArtifactStoreError("artifact_changed")
                    maximum = operation.length + 1
                    # A fixed allocation also bounds fragment metadata: a peer
                    # sending millions of one-byte chunks cannot grow a list.
                    document = bytearray(operation.length)
                    size = 0
                    # No HTTPX ByteChunker accumulation: reject the first raw
                    # chunk that would exceed the document bound before retaining
                    # it. HTTP/1.1 httpcore reads at most 64 KiB per network read;
                    # qualification pins that dependency evidence separately.
                    async for chunk in response.aiter_raw():
                        if (not chunk or len(chunk) > _RAW_CHUNK_BYTES
                                or len(chunk) > maximum - size):
                            raise ArtifactStoreError("artifact_changed")
                        next_size = size + len(chunk)
                        if next_size > operation.length:
                            raise ArtifactStoreError("artifact_changed")
                        document[size:next_size] = chunk
                        size = next_size
                    if size != operation.length:
                        raise ArtifactStoreError("artifact_changed")
                    return _Response(request, status, headers, bytes(document))


class BoundedAzureArtifactContainer:
    """Explicit private container with a bounded, fixed-origin custody transport.

    Credentials must already be selected. Network-refreshing TokenCredential and
    default identity discovery are intentionally unsupported here; an already
    acquired, expiry-bound selected-identity token is supported. Anonymous HTTP
    is permitted only at exact 127.0.0.1 for local synthetic SDK trials.
    """

    def __init__(self, *, account_url: str, container_name: str,
            credential: AzureNamedKeyCredential | AzureSasCredential | AcquiredAzureArtifactToken | None,
            operation_timeout_seconds: float = 60):
        if not isinstance(account_url, str) or not isinstance(container_name, str):
            raise ArtifactStoreError("storage_unavailable")
        try:
            parsed = urlsplit(account_url)
            _ = parsed.port
        except ValueError:
            raise ArtifactStoreError("storage_unavailable") from None
        local = parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
        if (parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or not parsed.hostname
                or (not local and (parsed.scheme != "https" or parsed.path not in {"", "/"}))
                or (local and re.fullmatch(r"(?:/[a-z0-9-]+)?/?", parsed.path) is None)
                or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61})[a-z0-9]", container_name) is None
                or "--" in container_name
                or (credential is None and not local)
                or (credential is not None and type(credential) not in
                    {AzureNamedKeyCredential, AzureSasCredential, AcquiredAzureArtifactToken})
                or (local and credential is not None)
                or type(operation_timeout_seconds) not in {int, float}
                or not math.isfinite(operation_timeout_seconds)
                or not 0 < operation_timeout_seconds <= 60):
            raise ArtifactStoreError("storage_unavailable")
        self._url = f"{account_url.rstrip('/')}/{container_name}"
        self._timeout = float(operation_timeout_seconds)
        query: tuple[tuple[str, str], ...] = ()
        expires_on = None
        selected: Any = credential
        if isinstance(credential, AcquiredAzureArtifactToken):
            if (not isinstance(credential.account_url, str)
                    or credential.account_url.rstrip("/") != account_url.rstrip("/")
                    or type(credential.expires_on) is not int
                    or credential.expires_on <= time.time()
                    or type(credential.selected_identity_client_id) is not UUID
                    or not isinstance(credential.token, str)
                    or not 1 <= len(credential.token) <= 16_384
                    or any(ord(char) <= 32 or ord(char) >= 127 for char in credential.token)):
                raise ArtifactStoreError("storage_unavailable")
            expires_on = credential.expires_on
            selected = _AcquiredCredential(credential)
        elif isinstance(credential, AzureNamedKeyCredential):
            # Snapshot mutable Azure credential objects; caller rotation must use
            # a new explicitly configured container, never change an in-flight op.
            selected = AzureNamedKeyCredential(credential.named_key.name, credential.named_key.key)
        elif isinstance(credential, AzureSasCredential):
            signature = credential.signature.removeprefix("?")
            try:
                query = tuple(parse_qsl(signature, strict_parsing=True, max_num_fields=32))
            except ValueError:
                raise ArtifactStoreError("storage_unavailable") from None
            if (not query or len({key for key, _ in query}) != len(query)
                    or "sig" not in dict(query)
                    or any(key not in _SAS_FIELDS or not value for key, value in query)):
                raise ArtifactStoreError("storage_unavailable")
            selected = AzureSasCredential(signature)
        self._transport = _Transport(query, expires_on)
        self._client = ContainerClient(account_url=account_url, container_name=container_name,
            credential=selected, transport=self._transport, retry_total=0,
            retry_connect=0, retry_read=0, retry_status=0, retry_to_secondary=False,
            max_single_put_size=MAX_DOCUMENT_BYTES,
            max_single_get_size=MAX_DOCUMENT_BYTES + 1, max_chunk_get_size=MAX_DOCUMENT_BYTES + 1)

    def __repr__(self):
        return "BoundedAzureArtifactContainer(<protected>)"

    def deadline(self) -> float:
        remaining = self._timeout
        if self._transport._expires_on is not None:
            remaining = min(remaining, self._transport._expires_on - time.time())
        return time.monotonic() + remaining

    @contextmanager
    def operation(self, kind: str, name: str, length: int, *, deadline: float) -> Iterator[None]:
        if (self._transport.operation.get() is not None or kind not in {"put", "read"}
                or type(length) is not int or not 1 <= length <= MAX_DOCUMENT_BYTES
                or not isinstance(name, str)
                or re.fullmatch(r"[0-9a-f-]{36}/vendor-documents/[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}\.pdf", name) is None
                or type(deadline) not in {int, float} or not math.isfinite(deadline)
                or deadline <= time.monotonic() or deadline > self.deadline()):
            raise ArtifactStoreError("storage_unavailable")
        state = _Operation(f"{self._url}/{name}", length, deadline,
            ["PUT"] if kind == "put" else ["HEAD", "GET"])
        token = self._transport.operation.set(state)
        try:
            yield
        finally:
            self._transport.operation.reset(token)

    def get_blob_client(self, name: str) -> Any:
        return self._client.get_blob_client(name)

    def close(self):
        self._client.close()
