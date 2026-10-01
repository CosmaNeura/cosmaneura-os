"""Callable fax boundaries on real services, with an explicit synthetic broker.

The vendor services currently require a human owner even for reads/proposals.
This local lab broker checks the active bot and performs only those boundaries
in the saved owner's scope. It grants no production agent authority. Approval
and submission are separate test-driver methods and never registered tools.
Every connector runtime has an injected MockTransport; no live client exists.
"""

import asyncio
import base64
import hashlib
import hmac
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl
from uuid import uuid4

import httpx
from pydantic import SecretStr, ValidationError
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
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError, VendorArtifactScope
from cosmas_os.ports.vendor_connectors import DocumentBinding
from cosmas_os.vendor_models import VendorConnectionVersion, VendorCorrespondenceVersion
from lab.fax_sandbox import bound, install_fax, synthetic_pdf, vendor_gates
from lab.spruce_fax_sandbox import SECRET, _events_enabled, _exact_media_upload, _install
from lab.store import LabError

Provider = Literal["spruce", "srfax", "documo", "efax"]
SCENARIOS = ("delivered", "lost_reply", "upload_reply_lost", "read_timeout", "unavailable",
             "missing_recipient", "changed_source", "changed_pdf")
BROKER_AUTHORITY = "synthetic_preparation_broker_only; no production agent authority"


class FaxReadinessArgs(p.Closed):
    provider: Provider


class FaxPrepareArgs(FaxReadinessArgs):
    expected_workspace_revision: p.Positive
    idempotency_key: p.Key
    proposed_operation_id: p.ID
    source: p.ReviewedSource
    connection: p.Selection
    action: Literal["fax", "media_upload"] = "fax"
    document: p.Document | None = None
    correspondence: p.Selection | None = None
    uploaded_media_operation_id: p.ID | None = None


class FaxReceiptArgs(p.BoundCommand):
    provider: Provider
    ticket_id: p.ID
    refresh: bool = False


class FaxPrepareReadyArgs(FaxReadinessArgs):
    idempotency_key: p.Key
    expected_workspace_revision: p.Positive
    action: Literal["fax", "media_upload"] = "fax"
    uploaded_media_operation_id: p.ID | None = None


class FaxInspectPreparedArgs(FaxReadinessArgs):
    action: Literal["fax", "media_upload"] = "fax"


FAX_SCHEMAS = {
    "fax_readiness": (FaxReadinessArgs, "Read synthetic fax readiness and exact reviewed source, PDF and recipient bindings. Spruce requires a separately reviewed media upload before its fax proposal."),
    "fax_list_proposals": (FaxReadinessArgs, "List up to 25 existing proposals for the selected synthetic fax provider in this fixed workspace. Use their exact ticket, operation, revision and payload hash to inspect a receipt instead of preparing duplicate work. No approval, send or provider I/O occurs."),
    "fax_prepare": (FaxPrepareArgs, "Prepare one exact private F-8 fax or Spruce media-upload proposal. Reuse identical IDs, hashes and request key to recover a lost response. This tool cannot approve or submit."),
    "fax_receipt": (FaxReceiptArgs, "Inspect the exact saved operation and receipt. An explicit refresh can read provider status after a separate scripted human submission; it cannot send or resend. Spruce posting is not verified fax delivery."),
    "fax_prepare_ready": (FaxPrepareReadyArgs, "Prepare the exact private proposal from readiness already read by your active role. Supply its workspace revision and a stable key. Saved source, PDF, connection, recipient and operation bindings are copied internally; changed readiness is refused. No approval or send occurs."),
    "fax_inspect_prepared": (FaxInspectPreparedArgs, "Inspect the exact fixture operation already seen by your role through fax_list_proposals. Select provider and action; ticket and hash bindings are retained internally. This only reads saved receipts and never refreshes provider status or submits."),
}
FAX_TOOL_ROLES = {name: frozenset({"chief", "follow_up"}) for name in FAX_SCHEMAS}


class FaxTools:
    def __init__(self, app, root, scenario="delivered"):
        if scenario not in SCENARIOS:
            raise LabError("unknown_fax_tool_scenario")
        self.app, self.root, self.scenario = app, Path(root), scenario
        self.sessions = sessionmaker(app.engine, expire_on_commit=False)
        self.scope = app.box, app.owner, app.workspace
        self.store = LocalVendorArtifactStore(self.root)
        self.providers, self.tickets, self.submissions = {}, {}, {}
        self.readiness_reads, self.catalog_reads, self.compact_preparations = {}, {}, {}
        self.calls = []
        self.due_date = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
        self.source = self.document = self.artifact_scope = None
        # The scripted setup establishes reviewed synthetic source/file custody
        # before any model-callable boundary runs. Tools never review a note.
        with vendor_gates():
            for provider in ("spruce", "srfax", "documo", "efax"):
                self._fixture(provider)

    def close(self):
        """No retained HTTP client; per-call gates restore their prior values."""
        return None

    def _role(self, role):
        self.app.check_agent(role)
        return role

    def _provenance(self, role):
        actual = self._role(role)
        return {"authority": BROKER_AUTHORITY, "requested_by_role": role,
                "requested_by_agent_id": self.app.agent_id(actual),
                "owner_scope_id": self.app.owner, "synthetic_only": True,
                "external_calls": 0, "simulated_provider_calls": len(self.calls)}

    def call(self, role, name, arguments):
        if name not in FAX_SCHEMAS:
            raise LabError("unknown_tool")
        if role not in FAX_TOOL_ROLES[name]:
            raise LabError("fax_tool_role_denied")
        self._role(role)
        try:
            request = FAX_SCHEMAS[name][0].model_validate(arguments)
        except (ValidationError, ValueError, TypeError):
            raise LabError("invalid_tool_arguments") from None
        with vendor_gates():
            if name in {"fax_prepare_ready", "fax_inspect_prepared"}:
                result = getattr(self, name)(role, request)
            else:
                result = getattr(self, name)(request)
        result["broker"] = self._provenance(role)
        if name == "fax_readiness":
            if result["ready_for_proposal"]:
                self.readiness_reads[(role, request.provider)] = deepcopy(result)
            else:
                self.readiness_reads.pop((role, request.provider), None)
        elif name == "fax_list_proposals":
            self.catalog_reads[(role, request.provider)] = deepcopy(result["catalog"]["items"])
        return result

    def _fixture(self, provider):
        if self.source is None:
            with self.sessions() as s:
                snapshot = workspace.read(s, *self.scope)
                snapshot = note_review.save(s, *self.scope, expected=snapshot["revision"],
                    key="fax-tool-reviewed-note", base_note_id=None, source_reply_id=None,
                    content="SYNTHETIC ONLY: request administrative confirmation of the next visit.")["workspace"]
                n = snapshot["note"]["latest"]
                note_review.review(s, *self.scope, n["id"], expected=snapshot["revision"],
                    key="fax-tool-note-review", content_hash=n["content_hash"], source_hash=n["source_fingerprint"])
                self.source = {"kind": "reviewed_note", "note_id": n["id"],
                    "content_sha256": n["content_hash"], "source_fingerprint": n["source_fingerprint"]}
                pdf = synthetic_pdf()
                self.document = {"artifact_id": str(uuid4()), "sha256": hashlib.sha256(pdf).hexdigest(),
                    "byte_length": len(pdf), "media_type": "application/pdf"}
                vendor_artifacts.intent(s, *self.scope, p.VendorArtifactIntent.model_validate({
                    **self.document, "source": self.source, "idempotency_key": "fax-tool-pdf-intent"}))
                admission = vendor_artifacts.begin_content(s, *self.scope, self.document["artifact_id"], "fax-tool-pdf-content")
                if admission.token is None:
                    raise LabError("artifact_not_admitted")
                outcome = vendor_artifacts.write_content(self.store, admission.token, pdf)
                vendor_artifacts.settle_in_session(s, admission.token, outcome)
                s.commit()
                if outcome != "ready":
                    raise LabError("artifact_not_ready")
                self.artifact_scope = admission.scope
            if self.scenario == "changed_source":
                self.change_source()
            elif self.scenario == "changed_pdf":
                self.change_pdf()
        if provider not in self.providers:
            with self.sessions() as s:
                if provider == "spruce":
                    selection, connection, correspondence, route = _install(s, self.app)
                else:
                    selection, connection, correspondence = install_fax(s, self.app, None, provider)
                    route = None
                if self.scenario == "unavailable":
                    row = s.get(VendorConnectionVersion, connection["id"])
                    if row is None:
                        raise LabError("fax_fixture_connection_unavailable")
                    row.write_enabled = row.read_enabled = False
                if self.scenario == "missing_recipient":
                    recipient = s.get(VendorCorrespondenceVersion, correspondence["id"])
                    if recipient is None:
                        raise LabError("fax_fixture_recipient_unavailable")
                    recipient.is_current = False
                s.commit()
            self.providers[provider] = {"selection": selection, "connection": connection,
                "correspondence": correspondence, "route": route,
                "reference": str(uuid4()) if provider in {"documo", "efax"} else "123456",
                "media_id": str(uuid4()),
                "proposal_ids": {action: str(uuid4()) for action in
                    (("fax", "media_upload") if provider == "spruce" else ("fax",))}}

    def fax_readiness(self, request):
        self._fixture(request.provider)
        with self.sessions() as s:
            options = vendor_work.options(s, *self.scope)
        fixture = self.providers[request.provider]
        options["connections"] = [c for c in options["connections"] if c["id"] == fixture["connection"]["id"]]
        options["correspondences"] = [c for c in options["correspondences"] if c["connection_id"] == fixture["connection"]["id"]]
        if self.artifact_scope is None:
            raise LabError("fax_fixture_artifact_unavailable")
        try:
            self.store.read_verified(self.artifact_scope)
            custody = "ready"
        except ArtifactStoreError:
            custody = "changed"
        available = bool(options["enabled"] and options["source"] and custody == "ready"
            and options["connections"] and options["connections"][0]["availability"] == "enabled"
            and options["correspondences"] and options["correspondences"][0]["permission"] == "reviewed")
        return {"provider": request.provider, "options": options,
            "document": self.document, "document_custody": custody, "ready_for_proposal": available,
            "proposal_ids": fixture["proposal_ids"],
            "next_action": "prepare separately reviewed media upload" if request.provider == "spruce"
                else "prepare exact private fax proposal",
            "delivery_limit": self._limit(request.provider)}

    def fax_prepare(self, request):
        self._fixture(request.provider)
        fixture = self.providers[request.provider]
        if request.connection.id != fixture["connection"]["id"]:
            raise LabError("fax_provider_selection_mismatch")
        if request.action == "media_upload" and request.provider != "spruce":
            raise LabError("fax_action_unavailable")
        body = request.public()
        body.pop("provider")
        body["action"] = "spruce_media_upload" if request.action == "media_upload" else request.provider + "_fax"
        body.update(due_date=self.due_date,
            expected_outcome="Synthetic clinic desk receives an administrative confirmation request.", share_to_practice=False)
        proposal = p.VendorProposal.model_validate(body)
        # Verify local bytes before creating a new proposal. Replaying an already
        # recorded request remains available after source or custody changes.
        with self.sessions() as s:
            prior, _ = vendor_work._receipt(s, vendor_work._owner(s, *self.scope), self.app.owner, "propose", proposal)
            if prior is None and proposal.document:
                document_scope = VendorArtifactScope(box_id=self.app.box, workspace_id=self.app.workspace,
                    owner_id=self.app.owner, document=DocumentBinding.model_validate(proposal.document.public()))
                self.store.read_verified(document_scope)
            receipt = vendor_work.propose(s, *self.scope, proposal)
            detail = vendor_work.detail(s, *self.scope, receipt["effect"]["ticket_id"])
        self.tickets[receipt["effect"]["ticket_id"]] = request.provider
        return {"provider": request.provider, "receipt": receipt, "detail": detail,
                "delivery_limit": self._limit(request.provider)}

    @staticmethod
    def _readiness_binding(readiness):
        options = readiness["options"]
        return {"revision": options["entry_revision"], "source": options["source"],
            "connections": options["connections"], "correspondences": options["correspondences"],
            "document": readiness["document"], "custody": readiness["document_custody"],
            "ready": readiness["ready_for_proposal"], "proposal_ids": readiness["proposal_ids"]}

    def fax_prepare_ready(self, role, request):
        saved = self.readiness_reads.get((role, request.provider))
        if saved is None:
            raise LabError("fax_readiness_not_read")
        key = (role, request.idempotency_key)
        previous = self.compact_preparations.get(key)
        if previous is not None:
            if previous["compact"] != request.public():
                raise LabError("fax_idempotency_conflict")
            # Exact lost-response recovery uses the saved request, even when
            # later source edits would refuse new proposal preparation.
            return self.fax_prepare(previous["exact"])
        current = self.fax_readiness(FaxReadinessArgs(provider=request.provider))
        if (request.expected_workspace_revision != saved["options"]["entry_revision"]
                or self._readiness_binding(current) != self._readiness_binding(saved)):
            raise LabError("fax_readiness_changed")
        fixture = self.providers[request.provider]
        if request.action not in fixture["proposal_ids"]:
            raise LabError("fax_action_unavailable")
        options = saved["options"]
        body = {"provider": request.provider, "expected_workspace_revision": request.expected_workspace_revision,
            "idempotency_key": request.idempotency_key, "proposed_operation_id": fixture["proposal_ids"][request.action],
            "source": options["source"], "connection": {k: options["connections"][0][k]
                for k in ("id", "revision", "public_sha256")}, "action": request.action}
        if request.action == "media_upload" or request.provider != "spruce":
            body["document"] = saved["document"]
        if request.action == "fax":
            body["correspondence"] = {k: options["correspondences"][0][k]
                for k in ("id", "revision", "public_sha256")}
        if request.uploaded_media_operation_id is not None:
            if request.uploaded_media_operation_id != fixture["proposal_ids"].get("media_upload"):
                raise LabError("fax_upload_binding_changed")
            body["uploaded_media_operation_id"] = request.uploaded_media_operation_id
        exact = FaxPrepareArgs.model_validate(body)
        result = self.fax_prepare(exact)
        self.compact_preparations[key] = {"compact": request.public(), "exact": exact}
        return result

    def fax_inspect_prepared(self, role, request):
        items = self.catalog_reads.get((role, request.provider))
        if items is None:
            raise LabError("fax_proposals_not_read")
        operation = self.providers[request.provider]["proposal_ids"].get(request.action)
        selected = next((item for item in items if item["operation_id"] == operation), None)
        if selected is None:
            raise LabError("fax_prepared_operation_not_seen")
        with self.sessions() as s:
            detail = self._ticket(s, request.provider, selected["ticket_id"])
            if any(detail["summary"][key] != selected[key] for key in
                    ("operation_id", "revision_id", "payload_hash")):
                raise LabError("fax_operation_binding_changed")
        exact = FaxReceiptArgs.model_validate({"provider": request.provider,
            "ticket_id": selected["ticket_id"], **bound(detail, "fax-inspect-" + selected["operation_id"]),
            "refresh": False})
        return self.fax_receipt(exact)

    def fax_list_proposals(self, request):
        fixture = self.providers[request.provider]
        items, bindings, cursor, more = [], [], None, False
        with self.sessions() as s:
            # The application caps one workspace at 100 vendor work records.
            # Scan at most those four pages so other providers cannot hide a
            # selected-provider proposal behind the first catalog page.
            for _ in range(4):
                page = vendor_work.catalog(s, *self.scope, cursor=cursor)
                for summary in page["items"]:
                    if not summary["action"].startswith(request.provider + "_"):
                        continue
                    detail = vendor_work.detail(s, *self.scope, summary["ticket_id"])
                    if detail["review"]["connection"]["id"] != fixture["connection"]["id"]:
                        continue
                    if len(items) == 25:
                        more = True
                        break
                    items.append(summary)
                    bindings.append({"ticket_id": summary["ticket_id"],
                        "source": detail["review"]["source"], "review_sha256": detail["review_sha256"]})
                cursor = page.get("next_cursor")
                if more or not cursor:
                    break
        return {"provider": request.provider, "catalog": {"workspace_id": self.app.workspace,
            "items": items, "has_more": more, "limit": 25, "observed_at": page["observed_at"]},
            "source_bindings": bindings, "delivery_limit": self._limit(request.provider)}

    def _ticket(self, s, provider, ticket_id, request=None):
        detail = vendor_work.detail(s, *self.scope, ticket_id)
        if not detail["summary"]["action"].startswith(provider + "_"):
            raise LabError("fax_provider_selection_mismatch")
        if request and any(detail["summary"][key] != getattr(request, key)
                for key in ("operation_id", "revision_id", "payload_hash")):
            raise LabError("fax_operation_binding_changed")
        return detail

    def fax_receipt(self, request):
        self._fixture(request.provider)
        receipt, invocation = None, None
        with self.sessions() as s:
            detail = self._ticket(s, request.provider, request.ticket_id, request)
            if request.refresh:
                receipt, invocation = vendor_execution.claim_read(s, *self.scope, request.ticket_id,
                    p.BoundCommand.model_validate({k: request.public()[k] for k in p.BoundCommand.model_fields}))
        if invocation is not None:
            asyncio.run(self._executor(request.provider).invoke(invocation))
        with self.sessions() as s:
            detail = self._ticket(s, request.provider, request.ticket_id, request)
            observations = vendor_work.observations(s, *self.scope, request.ticket_id)
        return {"provider": request.provider, "detail": detail, "observations": observations,
            "receipt": receipt, "delivery_limit": self._limit(request.provider)}

    def human_submit(self, provider, ticket_id, *, authorized=False, idempotency_key=None):
        """Test-driver boundary, absent from FAX_SCHEMAS and every tool call."""
        if authorized is not True:
            raise LabError("scripted_human_authorization_required")
        if provider not in self.providers:
            raise LabError("fax_provider_not_read")
        key = idempotency_key or "fax-human-submit-" + ticket_id
        with vendor_gates(), _events_enabled():
            with self.sessions() as s:
                detail = self._ticket(s, provider, ticket_id)
                if detail["summary"]["state"] == "pending_approval":
                    vendor_work.decide(s, *self.scope, ticket_id, p.VendorDecision.model_validate(
                        bound(detail, "fax-human-approve-" + ticket_id,
                            review_sha256=detail["review_sha256"], choice="approve")))
                    detail = self._ticket(s, provider, ticket_id)
                request = self.submissions.get((ticket_id, key)) or p.BoundCommand.model_validate(bound(detail, key))
                receipt, invocation = vendor_execution.claim_submit(s, *self.scope, ticket_id, request)
                self.submissions[(ticket_id, key)] = request
            if invocation is not None:
                asyncio.run(self._executor(provider).invoke(invocation))
                if provider == "spruce" and detail["summary"]["action"] == "spruce_fax" and self.scenario != "lost_reply":
                    self._spruce_callback()
            with self.sessions() as s:
                detail = self._ticket(s, provider, ticket_id)
        self.app.event("simulated_provider", "fax_tool_human_submission", ticket_id=ticket_id,
            operation_id=detail["summary"]["operation_id"], payload_hash=detail["summary"]["payload_hash"])
        return {"receipt": receipt, "detail": detail, "authority": "separate_scripted_human_only",
                "external_calls": 0, "simulated_provider_calls": len(self.calls)}

    def change_source(self):
        """Scripted fault injection, unavailable through the tool registry."""
        with self.sessions() as s:
            snapshot = workspace.read(s, *self.scope)
            note_review.save(s, *self.scope, expected=snapshot["revision"], key="fax-tool-changed-source",
                base_note_id=snapshot["note"]["latest"]["id"], source_reply_id=None,
                content="SYNTHETIC ONLY: the administrative plan changed after review.")

    def change_pdf(self):
        if self.artifact_scope is None:
            raise LabError("fax_fixture_artifact_unavailable")
        path = self.root.joinpath(*self.artifact_scope.storage_segments())
        path.write_bytes(synthetic_pdf() + b"SYNTHETIC CHANGED CONTENT")

    @staticmethod
    def _limit(provider):
        return ("Spruce proves posting only; actual fax delivery requires separate human verification."
                if provider == "spruce" else "Transport delivery is separate from human verification and task completion.")

    def _executor(self, provider):
        selected = self.providers[provider]["selection"]

        async def credentials(chosen):
            if chosen != selected:
                raise LabError("foreign_fax_selection")
            return Credential(selection_sha256=chosen.commitment(), credential_ref=str(chosen.credential_ref),
                secret=SecretStr("invented-fax-tool-secret"))

        async def current():
            # This executor is reached only by the scoped read tool or separate
            # scripted human, never by a model-controlled approval/send tool.
            self.app.check_agent("follow_up")
            return True

        return vendor_execution.VendorExecution(self.sessions, credentials, artifact_store=self.store,
            transport=httpx.MockTransport(lambda request: self._respond(provider, request)), identity_current=current)

    def _spruce_callback(self):
        event = {"object": "event", "type": "conversationItem.created", "eventTime": datetime.now(UTC).isoformat(),
            "data": {"object": {"id": "ti_invented_lab", "requestId": "asyncRequest_invented_lab",
                "object": "conversationItem", "direction": "outbound", "isInternalNote": False}}}
        raw = json.dumps(event, separators=(",", ":")).encode()
        signature = base64.b64encode(hmac.digest(SECRET, raw, "sha256")).decode()
        with self.sessions() as s:
            vendor_events.ingest(s, self.providers["spruce"]["route"], raw, signature=signature)

    def _respond(self, provider, request):
        fixture = self.providers[provider]
        ref, pdf = fixture["reference"], synthetic_pdf()
        origin = {"spruce": "api.sprucehealth.com", "srfax": "secure.srfax.com",
                  "documo": "api.sandbox.documo.com", "efax": "api.securedocex.com"}[provider]
        if request.url.scheme != "https" or request.url.host != origin or request.url.query:
            raise LabError("unexpected_fax_origin")
        if provider == "srfax":
            fields = dict(parse_qsl(request.content.decode("ascii"), strict_parsing=True))
            kind = "submit" if fields.get("action") == "Queue_Fax" else "read" if fields.get("action") == "Get_FaxStatus" else None
            expected = {"action": "Queue_Fax" if kind == "submit" else "Get_FaxStatus", "sResponseFormat": "JSON",
                "access_id": fixture["selection"].remote_account_id, "access_pwd": "invented-fax-tool-secret"}
            expected.update({"sCallerID": "2125550100", "sSenderEmail": "fax@example.invalid", "sFaxType": "SINGLE",
                "sToFaxNumber": "12125550101", "sRetries": "0", "sFileName_1": "document.pdf",
                "sFileContent_1": base64.b64encode(pdf).decode()} if kind == "submit" else {"sFaxDetailsID": ref})
            if request.method != "POST" or request.url.path != "/SRF_SecWebSvc.php" or fields != expected:
                raise LabError("fax_request_changed")
        else:
            kind = {"spruce": {("POST", "/v1/media"): "upload", ("POST", "/v1/internalendpoints/invented_endpoint/conversations"): "submit",
                        ("GET", "/v1/conversationItems/ti_invented_lab"): "read"},
                "documo": {("POST", "/v1/faxes"): "submit", ("GET", "/v1/fax/" + ref + "/info"): "read"},
                "efax": {("POST", "/faxes"): "submit", ("GET", "/faxes/" + ref + "/metadata"): "read"}}[provider].get((request.method, request.url.path))
            expected_auth = ("Basic " if provider == "documo" else "Bearer ") + "invented-fax-tool-secret"
            if request.headers.get("Authorization") != expected_auth:
                raise LabError("fax_authorization_changed")
            if provider == "efax" and request.headers.get("user-id") != fixture["selection"].remote_account_id:
                raise LabError("fax_account_changed")
            if kind == "upload" and not _exact_media_upload(request, pdf):
                raise LabError("fax_document_changed")
            if kind == "submit":
                if provider == "spruce":
                    expected = {"destination": {"faxEndpoint": "+12125550101"}, "message": {"body": [{"type": "text", "value": ""}],
                        "internal": False, "attachments": [{"attachmentId": fixture["media_id"], "title": "document.pdf"}]}}
                    if json.loads(request.content) != expected:
                        raise LabError("fax_request_changed")
                elif provider == "efax":
                    expected = {"destinations": [{"fax_number": "+12125550101"}], "documents": [{"document_type": "PDF",
                        "document_content": base64.b64encode(pdf).decode()}], "fax_options": {"custom_CallerID": "12125550100",
                            "include_cover_page": False, "non_billable_retries": 0, "billable_retries": 0}}
                    if json.loads(request.content) != expected:
                        raise LabError("fax_request_changed")
                else:
                    message = BytesParser(policy=policy.default).parsebytes(b"Content-Type: " + request.headers["Content-Type"].encode() + b"\r\n\r\n" + request.content)
                    parts = list(message.iter_parts())
                    expected = {"faxNumber": b"12125550101", "callerId": b"2125550100", "coverPage": b"false", "async": b"true", "attachments": pdf}
                    if len(parts) != len(expected) or {part.get_param("name", header="Content-Disposition"): part.get_payload(decode=True) for part in parts} != expected:
                        raise LabError("fax_document_changed")
        if kind is None or kind == "read" and provider != "srfax" and request.content:
            raise LabError("unexpected_fax_route")
        self.calls.append({"provider": provider, "method": request.method, "path": request.url.path, "action": kind})
        if kind == "submit" and self.scenario == "lost_reply" or kind == "upload" and self.scenario == "upload_reply_lost":
            raise httpx.ReadTimeout("synthetic acceptance response lost")
        if kind == "read" and self.scenario == "read_timeout" and sum(c["provider"] == provider and c["action"] == "read" for c in self.calls) == 1:
            raise httpx.ReadTimeout("synthetic status response lost")
        if provider == "spruce":
            return httpx.Response(200, json={"id": fixture["media_id"], "object": "media"} if kind == "upload" else
                {"requestId": "asyncRequest_invented_lab"} if kind == "submit" else {"conversationItem": {
                    "id": "ti_invented_lab", "requestId": "asyncRequest_invented_lab", "direction": "outbound", "isInternalNote": False}})
        if provider == "srfax":
            return httpx.Response(200, json={"Status": "Success", "Result": ref if kind == "submit" else {
                "ToFaxNumber": "12125550101", "SentStatus": "Sent", "Pages": 1}})
        if provider == "documo":
            return httpx.Response(200, json={"messageId": ref} if kind == "submit" else {"messageId": ref,
                "accountId": fixture["selection"].remote_account_id, "direction": "outbound", "faxNumber": "+12125550101",
                "pagesCount": 1, "pagesComplete": 1, "status": "success", "resultCode": "0"})
        return httpx.Response(201 if kind == "submit" else 200, json=[{"fax_id": ref, "destination_fax_number": "2125550101"}]
            if kind == "submit" else {"fax_id": ref, "fax_status": "STORED", "direction": "OUTBOUND", "pages": 1,
                "destination_fax_number": "+12125550101", "completed_timestamp": "2026-10-01T12:00:00.000+0000",
                "transmission_data": {"transmission_status": "COMPLETE", "error_code": "", "error_message": ""}})
