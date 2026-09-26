import hashlib
import multiprocessing
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)

import cosmas_os.adapters.vendor_artifacts as artifact_adapters
from cosmas_os.adapters.vendor_artifact_transport import BoundedAzureArtifactContainer
from cosmas_os.adapters.vendor_artifacts import (
    AzureVendorArtifactStore,
    LocalVendorArtifactStore,
)
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError, VendorArtifactScope
from cosmas_os.ports.vendor_connectors import DocumentBinding

PDF = b"%PDF-1.7\nInvented local referral document\n%%EOF"


def scope_for(data=PDF, **changes):
    scope = VendorArtifactScope(box_id=uuid4(), workspace_id=uuid4(), owner_id=uuid4(),
        document=DocumentBinding(artifact_id=uuid4(), sha256=hashlib.sha256(data).hexdigest(),
            byte_length=len(data)))
    return scope.model_copy(update=changes)


def path_for(root, scope):
    return Path(root).joinpath(*scope.storage_segments())


def assert_code(code, call):
    with pytest.raises(ArtifactStoreError) as error:
        call()
    assert error.value.code == code
    assert str(error.value) == code


@pytest.mark.parametrize("kind", ["read", "put"])
def test_local_expired_outer_deadline_starts_no_filesystem_io(tmp_path, monkeypatch, kind):
    store, scope = LocalVendorArtifactStore(tmp_path), scope_for()
    def unexpected(*_args, **_kwargs):
        pytest.fail("expired API budget must not start filesystem I/O")
    monkeypatch.setattr(artifact_adapters.os, "open", unexpected)
    deadline = time.monotonic() - 1
    assert_code("storage_unavailable", lambda: store.read_verified(scope, deadline=deadline)
        if kind == "read" else store.put_verified(scope, PDF, deadline=deadline))


@pytest.mark.parametrize("point", ["before_publish", "after_publish", "read"])
def test_local_outer_deadline_preserves_exclusive_bytes_and_returns_no_late_success(
        tmp_path, monkeypatch, point):
    store, scope = LocalVendorArtifactStore(tmp_path), scope_for()
    if point == "read":
        store.put_verified(scope, PDF)
    clock = [99.0]
    monkeypatch.setattr(artifact_adapters, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    if point == "before_publish":
        original = os.write
        def write(*args, **kwargs):
            value = original(*args, **kwargs)
            clock[0] = 101.0
            return value
        monkeypatch.setattr(os, "write", write)
    elif point == "after_publish":
        original = os.link
        def link(*args, **kwargs):
            value = original(*args, **kwargs)
            clock[0] = 101.0
            return value
        monkeypatch.setattr(os, "link", link)
    else:
        original = os.read
        def read(*args, **kwargs):
            value = original(*args, **kwargs)
            clock[0] = 101.0
            return value
        monkeypatch.setattr(os, "read", read)
    assert_code("storage_unavailable" if point == "read" else "storage_unconfirmed",
        lambda: store.read_verified(scope, deadline=100.0) if point == "read"
        else store.put_verified(scope, PDF, deadline=100.0))
    target = path_for(tmp_path, scope)
    assert target.exists() is (point != "before_publish")
    if target.exists():
        assert target.read_bytes() == PDF
    assert not list(target.parent.glob(".stage-*"))


def test_local_verified_document_survives_adapter_restart_and_exact_reupload(tmp_path):
    scope = scope_for()
    store = LocalVendorArtifactStore(tmp_path)
    store.put_verified(scope, PDF)
    target = path_for(tmp_path, scope)
    inode = target.stat().st_ino
    restarted = LocalVendorArtifactStore(tmp_path)
    restarted.put_verified(scope, PDF)
    assert restarted.read_verified(scope) == PDF
    assert target.stat().st_ino == inode
    assert target.stat().st_mode & 0o777 == 0o600
    assert not list(target.parent.glob(".stage-*"))


@pytest.mark.parametrize("field", ["box_id", "workspace_id", "owner_id"])
def test_local_other_scope_cannot_read_existing_document(tmp_path, field):
    scope = scope_for()
    store = LocalVendorArtifactStore(tmp_path)
    store.put_verified(scope, PDF)
    other = scope.model_copy(update={field: uuid4()})
    assert_code("artifact_not_found", lambda: store.read_verified(other))


def test_conflicting_record_cannot_replace_committed_bytes(tmp_path):
    scope = scope_for()
    store = LocalVendorArtifactStore(tmp_path)
    store.put_verified(scope, PDF)
    other = b"%PDF-1.7\nDifferent exact bytes\n%%EOF"
    changed = scope.model_copy(update={"document": DocumentBinding(
        artifact_id=scope.document.artifact_id, byte_length=len(other),
        sha256=hashlib.sha256(other).hexdigest())})
    assert_code("artifact_changed", lambda: store.put_verified(changed, other))
    assert store.read_verified(scope) == PDF


def test_concurrent_exact_uploads_publish_one_file(tmp_path):
    scope = scope_for()
    store = LocalVendorArtifactStore(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.put_verified(scope, PDF), range(16)))
    assert store.read_verified(scope) == PDF
    assert list(path_for(tmp_path, scope).parent.iterdir()) == [path_for(tmp_path, scope)]


def _crash_during_link(root, scope, after):
    actual = os.link

    def interrupted(*args, **kwargs):
        if after:
            actual(*args, **kwargs)
        os._exit(77)

    os.link = interrupted
    LocalVendorArtifactStore(root).put_verified(scope, PDF)


@pytest.mark.parametrize("after", [False, True])
def test_real_process_loss_before_or_after_publication_recovers_exactly(tmp_path, after):
    scope = scope_for()
    process = multiprocessing.get_context("fork").Process(
        target=_crash_during_link, args=(str(tmp_path), scope, after))
    process.start()
    process.join(timeout=10)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("storage child did not reach the fault")
    assert process.exitcode == 77
    store = LocalVendorArtifactStore(tmp_path)
    if after:
        assert store.read_verified(scope) == PDF
    else:
        assert_code("artifact_not_found", lambda: store.read_verified(scope))
    stages = list(path_for(tmp_path, scope).parent.glob(".stage-*"))
    assert len(stages) == 1
    store.put_verified(scope, PDF)
    assert store.read_verified(scope) == PDF
    assert list(path_for(tmp_path, scope).parent.glob(".stage-*")) == stages


@pytest.mark.parametrize("bad", [b"not a PDF", b"%PDF-wrong", PDF + b"extra"])
def test_invalid_upload_is_rejected_before_directory_creation(tmp_path, bad):
    scope = scope_for()
    store = LocalVendorArtifactStore(tmp_path)
    assert_code("artifact_changed", lambda: store.put_verified(scope, bad))
    assert list(tmp_path.iterdir()) == []


def test_corrupt_oversized_object_is_rejected_before_content_read(tmp_path, monkeypatch):
    scope = scope_for()
    store = LocalVendorArtifactStore(tmp_path)
    store.put_verified(scope, PDF)
    path_for(tmp_path, scope).write_bytes(PDF + b"large")
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("oversized file was read"))
    assert_code("artifact_changed", lambda: store.read_verified(scope))


def test_concurrent_growth_is_read_only_to_expected_length_plus_one(tmp_path, monkeypatch):
    scope = scope_for()
    store = LocalVendorArtifactStore(tmp_path)
    store.put_verified(scope, PDF)
    actual_stat, actual_read = os.fstat, os.read
    observed_reads = []

    def grew(descriptor):
        value = actual_stat(descriptor)
        with path_for(tmp_path, scope).open("ab") as stream:
            stream.write(b"x" * 1000)
        return value

    def bounded(descriptor, maximum):
        data = actual_read(descriptor, maximum)
        observed_reads.append((maximum, len(data)))
        return data

    monkeypatch.setattr(os, "fstat", grew)
    monkeypatch.setattr(os, "read", bounded)
    assert_code("artifact_changed", lambda: store.read_verified(scope))
    assert sum(length for _, length in observed_reads) == len(PDF) + 1
    assert max(size for size, _ in observed_reads) <= len(PDF) + 1


def test_symlink_directory_is_neither_followed_nor_written(tmp_path):
    root = tmp_path / "private"
    outside = tmp_path / "outside"
    outside.mkdir()
    scope = scope_for()
    store = LocalVendorArtifactStore(root)
    (root / str(scope.box_id)).symlink_to(outside, target_is_directory=True)
    assert_code("storage_unconfirmed", lambda: store.put_verified(scope, PDF))
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_nonregular_existing_document_is_not_followed_or_blocking(tmp_path, kind):
    scope = scope_for()
    store = LocalVendorArtifactStore(tmp_path / "private")
    target = path_for(tmp_path / "private", scope)
    target.parent.mkdir(parents=True)
    if kind == "symlink":
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(PDF)
        target.symlink_to(outside)
        expected = "storage_unavailable"
    else:
        os.mkfifo(target)
        expected = "artifact_changed"
    assert_code(expected, lambda: store.read_verified(scope))


class Blob:
    def __init__(self):
        self.data = None
        self.calls = []
        self.downloaded = None
        self.raise_after_put = False
        self.changed_during_read = False

    def upload_blob(self, data, **kwargs):
        self.calls.append(("put", kwargs))
        if self.data is not None:
            raise ResourceExistsError("private destination identifier")
        self.data = data
        if self.raise_after_put:
            raise RuntimeError("private credential in an SDK exception")

    def get_blob_properties(self, **kwargs):
        self.calls.append(("properties", kwargs))
        if self.data is None:
            raise ResourceNotFoundError("private destination identifier")
        return SimpleNamespace(size=len(self.data), etag='"version-1"')

    def download_blob(self, **kwargs):
        self.calls.append(("get", kwargs))
        if self.changed_during_read:
            raise ResourceModifiedError("private ETag")
        data = self.data if self.downloaded is None else self.downloaded
        return SimpleNamespace(chunks=lambda: iter([data]))


class Container(BoundedAzureArtifactContainer):
    def __init__(self):
        self.blobs = {}
        self.names = []

    def get_blob_client(self, name):
        self.names.append(name)
        return self.blobs.setdefault(name, Blob())

    def deadline(self):
        return time.monotonic() + 60

    def operation(self, kind, name, length, *, deadline):
        return nullcontext()


def azure_case():
    scope = scope_for()
    container = Container()
    store = AzureVendorArtifactStore(container, box_id=scope.box_id)
    blob = container.get_blob_client("/".join(scope.storage_segments()))
    container.names.clear()
    return scope, container, store, blob


def test_azure_exact_retry_uses_exclusive_upload_then_versioned_bounded_read():
    scope, _, store, blob = azure_case()
    store.put_verified(scope, PDF)
    store.put_verified(scope, PDF)
    assert store.read_verified(scope) == PDF
    for kind, kwargs in blob.calls:
        assert kwargs["retry_total"] == 0
        if kind == "put":
            assert kwargs["overwrite"] is False
            assert kwargs["length"] == len(PDF)
            assert kwargs["content_settings"].content_type == "application/pdf"
        if kind == "get":
            assert kwargs["offset"] == 0
            assert kwargs["length"] == len(PDF) + 1
            assert kwargs["max_concurrency"] == 1
            assert kwargs["etag"] == '"version-1"'


def test_azure_unknown_write_preserves_exact_read_recovery_and_safe_error():
    scope, _, store, blob = azure_case()
    blob.raise_after_put = True
    assert_code("storage_unconfirmed", lambda: store.put_verified(scope, PDF))
    assert store.read_verified(scope) == PDF
    assert [kind for kind, _ in blob.calls].count("put") == 1


@pytest.mark.parametrize("kind", ["read", "put"])
def test_azure_sdk_success_after_deadline_never_returns_late_success(kind, monkeypatch):
    scope, container, store, blob = azure_case()
    clock = [99.0]
    monkeypatch.setattr(container, "deadline", lambda: 100.0)
    monkeypatch.setattr(artifact_adapters, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    method = "download_blob" if kind == "read" else "upload_blob"
    original = getattr(blob, method)

    def late(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = 101.0
        return result

    monkeypatch.setattr(blob, method, late)
    if kind == "read":
        blob.data = PDF
        assert_code("storage_unavailable", lambda: store.read_verified(scope))
    else:
        assert_code("storage_unconfirmed", lambda: store.put_verified(scope, PDF))
        assert blob.data == PDF
        assert [name for name, _ in blob.calls] == ["put"]


def test_azure_scope_and_content_fail_before_client_access():
    scope, container, store, _ = azure_case()
    assert_code("artifact_changed", lambda: store.put_verified(scope, b"private bad body"))
    other = scope.model_copy(update={"box_id": uuid4()})
    assert_code("artifact_changed", lambda: store.read_verified(other))
    assert container.names == []


def test_azure_conflict_never_overwrites_prior_bytes():
    scope, _, store, blob = azure_case()
    blob.data = b"%PDF-prior content"
    assert_code("artifact_changed", lambda: store.put_verified(scope, PDF))
    assert blob.data == b"%PDF-prior content"
    assert [kind for kind, _ in blob.calls] == ["put", "properties"]


def test_azure_not_found_and_version_change_are_distinct():
    scope, _, store, blob = azure_case()
    assert_code("artifact_not_found", lambda: store.read_verified(scope))
    blob.data = PDF
    blob.changed_during_read = True
    assert_code("artifact_changed", lambda: store.read_verified(scope))


@pytest.mark.parametrize("body", [PDF + b"x", PDF[:-1], b"x" * len(PDF), b"x" * (len(PDF) + 2)])
def test_azure_download_corruption_is_never_returned(body):
    scope, _, store, blob = azure_case()
    blob.data, blob.downloaded = PDF, body
    assert_code("artifact_changed", lambda: store.read_verified(scope))


def test_scope_repr_hides_private_identifiers():
    scope = scope_for()
    assert repr(scope) == "VendorArtifactScope(<protected>)"
    assert str(scope.document) == "DocumentBinding(<protected>)"


@pytest.mark.parametrize("size", [len(PDF), 8_388_608])
def test_actual_azure_sdk_exclusive_round_trip_over_loopback(size):
    """Actual SDK/range HTTP; invented in-memory server, never Azure acceptance."""
    data = PDF + b" " * (size - len(PDF))
    scope = scope_for(data)
    objects = {}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, code, body=b"", *, length=None, headers=None):
            self.send_response(code)
            self.send_header("Content-Length", str(len(body) if length is None else length))
            self.send_header("ETag", '"local-version-1"')
            self.send_header("Last-Modified", "Mon, 21 Sep 2026 12:00:00 GMT")
            self.send_header("x-ms-blob-type", "BlockBlob")
            self.send_header("x-ms-request-id", str(uuid4()))
            for name, value in (headers or {}).items():
                self.send_header(name, str(value))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_PUT(self):
            length = int(self.headers.get("Content-Length", "0"))
            requests.append(("PUT", self.path, dict(self.headers)))
            assert length == size and length <= 8_388_608
            body = self.rfile.read(length)
            assert body == data
            assert self.headers.get("If-None-Match") == "*"
            if self.path in objects:
                self.respond(409, headers={"x-ms-error-code": "BlobAlreadyExists"})
            else:
                objects[self.path] = body
                self.respond(201)

        def do_HEAD(self):
            requests.append(("HEAD", self.path, dict(self.headers)))
            if self.path not in objects:
                self.respond(404, headers={"x-ms-error-code": "BlobNotFound"})
            else:
                self.respond(200, length=len(objects[self.path]))

        def do_GET(self):
            requests.append(("GET", self.path, dict(self.headers)))
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("x-ms-range", ""))
            assert match is not None
            start, end = map(int, match.groups())
            assert 0 <= start <= end <= size
            assert self.headers.get("If-Match") == '"local-version-1"'
            body = objects[self.path][start:end + 1]
            self.respond(206, body, headers={"Content-Range": f"bytes {start}-{start + len(body) - 1}/{size}"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = BoundedAzureArtifactContainer(account_url=f"http://127.0.0.1:{server.server_port}/localaccount",
        container_name="synthetic-documents", credential=None)
    try:
        store = AzureVendorArtifactStore(client, box_id=scope.box_id)
        store.put_verified(scope, data)
        store.put_verified(scope, data)
        assert store.read_verified(scope) == data
        assert len(objects) == 1
        assert [kind for kind, _, _ in requests] == ["PUT", "PUT", "HEAD", "GET", "HEAD", "GET"]
        assert all("Authorization" not in headers for _, _, headers in requests)
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
