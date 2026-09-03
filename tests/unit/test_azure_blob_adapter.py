from __future__ import annotations

from dataclasses import dataclass

import pytest
from azure.core.exceptions import ResourceNotFoundError

from cosmas_os.adapters import azure as azure_adapter
from cosmas_os.adapters.azure import AzureBlobAdapter


@dataclass
class Download:
    value: bytes

    def readall(self) -> bytes:
        return self.value


class FakeBlob:
    def __init__(self, store: dict[str, bytes], name: str) -> None:
        self.store = store
        self.name = name

    def upload_blob(self, value: bytes, **kwargs) -> None:
        assert kwargs["overwrite"] is False
        assert kwargs["content_settings"].content_type == "image/png"
        if self.name in self.store:
            raise RuntimeError("duplicate")
        self.store[self.name] = value

    def download_blob(self) -> Download:
        return Download(self.store[self.name])

    def delete_blob(self, **kwargs) -> None:
        assert kwargs["delete_snapshots"] == "include"
        self.store.pop(self.name)


class FakeContainer:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.representations: list[dict[str, object]] = []
        self.list_calls: list[dict[str, object]] = []

    def get_blob_client(self, name: str) -> FakeBlob:
        return FakeBlob(self.store, name)

    def list_blobs(self, **kwargs) -> list[dict[str, object]]:
        self.list_calls.append(kwargs)
        current = [{"name": name, "deleted": False} for name in self.store]
        return [*current, *self.representations]


def test_azure_blob_adapter_confines_objects_to_box_prefix() -> None:
    container = FakeContainer()
    adapter = AzureBlobAdapter(container, box_id="box-a")
    key = "box-a/artifact-1/front.png"
    assert adapter.put_bytes(key, b"image", "image/png") == key
    assert adapter.get_bytes(key) == b"image"
    adapter.delete(key)
    assert container.store == {}
    assert container.list_calls == [
        {
            "name_starts_with": key,
            "include": ["deleted", "deletedwithversions", "snapshots", "versions"],
        }
    ]

    for invalid in (
        "box-b/artifact-1/front.png",
        "/box-a/artifact-1/front.png",
        "box-a/../box-b/front.png",
    ):
        with pytest.raises(ValueError, match="outside"):
            adapter.put_bytes(invalid, b"image", "image/png")


def test_recoverable_absence_probe_ignores_prefix_collisions() -> None:
    container = FakeContainer()
    key = "box-a/artifact-1/front.png"
    container.representations = [
        {"name": f"{key}.other", "deleted": True, "version_id": "version-1"},
    ]
    adapter = AzureBlobAdapter(container, box_id="box-a")

    proof = adapter.probe_recoverable_absence(key)

    assert proof.verified is True
    assert proof.current_absent is True
    assert proof.versions_absent is True
    assert proof.snapshots_absent is True
    assert proof.deleted_absent is True


def test_recoverable_absence_probe_rejects_cross_box_key_before_listing() -> None:
    container = FakeContainer()
    adapter = AzureBlobAdapter(container, box_id="box-a")

    with pytest.raises(ValueError, match="outside"):
        adapter.probe_recoverable_absence("box-b/item.bin")

    assert container.list_calls == []


@pytest.mark.parametrize(
    ("representation", "failed_property"),
    [
        ({"name": "box-a/item.bin", "deleted": False}, "current_absent"),
        (
            {
                "name": "box-a/item.bin",
                "deleted": False,
                "version_id": "version-1",
                "is_current_version": False,
            },
            "versions_absent",
        ),
        (
            {
                "name": "box-a/item.bin",
                "deleted": False,
                "snapshot": "2026-09-03T00:00:00Z",
            },
            "snapshots_absent",
        ),
        ({"name": "box-a/item.bin", "deleted": True}, "deleted_absent"),
    ],
)
def test_recoverable_absence_probe_rejects_each_exact_key_representation(
    representation: dict[str, object],
    failed_property: str,
) -> None:
    container = FakeContainer()
    container.representations = [representation]
    adapter = AzureBlobAdapter(container, box_id="box-a")

    proof = adapter.probe_recoverable_absence("box-a/item.bin")

    assert proof.verified is False
    assert getattr(proof, failed_property) is False


def test_delete_fails_closed_when_a_recoverable_representation_remains() -> None:
    container = FakeContainer()
    key = "box-a/item.bin"
    container.store[key] = b"synthetic"
    container.representations = [{"name": key, "deleted": True}]
    adapter = AzureBlobAdapter(container, box_id="box-a")

    with pytest.raises(RuntimeError, match="recoverable-absence verification failed"):
        adapter.delete(key)


def test_delete_retry_accepts_not_found_only_after_exact_absence_proof() -> None:
    container = FakeContainer()
    key = "box-a/item.bin"

    class MissingBlob(FakeBlob):
        def delete_blob(self, **kwargs) -> None:
            assert kwargs["delete_snapshots"] == "include"
            raise ResourceNotFoundError("already absent")

    container.get_blob_client = lambda name: MissingBlob(container.store, name)  # type: ignore[method-assign]
    adapter = AzureBlobAdapter(container, box_id="box-a")

    adapter.delete(key)

    assert container.list_calls[0]["name_starts_with"] == key


def test_delete_does_not_swallow_non_not_found_provider_error() -> None:
    container = FakeContainer()

    class FailingBlob(FakeBlob):
        def delete_blob(self, **kwargs) -> None:
            assert kwargs["delete_snapshots"] == "include"
            raise RuntimeError("provider unavailable")

    container.get_blob_client = lambda name: FailingBlob(container.store, name)  # type: ignore[method-assign]
    adapter = AzureBlobAdapter(container, box_id="box-a")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        adapter.delete("box-a/item.bin")

    assert container.list_calls == []


def test_azure_blob_adapter_upload_token_is_single_use() -> None:
    adapter = AzureBlobAdapter(FakeContainer(), box_id="box-a")
    token = adapter.issue_upload_token("artifact-1")
    assert adapter.consume_upload_token(token) == "artifact-1"
    with pytest.raises(KeyError, match="invalid upload token"):
        adapter.consume_upload_token(token)


def test_user_assigned_factory_selects_exact_managed_identity_client_id(monkeypatch) -> None:
    client_id = "11111111-1111-4111-8111-111111111111"
    credential = object()
    container = FakeContainer()
    captured: dict[str, object] = {}

    def managed_identity_credential(*, client_id: str):
        captured["client_id"] = client_id
        return credential

    class BlobService:
        def __init__(self, *, account_url: str, credential: object) -> None:
            captured["account_url"] = account_url
            captured["credential"] = credential

        def get_container_client(self, container_name: str) -> FakeContainer:
            captured["container_name"] = container_name
            return container

    monkeypatch.setattr(azure_adapter, "ManagedIdentityCredential", managed_identity_credential)
    monkeypatch.setattr(azure_adapter, "BlobServiceClient", BlobService)

    adapter = AzureBlobAdapter.from_user_assigned_managed_identity(
        account_url="https://storage.example.invalid",
        container_name="box-artifacts",
        box_id="box-a",
        client_id=client_id,
    )

    assert captured == {
        "client_id": client_id,
        "account_url": "https://storage.example.invalid",
        "credential": credential,
        "container_name": "box-artifacts",
    }
    assert adapter.put_bytes("box-a/probe/item.bin", b"synthetic", "image/png") == (
        "box-a/probe/item.bin"
    )
