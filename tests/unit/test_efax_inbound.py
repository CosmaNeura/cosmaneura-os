"""Invented inbound eFax I/O, exact authorization, and uncertain-read custody."""

import asyncio
import base64
import hashlib
import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from cosmas_os.adapters.efax_pdf_validation import validate_received_pdf
from cosmas_os.adapters.vendor_connectors.efax_inbound import EFaxInboundConnector
from cosmas_os.adapters.vendor_connectors.efax_inbound_json import parse_image_json
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.ports.efax_inbound import (
    MAX_IMAGE_BYTES,
    Failure,
    ImageApproval,
    ImageCommand,
    ListRequest,
)
from cosmas_os.ports.vendor_connectors import ConnectionSelection

NOW = datetime(2026, 10, 2, 22, tzinfo=UTC)
PDF = b"%PDF-1.7\nInvented synthetic document\n%%EOF"


def fixture():
    s = SimpleNamespace(
        calls=[],
        enabled=True,
        allowed=True,
        marked=0,
        before=True,
        credential=True,
        pages=1,
        now=NOW,
        document=PDF,
        handler=None,
    )
    selection = ConnectionSelection(
        vendor="efax",
        environment="production",
        connection_id=uuid4(),
        box_id=uuid4(),
        owner_id=uuid4(),
        credential_ref=uuid4(),
        remote_account_id="invented_api_user",
        configuration_sha256="a" * 64,
    )
    s.fax_id = uuid4()
    s.item = dict(
        fax_id=str(s.fax_id),
        size=len(PDF),
        duration=12,
        pages=1,
        image_downloaded=False,
        completed_timestamp=(NOW - timedelta(hours=1)).isoformat(),
        destination_fax_number="12125550101",
        originating_fax_number="12125550102",
        originating_fax_tsid="Invented Sender",
    )

    async def credentials(sel):
        return Credential(
            selection_sha256=sel.commitment() if s.credential else "f" * 64,
            credential_ref=str(sel.credential_ref),
            secret=SecretStr("invented_bearer"),
        )

    async def authority(*_):
        return s.allowed

    async def before(*_):
        s.marked += 1
        if isinstance(s.before, Exception):
            raise s.before
        return s.before

    async def validate(_):
        return s.pages

    async def exchange(req):
        s.calls.append(req)
        if s.handler:
            return await s.handler(req)
        if req.url.path == "/faxes/received":
            return httpx.Response(
                200, json={"first_record": 0, "last_record": 0, "faxes": [s.item]}
            )
        assert s.marked == 1  # durable dispatch callback always precedes image GET
        return httpx.Response(
            200,
            json={
                "fax_id": str(s.fax_id),
                "file_name": "invented.pdf",
                "image": base64.b64encode(s.document).decode(),
            },
        )

    s.runtime = EFaxInboundConnector(
        selection,
        credentials,
        enabled=True,
        authorize=authority,
        before_image_dispatch=before,
        pdf_validator=validate,
        transport=httpx.MockTransport(exchange),
        now=lambda: s.now,
    )
    s.request = ListRequest(
        selection=selection,
        request_id=uuid4(),
        starts_at=NOW - timedelta(days=7),
        ends_at=NOW,
        limit=25,
        offset=0,
    )
    return s


async def prepare(s):
    snapshot = await s.runtime.list_received(s.request)
    command = ImageCommand(
        selection=s.request.selection,
        operation_id=uuid4(),
        source_sha256=snapshot.source_sha256,
        fax_id=s.fax_id,
        expires_at=NOW + timedelta(minutes=4),
    )
    approval = ImageApproval(
        operation_id=command.operation_id,
        command_sha256=command.commitment(),
        selection_sha256=command.selection.commitment(),
        operator_id=command.selection.owner_id,
        approved_at=NOW,
        expires_at=command.expires_at,
        reviewed_exact_fax=True,
        approved_mark_downloaded_or_read=True,
    )
    return snapshot, command, approval


@pytest.mark.asyncio
async def test_exact_metadata_and_approved_image_preserve_hashes_and_mark_read():
    s = fixture()
    snapshot, command, approval = await prepare(s)
    assert snapshot.inbox_complete is False and snapshot.continuation == "unknown"
    request = s.calls[0]
    assert request.url.host == "api.securedocex.com" and request.method == "GET"
    assert (
        request.headers["pagination-limit"] == "25" and request.headers["pagination-offset"] == "0"
    )
    assert request.headers["user-id"] == "invented_api_user"
    assert set(request.url.params) == {"min_completed_timestamp", "max_completed_timestamp"}
    acquired = await s.runtime.acquire_image(command, approval, snapshot)
    assert acquired.document == PDF and acquired.receipt.state == "acquired"
    assert acquired.receipt.document_sha256 == hashlib.sha256(PDF).hexdigest()
    assert acquired.receipt.provider_read_state == "endpoint_reported_download"
    assert acquired.receipt.retry_allowed is False and s.marked == 1 and len(s.calls) == 2
    assert s.calls[1].url.params["desired_format"] == "PDF"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["disabled", "missing_authority", "revoked", "wrong_credential"])
async def test_denied_metadata_never_dispatches(phase):
    s = fixture()
    if phase == "disabled":
        s.runtime.enabled = False
    if phase == "missing_authority":
        s.runtime.authorize = None
    if phase == "revoked":
        s.allowed = False
    if phase == "wrong_credential":
        s.credential = False
    with pytest.raises(Failure):
        await s.runtime.list_received(s.request)
    assert not s.calls and s.marked == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["fax", "operator", "command", "expired", "stale_page"])
async def test_exact_image_approval_scope_before_dispatch(kind):
    s = fixture()
    snapshot, command, approval = await prepare(s)
    if kind == "fax":
        command = command.model_copy(update={"fax_id": uuid4()})
    if kind == "operator":
        approval = approval.model_copy(update={"operator_id": uuid4()})
    if kind == "command":
        approval = approval.model_copy(update={"command_sha256": "f" * 64})
    if kind == "expired":
        s.now = NOW + timedelta(minutes=4)
    if kind == "stale_page":
        s.now = NOW + timedelta(minutes=6)
    with pytest.raises(Failure):
        await s.runtime.acquire_image(command, approval, snapshot)
    assert s.marked == 0 and len(s.calls) == 1


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_mark_read_requires_explicit_true(value):
    s = fixture()
    with pytest.raises(ValidationError):
        ImageApproval(
            operation_id=uuid4(),
            command_sha256="a" * 64,
            selection_sha256="a" * 64,
            operator_id=s.request.selection.owner_id,
            approved_at=NOW,
            expires_at=NOW + timedelta(minutes=4),
            reviewed_exact_fax=True,
            approved_mark_downloaded_or_read=value,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("before", [False, RuntimeError("private sentinel")])
async def test_dispatch_callback_failure_does_not_repeat_or_claim_success(before):
    s = fixture()
    snapshot, command, approval = await prepare(s)
    s.before = before
    result = await s.runtime.acquire_image(command, approval, snapshot)
    assert result.document is None and len(s.calls) == 1
    assert result.receipt.state == ("not_attempted" if before is False else "outcome_unconfirmed")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "timeout",
        "redirect",
        "gzip",
        "identity",
        "duplicate_json",
        "wrong_fax",
        "bad_base64",
        "path_name",
        "revocation",
    ],
)
async def test_dispatched_uncertainty_never_publishes_document(kind):
    s = fixture()
    snapshot, command, approval = await prepare(s)

    async def broken(req):
        if kind == "timeout":
            raise httpx.ReadTimeout("private sentinel")
        if kind == "redirect":
            return httpx.Response(302, headers={"location": "https://other.invalid/"})
        if kind == "gzip":
            return httpx.Response(
                200,
                headers={"content-type": "application/json", "content-encoding": "gzip"},
                content=b"invalid",
            )
        if kind == "identity":
            return httpx.Response(
                200, headers={"content-type": "text/html"}, text="private sentinel"
            )
        if kind == "duplicate_json":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b'{"fax_id":"x","fax_id":"y"}',
            )
        if kind == "revocation":
            s.allowed = False
        return httpx.Response(
            200,
            json={
                "fax_id": str(uuid4()) if kind == "wrong_fax" else str(s.fax_id),
                "file_name": "../invented.pdf" if kind == "path_name" else "invented.pdf",
                "image": "@@@" if kind == "bad_base64" else base64.b64encode(PDF).decode(),
            },
        )

    s.handler = broken
    result = await s.runtime.acquire_image(command, approval, snapshot)
    assert result.document is None and result.receipt.state == "outcome_unconfirmed"
    assert (
        result.receipt.provider_read_state == "may_have_changed"
        and result.receipt.retry_allowed is False
    )
    assert len(s.calls) == 2 and s.marked == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("pages", [False, 0, 2, 51])
async def test_pdf_validation_or_page_mismatch_needs_human(pages):
    s = fixture()
    snapshot, command, approval = await prepare(s)
    s.pages = pages
    result = await s.runtime.acquire_image(command, approval, snapshot)
    assert result.document is None and result.receipt.state == "needs_human"
    assert result.receipt.provider_read_state == "endpoint_reported_download"


@pytest.mark.asyncio
async def test_cancellation_keeps_product_claim_and_never_returns_success():
    s = fixture()
    snapshot, command, approval = await prepare(s)

    async def cancel(req):
        raise asyncio.CancelledError

    s.handler = cancel
    with pytest.raises(asyncio.CancelledError):
        await s.runtime.acquire_image(command, approval, snapshot)
    assert s.marked == 1 and len(s.calls) == 2


@pytest.mark.parametrize(
    "raw", [b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b"x" * (MAX_IMAGE_BYTES + 1)]
)
def test_image_json_closed_and_bounded(raw):
    with pytest.raises(Failure):
        parse_image_json(raw)


@pytest.mark.asyncio
async def test_pdf_worker_inspects_real_invented_pdf_in_separate_process():
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    writer.write(out)
    assert await validate_received_pdf(out.getvalue()) == 1
    writer.add_js("app.alert('invented')")
    bad = io.BytesIO()
    writer.write(bad)
    with pytest.raises(Failure):
        await validate_received_pdf(bad.getvalue())
