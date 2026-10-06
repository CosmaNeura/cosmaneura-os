"""Actual socket bytes to owned recipient; no external provider/account."""
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from lab.completed_action_sandbox import (
    SYNTHETIC_CREDENTIAL,
    CompletedActionSandbox,
    SandboxVendorTransport,
    digest,
)

from cosmas_os.adapters.vendor_connectors.spruce import SpruceConnector
from cosmas_os.adapters.vendor_connectors.transport import Credential, VendorRuntime
from cosmas_os.ports.vendor_connectors import (
    ApprovalBinding,
    ConnectionSelection,
    ProviderReference,
    SpruceMessageIntent,
    VendorCommand,
)


@pytest.mark.asyncio
async def test_real_connector_socket_acceptance_distinct_recipient_receipt_and_status(tmp_path):
    sandbox = CompletedActionSandbox(tmp_path / "owned-receiver")
    origin = sandbox.start()
    selected = ConnectionSelection(vendor="spruce", connection_id=uuid4(), box_id=uuid4(), owner_id=uuid4(),
        environment="production", remote_account_id="invented_account", credential_ref=str(uuid4()),
        configuration_sha256="a" * 64)
    command = VendorCommand(operation_id=uuid4(), revision_id=uuid4(), selection=selected,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        intent=SpruceMessageIntent(internal_endpoint_id="invented_endpoint",
            destination={"channel": "secure", "contact_id": "virtual_patient_private_inbox"},
            text="Please confirm the next visit date with the virtual coordinator."))
    approval = ApprovalBinding(operation_id=command.operation_id, revision_id=command.revision_id,
        action=command.intent.kind, approved_payload_sha256=command.commitment(), selection_sha256=selected.commitment(),
        expires_at=command.expires_at)

    async def credentials(selection):
        return Credential(selection_sha256=selection.commitment(), credential_ref=str(selection.credential_ref),
                          secret=SYNTHETIC_CREDENTIAL)

    async def authorize(*_):
        return True

    connector = SpruceConnector(VendorRuntime(selected, credentials, enabled=True, authorize=authorize,
                                             transport=SandboxVendorTransport(origin)))
    try:
        submitted = await connector.submit(command, approval)
        assert submitted.state == "accepted" and submitted.reference.kind == "async_request"
        receipt = sandbox.receipt(str(command.operation_id))
        assert receipt["state"] == "received" and receipt["sha256"] == digest({k:v for k,v in receipt.items() if k != "sha256"})
        assert receipt["content_sha256"] == hashlib.sha256(command.intent.text.encode()).hexdigest()
        reference = ProviderReference(**{**submitted.reference.model_dump(mode="python"),
            "kind": "conversation_item", "value": receipt["item_id"], "request_id": receipt["request_id"]})
        observed = await connector.observe(command, reference)
        # Documented Spruce read proves posting, not transport/patient delivery.
        assert observed.state == "pending" and sandbox.counters() == {"submission_requests": 1, "receiver_items": 1, "status_reads": 1}
    finally:
        sandbox.close()
    assert (tmp_path / "owned-receiver/CLEANUP.json").exists()
