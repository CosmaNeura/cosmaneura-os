"""Metadata-only boundary and closed model-tool contracts, no database required."""

from types import SimpleNamespace

import pytest
from lab.inbox_tools import INBOX_SCHEMAS, INBOX_TOOL_ROLES
from pydantic import ValidationError

from cosmas_os.adapters.google_inbox import GoogleInboxMetadata


def observed(**changes):
    return {"kind": "mail", "account": {"label": "Synthetic owner", "email": "owner@example.invalid"},
        "items": [{"id": "invented1", "subject": "Synthetic administrative request", "sender": "sender@example.invalid",
                   "received_at": "2026-10-01T10:00:00+00:00", "is_read": False}],
        "more": False, "observed_at": "2026-10-01T10:01:00+00:00", **changes}


def test_adapter_calls_existing_selected_google_mail_only():
    calls = []
    identity = object()
    service = SimpleNamespace(provider="google", mail=lambda actor: calls.append(actor) or observed())
    result = GoogleInboxMetadata(service, identity).read()
    assert calls == [identity]
    assert result["metadata_only"] and result["incomplete_message"]
    assert result["classification"] == "needs_human" and result["clinical_priority"] is None
    assert result["provider_revision"] is None and len(result["source_sha256"]) == 64
    assert "future permission contract" in result["limits"]
    assert "body" not in result["items"][0] and "attachments" not in result["items"][0]


@pytest.mark.parametrize("change", [
    {"items": observed()["items"] * 2},
    {"items": [{**observed()["items"][0], "body": "invented but unauthorized"}]},
    {"items": [{**observed()["items"][0], "id": "../arbitrary"}]},
    {"observed_at": "2026-10-01T10:01:00"},
])
def test_metadata_adapter_rejects_expanded_or_ambiguous_observation(change):
    service = SimpleNamespace(provider="google", mail=lambda actor: observed(**change))
    with pytest.raises((ValueError, ValidationError)):
        GoogleInboxMetadata(service, object()).read()


def test_adapter_refuses_other_provider():
    with pytest.raises(ValueError, match="google_account_required"):
        GoogleInboxMetadata(SimpleNamespace(provider="microsoft"), object())


@pytest.mark.parametrize("name", sorted(INBOX_SCHEMAS))
def test_all_model_contracts_closed_without_human_or_body_authority(name):
    schema = INBOX_SCHEMAS[name][0].model_json_schema()
    assert schema["additionalProperties"] is False
    assert not {"actor_id", "recipient_id", "approve", "send", "body", "query", "scope"}.intersection(schema["properties"])
    assert INBOX_TOOL_ROLES[name] == {"chief", "follow_up"}


@pytest.mark.parametrize("name,args", [
    ("google_inbox_read_headers", {"idempotency_key": "read"}),
    ("google_inbox_select_message", {"read_key": "read", "message_id": "invented1", "expected_workspace_revision": 2, "idempotency_key": "select"}),
    ("google_inbox_prepare_review", {"selection_key": "select", "expected_workspace_revision": 3, "idempotency_key": "review"}),
    ("google_inbox_review_status", {"review_key": "review"}),
    ("google_inbox_list_reviews", {}),
])
def test_actor_override_rejected(name, args):
    with pytest.raises(ValidationError):
        INBOX_SCHEMAS[name][0].model_validate({**args, "actor_id": "invented-human"})
