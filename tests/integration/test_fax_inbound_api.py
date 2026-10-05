"""Signed installed multi-provider inbox -> F8 -> real PDF custody, synthetic HTTP."""

import base64
import io
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration import test_managed_services as managed_fixture

from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.application.fax_inbound import Installation
from cosmas_os.config import settings
from cosmas_os.fax_inbound_models import FaxInboundAttempt, FaxInboundOutcome
from cosmas_os.models import Operation, Ticket
from cosmas_os.ports.vendor_connectors import ConnectionSelection

managed_case = managed_fixture.managed_case


def stamp(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def key():
    return "fax-invented-" + uuid4().hex


@pytest.fixture
def inbox(managed_case, monkeypatch):
    case = managed_case
    monkeypatch.setattr(settings, "fax_inbound_enabled", True)
    monkeypatch.setattr(settings, "fax_inbound_document_encryption_key", SecretStr(base64.b64encode(b"F" * 32).decode()))
    monkeypatch.setattr(settings, "vendor_io_enabled", False)
    monkeypatch.setattr(settings, "vendor_work_enabled", False)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    out = io.BytesIO()
    writer.write(out)
    f = SimpleNamespace(
        case=case, pdf=out.getvalue(), wire=[], lost=False, bad=False, revoked_hook=None, sender_label=None, sender_number=None, viewed=False
    )
    f.items = []
    for vendor in ("srfax", "documo", "spruce"):
        selection = ConnectionSelection(
            vendor=vendor,
            environment="production",
            connection_id=uuid4(),
            box_id=case.vendor["box"],
            owner_id=case.vendor["actor"],
            remote_account_id=str(uuid4()) if vendor == "documo" else "12345",
            credential_ref=uuid4(),
            configuration_sha256="a" * 64,
        )
        f.items.append(
            Installation(
                selection,
                "Invented " + vendor + " inbox",
                vendor != "spruce",
                "America/New_York",
                "%Y-%m-%d %H:%M:%S",
                "Received",
                "t_invented",
                "ep_invented",
            )
        )
    f.documo_id = str(uuid4())

    async def credential(selection):
        assert any(i.selection == selection for i in f.items)
        return Credential(
            selection_sha256=selection.commitment(),
            credential_ref=str(selection.credential_ref),
            secret=SecretStr("PRIVATE-invented"),
        )

    async def provider(request):
        f.wire.append((request.method, request.url.host, request.url.path))
        at = datetime.now(UTC) - timedelta(minutes=1)
        if request.url.host == "secure.srfax.com":
            fields = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            assert fields["access_id"] == "12345" and fields["access_pwd"] == "PRIVATE-invented"
            if fields["action"] == "Get_Fax_Inbox":
                assert fields["sViewedStatus"] == "ALL"
                from zoneinfo import ZoneInfo

                return httpx.Response(
                    200,
                    json={
                        "Status": "Success",
                        "Result": [
                            {
                                "FileName": "invented.pdf|123456789012345",
                                "ReceiveStatus": "Received",
                                "Date": at.astimezone(ZoneInfo("America/New_York")).strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                ),
                                "Pages": 1,
                                "Size": len(f.pdf),
                                "ViewedStatus": "N",
                            }
                        ],
                    },
                )
            assert (
                fields["action"] == "Retrieve_Fax"
                and fields["sMarkasViewed"] == "N"
                and fields["sDirection"] == "IN"
            )
            image = True
            content = {"Status": "Success", "Result": base64.b64encode(f.pdf).decode()}
        elif request.url.path == "/v1/fax/history":
            assert request.method == "GET" and request.url.params["direction"] == "inbound"
            return httpx.Response(
                200,
                json={
                    "rows": [
                        {
                            "accountId": f.items[1].selection.remote_account_id,
                            "direction": "inbound",
                            "status": "success",
                            "messageId": f.documo_id,
                            "createdAt": stamp(at),
                            "pagesCount": 1,
                            "pagesComplete": 1,
                            "resultCode": "0",
                            "isRead": f.viewed,
                            "faxCsid": f.sender_label,
                            "faxCallerId": f.sender_number,
                            "isFilePurged": False,
                        }
                    ]
                },
            )
        elif request.url.host == "api.sprucehealth.com":
            if request.url.path == "/v1/conversations/t_invented":
                return httpx.Response(
                    200,
                    json={
                        "conversation": {
                            "id": "t_invented",
                            "type": "fax",
                            "internalEndpoint": {
                                "id": "ep_invented",
                                "channel": "fax",
                                "isInternal": True,
                            },
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "conversationItems": [
                        {
                            "id": "ti_invented",
                            "conversationId": "t_invented",
                            "direction": "inbound",
                            "isInternalNote": False,
                            "createdAt": stamp(at),
                            "attachments": [
                                {
                                    "type": "document",
                                    "data": {
                                        "mimetype": "application/pdf",
                                        "signedUrl": {
                                            "url": "https://unverified.invalid/private?token=PRIVATE",
                                            "expiresAt": stamp(at + timedelta(minutes=5)),
                                        },
                                    },
                                }
                            ],
                        }
                    ]
                },
            )
        else:
            assert request.url.path == "/v1/fax/" + f.documo_id + "/download"
            image = True
            content = None
        if image:
            with Session(case.engine) as s:
                attempt = s.scalar(
                    select(FaxInboundAttempt).order_by(FaxInboundAttempt.created_at.desc())
                )
                assert attempt is not None
                op = s.get(Operation, attempt.operation_id)
                assert op.status == "unknown" and op.attempt_count == 1
            if f.lost:
                raise httpx.ReadTimeout("PRIVATE-lost")
            if f.revoked_hook:
                f.revoked_hook()
            if content is not None:
                return httpx.Response(200, json=content)
            return httpx.Response(
                200,
                content=b"not PDF" if f.bad else f.pdf,
                headers={"content-type": "application/pdf"},
            )

    f.profile = replace(
        case.profile,
        credentials=credential,
        transport_factory=lambda: httpx.MockTransport(provider),
        fax_inbound_installations=tuple(f.items),
    )
    f.headers = lambda subject="owner": {
        "Authorization": case.headers("Vendor", subject)["Authorization"],
        "X-Cosmas-Draft-Recovery": "2",
        "X-Cosmas-Fax-Inbound": "1",
    }
    return f


def reply(r, status=200):
    assert r.status_code == status, r.text
    assert r.headers["cache-control"] == "no-store"
    assert "PRIVATE" not in r.text and "credential_ref" not in r.text and "locator" not in r.text
    return r.json()


def begin(f, c, vendor):
    item = next(i for i in f.items if i.selection.vendor == vendor)
    g = reply(
        c.post(
            "/fax-inbound/grant",
            headers=f.headers(),
            json={
                "idempotency_key": key(),
                "connection_id": str(item.selection.connection_id),
                "reviewed_account": True,
                "image_enabled": item.image_enabled,
                "expires_at": stamp(datetime.now(UTC) + timedelta(hours=23)),
            },
        )
    )
    cmd = {
        "idempotency_key": key(),
        "grant_id": g["grant_id"],
        "starts_at": stamp(datetime.now(UTC) - timedelta(days=1)),
        "ends_at": stamp(datetime.now(UTC)),
        "limit": 25,
    }
    obs = reply(c.post("/fax-inbound/observe", headers=f.headers(), json=cmd))
    assert obs["state"] == "observed" and obs["inbox_complete"] is False
    count = len(f.wire)
    assert reply(c.post("/fax-inbound/observe", headers=f.headers(), json=cmd)) == obs
    assert len(f.wire) == count
    return g, obs


def approved(f, c, g, obs):
    proposed = reply(
        c.post(
            "/fax-inbound/propose",
            headers=f.headers(),
            json={
                "idempotency_key": key(),
                "grant_id": g["grant_id"],
                "observation_id": obs["observation_id"],
                "observation_sha256": obs["source_sha256"],
                "source_sha256": obs["items"][0]["source_sha256"],
            },
        )
    )
    p = reply(
        c.get(
            "/fax-inbound/proposal/" + proposed["ticket_id"] + "/" + proposed["revision_id"],
            headers=f.headers(),
        )
    )
    assert (
        p["fax"]["pages"] == 1
        and p["fax"]["sender_label"] == "Sender not provided"
        and not p["expired"]
    )
    d = reply(
        c.post(
            "/fax-inbound/decide",
            headers=f.headers(),
            json={
                "idempotency_key": key(),
                "ticket_id": p["ticket_id"],
                "revision_id": p["revision_id"],
                "expected_version": p["version"],
                "choice": "approve",
                "reviewed_exact_fax": True,
            },
        )
    )
    cmd = {
        "idempotency_key": key(),
        "ticket_id": p["ticket_id"],
        "revision_id": p["revision_id"],
        "expected_version": d["version"],
        "approval_sha256": d["approval_sha256"],
    }
    return cmd


@pytest.mark.parametrize("vendor", ["srfax", "documo"])
@pytest.mark.parametrize("round_number", [1, 2])
def test_installed_signed_inbox_f8_pdf_reopen_replay(inbox, vendor, round_number):
    f = inbox
    with f.case.start(f.profile) as c:
        status = reply(c.get("/fax-inbound", headers=f.headers()))
        assert len(status["installations"]) == 3
        g, obs = begin(f, c, vendor)
        cmd = approved(f, c, g, obs)
        outcome = reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=cmd))
        assert outcome["state"] == "acquired", outcome
        count = len(f.wire)
        again = reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=cmd))
        assert again == outcome and len(f.wire) == count
        r = c.get("/fax-inbound/document/" + outcome["operation_id"], headers=f.headers())
        assert r.status_code == 200 and r.content == f.pdf
        reply(
            c.get("/fax-inbound/document/" + outcome["operation_id"], headers=f.headers("peer")),
            404,
        )
        reply(
            c.post(
                "/fax-inbound/revoke",
                headers=f.headers(),
                json={"idempotency_key": key(), "grant_id": g["grant_id"]},
            )
        )
        reply(c.get("/fax-inbound/document/" + outcome["operation_id"], headers=f.headers()), 403)
    with Session(f.case.engine) as s:
        op = s.get(Operation, outcome["operation_id"])
        assert op.attempt_count == 1 and op.status == "succeeded"
        assert s.get(Ticket, op.ticket_id).lane == "account_fax_inbound"
        assert s.get(FaxInboundOutcome, op.id).document != f.pdf
        assert s.get(FaxInboundOutcome, op.id).document_byte_length == len(f.pdf)


def test_spruce_metadata_closed_images(inbox):
    f = inbox
    with f.case.start(f.profile) as c:
        g, obs = begin(f, c, "spruce")
        assert obs["items"][0]["image_available"] is False
        assert obs["items"][0]["image_block_reason"] == "download_host_unverified"
        reply(
            c.post(
                "/fax-inbound/propose",
                headers=f.headers(),
                json={
                    "idempotency_key": key(),
                    "grant_id": g["grant_id"],
                    "observation_id": obs["observation_id"],
                    "observation_sha256": obs["source_sha256"],
                    "source_sha256": obs["items"][0]["source_sha256"],
                },
            ),
            403,
        )
        assert all(host != "unverified.invalid" for _, host, _ in f.wire)


@pytest.mark.parametrize("bad", ["lost", "invalid_pdf"])
def test_unknown_is_durable_and_never_retried(inbox, bad):
    f = inbox
    with f.case.start(f.profile) as c:
        g, obs = begin(f, c, "documo")
        cmd = approved(f, c, g, obs)
        f.lost = bad == "lost"
        f.bad = bad == "invalid_pdf"
        outcome = reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=cmd))
        assert outcome["state"] == "outcome_unconfirmed"
        count = len(f.wire)
    with f.case.start(f.profile) as c:
        assert reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=cmd)) == outcome
        assert (
            reply(
                c.post(
                    "/fax-inbound/resolve",
                    headers=f.headers(),
                    json={"idempotency_key": cmd["idempotency_key"]},
                )
            )
            == outcome
        )
        assert len(f.wire) == count
        reply(c.get("/fax-inbound/document/" + outcome["operation_id"], headers=f.headers()), 404)


def test_revoked_during_valid_reply_preserves_private_custody(inbox):
    f = inbox
    with f.case.start(f.profile) as c:
        g, obs = begin(f, c, "documo")
        cmd = approved(f, c, g, obs)

        def revoke():
            from cosmas_os.application import fax_inbound as ledger

            with Session(f.case.engine) as s:
                ledger.revoke(
                    s, f.case.vendor["box"], f.case.vendor["actor"], g["grant_id"], key=key()
                )

        f.revoked_hook = revoke
        outcome = reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=cmd))
        assert outcome["state"] == "acquired" and outcome["source_withheld"] is True
        assert outcome["document_sha256"] is None and outcome["pages"] is None
        reply(c.get("/fax-inbound/document/" + outcome["operation_id"], headers=f.headers()), 403)
    with Session(f.case.engine) as s:
        assert s.get(FaxInboundOutcome, outcome["operation_id"]).document != f.pdf
        assert s.get(Operation, outcome["operation_id"]).status == "succeeded"


def test_changed_account_and_exact_command_conflict(inbox):
    f = inbox
    with f.case.start(f.profile) as c:
        g, obs = begin(f, c, "documo")
        cmd = approved(f, c, g, obs)
        changed = {**cmd, "expected_version": cmd["expected_version"] + 1}
        reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=changed), 409)
        assert len(f.wire) == 1
    replaced = tuple(
        replace(i, label=i.label + " changed") if i.selection.vendor == "documo" else i
        for i in f.items
    )
    with f.case.start(replace(f.profile, fax_inbound_installations=replaced)) as c:
        reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=cmd), 403)
        assert len(f.wire) == 1


def test_database_immutable_custody_and_no_agent_forged_grants(inbox):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    f = inbox
    with f.case.start(f.profile) as c:
        g, obs = begin(f, c, "documo")
        cmd = approved(f, c, g, obs)
        out = reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=cmd))
    with Session(f.case.engine) as s:
        for statement in (
            "UPDATE fax_inbound_observations SET source_sha256=repeat('a',64)",
            "DELETE FROM fax_inbound_commands",
            "UPDATE fax_inbound_attempts SET token_sha256=repeat('a',64)",
            "UPDATE fax_inbound_outcomes SET document=decode('255044462d','hex')",
            "UPDATE fax_inbound_grants SET image_enabled=false",
        ):
            with pytest.raises(DBAPIError), s.begin_nested():
                s.execute(text(statement))
        assert s.get(FaxInboundOutcome, out["operation_id"]).document != f.pdf


def test_closed_default_and_request_schema(inbox, monkeypatch):
    f = inbox
    monkeypatch.setattr(settings, "fax_inbound_enabled", False)
    with f.case.start(f.profile) as c:
        reply(c.get("/fax-inbound", headers=f.headers()), 409)
        assert f.wire == []
        from cosmas_os.api.app import app

        spec = app.openapi()
        for path in ("grant", "observe", "propose", "decide", "acquire", "resolve"):
            body = spec["paths"]["/fax-inbound/" + path]["post"]["requestBody"]
            assert (
                body["required"] is True
                and body["content"]["application/json"]["schema"]["additionalProperties"] is False
            )


def test_resolve_keeps_original_browser_wire_hash(inbox):
    from cosmas_os.application.fax_inbound import commitment

    f = inbox
    with f.case.start(f.profile) as c:
        item = f.items[1]
        command = {
            "idempotency_key": key(),
            "connection_id": str(item.selection.connection_id),
            "reviewed_account": True,
            "image_enabled": True,
            "expires_at": stamp(datetime.now(UTC) + timedelta(hours=23)),
        }
        saved = reply(c.post("/fax-inbound/grant", headers=f.headers(), json=command))
        recovered = reply(
            c.post(
                "/fax-inbound/resolve",
                headers=f.headers(),
                json={"idempotency_key": command["idempotency_key"]},
            )
        )
        assert saved == recovered
        assert recovered["public_request_sha256"] == commitment(command)


@pytest.mark.parametrize("secret", [None, SecretStr("invalid"), SecretStr(base64.b64encode(b"short").decode())])
def test_missing_protected_custody_refuses_before_dispatch_or_claim(inbox, monkeypatch, secret):
    f = inbox
    with f.case.start(f.profile) as c:
        g, obs = begin(f, c, "documo")
        cmd = approved(f, c, g, obs)
        monkeypatch.setattr(settings, "fax_inbound_document_encryption_key", secret)
        reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=cmd), 409)
        assert len(f.wire) == 1
        with Session(f.case.engine) as s:
            assert s.scalar(select(FaxInboundAttempt.operation_id).where(FaxInboundAttempt.box_id == f.case.vendor["box"], FaxInboundAttempt.owner_id == f.case.vendor["actor"])) is None


def test_signed_unicode_account_and_sender_labels_share_canonical_commitments(inbox):
    from cosmas_os.application.fax_inbound import commitment
    from cosmas_os.ports.fax_inbound import commitment as source_commitment
    f = inbox
    changed = replace(f.items[1], label="Invented café 🩺 inbox")
    f.items[1] = changed
    f.profile = replace(f.profile, fax_inbound_installations=tuple(f.items))
    f.sender_label, f.sender_number = "Invented Clínica José 🩺", "+1 (212) 555-0199"
    with f.case.start(f.profile) as c:
        status = reply(c.get("/fax-inbound", headers=f.headers()))
        assert status["installations"][1]["label"] == changed.label
        g, observation = begin(f, c, "documo")
        item = observation["items"][0]
        assert item["sender_label"] == f.sender_label and item["sender_number"] == f.sender_number
        assert item["viewed"] is False and item["sender_identity"] == "provider_reported_unverified"
        unsigned = {k: v for k, v in observation.items() if k != "receipt_sha256"}
        assert observation["receipt_sha256"] == commitment(unsigned)
        assert source_commitment({"label": f.sender_label}) == commitment({"label": f.sender_label})
        proposed = reply(c.post("/fax-inbound/propose", headers=f.headers(), json={
            "idempotency_key": key(), "grant_id": g["grant_id"], "observation_id": observation["observation_id"],
            "observation_sha256": observation["source_sha256"], "source_sha256": item["source_sha256"]}))
        proposal = reply(c.get("/fax-inbound/proposal/" + proposed["ticket_id"] + "/" + proposed["revision_id"], headers=f.headers()))
        assert proposal["fax"]["sender_label"] == f.sender_label and proposal["label"] == changed.label
        assert proposal["receipt_sha256"] == commitment({k: v for k, v in proposal.items() if k != "receipt_sha256"})


def test_lost_or_changed_custody_key_masks_retained_outcome_without_refetch(inbox, monkeypatch):
    f = inbox
    with f.case.start(f.profile) as c:
        g, obs = begin(f, c, "documo")
        cmd = approved(f, c, g, obs)
        outcome = reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=cmd))
        original_key = settings.fax_inbound_document_encryption_key
        monkeypatch.setattr(settings, "fax_inbound_document_encryption_key", SecretStr(base64.b64encode(b"G" * 32).decode()))
        recovered = reply(c.post("/fax-inbound/resolve", headers=f.headers(), json={"idempotency_key": cmd["idempotency_key"]}))
        assert recovered["state"] == "acquired" and recovered["source_withheld"] is True
        assert recovered["document_sha256"] is None and recovered["pages"] is None
        reply(c.get("/fax-inbound/document/" + outcome["operation_id"], headers=f.headers()), 409)
        assert len(f.wire) == 2
        monkeypatch.setattr(settings, "fax_inbound_document_encryption_key", original_key)
        assert c.get("/fax-inbound/document/" + outcome["operation_id"], headers=f.headers()).content == f.pdf
        assert len(f.wire) == 2


def test_ciphertext_and_associated_scope_metadata_tamper_are_refused(inbox):
    from cosmas_os.application import fax_inbound_document as custody
    from cosmas_os.application.workspace import WorkspaceError
    from cosmas_os.fax_inbound_models import FaxInboundGrant, FaxInboundImage
    f = inbox
    with f.case.start(f.profile) as c:
        g, obs = begin(f, c, "documo")
        cmd = approved(f, c, g, obs)
        acquired = reply(c.post("/fax-inbound/acquire", headers=f.headers(), json=cmd))
    with Session(f.case.engine) as s:
        outcome = s.get(FaxInboundOutcome, acquired["operation_id"])
        attempt = s.get(FaxInboundAttempt, outcome.operation_id)
        image = s.get(FaxInboundImage, attempt.image_id)
        grant = s.get(FaxInboundGrant, image.grant_id)
        assert outcome.document != f.pdf and not outcome.document.startswith(b"%PDF-")
        assert len(outcome.document) == len(f.pdf) + 28
        assert custody.open_document(outcome, attempt, image, grant) == f.pdf
        values = SimpleNamespace(**{field: getattr(outcome, field) for field in (
            "document", "state", "document_key_id", "document_ciphertext_sha256", "document_sha256", "pages", "document_byte_length")})
        values.document = values.document[:-1] + bytes([values.document[-1] ^ 1])
        import hashlib
        values.document_ciphertext_sha256 = hashlib.sha256(values.document).hexdigest()
        with pytest.raises(WorkspaceError, match="fax_inbound_document_custody_invalid"):
            custody.open_document(values, attempt, image, grant)
        values.document = outcome.document
        values.document_ciphertext_sha256 = outcome.document_ciphertext_sha256
        values.pages = 2
        with pytest.raises(WorkspaceError, match="fax_inbound_document_custody_invalid"):
            custody.open_document(values, attempt, image, grant)
        altered_attempt = SimpleNamespace(box_id=attempt.box_id, owner_id=str(uuid4()), operation_id=attempt.operation_id)
        with pytest.raises(WorkspaceError, match="fax_inbound_document_custody_invalid"):
            custody.open_document(outcome, altered_attempt, image, grant)


@pytest.mark.parametrize("boundary", ["decision", "acquire"])
def test_expired_exact_image_approval_refuses_without_provider_or_attempt(inbox, monkeypatch, boundary):
    from cosmas_os.application import fax_inbound as ledger
    f = inbox
    with f.case.start(f.profile) as c:
        g, observation = begin(f, c, "documo")
        if boundary == "acquire":
            command = approved(f, c, g, observation)
        else:
            proposed = reply(c.post("/fax-inbound/propose", headers=f.headers(), json={
                "idempotency_key": key(), "grant_id": g["grant_id"],
                "observation_id": observation["observation_id"],
                "observation_sha256": observation["source_sha256"],
                "source_sha256": observation["items"][0]["source_sha256"]}))
            command = {"idempotency_key": key(), "ticket_id": proposed["ticket_id"],
                "revision_id": proposed["revision_id"], "expected_version": proposed["version"],
                "choice": "approve", "reviewed_exact_fax": True}
        real_now = ledger.now
        monkeypatch.setattr(ledger, "now", lambda s: real_now(s) + timedelta(minutes=6))
        reply(c.post("/fax-inbound/" + ("decide" if boundary == "decision" else "acquire"),
            headers=f.headers(), json=command), 409)
        assert len(f.wire) == 1
        with Session(f.case.engine) as s:
            assert s.scalar(select(FaxInboundAttempt.operation_id).where(
                FaxInboundAttempt.box_id == f.case.vendor["box"],
                FaxInboundAttempt.owner_id == f.case.vendor["actor"])) is None
