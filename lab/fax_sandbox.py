"""Real F-8 fax approval, custody and recovery against offline fax provider twins."""

import asyncio
import base64
import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from urllib.parse import parse_qsl
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
    vendor_execution,
    vendor_work,
    workspace,
)
from cosmas_os.config import settings
from cosmas_os.models import EncounterWorkspace
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.vendor_models import VendorConnectionVersion, VendorCorrespondenceVersion
from lab.store import LabError

RECOVERY_SCENARIOS = ("pending_recovery", "read_timeout", "throttled", "expired_access")
FAX_SCENARIOS = {
    "documo": ("delivered", "failed", "partial", "lost_reply", "wrong_account", "wrong_destination",
               "malformed_status", "contradictory_result", "wrong_reference", *RECOVERY_SCENARIOS),
    "srfax": ("delivered", "failed", "partial", "lost_reply", "wrong_destination", "expired_credentials",
              "malformed_status", "contradictory_error", *RECOVERY_SCENARIOS),
}


@contextmanager
def vendor_gates():
    prior = {name: getattr(settings, name) for name in ("vendor_work_enabled", "vendor_io_enabled")}
    try:
        settings.vendor_work_enabled = settings.vendor_io_enabled = True
        yield
    finally:
        for name, value in prior.items():
            setattr(settings, name, value)


def synthetic_pdf():
    """One valid page, fixed invented administrative content, no external assets."""
    text = b"BT /F1 12 Tf 50 740 Td (SYNTHETIC ONLY - appointment confirmation request) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream"]
    data, offsets = b"%PDF-1.4\n", [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{n:010d} 00000 n \n".encode() for n in offsets[1:])
    return data + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()


def bound(detail, key, **extra):
    value = detail["summary"]
    return {"expected_version": value["version"], "operation_id": value["operation_id"],
        "revision_id": value["revision_id"], "payload_hash": value["payload_hash"],
        "idempotency_key": key, **extra}


def install_fax(session, app, snapshot, provider):
    cid, coid = str(uuid4()), str(uuid4())
    selection = private.ConnectionSelection(vendor=provider, connection_id=UUID(cid), box_id=app.box,
        owner_id=app.owner, environment="sandbox" if provider == "documo" else "production",
        remote_account_id=str(uuid4()) if provider == "documo" else "12345", credential_ref=uuid4(),
        configuration_sha256="a" * 64)
    cv = {"id": cid, "revision": 1, "vendor": provider, "environment": selection.environment,
          "label": "Synthetic " + provider + " twin", "actions": [provider + "_fax"], "availability": "enabled"}
    cv["public_sha256"] = p.public_digest("cosmas-vendor-public-selection.v1", cv)
    session.add(VendorConnectionVersion(id=cid, family_id=str(uuid4()), revision=1, box_id=app.box,
        owner_id=app.owner, vendor=provider, environment=selection.environment, private_selection=selection.model_dump(mode="json"),
        routing={"caller_id": "2125550100", "event_route_id": str(uuid4()),
                 **({"sender_email": "fax@example.invalid"} if provider == "srfax" else {})}, private_sha256=selection.commitment(),
        public_view=cv, public_sha256=cv["public_sha256"], reviewed_by=app.owner,
        reviewed_at=datetime.now(UTC), write_enabled=True, read_enabled=True))
    session.flush()
    expiry = datetime.now(UTC) + timedelta(days=2)
    co = {"id": coid, "revision": 1, "connection_id": cid, "channel": "fax", "recipient_label": "Synthetic clinic desk",
          "destination_display": "Synthetic fax ending 0101", "permission": "reviewed", "expires_at": p.timestamp(expiry)}
    co["public_sha256"] = p.public_digest("cosmas-vendor-public-selection.v1", co)
    proof = {"destination": "12125550101", "permission_sha256": "b" * 64, "patient_mapping_sha256": "c" * 64,
             "practice_mapping_sha256": "d" * 64, "recipient_mapping_sha256": "e" * 64}
    session.add(VendorCorrespondenceVersion(id=coid, family_id=str(uuid4()), revision=1, box_id=app.box,
        owner_id=app.owner, patient_link_id=session.get(EncounterWorkspace, app.workspace).patient_link_id, connection_version_id=cid,
        private_proof=proof, private_sha256=private.digest("cosmas-vendor-correspondence.v1", proof),
        public_view=co, public_sha256=co["public_sha256"], reviewed_by=app.owner,
        reviewed_at=datetime.now(UTC), expires_at=expiry))
    session.commit()
    return selection, cv, co


def exercise_fax(app, root, scenario="delivered", *, provider="documo"):
    with vendor_gates():
        return _exercise(app, root, scenario, provider)


def _exercise(app, root, scenario, provider):
    if scenario not in FAX_SCENARIOS.get(provider, ()):
        raise LabError("unknown_fax_scenario")
    calls, checks, receipt_stages = [], {}, []
    factory = sessionmaker(app.engine, expire_on_commit=False)
    store = LocalVendorArtifactStore(root)
    pdf = synthetic_pdf()
    artifact = {"artifact_id": str(uuid4()), "sha256": hashlib.sha256(pdf).hexdigest(),
                "byte_length": len(pdf), "media_type": "application/pdf"}
    scope = (app.box, app.owner, app.workspace)
    with factory() as s:
        snapshot = workspace.read(s, *scope)
        if not snapshot["note"]["latest"]:
            snapshot = note_review.save(s, *scope, expected=snapshot["revision"], key="fax-note",
                base_note_id=None, source_reply_id=None, content="SYNTHETIC administrative plan: request confirmation of the next visit.")["workspace"]
            n = snapshot["note"]["latest"]
            snapshot = note_review.review(s, *scope, n["id"], expected=snapshot["revision"], key="fax-review",
                content_hash=n["content_hash"], source_hash=n["source_fingerprint"])["workspace"]
        n = snapshot["note"]["latest"]
        source = {"kind": "reviewed_note", "note_id": n["id"], "content_sha256": n["content_hash"],
                  "source_fingerprint": n["source_fingerprint"]}
        selection, cv, co = install_fax(s, app, snapshot, provider)
        vendor_artifacts.intent(s, *scope, p.VendorArtifactIntent.model_validate({**artifact,
            "source": source, "idempotency_key": "fax-file-intent"}))
        admission = vendor_artifacts.begin_content(s, *scope, artifact["artifact_id"], "fax-file-write")
        if admission.token is None:
            raise LabError("artifact_not_admitted")
        outcome = vendor_artifacts.write_content(store, admission.token, pdf)
        vendor_artifacts.settle_in_session(s, admission.token, outcome)
        s.commit()
        checks["verified_pdf_custody"] = outcome == "ready"
        snapshot = workspace.read(s, *scope)
        proposal = p.VendorProposal.model_validate({"expected_workspace_revision": snapshot["revision"],
            "idempotency_key": "fax-proposal", "proposed_operation_id": str(uuid4()), "action": provider + "_fax",
            "connection": {k: cv[k] for k in ("id", "revision", "public_sha256")},
            "correspondence": {k: co[k] for k in ("id", "revision", "public_sha256")}, "document": artifact,
            "source": source, "due_date": (datetime.now(UTC) + timedelta(days=2)).date().isoformat(),
            "expected_outcome": "Synthetic clinic desk receives the administrative confirmation request.", "share_to_practice": False})
        created = vendor_work.propose(s, *scope, proposal)
        tid = created["effect"]["ticket_id"]
        checks["duplicate_proposal_same_ticket"] = vendor_work.propose(s, *scope, proposal)["effect"]["ticket_id"] == tid
        detail = vendor_work.detail(s, *scope, tid)
        decision = p.VendorDecision.model_validate(bound(detail, "fax-approve", review_sha256=detail["review_sha256"], choice="approve"))
        try:
            vendor_work.decide(s, app.box, app.agent_id("follow_up"), app.workspace, tid, decision)
        except workspace.WorkspaceError:
            s.rollback()
            checks["agent_cannot_approve"] = True
        else:
            raise LabError("agent_approved_fax")
        vendor_work.decide(s, *scope, tid, decision)
        app.event("simulated_provider", "fax_exact_approval", ticket_id=tid, payload_hash=decision.payload_hash)
        request = p.BoundCommand.model_validate(bound(vendor_work.detail(s, *scope, tid), "fax-submit"))
        _, invocation = vendor_execution.claim_submit(s, *scope, tid, request)
        if invocation is None:
            raise LabError("fax_not_admitted")
    ref = str(uuid4()) if provider == "documo" else "123456"

    async def credentials(chosen):
        if chosen != selection:
            raise LabError("foreign_fax_selection")
        return Credential(selection_sha256=chosen.commitment(), credential_ref=str(chosen.credential_ref),
                          secret=SecretStr("invented-lab-secret"))

    async def current():
        app.check_agent("follow_up")
        return True

    async def respond(request):
        checks.setdefault("exact_approved_request", False)
        origin = "api.sandbox.documo.com" if provider == "documo" else "secure.srfax.com"
        if request.url.scheme != "https" or request.url.host != origin or request.url.query:
            raise LabError("unexpected_fax_origin")
        if provider == "documo":
            submitting = request.method == "POST" and request.url.path == "/v1/faxes"
            reading = request.method == "GET" and request.url.path == "/v1/fax/" + ref + "/info"
            if request.headers.get("Authorization") != "Basic invented-lab-secret":
                raise LabError("foreign_fax_credential")
            if submitting:
                mime = BytesParser(policy=policy.default).parsebytes(
                    b"Content-Type: " + request.headers.get("Content-Type", "").encode("ascii")
                    + b"\r\nMIME-Version: 1.0\r\n\r\n" + request.content)
                if mime.get_content_type() != "multipart/form-data" or not mime.is_multipart() or mime.defects:
                    raise LabError("fax_request_changed")
                expected = {"faxNumber": b"12125550101", "callerId": b"2125550100",
                            "coverPage": b"false", "async": b"true", "attachments": pdf}
                parts = list(mime.iter_parts())
                observed = {}
                for part in parts:
                    name = part.get_param("name", header="Content-Disposition")
                    if (part.is_multipart() or part.defects or part.get_content_disposition() != "form-data"
                            or name not in expected or name in observed):
                        raise LabError("fax_request_changed")
                    if name == "attachments":
                        if part.get_filename() != "document.pdf" or part.get_content_type() != "application/pdf":
                            raise LabError("fax_document_changed")
                    elif part.get_filename() is not None:
                        raise LabError("fax_request_changed")
                    observed[name] = part.get_payload(decode=True)
                if len(parts) != len(expected) or observed != expected:
                    raise LabError("fax_request_changed")
            elif request.content:
                raise LabError("fax_status_request_changed")
        else:
            if request.method != "POST" or request.url.path != "/SRF_SecWebSvc.php":
                raise LabError("unexpected_fax_route")
            if (request.headers.get("Content-Type") != "application/x-www-form-urlencoded"
                    or "Authorization" in request.headers):
                raise LabError("fax_request_changed")
            pairs = parse_qsl(request.content.decode("ascii"), strict_parsing=True,
                              keep_blank_values=True, max_num_fields=12)
            fields = dict(pairs)
            if len(pairs) != len(fields):
                raise LabError("fax_request_changed")
            submitting = fields.get("action") == "Queue_Fax"
            reading = fields.get("action") == "Get_FaxStatus"
            expected = {"action": "Queue_Fax" if submitting else "Get_FaxStatus", "sResponseFormat": "JSON",
                        "access_id": selection.remote_account_id, "access_pwd": "invented-lab-secret"}
            expected.update({"sCallerID": "2125550100", "sSenderEmail": "fax@example.invalid", "sFaxType": "SINGLE",
                "sToFaxNumber": "12125550101", "sRetries": "0", "sFileName_1": "document.pdf",
                "sFileContent_1": base64.b64encode(pdf).decode("ascii")} if submitting else {"sFaxDetailsID": ref})
            if fields != expected:
                raise LabError("fax_request_changed")
        if not submitting and not reading:
            raise LabError("unexpected_fax_route")
        calls.append({"method": request.method, "path": request.url.path, "action": "submit" if submitting else "read"})
        if submitting:
            checks["exact_approved_request"] = True
            if scenario == "lost_reply":
                raise httpx.ReadTimeout("synthetic acceptance response lost")
            if scenario == "expired_credentials":
                return httpx.Response(200, json={"Status": "Failed", "Result": "Synthetic access denied"})
            return httpx.Response(200, json={"messageId": ref} if provider == "documo"
                                  else {"Status": "Success", "Result": ref})
        first_read = sum(call["action"] == "read" for call in calls) == 1
        if first_read and scenario == "read_timeout":
            raise httpx.ReadTimeout("synthetic status response lost")
        if first_read and scenario == "throttled":
            return httpx.Response(429, json={"error": "synthetic rate limit"})
        if first_read and scenario == "expired_access":
            return httpx.Response(401, json={"error": "synthetic expired access"})
        pending = first_read and scenario == "pending_recovery"
        destination = "12125550102" if scenario == "wrong_destination" else "12125550101"
        if provider == "srfax":
            return httpx.Response(200, json={"Status": "Success", "Result": {
                "ToFaxNumber": destination, "SentStatus": None if scenario == "malformed_status" else
                "In Progress" if pending else "Failed" if scenario == "failed" else "Sent",
                "Pages": 0 if scenario == "partial" else 1,
                **({"ErrorCode": "Busy"} if scenario == "contradictory_error" else {})}})
        return httpx.Response(200, json={"messageId": str(uuid4()) if scenario == "wrong_reference" else ref,
            "accountId": str(uuid4()) if scenario == "wrong_account" else selection.remote_account_id,
            "direction": "outbound", "faxNumber": "+" + destination, "pagesCount": 1,
            "pagesComplete": True if scenario == "malformed_status" else 0 if scenario in {"failed", "partial"} else 1,
            "status": "processing" if pending else "failed" if scenario == "failed" else "success",
            "resultCode": "6100" if scenario == "failed" else "0",
            **({"errorCode": "6100"} if scenario == "contradictory_result" else {})})

    executor = vendor_execution.VendorExecution(factory, credentials, artifact_store=store,
        transport=httpx.MockTransport(respond), identity_current=current)
    asyncio.run(executor.invoke(invocation))
    with factory() as s:
        _, duplicate = vendor_execution.claim_submit(s, *scope, tid, request)
        checks["lost_submit_reply_cannot_dispatch_twice"] = duplicate is None
        detail = vendor_work.detail(s, *scope, tid)
        try:
            _, fresh_duplicate = vendor_execution.claim_submit(s, *scope, tid,
                p.BoundCommand.model_validate(bound(detail, "fax-submit-new-key")))
        except workspace.WorkspaceError as error:
            s.rollback()
            checks["new_request_key_cannot_resend"] = str(error) == "vendor_submit_already_claimed"
        else:
            checks["new_request_key_cannot_resend"] = fresh_duplicate is None
        receipt_stages.append({"stage": "submission_response", "submit_calls": len(calls),
            **{key: detail["summary"][key] for key in ("acceptance", "transport", "state")}})
        if scenario not in {"lost_reply", "expired_credentials"}:
            read_request = p.BoundCommand.model_validate(bound(detail, "fax-observe"))
            _, read = vendor_execution.claim_read(s, *scope, tid, read_request)
        else:
            read = None
    if read:
        asyncio.run(executor.invoke(read))
        with factory() as s:
            observed = vendor_work.detail(s, *scope, tid)["summary"]
            receipt_stages.append({"stage": "status_read", "submit_calls": 1,
                **{key: observed[key] for key in ("acceptance", "transport", "state")}})
    if scenario in RECOVERY_SCENARIOS:
        with factory() as s:
            first = vendor_work.detail(s, *scope, tid)["summary"]
            checks["uncertain_status_keeps_task_open"] = (first["state"] == "approved"
                and first["acceptance"] == "accepted"
                and first["transport"] == ("pending" if scenario == "pending_recovery" else "unknown"))
            _, duplicate_read = vendor_execution.claim_read(s, *scope, tid, read_request)
            checks["duplicate_status_request_does_not_read_again"] = duplicate_read is None
            checks["no_automatic_status_retry"] = len(calls) == 2
            detail = vendor_work.detail(s, *scope, tid)
            _, recovery = vendor_execution.claim_read(s, *scope, tid,
                p.BoundCommand.model_validate(bound(detail, "fax-observe-recovery")))
        if recovery is None:
            raise LabError("fax_recovery_not_admitted")
        asyncio.run(executor.invoke(recovery))
    with factory() as s:
        detail = vendor_work.detail(s, *scope, tid)
        summary = detail["summary"]
        checks["one_fax_submission"] = sum(c["action"] == "submit" for c in calls) == 1
        checks["delivery_is_not_automatic_task_completion"] = summary["state"] == "approved"
        expected = {"delivered": "delivered", "failed": "failed", "partial": "unknown", "wrong_account": "unknown",
                    "wrong_destination": "unknown", "lost_reply": "not_observed",
                    "expired_credentials": "not_observed", "malformed_status": "unknown", "contradictory_error": "unknown",
                    "contradictory_result": "unknown", "wrong_reference": "unknown",
                    **dict.fromkeys(RECOVERY_SCENARIOS, "delivered")}[scenario]
        checks["honest_delivery_outcome"] = summary["transport"] == expected
        checks["honest_acceptance_outcome"] = summary["acceptance"] == (
            "unconfirmed" if scenario == "lost_reply" else "rejected" if scenario == "expired_credentials" else "accepted")
        if scenario == "expired_credentials":
            checks["rejected_send_has_no_status_read_or_retry"] = len(calls) == 1
        if scenario in RECOVERY_SCENARIOS:
            checks["explicit_status_recovery_without_resend"] = summary["transport"] == "delivered" and len(calls) == 3
        if scenario == "lost_reply":
            checks["uncertain_acceptance_stays_uncertain"] = summary["acceptance"] == "unconfirmed" and len(calls) == 1
        if scenario == "delivered" and all(checks.values()):
            vendor_work.record_result(s, *scope, tid, p.VendorResult.model_validate(bound(detail, "fax-result",
                observation_head=summary["observation_head"], evidence_sha256=summary["evidence_sha256"],
                disposition="verified_in_vendor", evidence="SIMULATED provider verified the synthetic transport receipt; no real delivery.")))
            detail = vendor_work.detail(s, *scope, tid)
            result = detail["latest_result"]
            vendor_work.verify(s, *scope, tid, p.VendorVerify.model_validate(bound(detail, "fax-verify",
                result_receipt_id=result["receipt_id"], result_receipt_sha256=result["receipt_sha256"],
                observation_head=detail["summary"]["observation_head"], evidence_sha256=detail["summary"]["evidence_sha256"],
                reviewed_result=True, reviewed_observations=True, outcome_confirmed=True, reviewed_conflicting_evidence=False)))
            checks["separate_synthetic_human_verification_closes_task"] = vendor_work.detail(s, *scope, tid)["summary"]["state"] == "closed"
        final = vendor_work.detail(s, *scope, tid)["summary"]
    app.engine.dispose()
    with factory() as s:
        reopened = vendor_work.detail(s, *scope, tid)["summary"]
    checks["delivery_evidence_survives_database_reopen"] = all(reopened[key] == final[key]
        for key in ("operation_id", "state", "acceptance", "transport", "observation_head", "evidence_sha256"))
    receipt_stages.append({"stage": "reopened_receipt", "submit_calls": sum(c["action"] == "submit" for c in calls),
        **{key: reopened[key] for key in ("acceptance", "transport", "state")}})
    return {"provider": provider, "scenario": scenario, "passed": all(checks.values()), "checks": checks,
        "requests": calls, "ticket": reopened, "document_sha256": artifact["sha256"],
        "receipt_stages": receipt_stages,
        "evidence_level": "real F-8, file custody and connector; scripted human, synthetic HTTP; no real fax"}
