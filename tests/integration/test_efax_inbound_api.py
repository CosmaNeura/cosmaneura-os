"""Registered signed eFax routes, real custody/PDF worker; vendor HTTP mocked only."""

import base64
import hashlib
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pypdf
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration import test_managed_services as managed_fixture
from tests.integration import test_vendor_settings as vendor_fixture

from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.application import efax_inbound as ledger
from cosmas_os.application import vendor_settings
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.efax_inbound_models import (
    EFaxInboundAcquisition,
    EFaxInboundGrant,
    EFaxInboundInvocation,
    EFaxInboundObservationRequest,
    EFaxInboundOutcome,
)
from cosmas_os.models import Decision, ExternalIdentity, Operation, Ticket
from cosmas_os.ports.vendor_connectors import ConnectionSelection, digest

managed_case = managed_fixture.managed_case


def stamp(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def key():
    return "api-invented-" + uuid4().hex


def private(response, status=200):
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    if "application/pdf" not in response.headers.get("content-type", ""):
        assert "PRIVATE" not in response.text and "credential_ref" not in response.text
    return response


def result(response):
    return private(response).json()


@pytest.fixture
def efax_http(managed_case, monkeypatch):
    case = managed_case
    monkeypatch.setattr(settings, "efax_inbound_enabled", True)
    # Proves inbound authority does not depend on outbound fax flags.
    monkeypatch.setattr(settings, "vendor_work_enabled", False)
    monkeypatch.setattr(settings, "vendor_io_enabled", False)
    chosen = ConnectionSelection(vendor="efax", environment="production",
        connection_id=uuid4(), box_id=case.vendor["box"], owner_id=case.vendor["actor"],
        remote_account_id="invented_efax_inbox_user", credential_ref=uuid4(),
        configuration_sha256="e" * 64)
    installation = ledger.Installation(chosen, "Invented eFax inbox", True, True)
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    writer.write(out)
    f = SimpleNamespace(case=case, selection=chosen, installation=installation,
        fax_id=str(uuid4()), pdf=out.getvalue(), wire=[], credentials=[], hooks={},
        grant_id=None, operation_id=None, lost=False, invalid_pdf=False, bad_stamp=False)

    async def credentials(selected):
        assert selected == chosen
        f.credentials.append(selected.commitment())
        if "credential" in f.hooks:
            f.hooks["credential"]()
        return Credential(selection_sha256=selected.commitment(),
            credential_ref=str(selected.credential_ref), secret=SecretStr("PRIVATE-invented-inbound-token"))

    class LostImage(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"fax_id":'
            raise httpx.ReadTimeout("PRIVATE invented response was lost")

    async def provider(request):
        assert request.method == "GET" and request.url.host == "api.securedocex.com"
        assert request.headers["authorization"] == "Bearer PRIVATE-invented-inbound-token"
        assert request.headers["user-id"] == "invented_efax_inbox_user"
        assert request.headers["cache-control"] == "no-store"
        f.wire.append({"path": request.url.path, "params": dict(request.url.params),
            "pagination_limit": request.headers.get("pagination-limit"),
            "pagination_offset": request.headers.get("pagination-offset")})
        if request.url.path == "/faxes/received":
            assert request.headers["pagination-limit"] == "25" and request.headers["pagination-offset"] == "0"
            assert set(request.url.params) == {"min_completed_timestamp", "max_completed_timestamp"}
            ended = datetime.fromisoformat(request.url.params["max_completed_timestamp"].replace("Z", "+00:00"))
            item = {"fax_id": f.fax_id, "size": len(f.pdf), "duration": 12, "pages": 1,
                "image_downloaded": False, "completed_timestamp": stamp(ended - timedelta(minutes=1)),
                "destination_fax_number": "12125550101", "originating_fax_number": "12125550102",
                "originating_fax_tsid": "Invented café sender", "fax_status": "STORED"}
            if f.bad_stamp:
                item["completed_timestamp"] = "2026-10-02 22:00:00"
            return httpx.Response(200, json={"first_record": 0, "last_record": 0, "faxes": [item]})
        assert request.url.path == "/faxes/" + f.fax_id + "/image"
        assert dict(request.url.params) == {"desired_format": "PDF"}
        # Actual independent transaction must see the committed one-shot marker
        # before this effectful GET. The test never inserts a marker itself.
        with Session(case.engine) as session:
            assert session.get(EFaxInboundInvocation, f.operation_id) is not None
            operation = session.get(Operation, f.operation_id)
            assert operation is not None and operation.attempt_count == 1
        if "dispatch" in f.hooks:
            f.hooks["dispatch"]()
        if f.lost:
            return httpx.Response(200, headers={"content-type": "application/json"}, stream=LostImage())
        document = b"%PDF-1.7\nnot a parsed PDF\n%%EOF" if f.invalid_pdf else f.pdf
        return httpx.Response(200, json={"fax_id": f.fax_id, "file_name": "invented.pdf",
            "image": base64.b64encode(document).decode("ascii")})

    f.profile = replace(case.profile, credentials=credentials,
        transport_factory=lambda: httpx.MockTransport(provider), efax_inbound_installations=(installation,))
    def inbound_headers(subject="owner"):
        signed = case.headers("Vendor", subject)
        return {"Authorization": signed["Authorization"], "X-Cosmas-Draft-Recovery": "2",
            "X-Cosmas-EFax-Inbound": "1"}
    f.headers = inbound_headers
    yield f
    # Profile fixture teardown verifies actual managed runtime closes on every
    # TestClient exit. No dependency override or live transport is installed.


def grant(f, client, *, image=True):
    command = {"idempotency_key": key(), "installation_id": str(f.selection.connection_id),
        "reviewed_account": True, "reviewed_mark_read": image, "image_enabled": image,
        "expires_at": stamp(datetime.now(UTC) + timedelta(days=1))}
    saved = result(client.post("/efax-inbound/grant", headers=f.headers(), json=command))
    assert saved["state"] == "granted" and saved["image_enabled"] is image
    assert saved["public_request_sha256"] == digest("cosmas-efax-inbound-api-command.v1", {
        "scope": saved["scope"], "kind": "grant", "request": command})
    f.grant_id = saved["grant_id"]
    return saved


def observe(f, client, g=None):
    g = g or grant(f, client)
    ended = datetime.now(UTC).replace(microsecond=0)
    command = {"idempotency_key": key(), "grant_id": g["grant_id"],
        "starts_at": stamp(ended - timedelta(days=7)), "ends_at": stamp(ended), "limit": 25, "offset": 0}
    saved = result(client.post("/efax-inbound/observe", headers=f.headers(), json=command))
    return command, saved


def approve(f, client):
    command, observed = observe(f, client)
    assert observed["state"] == "observed"
    snapshot = observed["snapshot"]
    assert snapshot["inbox_complete"] is False and snapshot["continuation"] == "unknown"
    assert set(snapshot["request"]) == {"request_id", "starts_at", "ends_at", "limit", "offset"}
    item = snapshot["items"][0]
    proposed = result(client.post("/efax-inbound/propose", headers=f.headers(), json={
        "idempotency_key": key(), "grant_id": f.grant_id, "observation_id": observed["observation_id"],
        "observation_sha256": observed["source_sha256"], "fax_id": item["fax_id"],
        "fax_sha256": digest("cosmas-efax-inbound-fax.v1", item)}))
    assert proposed["state"] == "approval_required"
    assert proposed["side_effect"] == "marks_fax_downloaded_or_read"
    decision = {"idempotency_key": key(), "ticket_id": proposed["ticket_id"],
        "revision_id": proposed["revision_id"], "expected_version": proposed["version"],
        "choice": "approve", "reviewed_mark_read": True}
    saved = result(client.post("/efax-inbound/decide", headers=f.headers(), json=decision))
    assert saved["state"] == "approved" and len(f.wire) == 1
    with Session(f.case.engine) as session:
        operation = session.scalar(select(Operation).where(Operation.ticket_id == proposed["ticket_id"]))
        assert operation is not None and operation.status == "pending" and operation.attempt_count == 0
        f.operation_id = operation.id
    acquire = {"idempotency_key": key(), "ticket_id": proposed["ticket_id"],
        "revision_id": proposed["revision_id"], "expected_version": saved["version"],
        "approval_sha256": saved["approval_sha256"]}
    return proposed, acquire, command


def resolve(f, client, command, kind="image"):
    return result(client.post("/efax-inbound/resolve", headers=f.headers(),
        json={"idempotency_key": command["idempotency_key"], "kind": kind}))


def test_signed_metadata_approval_one_actual_pdf_get_private_document_and_restart(efax_http):
    f = efax_http
    with Session(f.case.engine) as session:
        note_before = ws.read(session, f.case.vendor["box"], f.case.vendor["actor"], f.case.vendor["wid"])["note"]
    with f.case.start(f.profile) as client:
        inventory = result(client.get("/efax-inbound", headers=f.headers()))
        assert inventory["grants"] == [] and inventory["installations"] == [{
            "installation_id": str(f.selection.connection_id), "label": "Invented eFax inbox",
            "metadata_available": True, "image_available": True}]
        proposed, command, observed_command = approve(f, client)
        saved = result(client.post("/efax-inbound/acquire", headers=f.headers(), json=command))
        assert saved["state"] == "acquired" and saved["content_available"] is True and saved["retry_allowed"] is False
        assert saved["document"] == {"sha256": hashlib.sha256(f.pdf).hexdigest(), "byte_length": len(f.pdf), "pages": 1}
        pdf = private(client.get("/efax-inbound/documents/" + saved["operation_id"], headers=f.headers()))
        assert pdf.content == f.pdf and pdf.headers["content-type"] == "application/pdf"
        assert pdf.headers["content-disposition"] == "attachment; filename=received-fax.pdf"
        assert pdf.headers["x-content-type-options"] == "nosniff"
        assert client.get("/efax-inbound/documents/" + saved["operation_id"], headers=f.headers("peer")).status_code == 404
        assert client.get("/efax-inbound/proposals/" + proposed["ticket_id"], headers=f.headers("peer")).status_code == 404
    assert len(f.credentials) == len(f.wire) == 2
    with f.case.start(f.profile) as client:
        restored = resolve(f, client, command)
        assert restored == saved
        assert resolve(f, client, observed_command, "observation")["state"] == "observed"
        assert private(client.get("/efax-inbound/documents/" + saved["operation_id"], headers=f.headers())).content == f.pdf
    assert len(f.credentials) == len(f.wire) == 2
    with Session(f.case.engine) as session:
        operation = session.get(Operation, saved["operation_id"])
        assert operation is not None and operation.status == "succeeded" and operation.attempt_count == 1
        assert session.get(EFaxInboundAcquisition, operation.id) is not None
        assert session.get(EFaxInboundInvocation, operation.id) is not None
        outcome = session.get(EFaxInboundOutcome, operation.id)
        assert outcome is not None and outcome.document == f.pdf and outcome.pages == 1
        ticket = session.get(Ticket, proposed["ticket_id"])
        assert ticket is not None and ticket.patient_link_id is None and ticket.appointment_id is None
        assert session.scalar(select(func.count()).select_from(Decision).where(Decision.ticket_id == ticket.id)) == 1
        assert ws.read(session, f.case.vendor["box"], f.case.vendor["actor"], f.case.vendor["wid"])["note"] == note_before
    (f.case.output / "signed-efax-api-evidence.json").write_text(json.dumps({"wire": f.wire,
        "saved": saved, "pdf_sha256": hashlib.sha256(f.pdf).hexdigest(), "dependency_overrides": 0,
        "pdf_parser": "actual bounded separate process", "recovery_additional_provider_calls": 0}, indent=2))


@pytest.mark.parametrize("bad_timestamp", ["2026-10-02 22:00:00", "2026-10-02T22:00:00",
    "2026-10-02T22:00:00.123Z", "2026-10-02T22:00:00+00:00", 1790978400])
def test_signed_request_rejects_malformed_timestamp_before_any_vendor_call(efax_http, bad_timestamp):
    f = efax_http
    with f.case.start(f.profile) as client:
        saved = grant(f, client)
        command = {"idempotency_key": key(), "grant_id": saved["grant_id"], "starts_at": bad_timestamp,
            "ends_at": stamp(datetime.now(UTC)), "limit": 25, "offset": 0}
        response = private(client.post("/efax-inbound/observe", headers=f.headers(), json=command), 400)
        assert response.json()["error"]["code"] == "efax_inbound_request_invalid"
    assert not f.credentials and not f.wire
    with Session(f.case.engine) as session:
        assert session.scalar(select(func.count()).select_from(EFaxInboundObservationRequest).where(
            EFaxInboundObservationRequest.box_id == f.case.vendor["box"])) == 0


def test_signed_missing_header_peer_and_outbound_installation_do_not_grant_inbox(efax_http):
    f = efax_http
    with f.case.start(f.profile) as client:
        no_inbound_contract = {k: v for k, v in f.headers().items() if k != "X-Cosmas-EFax-Inbound"}
        assert private(client.get("/efax-inbound", headers=no_inbound_contract), 426).json() == {
            "error": {"code": "efax_inbound_client_update_required"}}
        assert private(client.get("/efax-inbound", headers={"X-Cosmas-EFax-Inbound": "1"}), 401).json() == {
            "error": {"code": "efax_inbound_sign_in_required"}}
        command = {"idempotency_key": key(), "installation_id": str(f.selection.connection_id),
            "reviewed_account": True, "reviewed_mark_read": True, "image_enabled": True,
            "expires_at": stamp(datetime.now(UTC) + timedelta(days=1))}
        private(client.post("/efax-inbound/grant", headers=f.headers("peer"), json=command), 400)
    # Same installed outbound catalogs/credentials/lifespan, but no independent
    # inbound Installation. They must not be promoted into inbound authority.
    outbound = vendor_settings.Installation(f.selection, "Invented outbound eFax", "Invented sender",
        {"caller_id": "2125550199"}, ("efax_fax",))
    catalog = vendor_settings.Catalog((*f.profile.vendor_catalog.installations.values(), outbound))
    with f.case.start(replace(f.profile, vendor_catalog=catalog, efax_inbound_installations=())) as client:
        account = vendor_fixture.account_request({**f.case.vendor, "installed": catalog}, "efax")
        proposed = result(client.post("/vendor-settings/propose_account", headers=f.case.headers("Vendor-Setup"), json=account.public()))
        activated = result(client.post("/vendor-settings/activate", headers=f.case.headers("Vendor-Setup"), json={
            **vendor_fixture.binding(proposed), "idempotency_key": key(), "reviewed_account": True,
            "reviewed_environment": True, "reviewed_sender": True, "reviewed_capabilities": True,
            "confirm_local_activation": True}))
        assert activated["effect"]["state"] == "active"
        assert result(client.get("/efax-inbound", headers=f.headers()))["installations"] == []
        private(client.post("/efax-inbound/grant", headers=f.headers(), json=command), 400)
    assert not f.credentials and not f.wire


def test_mark_read_approval_and_metadata_only_grant_cannot_authorize_image(efax_http):
    f = efax_http
    with f.case.start(f.profile) as client:
        g = grant(f, client, image=False)
        _, observed = observe(f, client, g)
        assert observed["state"] == "observed"
        item = observed["snapshot"]["items"][0]
        response = private(client.post("/efax-inbound/propose", headers=f.headers(), json={
            "idempotency_key": key(), "grant_id": g["grant_id"], "observation_id": observed["observation_id"],
            "observation_sha256": observed["source_sha256"], "fax_id": item["fax_id"],
            "fax_sha256": digest("cosmas-efax-inbound-fax.v1", item)}), 409)
        assert response.json()["error"]["code"] == "efax_inbound_grant_changed"
    assert len(f.wire) == 1
    with Session(f.case.engine) as session:
        assert session.scalar(select(func.count()).select_from(EFaxInboundAcquisition).where(
            EFaxInboundAcquisition.box_id == f.case.vendor["box"])) == 0


def test_provider_malformed_metadata_stays_unconfirmed_and_exact_resolve_never_repeats(efax_http):
    f = efax_http
    f.bad_stamp = True
    with f.case.start(f.profile) as client:
        command, saved = observe(f, client)
        assert saved["state"] == "unconfirmed" and saved["source_withheld"] is True
        assert resolve(f, client, command, "observation") == saved
        assert result(client.post("/efax-inbound/observe", headers=f.headers(), json=command)) == saved
    with f.case.start(f.profile) as client:
        assert resolve(f, client, command, "observation") == saved
    assert len(f.wire) == len(f.credentials) == 1


@pytest.mark.parametrize("fault", ["disabled", "identity", "grant"])
def test_actual_credential_boundary_revocation_prevents_image_dispatch(efax_http, monkeypatch, fault):
    f = efax_http
    with f.case.start(f.profile) as client:
        _, command, _ = approve(f, client)
        def revoke():
            if fault == "disabled":
                monkeypatch.setattr(settings, "efax_inbound_enabled", False)
            else:
                with Session(f.case.engine) as session:
                    if fault == "identity":
                        row = session.get(ExternalIdentity, f.case.owner_binding)
                        assert row is not None
                        row.active = False
                    else:
                        row = session.get(EFaxInboundGrant, f.grant_id)
                        assert row is not None
                        row.revoked_at = datetime.now(UTC)
                    session.commit()
        f.hooks["credential"] = revoke
        response = client.post("/efax-inbound/acquire", headers=f.headers(), json=command)
        if fault == "grant":
            retained = result(response)
            assert retained["content_available"] is False and retained["retry_allowed"] is False
        else:
            private(response, 403)
    assert len(f.credentials) == 2 and len(f.wire) == 1
    with Session(f.case.engine) as session:
        assert session.get(EFaxInboundAcquisition, f.operation_id) is not None
        assert session.get(EFaxInboundInvocation, f.operation_id) is None
        assert session.get(EFaxInboundOutcome, f.operation_id) is None


def test_revocation_after_committed_image_dispatch_withholds_pdf_and_preserves_one_shot(efax_http):
    f = efax_http
    with f.case.start(f.profile) as client:
        _, command, _ = approve(f, client)
        def revoke():
            with Session(f.case.engine) as session:
                row = session.get(EFaxInboundGrant, f.grant_id)
                assert row is not None
                row.revoked_at = datetime.now(UTC)
                session.commit()
        f.hooks["dispatch"] = revoke
        saved = result(client.post("/efax-inbound/acquire", headers=f.headers(), json=command))
        assert saved["state"] == "outcome_unconfirmed" and saved["content_available"] is False
        private(client.get("/efax-inbound/documents/" + f.operation_id, headers=f.headers()), 409)
    with f.case.start(f.profile) as client:
        assert resolve(f, client, command) == saved
    assert len(f.wire) == len(f.credentials) == 2
    with Session(f.case.engine) as session:
        outcome = session.get(EFaxInboundOutcome, f.operation_id)
        assert outcome is not None and outcome.document is None


def test_uncertain_partial_image_reply_never_repeats_same_new_key_or_restarted_process(efax_http):
    f = efax_http
    f.lost = True
    with f.case.start(f.profile) as client:
        proposed, command, _ = approve(f, client)
        saved = result(client.post("/efax-inbound/acquire", headers=f.headers(), json=command))
        assert saved["state"] == "outcome_unconfirmed" and saved["retry_allowed"] is False
        assert saved["content_available"] is False
        assert result(client.post("/efax-inbound/acquire", headers=f.headers(), json=command)) == saved
        private(client.post("/efax-inbound/acquire", headers=f.headers(), json={**command, "idempotency_key": key()}), 409)
    with f.case.start(f.profile) as client:
        assert resolve(f, client, command) == saved
        assert result(client.post("/efax-inbound/acquire", headers=f.headers(), json=command)) == saved
        private(client.post("/efax-inbound/acquire", headers=f.headers(), json={**command, "idempotency_key": key()}), 409)
        private(client.get("/efax-inbound/documents/" + saved["operation_id"], headers=f.headers()), 409)
        assert result(client.get("/efax-inbound/proposals/" + proposed["ticket_id"], headers=f.headers()))["version"] == saved["version"]
    assert len(f.wire) == len(f.credentials) == 2
    with Session(f.case.engine) as session:
        operation = session.get(Operation, saved["operation_id"])
        assert operation is not None and operation.status == "unknown" and operation.attempt_count == 1
        assert session.get(EFaxInboundInvocation, operation.id) is not None
        outcome = session.get(EFaxInboundOutcome, operation.id)
        assert outcome is not None and outcome.document is None


def test_actual_pdf_parser_rejects_invalid_document_without_publishing_bytes(efax_http):
    f = efax_http
    f.invalid_pdf = True
    with f.case.start(f.profile) as client:
        _, command, _ = approve(f, client)
        saved = result(client.post("/efax-inbound/acquire", headers=f.headers(), json=command))
        assert saved["state"] == "needs_human" and saved["content_available"] is False
        assert saved["retry_allowed"] is False
        private(client.get("/efax-inbound/documents/" + saved["operation_id"], headers=f.headers()), 409)
    assert len(f.wire) == len(f.credentials) == 2
    with Session(f.case.engine) as session:
        outcome = session.get(EFaxInboundOutcome, saved["operation_id"])
        assert outcome is not None and outcome.document is None
