"""Bounded private observation validation and public custody projections."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cosmas_os.application import microsoft_message as messages


def observation():
    return {
        "kind": "mail",
        "account": {"label": "Invented account", "email": "owner@example.invalid"},
        "items": [
            {
                "id": "invented-id",
                "subject": "Invented request",
                "sender": "sender@example.invalid",
                "received_at": "2026-10-02T12:00:00+00:00",
                "is_read": False,
            }
        ],
        "more": False,
        "observed_at": "2026-10-02T12:01:00+00:00",
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(extra="private"),
        lambda p: p.update(items=None),
        lambda p: p.update(items=[p["items"][0]] * 26),
        lambda p: p.update(more=1),
        lambda p: p.update(observed_at="2026-10-02T12:00:00"),
        lambda p: p["items"][0].update(id="https://outside.invalid/path"),
        lambda p: p["items"].append(p["items"][0]),
        lambda p: p["items"][0].update(body="not metadata"),
        lambda p: p["items"][0].update(is_read="false"),
        lambda p: p["items"][0].update(subject="x" * 999),
    ],
)
def test_observation_rejects_unbounded_or_non_metadata_payload(change):
    payload = observation()
    change(payload)
    with pytest.raises(ValueError):
        messages._list_payload(payload)


def test_empty_list_is_honest_and_twenty_five_is_maximum_contract():
    payload = observation()
    payload["items"] = []
    assert messages._list_payload(payload)["items"] == []
    payload["items"] = [{**observation()["items"][0], "id": f"invented-{i}"} for i in range(25)]
    assert len(messages._list_payload(payload)["items"]) == 25


def test_payload_digest_preserves_exact_unicode_plaintext():
    assert (
        messages._payload_digest({"content": "Invented café"})
        == hashlib.sha256('{"content":"Invented café"}'.encode()).hexdigest()
    )


def test_read_receipt_excludes_private_custody_and_retains_exact_source_hash():
    read = SimpleNamespace(
        id="read", idempotency_key="key", kind="message", observation_id="observation"
    )
    snap = SimpleNamespace(
        source_sha256="a" * 64,
        payload_sha256="b" * 64,
        payload={
            "status": "complete",
            "content": "Exact invented plaintext",
            "custody": {"grant_sha256": "private"},
        },
    )
    result = messages._receipt(read, snap)
    assert set(result) == {
        "read_id",
        "read_key",
        "kind",
        "observation_id",
        "source_sha256",
        "payload_sha256",
        "status",
        "message",
        "observation",
    }
    assert result["message"] == {"status": "complete", "content": "Exact invented plaintext"}
    assert result["source_sha256"] == "a" * 64 and result["observation"] is None


def test_binding_reader_context_restores_previous_reader_on_failure():
    old = messages._binding_reader
    with pytest.raises(RuntimeError), messages.install_binding_reader("synthetic reader"):
        assert messages._binding_reader == "synthetic reader"
        raise RuntimeError("invented failure")
    assert messages._binding_reader is old


def test_source_commitment_binds_selected_request_scope_and_payload():
    read = SimpleNamespace(
        id="read",
        account_id="account",
        ordinal=2,
        request_hash="a" * 64,
        binding_digest="b" * 64,
        grant_sha256="c" * 64,
        connected_at=datetime.now(UTC),
    )
    original = messages._commitment(read, "d" * 64)
    assert original != messages._commitment(read, "e" * 64)
    read.ordinal = 3
    assert original != messages._commitment(read, "d" * 64)
