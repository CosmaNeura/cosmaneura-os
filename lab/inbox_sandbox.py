"""Real Spruce inbox adapter, durable source ordering and human review, offline."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.adapters.vendor_connectors.spruce_inbox import SpruceInboxConnector
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.api import inbox_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import inbox_work as inbox
from cosmas_os.application import workspace
from cosmas_os.inbox_models import InboxSource
from cosmas_os.models import EncounterWorkspace, Operation
from cosmas_os.ports.vendor_connectors import ConnectionSelection, digest
from cosmas_os.ports.vendor_inbox import SpruceInboxParticipant, SpruceInboxReadBinding
from cosmas_os.vendor_models import VendorConnectionVersion, VendorCorrespondenceVersion
from lab.store import LabError


def exercise_inbox(app):
    now, cid, coid = datetime.now(UTC), str(uuid4()), str(uuid4())
    selection = ConnectionSelection(vendor="spruce", connection_id=cid, box_id=app.box, owner_id=app.owner,
        environment="production", remote_account_id="synthetic-practice", credential_ref=uuid4(), configuration_sha256="a" * 64)
    cv = dict(id=cid, revision=1, vendor="spruce", environment="production", label="Synthetic secure inbox",
        actions=["spruce_secure_message"], availability="enabled")
    cv["public_sha256"] = public.public_digest("cosmas-vendor-public-selection.v1", cv)
    expiry = now + timedelta(days=1)
    co = dict(id=coid, revision=1, connection_id=cid, channel="secure", recipient_label="Synthetic Jordan",
        destination_display="Reviewed synthetic secure contact", permission="reviewed", expires_at=public.timestamp(expiry))
    co["public_sha256"] = public.public_digest("cosmas-vendor-public-selection.v1", co)
    proof = dict(destination={"channel": "secure", "contact_id": "synthetic-contact"}, permission_sha256="b" * 64,
        patient_mapping_sha256="c" * 64, practice_mapping_sha256="d" * 64, recipient_mapping_sha256="e" * 64)
    proof_hash = digest("cosmas-vendor-correspondence.v1", proof)
    with Session(app.engine) as s:
        patient = s.get(EncounterWorkspace, app.workspace).patient_link_id
        s.add(VendorConnectionVersion(id=cid, family_id=str(uuid4()), revision=1, box_id=app.box, owner_id=app.owner,
            vendor="spruce", environment="production", private_selection=selection.model_dump(mode="json"),
            routing={"internal_endpoint_id": "synthetic-endpoint", "event_route_id": str(uuid4())}, private_sha256=selection.commitment(),
            public_view=cv, public_sha256=cv["public_sha256"], reviewed_by=app.owner, reviewed_at=now,
            write_enabled=False, read_enabled=False))
        s.flush()
        s.add(VendorCorrespondenceVersion(id=coid, family_id=str(uuid4()), revision=1, box_id=app.box, owner_id=app.owner,
            patient_link_id=patient, connection_version_id=cid, private_proof=proof, private_sha256=proof_hash,
            public_view=co, public_sha256=co["public_sha256"], reviewed_by=app.owner, reviewed_at=now, expires_at=expiry))
        s.commit()
    binding = SpruceInboxReadBinding(selection=selection, patient_link_id=patient, correspondence_version_id=coid,
        correspondence_sha256=proof_hash, contact_id="synthetic-contact", conversation_id="synthetic-thread",
        item_id="synthetic-message", secure_endpoint_raw_value="spruce://synthetic-reviewed",
        permitted_participants=(SpruceInboxParticipant(contact_id="synthetic-contact", relationship="patient"),))
    grant = inbox.InboxReadGrant(grant_id=uuid4(), binding=binding, label="Synthetic reviewed incoming item",
        reviewed_by=app.owner, review_reference="lab:inbound-source", reviewed_inbox_read=True,
        reviewed_at=now - timedelta(seconds=1), expires_at=expiry, correspondence_public_sha256=co["public_sha256"])
    def registry():
        return inbox.InboxRegistry([grant])
    policy = inbox.InboxPolicy(True)
    fixture, calls = {"offset": 0, "attachments": False}, []

    async def authorize(chosen):
        with Session(app.engine) as s:
            inbox.authorize_read(s, grant, registry=registry, policy=policy)
        return chosen == binding

    async def credentials(chosen):
        return Credential(selection_sha256=chosen.commitment(), credential_ref=str(chosen.credential_ref),
            secret=SecretStr("synthetic-not-a-credential"))

    def respond(request):
        if request.method != "GET" or request.url.host != "api.sprucehealth.com":
            raise LabError("unexpected_inbox_route")
        calls.append(request.url.path)
        if request.url.path == "/v1/conversationItems/synthetic-message":
            value = {"conversationItem": {"id": binding.item_id, "conversationId": binding.conversation_id,
                "direction": "inbound", "isInternalNote": False, "author": {"id": binding.contact_id},
                "text": "SYNTHETIC appointment question " + str(fixture["offset"]),
                "createdAt": public.timestamp(now - timedelta(hours=1)),
                "modifiedAt": public.timestamp(now + timedelta(seconds=fixture["offset"])),
                "attachments": [{"type": "document", "url": "https://not-fetched.invalid/attachment"}] if fixture["attachments"] else [],
                "pages": [], "buttons": []}}
        elif request.url.path == "/v1/conversations/synthetic-thread":
            value = {"conversation": {"id": binding.conversation_id, "type": "secure", "archived": False, "isReadOnly": False,
                "externalParticipants": [{"contact": binding.contact_id}], "internalEndpoint": {"id": "synthetic-endpoint",
                    "channel": "secure", "rawValue": binding.secure_endpoint_raw_value, "isInternal": True}}}
        else:
            raise LabError("unexpected_inbox_route")
        return httpx.Response(200, json=value)

    connector = SpruceInboxConnector(selection, credentials, enabled=True, authorize=authorize, transport=httpx.MockTransport(respond))

    def arrive(s, key):
        # Do not retain the preceding read's owner lock while the connector
        # independently reauthorizes in another database session.
        s.commit()
        value = asyncio.run(connector.read(binding))
        return inbox.ingest(s, grant, value, key, registry=registry, policy=policy), value

    def detail(s, item):
        return inbox.detail(s, app.box, app.owner, item, registry=registry, policy=policy)

    def command(s, item, kind, **values):
        summary = detail(s, item)["summary"]
        q = schema.COMMANDS[kind].model_validate(dict(item_id=item, expected_version=summary["version"],
            source_id=summary["source_id"], source_sha256=summary["source_sha256"], idempotency_key="lab-" + kind, **values))
        result = inbox.command(s, app.box, app.owner, item, kind, q, registry=registry, policy=policy)
        replay = inbox.command(s, app.box, app.owner, item, kind, q, registry=registry, policy=policy)
        if result != replay:
            raise LabError("inbox_command_replay_changed")
        return result

    with Session(app.engine) as s:
        first, value = arrive(s, "lab-first")
        iid = first["item_id"]
        checks = {"same_read_receipt_replayed": inbox.ingest(s, grant, value, "lab-first", registry=registry, policy=policy) == first}
        fixture["offset"] = -10
        older, _ = arrive(s, "lab-older")
        checks["older_source_not_current"] = older["outcome"] == "older" and detail(s, iid)["summary"]["source_id"] == first["source_id"]
        fixture.update(offset=10, attachments=True)
        arrive(s, "lab-attachment")
        checks["attachment_requires_human"] = detail(s, iid)["summary"]["state"] == "needs_human" and detail(s, iid)["source"]["attachments"]
        fixture.update(offset=20, attachments=False)
        latest, _ = arrive(s, "lab-readable")
        revision = workspace.read(s, app.box, app.owner, app.workspace)["revision"]
        reviewed = command(s, iid, "review", workspace_id=app.workspace, expected_workspace_revision=revision,
            patient_link_id=patient, reviewed_patient=True, reviewed_exact_thread=True, reviewed_untrusted_source=True)
        triage = command(s, iid, "triage", classification="administrative_review", due_date=now.date().isoformat(),
            instructions="SYNTHETIC human requests internal appointment review only.", human_disposition_required=True)
        result = command(s, iid, "result", triage_receipt_id=triage["receipt_id"], triage_receipt_sha256=triage["receipt_sha256"],
            disposition="local_review_complete", evidence="SYNTHETIC owner reviewed the administrative question.", no_external_action_claimed=True)
        verified = command(s, iid, "verify", result_receipt_id=result["receipt_id"], result_receipt_sha256=result["receipt_sha256"],
            reviewed_patient=True, reviewed_exact_source=True, reviewed_human_result=True, confirm_local_review_only=True)
        checks["exact_review_chain_recorded"] = all(r["outcome"] == "recorded" for r in (reviewed, triage, result, verified))
        checks["local_review_closed"] = detail(s, iid)["summary"]["state"] == "closed_local_review"
        checks["no_external_operation"] = s.scalar(select(func.count()).select_from(Operation).where(Operation.box_id == app.box)) == 0
        source_count = s.scalar(select(func.count()).select_from(InboxSource).where(InboxSource.item_id == iid))
    app.engine.dispose()
    with Session(app.engine) as s:
        current = detail(s, iid)["summary"]
        checks["reopened_exact_source"] = current["source_id"] == latest["source_id"] and current["state"] == "closed_local_review"
    return {"scenario": "inbound.spruce_source_review", "provider": "spruce", "passed": all(checks.values()),
        "checks": checks, "source_versions": source_count, "provider_reads": len(calls), "external_actions": 0,
        "coverage": "actual inbox adapter/service; synthetic human review; attachments flagged, never fetched"}
