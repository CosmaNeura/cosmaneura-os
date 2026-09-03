from __future__ import annotations

import secrets
from typing import Any

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from cosmas_os.ports import BlobRepresentationAbsence

_RECOVERABLE_REPRESENTATIONS = [
    "deleted",
    "deletedwithversions",
    "snapshots",
    "versions",
]


class AzureBlobAdapter:
    """Managed-identity BlobPort adapter confined to one Box prefix."""

    def __init__(self, container_client: Any, *, box_id: str) -> None:
        self._container = container_client
        self._box_id = box_id
        self._tokens: dict[str, str] = {}

    @classmethod
    def from_managed_identity(
        cls,
        *,
        account_url: str,
        container_name: str,
        box_id: str,
    ) -> AzureBlobAdapter:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        service = BlobServiceClient(account_url=account_url, credential=credential)
        return cls(service.get_container_client(container_name), box_id=box_id)

    @classmethod
    def from_user_assigned_managed_identity(
        cls,
        *,
        account_url: str,
        container_name: str,
        box_id: str,
        client_id: str,
    ) -> AzureBlobAdapter:
        """Use only the explicitly selected user-assigned managed identity."""

        credential = ManagedIdentityCredential(client_id=client_id)
        service = BlobServiceClient(account_url=account_url, credential=credential)
        return cls(service.get_container_client(container_name), box_id=box_id)

    def _blob_name(self, key: str) -> str:
        segments = key.split("/")
        if (
            not key
            or key.startswith("/")
            or any(segment in {"", ".", ".."} for segment in segments)
            or segments[0] != self._box_id
        ):
            raise ValueError("blob key is outside the configured Box")
        return key

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        blob_name = self._blob_name(key)
        blob = self._container.get_blob_client(blob_name)
        blob.upload_blob(
            data,
            overwrite=False,
            content_settings=ContentSettings(content_type=content_type),
        )
        return blob_name

    def get_bytes(self, key: str) -> bytes:
        blob = self._container.get_blob_client(self._blob_name(key))
        return bytes(blob.download_blob().readall())

    def delete(self, key: str) -> None:
        blob_name = self._blob_name(key)
        blob = self._container.get_blob_client(blob_name)
        try:
            blob.delete_blob(delete_snapshots="include")
        except ResourceNotFoundError:
            pass
        if not self.probe_recoverable_absence(blob_name).verified:
            raise RuntimeError("blob recoverable-absence verification failed")

    @staticmethod
    def _representation_property(representation: Any, name: str) -> Any:
        if isinstance(representation, dict):
            return representation.get(name)
        return getattr(representation, name, None)

    def probe_recoverable_absence(self, key: str) -> BlobRepresentationAbsence:
        """Prove exact-key absence across current and recoverable Azure representations."""

        blob_name = self._blob_name(key)
        current_absent = True
        versions_absent = True
        snapshots_absent = True
        deleted_absent = True
        for representation in self._container.list_blobs(
            name_starts_with=blob_name,
            include=_RECOVERABLE_REPRESENTATIONS,
        ):
            if self._representation_property(representation, "name") != blob_name:
                continue
            deleted = self._representation_property(representation, "deleted") is True
            version_id = self._representation_property(representation, "version_id")
            snapshot = self._representation_property(representation, "snapshot")
            is_current_version = self._representation_property(
                representation,
                "is_current_version",
            )

            if deleted:
                deleted_absent = False
            if version_id is not None:
                versions_absent = False
            if snapshot is not None:
                snapshots_absent = False
            if (
                not deleted
                and snapshot is None
                and (version_id is None or is_current_version is True)
            ):
                current_absent = False

        return BlobRepresentationAbsence(
            current_absent=current_absent,
            versions_absent=versions_absent,
            snapshots_absent=snapshots_absent,
            deleted_absent=deleted_absent,
        )

    def issue_upload_token(self, artifact_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = artifact_id
        return token

    def consume_upload_token(self, token: str) -> str:
        try:
            return self._tokens.pop(token)
        except KeyError as exc:
            raise KeyError("invalid upload token") from exc
