"""Actual Azure SDK over bounded loopback HTTP, never an Azure acceptance claim."""

import hashlib
import inspect
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential
from azure.core.pipeline.transport import HttpRequest
from azure.storage.blob import ContainerClient

import cosmas_os.adapters.vendor_artifact_transport as boundary
from cosmas_os.adapters.vendor_artifact_transport import (
    AcquiredAzureArtifactToken,
    BoundedAzureArtifactContainer,
)
from cosmas_os.adapters.vendor_artifacts import AzureVendorArtifactStore
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError, VendorArtifactScope
from cosmas_os.ports.vendor_connectors import DocumentBinding

PDF = b"%PDF-1.7\nInvented bounded HTTP document\n%%EOF"
ORIGIN = "https://invented.blob.core.windows.net"
NAME = "synthetic-documents"


def scope_for():
    return VendorArtifactScope(box_id=uuid4(), workspace_id=uuid4(), owner_id=uuid4(),
        document=DocumentBinding(artifact_id=uuid4(), sha256=hashlib.sha256(PDF).hexdigest(),
            byte_length=len(PDF)))


def assert_code(code, call):
    with pytest.raises(ArtifactStoreError) as error:
        call()
    assert str(error.value) == error.value.code == code


def test_actual_sdk_inherits_body_consumed_outer_budget_without_fresh_timeout(tmp_path):
    scope = scope_for()
    with scenario("shared_deadline") as (container, requests):
        store = AzureVendorArtifactStore(container, box_id=scope.box_id)
        started = time.monotonic()
        deadline = started + 0.2
        time.sleep(0.12)  # Simulates time already consumed by the API request body.
        assert_code("storage_unavailable", lambda: store.read_verified(scope, deadline=deadline))
        elapsed = time.monotonic() - started
        assert_code("storage_unconfirmed", lambda: store.put_verified(scope, PDF, deadline=deadline))
    assert [request["method"] for request in requests] == ["HEAD"]
    assert elapsed < 0.65
    (tmp_path / "outer-deadline.json").write_text(json.dumps({"body_budget_consumed_seconds": 0.12,
        "whole_budget_seconds": 0.2, "elapsed_seconds": elapsed, "requests": requests,
        "late_read_success": False, "late_put_started": False, "live_azure_acceptance": False}, indent=2) + "\n")


@contextmanager
def scenario(mode):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def headers_for(self, status, *, length=None, chunked=False, extra=None):
            self.send_response(status)
            self.send_header("ETag", '"invented-version"')
            self.send_header("Last-Modified", "Mon, 21 Sep 2026 12:00:00 GMT")
            self.send_header("x-ms-blob-type", "BlockBlob")
            self.send_header("x-ms-request-id", "invented")
            self.send_header("Connection", "close")
            if chunked:
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Content-Length", str(0 if length is None else length))
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()

        def remember(self):
            requests.append({"method": self.command, "path": self.path,
                "range": self.headers.get("x-ms-range"),
                "if_match": self.headers.get("If-Match"),
                "identity_encoding": self.headers.get("Accept-Encoding") == "identity",
                "authorization_present": "Authorization" in self.headers})

        def do_HEAD(self):
            self.remember()
            if mode == "shared_deadline":
                time.sleep(0.13)
            if mode == "redirect":
                self.headers_for(307, extra={"Location": "https://unapproved.invalid/document"})
            elif mode == "head_503":
                self.headers_for(503)
            elif mode == "head_missing":
                self.headers_for(404, length=2_097_152, extra={"x-ms-error-code": "BlobNotFound"})
            elif mode == "head_oversized":
                self.headers_for(200, length=2_097_152)
            else:
                self.headers_for(200, length=len(PDF))

        def do_GET(self):
            self.remember()
            size = len(PDF)
            body = PDF
            extra = {"Content-Range": f"bytes 0-{size - 1}/{size}"}
            if mode == "get_503":
                self.headers_for(503)
                return
            if mode == "bad_range":
                extra["Content-Range"] = "bytes 0-2097151/2097152"
                body = b"x" * 2_097_152
            elif mode == "bad_length":
                body = b"x" * 2_097_152
            elif mode == "gzip":
                extra["Content-Encoding"] = "gzip"
            elif mode == "changed_etag":
                extra["ETag"] = '"another-version"'
            elif mode == "wrong_bytes":
                body = b"x" * size
            chunked = mode in {"chunked_excess", "chunked_truncated", "chunked_valid", "tiny_chunks"}
            if mode == "chunked_excess":
                body = PDF + b"x" * 2_097_152
            elif mode in {"truncated", "chunked_truncated"}:
                body = PDF[:-1]
            length = size if mode == "truncated" else len(body)
            self.headers_for(200 if mode == "ignored_range" else 206,
                length=length, chunked=chunked, extra=extra)
            try:
                if mode == "shared_deadline":
                    time.sleep(0.13)
                if mode == "trickle":
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.025)
                elif chunked:
                    chunk_size = 1 if mode == "tiny_chunks" else 65_536
                    for offset in range(0, len(body), chunk_size):
                        chunk = body[offset:offset + chunk_size]
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected when the bounded reader rejects and closes early.

        def do_PUT(self):
            self.remember()
            assert self.rfile.read(int(self.headers["Content-Length"])) == PDF
            assert self.headers["If-None-Match"] == "*"
            if mode == "put_lost":
                self.close_connection = True
                return
            self.headers_for(503 if mode == "put_503" else 201)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    client = BoundedAzureArtifactContainer(
        account_url=f"http://127.0.0.1:{server.server_port}/localaccount", container_name=NAME,
        credential=None, operation_timeout_seconds=0.2 if mode in {"trickle", "shared_deadline"} else 5)
    try:
        yield client, requests
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def observe_body_boundary(monkeypatch):
    from anyio._backends._asyncio import StreamProtocol

    observations = {"raw_chunks": [], "sdk_response_bodies": [], "raw_iterator_entries": 0,
        "socket_callback_max_bytes": 0, "socket_queue_peak_bytes": 0}
    raw = httpx.Response.aiter_raw
    body_init = boundary._Response.__init__
    received = StreamProtocol.data_received

    async def counted(response, chunk_size=None):
        assert chunk_size is None, "Do not accumulate raw network chunks in an HTTPX ByteChunker"
        observations["raw_iterator_entries"] += 1
        async for chunk in raw(response, chunk_size=chunk_size):
            observations["raw_chunks"].append(len(chunk))
            yield chunk

    def captured(self, request, status, headers, body):
        observations["sdk_response_bodies"].append({"method": request.method, "bytes": len(body)})
        body_init(self, request, status, headers, body)

    def socket_received(protocol, data):
        received(protocol, data)
        observations["socket_callback_max_bytes"] = max(
            observations["socket_callback_max_bytes"], len(data))
        observations["socket_queue_peak_bytes"] = max(
            observations["socket_queue_peak_bytes"], sum(map(len, protocol.read_queue)))

    monkeypatch.setattr(httpx.Response, "aiter_raw", counted)
    monkeypatch.setattr(boundary._Response, "__init__", captured)
    monkeypatch.setattr(StreamProtocol, "data_received", socket_received)
    return observations


@pytest.mark.parametrize(("mode", "code", "methods", "reads_body"), [
    ("head_oversized", "artifact_changed", ["HEAD"], False),
    ("bad_range", "artifact_changed", ["HEAD", "GET"], False),
    ("bad_length", "artifact_changed", ["HEAD", "GET"], False),
    ("ignored_range", "artifact_changed", ["HEAD", "GET"], False),
    ("gzip", "artifact_changed", ["HEAD", "GET"], False),
    ("changed_etag", "artifact_changed", ["HEAD", "GET"], False),
    ("chunked_excess", "artifact_changed", ["HEAD", "GET"], True),
    ("truncated", "storage_unavailable", ["HEAD", "GET"], True),
    ("chunked_truncated", "artifact_changed", ["HEAD", "GET"], True),
    ("wrong_bytes", "artifact_changed", ["HEAD", "GET"], True),
    ("redirect", "storage_unavailable", ["HEAD"], False),
    ("head_503", "storage_unavailable", ["HEAD"], False),
    ("get_503", "storage_unavailable", ["HEAD", "GET"], False),
    ("head_missing", "artifact_not_found", ["HEAD"], False),
    ("trickle", "storage_unavailable", ["HEAD", "GET"], True),
    ("shared_deadline", "storage_unavailable", ["HEAD", "GET"], True),
])
def test_actual_sdk_refuses_malformed_or_unbounded_reads_without_retry(
        mode, code, methods, reads_body, monkeypatch, tmp_path):
    observations = observe_body_boundary(monkeypatch)
    scope = scope_for()
    with scenario(mode) as (container, requests):
        started = time.monotonic()
        assert_code(code, lambda: AzureVendorArtifactStore(container, box_id=scope.box_id)
            .read_verified(scope))
        elapsed = time.monotonic() - started
    assert [request["method"] for request in requests] == methods
    assert all(request["identity_encoding"] for request in requests)
    assert all(not request["authorization_present"] for request in requests)
    assert all(size <= 65_536 for size in observations["raw_chunks"])
    assert observations["socket_callback_max_bytes"] <= 262_144
    assert observations["socket_queue_peak_bytes"] <= 262_144
    assert all(item["bytes"] <= len(PDF) for item in observations["sdk_response_bodies"])
    assert bool(observations["raw_iterator_entries"]) == reads_body
    if not reads_body:
        assert observations["raw_chunks"] == []
    if mode == "chunked_excess":
        # At most the already accepted prefix and one bounded transport chunk;
        # excess is rejected before it is retained or handed to the Azure SDK.
        assert sum(observations["raw_chunks"]) <= len(PDF) + 65_536
        assert all(item["bytes"] == 0 for item in observations["sdk_response_bodies"])
    if mode in {"trickle", "shared_deadline"}:
        assert elapsed < 0.8
    (tmp_path / "observed-boundary.json").write_text(json.dumps({"mode": mode,
        "error": code, "requests": requests, "body_observations": observations,
        "deadline_elapsed_seconds": elapsed, "expected_length_plus_one": len(PDF) + 1,
        "live_azure_acceptance": False}, indent=2) + "\n")


@pytest.mark.parametrize("mode", ["chunked_valid", "tiny_chunks"])
def test_actual_sdk_accepts_exact_chunked_document(mode, monkeypatch):
    observations = observe_body_boundary(monkeypatch)
    scope = scope_for()
    with scenario(mode) as (container, requests):
        assert AzureVendorArtifactStore(container, box_id=scope.box_id).read_verified(scope) == PDF
    assert [request["method"] for request in requests] == ["HEAD", "GET"]
    assert sum(observations["raw_chunks"]) == len(PDF)
    assert observations["sdk_response_bodies"] == [
        {"method": "HEAD", "bytes": 0}, {"method": "GET", "bytes": len(PDF)}]


@pytest.mark.parametrize("mode", ["put_503", "put_lost"])
def test_actual_sdk_unknown_upload_is_once_only(mode):
    scope = scope_for()
    with scenario(mode) as (container, requests):
        assert_code("storage_unconfirmed", lambda: AzureVendorArtifactStore(container,
            box_id=scope.box_id).put_verified(scope, PDF))
    assert [request["method"] for request in requests] == ["PUT"]


def test_plain_sdk_container_is_not_an_accepted_store_transport():
    client = ContainerClient(account_url=ORIGIN, container_name=NAME, credential=None)
    try:
        assert_code("storage_unavailable", lambda: AzureVendorArtifactStore(cast(Any, client), box_id=uuid4()))
    finally:
        client.close()


@pytest.mark.parametrize("change", [
    {"account_url": "http://invented.invalid"},
    {"account_url": "http://127.0.0.1.evil.invalid"},
    {"account_url": "http://localhost"},
    {"account_url": "http://127.0.0.1:bad"},
    {"account_url": "http://127.0.0.1/path/another"},
    {"account_url": "https://invented.invalid?sig=private"},
    {"account_url": "https://private@invented.invalid"},
    {"account_url": ORIGIN},
    {"container_name": "../another"},
    {"container_name": "two--hyphens"},
    {"operation_timeout_seconds": 61},
    {"operation_timeout_seconds": float("inf")},
    {"credential": object()},
])
def test_factory_rejects_nonexplicit_origin_credential_and_bounds(change):
    config = {"account_url": "http://127.0.0.1:12345", "container_name": NAME, "credential": None}
    assert_code("storage_unavailable", lambda: BoundedAzureArtifactContainer(**(config | change)))


def token_value(**changes):
    values = {"token": "invented-token", "expires_on": int(time.time()) + 3600,
        "account_url": ORIGIN, "selected_identity_client_id": uuid4()}
    return AcquiredAzureArtifactToken(**(values | changes))


@pytest.mark.parametrize("change", [
    {"expires_on": 1}, {"expires_on": float("inf")}, {"token": ""}, {"token": "bad\nvalue"},
    {"account_url": "https://another.invalid"}, {"selected_identity_client_id": "unselected"},
    {"account_url": None},
])
def test_acquired_token_is_bound_to_exact_origin_selection_and_expiry(change):
    assert_code("storage_unavailable", lambda: BoundedAzureArtifactContainer(account_url=ORIGIN,
        container_name=NAME, credential=token_value(**change)))


def test_selected_managed_identity_token_signs_without_identity_discovery(monkeypatch):
    observed = []

    async def pretend_send(request, operation):
        observed.append((request.headers["Authorization"] == "Bearer invented-token",
            operation.deadline <= time.monotonic() + 60))
        return boundary._Response(request, 201, {"ETag": '"v1"'}, b"")

    monkeypatch.setattr(boundary._Transport, "_send", staticmethod(pretend_send))
    credential = token_value()
    client = BoundedAzureArtifactContainer(account_url=ORIGIN, container_name=NAME,
        credential=credential)
    scope = scope_for()
    try:
        AzureVendorArtifactStore(client, box_id=scope.box_id).put_verified(scope, PDF)
        assert observed == [(True, True)]
        assert repr(credential) == "AcquiredAzureArtifactToken(<protected>)"
        assert repr(client) == "BoundedAzureArtifactContainer(<protected>)"
        observed.clear()
        monkeypatch.setattr(boundary.time, "time", lambda: credential.expires_on + 1)
        assert_code("storage_unconfirmed", lambda: AzureVendorArtifactStore(client,
            box_id=scope.box_id).put_verified(scope, PDF))
        assert observed == []
    finally:
        client.close()


@pytest.mark.parametrize("signature", ["sig=one&comp=list", "sig=one&sig=two", "sig=", "sv=1"])
def test_sas_cannot_add_an_operation_or_duplicate_query(signature):
    assert_code("storage_unavailable", lambda: BoundedAzureArtifactContainer(account_url=ORIGIN,
        container_name=NAME, credential=AzureSasCredential(signature)))


@pytest.mark.parametrize("kind", ["named_key", "sas"])
def test_explicit_credentials_are_snapshotted_not_mutated_in_flight(kind, monkeypatch):
    observed = []

    async def pretend_send(request, operation):
        observed.append((request.url, request.headers.get("Authorization", "")))
        return boundary._Response(request, 201, {"ETag": '"v1"'}, b"")

    monkeypatch.setattr(boundary._Transport, "_send", staticmethod(pretend_send))
    if kind == "named_key":
        credential = AzureNamedKeyCredential("invented", "aW52ZW50ZWQ=")
    else:
        credential = AzureSasCredential("sv=2025-01-05&sig=invented%2Bsignature")
    client = BoundedAzureArtifactContainer(account_url=ORIGIN, container_name=NAME, credential=credential)
    scope = scope_for()
    try:
        if isinstance(credential, AzureNamedKeyCredential):
            credential.update("different", "ZGlmZmVyZW50")
        else:
            credential.update("sig=changed")
        AzureVendorArtifactStore(client, box_id=scope.box_id).put_verified(scope, PDF)
        assert len(observed) == 1
        url, authorization = observed[0]
        if kind == "named_key":
            assert authorization.startswith("SharedKey invented:")
            assert "sig=" not in url
        else:
            assert "invented%2Bsignature" in url and "changed" not in url
            assert authorization == ""
    finally:
        client.close()


@pytest.mark.parametrize("change", [
    {"method": "DELETE"}, {"url": "http://127.0.0.1:12345/other"},
    {"query": "comp=list&timeout=30"}, {"query": "timeout=30&timeout=30"},
    {"query": "snapshot=other&timeout=30"},
])
def test_operation_budget_refuses_changed_method_origin_path_or_query(change, monkeypatch):
    client = BoundedAzureArtifactContainer(account_url="http://127.0.0.1:12345",
        container_name=NAME, credential=None)
    scope = scope_for()
    name = "/".join(scope.storage_segments())
    called = []

    async def pretend_send(request, operation):
        called.append(request.method)
        return boundary._Response(request, 200, {}, b"")

    monkeypatch.setattr(boundary._Transport, "_send", staticmethod(pretend_send))
    query = change.get("query", "timeout=30")
    request = HttpRequest(change.get("method", "HEAD"),
        change.get("url", f"http://127.0.0.1:12345/{NAME}/{name}?{query}"))
    try:
        with client.operation("read", name, len(PDF), deadline=client.deadline()):
            assert_code("storage_unavailable", lambda: client._transport.send(request))
        assert called == []
    finally:
        client.close()


def test_operation_budget_refuses_sdk_retry_after_first_request(monkeypatch):
    client = BoundedAzureArtifactContainer(account_url="http://127.0.0.1:12345",
        container_name=NAME, credential=None)
    name = "/".join(scope_for().storage_segments())
    called = []

    async def lost_reply(request, operation):
        called.append(request.method)
        raise httpx.ReadError("invented private URL and credentials")

    monkeypatch.setattr(boundary._Transport, "_send", staticmethod(lost_reply))
    request = HttpRequest("HEAD", f"http://127.0.0.1:12345/{NAME}/{name}?timeout=30")
    try:
        with client.operation("read", name, len(PDF), deadline=client.deadline()):
            assert_code("storage_unavailable", lambda: client._transport.send(request))
            assert_code("storage_unavailable", lambda: client._transport.send(request))
        assert_code("storage_unavailable", lambda: client._transport.send(request))
        assert called == ["HEAD"]
    finally:
        client.close()


def test_installed_httpx_httpcore_streaming_bound_is_explicit():
    """Dependency acceptance evidence only; production code uses public APIs."""
    import asyncio.selector_events as selector_events

    from anyio._backends._asyncio import SocketStream
    from httpcore._async.http11 import AsyncHTTP11Connection
    from httpx._decoders import ByteChunker

    assert AsyncHTTP11Connection.READ_NUM_BYTES == 65_536
    assert AsyncHTTP11Connection.MAX_INCOMPLETE_EVENT_SIZE == 102_400
    assert cast(Any, selector_events)._SelectorTransport.max_size == 262_144
    socket_source = inspect.getsource(SocketStream.receive)
    assert "self._transport.pause_reading()" in socket_source
    assert "chunk[:max_bytes]" in socket_source
    receive_source = inspect.getsource(AsyncHTTP11Connection._receive_event)
    assert "self.READ_NUM_BYTES, timeout=timeout" in receive_source
    chunker = ByteChunker(chunk_size=None)
    raw = b"invented raw chunk"
    assert chunker.decode(raw) == [raw]
    assert chunker.flush() == []
