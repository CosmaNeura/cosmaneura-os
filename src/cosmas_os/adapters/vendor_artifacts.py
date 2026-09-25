"""Exclusive vendor document stores; no implicit live client or credentials."""

import math
import os
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from azure.core import MatchConditions
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)
from azure.storage.blob import ContentSettings

from cosmas_os.adapters.vendor_artifact_transport import BoundedAzureArtifactContainer
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError, VendorArtifactScope

_CHUNK = 65_536
_AZURE_IO = {"timeout": 30, "connection_timeout": 5, "read_timeout": 30, "retry_total": 0}


def _absolute_deadline(value: float | None, maximum: float) -> float:
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ArtifactStoreError("storage_unavailable")
    result = maximum if value is None else min(value, maximum)
    _before_io(result)
    return result


def _before_io(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ArtifactStoreError("storage_unavailable")


class LocalVendorArtifactStore:
    """Atomic exclusive publication in a configured private local directory.

    Staging files are private and never addressed by the application. A crash
    before linking may leave an orphan stage, but cannot publish a partial PDF.
    Existing objects and older stages are never deleted during recovery.
    """

    def __init__(self, root: str | Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def _directory(self, scope: VendorArtifactScope, *, create: bool, deadline: float) -> Iterator[int]:
        descriptors: list[int] = []
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            _before_io(deadline)
            descriptors.append(os.open(self._root, flags))
            for segment in scope.storage_segments()[:-1]:
                if create:
                    try:
                        _before_io(deadline)
                        os.mkdir(segment, mode=0o700, dir_fd=descriptors[-1])
                        _before_io(deadline)
                        os.fsync(descriptors[-1])
                    except FileExistsError:
                        pass
                _before_io(deadline)
                descriptors.append(os.open(segment, flags, dir_fd=descriptors[-1]))
            yield descriptors[-1]
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    @staticmethod
    def _read(scope: VendorArtifactScope, directory: int, *, deadline: float) -> bytes:
        _before_io(deadline)
        descriptor = os.open(scope.storage_segments()[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            _before_io(deadline)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size != scope.document.byte_length:
                raise ArtifactStoreError("artifact_changed")
            remaining = scope.document.byte_length + 1
            chunks: list[bytes] = []
            while remaining:
                _before_io(deadline)
                chunk = os.read(descriptor, min(_CHUNK, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            scope.require_bytes(data)
            _before_io(deadline)
            return data
        finally:
            os.close(descriptor)

    def read_verified(self, scope: VendorArtifactScope, *, deadline: float | None = None) -> bytes:
        deadline = _absolute_deadline(deadline, time.monotonic() + 60)
        try:
            with self._directory(scope, create=False, deadline=deadline) as directory:
                data = self._read(scope, directory, deadline=deadline)
            _before_io(deadline)
            return data
        except ArtifactStoreError:
            raise
        except FileNotFoundError:
            raise ArtifactStoreError("artifact_not_found") from None
        except OSError:
            raise ArtifactStoreError("storage_unavailable") from None

    def put_verified(self, scope: VendorArtifactScope, data: bytes, *, deadline: float | None = None) -> None:
        deadline = _absolute_deadline(deadline, time.monotonic() + 60)
        scope.require_bytes(data)
        try:
            with self._directory(scope, create=True, deadline=deadline) as directory:
                stage = f".stage-{uuid4()}"
                _before_io(deadline)
                descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600, dir_fd=directory)
                try:
                    try:
                        remaining = memoryview(data)
                        while remaining:
                            _before_io(deadline)
                            written = os.write(descriptor, remaining[:_CHUNK])
                            if written <= 0:
                                raise OSError("write incomplete")
                            remaining = remaining[written:]
                        _before_io(deadline)
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                    try:
                        _before_io(deadline)
                        os.link(stage, scope.storage_segments()[-1], src_dir_fd=directory,
                            dst_dir_fd=directory, follow_symlinks=False)
                    except FileExistsError:
                        self._read(scope, directory, deadline=deadline)
                    _before_io(deadline)
                    os.fsync(directory)
                finally:
                    os.unlink(stage, dir_fd=directory)
                    os.fsync(directory)
            _before_io(deadline)
        except ArtifactStoreError as exc:
            if exc.code == "artifact_changed":
                raise
            raise ArtifactStoreError("storage_unconfirmed") from None
        except OSError:
            # The link may have committed before a durability/cleanup failure.
            raise ArtifactStoreError("storage_unconfirmed") from None


class AzureVendorArtifactStore:
    """Uses an explicitly provisioned container, confined to one Box.

    The container transport caps bytes before SDK buffering, shares a deadline
    and admits each request only once. A current ETag pins the bounded download.
    This adapter has no default Azure
    account, identity discovery, container creation, public URL or delete action.
    """

    def __init__(self, container_client: BoundedAzureArtifactContainer, *, box_id):
        from uuid import UUID

        if not isinstance(container_client, BoundedAzureArtifactContainer):
            raise ArtifactStoreError("storage_unavailable")
        self._container = container_client
        self._box_id = UUID(str(box_id))

    def _blob(self, scope: VendorArtifactScope):
        if scope.box_id != self._box_id:
            raise ArtifactStoreError("artifact_changed")
        return self._container.get_blob_client("/".join(scope.storage_segments()))

    def read_verified(self, scope: VendorArtifactScope, *, deadline: float | None = None) -> bytes:
        return self._read_verified(scope, deadline=_absolute_deadline(deadline, self._container.deadline()))

    def _read_verified(self, scope: VendorArtifactScope, *, deadline: float) -> bytes:
        try:
            _before_io(deadline)
            blob = self._blob(scope)
            with self._container.operation("read", "/".join(scope.storage_segments()),
                    scope.document.byte_length, deadline=deadline):
                properties = blob.get_blob_properties(**_AZURE_IO)
                if type(properties.size) is not int or properties.size != scope.document.byte_length:
                    raise ArtifactStoreError("artifact_changed")
                if not isinstance(properties.etag, str) or not properties.etag:
                    raise ArtifactStoreError("artifact_changed")
                maximum = scope.document.byte_length + 1
                download = blob.download_blob(offset=0, length=maximum, max_concurrency=1,
                    etag=properties.etag, match_condition=MatchConditions.IfNotModified, **_AZURE_IO)
                chunks: list[bytes] = []
                size = 0
                for chunk in download.chunks():
                    if type(chunk) is not bytes or not chunk or len(chunk) > maximum - size:
                        raise ArtifactStoreError("artifact_changed")
                    size += len(chunk)
                    chunks.append(chunk)
                data = b"".join(chunks)
                scope.require_bytes(data)
                if time.monotonic() >= deadline:
                    raise ArtifactStoreError("storage_unavailable")
                return data
        except ArtifactStoreError:
            raise
        except ResourceNotFoundError:
            raise ArtifactStoreError("artifact_not_found") from None
        except ResourceModifiedError:
            raise ArtifactStoreError("artifact_changed") from None
        except Exception:
            raise ArtifactStoreError("storage_unavailable") from None

    def put_verified(self, scope: VendorArtifactScope, data: bytes, *, deadline: float | None = None) -> None:
        scope.require_bytes(data)
        try:
            deadline = _absolute_deadline(deadline, self._container.deadline())
            blob = self._blob(scope)
            with self._container.operation("put", "/".join(scope.storage_segments()),
                    len(data), deadline=deadline):
                blob.upload_blob(data, length=len(data), overwrite=False, max_concurrency=1,
                    validate_content=True, content_settings=ContentSettings(content_type="application/pdf"),
                    **_AZURE_IO)
                if time.monotonic() >= deadline:
                    raise ArtifactStoreError("storage_unconfirmed")
        except ResourceExistsError:
            assert deadline is not None
            self._read_verified(scope, deadline=deadline)
        except ArtifactStoreError as error:
            if error.code == "artifact_changed":
                raise
            # Request timeout or lost reply cannot establish that upload failed.
            raise ArtifactStoreError("storage_unconfirmed") from None
        except Exception:
            raise ArtifactStoreError("storage_unconfirmed") from None
