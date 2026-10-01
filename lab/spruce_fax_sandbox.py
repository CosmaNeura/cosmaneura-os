"""Spruce's two reviewed actions on real services and an offline provider twin.

Spruce's public API proves posting, not fax transmission. None of these
scenarios is a claim that an actual fax was delivered.
"""

import asyncio
import base64
import hashlib
import hmac
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy.orm import sessionmaker

from cosmas_os.adapters.vendor_artifacts import LocalVendorArtifactStore
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.api import vendor_work_schemas as p
from cosmas_os.application import (
    note_review,
    vendor_artifacts,
    vendor_events,
    vendor_execution,
    vendor_work,
    workspace,
)
from cosmas_os.config import settings
from cosmas_os.models import EncounterWorkspace
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.vendor_models import VendorConnectionVersion, VendorCorrespondenceVersion
from lab.fax_sandbox import bound, synthetic_pdf, vendor_gates
from lab.store import LabError

SCENARIOS = ("posted", "upload_reply_lost", "send_reply_lost", "wrong_callback_request",
    "wrong_callback_account", "invalid_signature", "status_reply_lost", "misleading_delivery_fields",
    "altered_source", "contradictory_callback")
SECRET = b"invented-lab-webhook-secret"


def _exact_media_upload(request, pdf):
    """Independently parse MIME; a PDF substring is not an approved upload."""
    content_types = request.headers.get_list("content-type")
    if (len(content_types) != 1 or not content_types[0].isascii()
            or any(c in content_types[0] for c in "\r\n")):
        return False
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_types[0].encode("ascii") + b"\r\n\r\n" + request.content)
    if (message.defects or message.get_content_type() != "multipart/form-data"
            or not message.is_multipart() or not message.get_boundary()
            or message.get_params(header="content-type") != [
                ("multipart/form-data", ""), ("boundary", message.get_boundary())]
            or message.preamble not in (None, "") or message.epilogue not in (None, "")):
        return False
    parts = list(message.iter_parts())
    if len(parts) != 1:
        return False
    part = parts[0]
    return (not part.defects and not part.is_multipart()
        and sorted(key.lower() for key in part.keys()) == ["content-disposition", "content-type"]
        and part.get_params(header="content-disposition") == [
            ("form-data", ""), ("name", "media"), ("filename", "document.pdf")]
        and part.get_params(header="content-type") == [("application/pdf", "")]
        and part.get_payload(decode=True) == pdf)


@contextmanager
def _events_enabled():
    prior = settings.vendor_events_enabled
    try:
        settings.vendor_events_enabled = True
        yield
    finally:
        settings.vendor_events_enabled = prior


def _install(s, app):
    cid, coid, route_id = str(uuid4()), str(uuid4()), str(uuid4())
    selection = private.ConnectionSelection(vendor="spruce", connection_id=UUID(cid), box_id=app.box,
        owner_id=app.owner, environment="production", remote_account_id="entity_invented_lab",
        credential_ref=uuid4(), configuration_sha256="a" * 64)
    cv = {"id": cid, "revision": 1, "vendor": "spruce", "environment": "production",
          "label": "Synthetic Spruce twin", "actions": ["spruce_media_upload", "spruce_fax"],
          "availability": "enabled"}
    cv["public_sha256"] = p.public_digest("cosmas-vendor-public-selection.v1", cv)
    s.add(VendorConnectionVersion(id=cid, family_id=str(uuid4()), revision=1, box_id=app.box,
        owner_id=app.owner, vendor="spruce", environment="production",
        private_selection=selection.model_dump(mode="json"),
        routing={"internal_endpoint_id": "invented_endpoint", "event_route_id": route_id},
        private_sha256=selection.commitment(), public_view=cv, public_sha256=cv["public_sha256"],
        reviewed_by=app.owner, reviewed_at=datetime.now(UTC), write_enabled=True, read_enabled=True))
    s.flush()
    expires = datetime.now(UTC) + timedelta(days=2)
    co = {"id": coid, "revision": 1, "connection_id": cid, "channel": "fax",
          "recipient_label": "Synthetic clinic desk", "destination_display": "Synthetic fax ending 0101",
          "permission": "reviewed", "expires_at": p.timestamp(expires)}
    co["public_sha256"] = p.public_digest("cosmas-vendor-public-selection.v1", co)
    proof = {"destination": {"channel": "fax", "number": "+12125550101"},
             "permission_sha256": "b" * 64, "patient_mapping_sha256": "c" * 64,
             "practice_mapping_sha256": "d" * 64, "recipient_mapping_sha256": "e" * 64}
    s.add(VendorCorrespondenceVersion(id=coid, family_id=str(uuid4()), revision=1,
        box_id=app.box, owner_id=app.owner,
        patient_link_id=s.get(EncounterWorkspace, app.workspace).patient_link_id,
        connection_version_id=cid, private_proof=proof,
        private_sha256=private.digest("cosmas-vendor-correspondence.v1", proof), public_view=co,
        public_sha256=co["public_sha256"], reviewed_by=app.owner, reviewed_at=datetime.now(UTC), expires_at=expires))
    s.commit()
    return selection, cv, co, vendor_events.EventRoute(route_id, cid, "spruce", SECRET, selection)


def _denied(s, checks, name, operation, *args, code=None):
    try:
        operation(s, *args)
    except workspace.WorkspaceError as error:
        s.rollback()
        checks[name] = code is None or str(error) == code
    else:
        raise LabError(name + "_unexpectedly_allowed")


def exercise(app, root, scenario="posted"):
    if scenario not in SCENARIOS:
        raise LabError("unknown_spruce_fax_scenario")
    with vendor_gates(), _events_enabled():
        return _exercise(app, root, scenario)


def _exercise(app, root, scenario):
    checks, calls, stages = {}, [], []
    factory = sessionmaker(app.engine, expire_on_commit=False)
    scope = app.box, app.owner, app.workspace
    store = LocalVendorArtifactStore(root)
    pdf, media_id = synthetic_pdf(), str(uuid4())
    artifact = {"artifact_id": str(uuid4()), "sha256": hashlib.sha256(pdf).hexdigest(),
                "byte_length": len(pdf), "media_type": "application/pdf"}
    with factory() as s:
        snapshot = workspace.read(s, *scope)
        snapshot = note_review.save(s, *scope, expected=snapshot["revision"], key="spruce-note",
            base_note_id=None, source_reply_id=None,
            content="SYNTHETIC ONLY: request administrative confirmation of the next visit.")["workspace"]
        n = snapshot["note"]["latest"]
        snapshot = note_review.review(s, *scope, n["id"], expected=snapshot["revision"], key="spruce-review",
            content_hash=n["content_hash"], source_hash=n["source_fingerprint"])["workspace"]
        source = {"kind": "reviewed_note", "note_id": n["id"], "content_sha256": n["content_hash"],
                  "source_fingerprint": n["source_fingerprint"]}
        selection, cv, co, route = _install(s, app)
        other_route = _install(s, app)[3] if scenario == "wrong_callback_account" else None
        vendor_artifacts.intent(s, *scope, p.VendorArtifactIntent.model_validate({**artifact,
            "source": source, "idempotency_key": "spruce-file-intent"}))
        admission = vendor_artifacts.begin_content(s, *scope, artifact["artifact_id"], "spruce-file-write")
        if admission.token is None:
            raise LabError("artifact_not_admitted")
        outcome = vendor_artifacts.write_content(store, admission.token, pdf)
        vendor_artifacts.settle_in_session(s, admission.token, outcome)
        s.commit()
        checks["verified_pdf_custody"] = outcome == "ready"
        common = {"connection": {k: cv[k] for k in ("id", "revision", "public_sha256")}, "source": source,
                  "due_date": (datetime.now(UTC) + timedelta(days=2)).date().isoformat(),
                  "expected_outcome": "Synthetic clinic desk receives an administrative confirmation request.",
                  "share_to_practice": False}
        proposal = p.VendorProposal.model_validate({**common,
            "expected_workspace_revision": workspace.read(s, *scope)["revision"],
            "idempotency_key": "spruce-upload-proposal", "proposed_operation_id": str(uuid4()),
            "action": "spruce_media_upload", "document": artifact})
        upload_tid = vendor_work.propose(s, *scope, proposal)["effect"]["ticket_id"]
        upload = vendor_work.detail(s, *scope, upload_tid)
        _denied(s, checks, "upload_requires_own_approval", vendor_execution.claim_submit,
            *scope, upload_tid, p.BoundCommand.model_validate(bound(upload, "spruce-upload-too-early")),
            code="vendor_revision_changed")
        decision = p.VendorDecision.model_validate(bound(upload, "spruce-upload-approve",
            review_sha256=upload["review_sha256"], choice="approve"))
        _denied(s, checks, "agent_cannot_approve_upload", vendor_work.decide,
            app.box, app.agent_id("follow_up"), app.workspace, upload_tid, decision)
        vendor_work.decide(s, *scope, upload_tid, decision)
        app.event("simulated_provider", "spruce_upload_exact_approval", ticket_id=upload_tid)
        upload = vendor_work.detail(s, *scope, upload_tid)
        upload_request = p.BoundCommand.model_validate(bound(upload, "spruce-upload-submit"))
        _, invocation = vendor_execution.claim_submit(s, *scope, upload_tid, upload_request)
    if invocation is None:
        raise LabError("spruce_upload_not_admitted")

    async def credentials(chosen):
        if chosen != selection:
            raise LabError("foreign_spruce_selection")
        return Credential(selection_sha256=chosen.commitment(), credential_ref=str(chosen.credential_ref),
                          secret=SecretStr("invented-spruce-lab-secret"))

    async def current():
        app.check_agent("follow_up")
        return True

    async def respond(request):
        if request.url.host != "api.sprucehealth.com" or request.url.scheme != "https" or request.url.query:
            raise LabError("unexpected_spruce_origin")
        authorized = request.headers.get_list("authorization") == ["Bearer invented-spruce-lab-secret"]
        checks["every_request_uses_exact_bound_authorization"] = (
            checks.get("every_request_uses_exact_bound_authorization", True) and authorized)
        if not authorized:
            raise LabError("foreign_spruce_authorization")
        kind = {("POST", "/v1/media"): "upload",
                ("POST", "/v1/internalendpoints/invented_endpoint/conversations"): "submit",
                ("GET", "/v1/conversationItems/ti_invented_lab"): "read"}.get((request.method, request.url.path))
        if kind is None:
            raise LabError("unexpected_spruce_route")
        calls.append({"method": request.method, "path": request.url.path, "action": kind})
        if kind == "upload":
            checks["upload_is_exactly_one_approved_pdf_part"] = _exact_media_upload(request, pdf)
            if not checks["upload_is_exactly_one_approved_pdf_part"]:
                raise LabError("spruce_document_changed")
            if scenario == "upload_reply_lost":
                raise httpx.ReadTimeout("synthetic upload acceptance response lost")
            return httpx.Response(200, json={"id": media_id, "object": "media"})
        if kind == "submit":
            body = json.loads(request.content)
            if body != {"destination": {"faxEndpoint": "+12125550101"}, "message": {
                    "body": [{"type": "text", "value": ""}], "internal": False,
                    "attachments": [{"attachmentId": media_id, "title": "document.pdf"}]}}:
                raise LabError("spruce_exact_fax_changed")
            if scenario == "send_reply_lost":
                raise httpx.ReadTimeout("synthetic fax acceptance response lost")
            return httpx.Response(200, json={"requestId": "asyncRequest_invented_lab"})
        if scenario == "status_reply_lost" and sum(c["action"] == "read" for c in calls) == 1:
            raise httpx.ReadTimeout("synthetic posting-status response lost")
        item = {"id": "ti_invented_lab", "requestId": "asyncRequest_invented_lab",
                "direction": "outbound", "isInternalNote": False}
        if scenario == "misleading_delivery_fields":
            item.update({"status": "delivered", "pages": [{"id": "page_invented", "memberId": "entity_invented", "resolved": True}],
                         "event": {"type": "outboundCall", "data": {"answered": True}}})
        return httpx.Response(200, json={"conversationItem": item})

    executor = vendor_execution.VendorExecution(factory, credentials, artifact_store=store,
        transport=httpx.MockTransport(respond), identity_current=current)
    asyncio.run(executor.invoke(invocation))
    with factory() as s:
        _, duplicate = vendor_execution.claim_submit(s, *scope, upload_tid, upload_request)
        checks["upload_claim_never_dispatches_twice"] = duplicate is None and len(calls) == 1
        upload = vendor_work.detail(s, *scope, upload_tid)
        _denied(s, checks, "new_click_cannot_replay_upload", vendor_execution.claim_submit,
            *scope, upload_tid, p.BoundCommand.model_validate(bound(upload, "spruce-upload-new-click")),
            code="vendor_submit_already_claimed")
        stages.append({"stage": "upload_response", **_summary(upload), "fax_submissions": 0})
        if scenario == "upload_reply_lost":
            checks["lost_upload_does_not_authorize_fax"] = upload["summary"]["acceptance"] == "unconfirmed"
            final_tid = upload_tid
        else:
            fax_proposal = p.VendorProposal.model_validate({**common,
                "expected_workspace_revision": workspace.read(s, *scope)["revision"],
                "idempotency_key": "spruce-fax-proposal", "proposed_operation_id": str(uuid4()),
                "action": "spruce_fax", "uploaded_media_operation_id": upload["summary"]["operation_id"],
                "correspondence": {k: co[k] for k in ("id", "revision", "public_sha256")}})
            final_tid = vendor_work.propose(s, *scope, fax_proposal)["effect"]["ticket_id"]
            fax = vendor_work.detail(s, *scope, final_tid)
            checks["upload_and_fax_are_separate_operations"] = fax["summary"]["operation_id"] != upload["summary"]["operation_id"]
            _denied(s, checks, "upload_approval_never_authorizes_fax", vendor_execution.claim_submit,
                *scope, final_tid, p.BoundCommand.model_validate(bound(fax, "spruce-send-too-early")),
                code="vendor_revision_changed")
            choice = p.VendorDecision.model_validate(bound(fax, "spruce-fax-approve",
                review_sha256=fax["review_sha256"], choice="approve"))
            _denied(s, checks, "agent_cannot_approve_fax", vendor_work.decide,
                app.box, app.agent_id("follow_up"), app.workspace, final_tid, choice)
            vendor_work.decide(s, *scope, final_tid, choice)
            app.event("simulated_provider", "spruce_fax_exact_approval", ticket_id=final_tid)
            fax = vendor_work.detail(s, *scope, final_tid)
            send_request = p.BoundCommand.model_validate(bound(fax, "spruce-send"))
            if scenario == "altered_source":
                snapshot = workspace.read(s, *scope)
                note_review.save(s, *scope, expected=snapshot["revision"], key="spruce-source-change",
                    base_note_id=n["id"], source_reply_id=None, content="SYNTHETIC ONLY: changed administrative plan.")
                _denied(s, checks, "source_edit_invalidates_fax_approval", vendor_execution.claim_submit,
                    *scope, final_tid, send_request, code="vendor_source_changed")
                checks["source_edit_does_not_send"] = len(calls) == 1
            else:
                _, send = vendor_execution.claim_submit(s, *scope, final_tid, send_request)
                if send is None:
                    raise LabError("spruce_send_not_admitted")
    if scenario not in {"upload_reply_lost", "altered_source"}:
        asyncio.run(executor.invoke(send))
        with factory() as s:
            _, duplicate = vendor_execution.claim_submit(s, *scope, final_tid, send_request)
            checks["fax_claim_never_dispatches_twice"] = duplicate is None
            fax = vendor_work.detail(s, *scope, final_tid)
            _denied(s, checks, "new_click_cannot_replay_fax", vendor_execution.claim_submit,
                *scope, final_tid, p.BoundCommand.model_validate(bound(fax, "spruce-send-new-click")),
                code="vendor_submit_already_claimed")
            stages.append({"stage": "fax_response", **_summary(fax), "fax_submissions": 1})
            _denied(s, checks, "acceptance_alone_has_no_read_reference", vendor_execution.claim_read,
                *scope, final_tid, p.BoundCommand.model_validate(bound(fax, "spruce-before-event")),
                code="vendor_reference_unavailable")
            event = {"object": "event", "type": "conversationItem.created", "eventTime": datetime.now(UTC).isoformat(),
                "data": {"object": {"id": "ti_invented_lab", "requestId": "asyncRequest_other"
                    if scenario == "wrong_callback_request" else "asyncRequest_invented_lab",
                    "object": "conversationItem", "direction": "inbound" if scenario == "contradictory_callback" else "outbound",
                    "isInternalNote": False}}}
            raw = json.dumps(event, separators=(",", ":")).encode()
            signature = base64.b64encode(hmac.digest(SECRET, raw, "sha256")).decode()
            head = fax["summary"]["observation_head"]
            if scenario == "invalid_signature":
                try:
                    vendor_events.ingest(s, route, raw + b" ", signature=signature)
                except workspace.WorkspaceError as error:
                    s.rollback()
                    checks["altered_callback_rejected"] = str(error) == "invalid_vendor_request"
                else:
                    raise LabError("altered_callback_accepted")
            else:
                vendor_events.ingest(s, other_route or route, raw, signature=signature)
            fax = vendor_work.detail(s, *scope, final_tid)
            correlated = scenario not in {"send_reply_lost", "wrong_callback_request", "wrong_callback_account",
                                          "invalid_signature", "contradictory_callback"}
            checks["exact_signed_callback_correlation"] = (fax["summary"]["observation_head"] != head) == correlated
            if correlated:
                before = fax["summary"]["observation_head"]
                vendor_events.ingest(s, route, raw, signature=signature)
                checks["duplicate_callback_does_not_create_another_receipt"] = vendor_work.detail(s, *scope, final_tid)["summary"]["observation_head"] == before
                read_request = p.BoundCommand.model_validate(bound(fax, "spruce-observe"))
                _, read = vendor_execution.claim_read(s, *scope, final_tid, read_request)
            else:
                _denied(s, checks, "unmatched_event_does_not_allow_read", vendor_execution.claim_read,
                    *scope, final_tid, p.BoundCommand.model_validate(bound(fax, "spruce-unmatched-event")),
                    code="vendor_reference_unavailable")
                read = None
        if read is not None:
            asyncio.run(executor.invoke(read))
            with factory() as s:
                fax = vendor_work.detail(s, *scope, final_tid)
                stages.append({"stage": "posting_status_read", **_summary(fax), "fax_submissions": 1})
                _, duplicate = vendor_execution.claim_read(s, *scope, final_tid, read_request)
                checks["duplicate_read_does_not_repeat_io"] = duplicate is None
                if scenario == "status_reply_lost":
                    checks["lost_status_stays_unknown_without_retry"] = fax["summary"]["transport"] == "unknown" and len(calls) == 3
                    _, recovery = vendor_execution.claim_read(s, *scope, final_tid,
                        p.BoundCommand.model_validate(bound(fax, "spruce-observe-recovery")))
                else:
                    recovery = None
            if recovery is not None:
                asyncio.run(executor.invoke(recovery))
                with factory() as s:
                    recovered = vendor_work.detail(s, *scope, final_tid)
                    observed = vendor_work.observations(s, *scope, final_tid)["observations"]
                    # The ledger deliberately retains prior unknown evidence.
                    # A current posted item recovers the read, but cannot erase
                    # fax uncertainty because Spruce supplies no terminal proof.
                    checks["explicit_read_recovery_saves_current_posting"] = (
                        observed[-1].get("transport") == "pending"
                        and recovered["summary"]["observation_head"] != fax["summary"]["observation_head"]
                        and sum(c["action"] == "read" for c in calls) == 2)
                    checks["nonterminal_recovery_preserves_prior_uncertainty"] = (
                        recovered["summary"]["transport"] == "unknown"
                        and any(o.get("transport") == "unknown" for o in observed))
                    stages.append({"stage": "explicit_posting_read_recovered", **_summary(recovered),
                                   "latest_transport_observation": observed[-1].get("transport"), "fax_submissions": 1})
    with factory() as s:
        final = vendor_work.detail(s, *scope, final_tid)["summary"]
        checks["fax_delivery_not_inferred_from_posting"] = final["transport"] not in {"delivered", "failed"}
        checks["posting_is_not_automatic_task_completion"] = final["state"] != "closed"
        expected_sends = 0 if scenario in {"upload_reply_lost", "altered_source"} else 1
        checks["exactly_one_or_zero_reviewed_fax_submissions"] = sum(c["action"] == "submit" for c in calls) == expected_sends
        if scenario == "send_reply_lost":
            checks["lost_send_acceptance_remains_unconfirmed"] = final["acceptance"] == "unconfirmed"
        if scenario in {"posted", "misleading_delivery_fields"}:
            checks["current_posting_observation_is_pending_only"] = final["transport"] == "pending"
        observations = vendor_work.observations(s, *scope, final_tid)["observations"]
    app.engine.dispose()
    with factory() as s:
        reopened = vendor_work.detail(s, *scope, final_tid)["summary"]
    checks["receipts_survive_database_reopen"] = all(reopened[k] == final[k]
        for k in ("operation_id", "state", "acceptance", "transport", "observation_head", "evidence_sha256"))
    stages.append({"stage": "reopened_receipt", **_summary({"summary": reopened}), "fax_submissions": expected_sends})
    return {"provider": "spruce", "scenario": scenario, "passed": all(checks.values()), "checks": checks,
        "requests": calls, "receipt_stages": stages, "ticket": reopened, "document_sha256": artifact["sha256"],
        "observations": observations,
        "evidence_level": "real F-8, file custody, signed event correlation and connector; scripted human, synthetic HTTP; no real fax",
        "delivery_limit": "Public Spruce API documents posting, not fax transmission completion. Verify actual delivery in Spruce."}


def _summary(detail):
    return {k: detail["summary"][k] for k in ("acceptance", "transport", "state")}
