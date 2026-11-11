"""Upload proxy must never log audio, transcript, ciphertext, or SAS query strings."""

from __future__ import annotations

import concurrent.futures
import importlib
import io
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from cosmas_os.application import capture_upload_proxy as proxy
from cosmas_os.models import (
    AppointmentObservation,
    BoxContext,
    EncounterWorkspace,
    PatientLink,
    Principal,
)
from cosmas_os.ports.capture_protocol import UploadReceipt


class _Runtime:
    clinic_approval_ref = None
    baa_evidence_ref = None
    phi_authorization_ref = None


def _seed(session: Session):
    box = BoxContext(display_name="Invented logging clinic")
    session.add(box)
    session.flush()
    owner = Principal(
        box_id=box.id, principal_type="human", display_name="Alex Owner",
        is_owner=True, state="active",
    )
    session.add(owner)
    session.flush()
    patient = PatientLink(
        box_id=box.id, source_pair_key="invented:" + str(uuid4()),
        label="Invented person", state="confirmed",
        confirmed_by_principal_id=owner.id, attested_at=datetime.now(UTC),
        recording_class="synthetic",
    )
    session.add(patient)
    session.flush()
    appointment = AppointmentObservation(
        box_id=box.id, external_id="invented-" + str(uuid4()), source="synthetic",
        start_at=datetime.now(UTC), patient_label="Invented person",
        patient_link_id=patient.id, coverage_status="missing",
        recording_class="synthetic",
    )
    session.add(appointment)
    session.flush()
    workspace = EncounterWorkspace(
        box_id=box.id, owner_id=owner.id, appointment_id=appointment.id,
        patient_link_id=patient.id, create_key="upload-proxy-log-" + uuid4().hex,
    )
    session.add(workspace)
    session.commit()
    return box, owner, workspace


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session


def _signed_blob_url(marker: str) -> str:
    return (
        "https://cosmaneurastaginguploads.blob.core.windows.net/synth/"
        f"{marker}?sv=2025-01-05&sig=invented-secret-{marker}&se=2099-01-01T00:00:00Z"
    )


def test_stream_ciphertext_does_not_log_audio_or_transcript_content(db, caplog):
    box, owner, workspace = _seed(db)
    receipt = UploadReceipt(
        authorization_receipt_id=uuid4(),
        object_id=uuid4(),
        additional_authenticated_data="e30",
        upload_url=_signed_blob_url("body"),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    minted = proxy.mint_proxy_upload(
        db, receipt=receipt, box_id=box.id, workspace_id=workspace.id,
        session_id=str(uuid4()), principal_id=owner.id,
        proxy_origin="https://api.invented-cosmabot.test",
    )
    proxy_id = minted.upload_url.rsplit("/", 1)[-1]
    canary = b"CANARY_AUDIO_TRANSCRIPT_BYTES_DO_NOT_LOG_" + uuid4().bytes

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.content == canary
        return httpx.Response(201, request=request)

    transport = httpx.MockTransport(handler)
    with caplog.at_level(logging.DEBUG):
        proxy.stream_ciphertext_to_core(
            db,
            box_id=box.id,
            workspace_id=workspace.id,
            principal_id=owner.id,
            proxy_id=proxy_id,
            body=canary,
            runtime=_Runtime(),
            transport=transport,
        )
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert canary.decode("latin1") not in joined
    assert "CANARY_AUDIO_TRANSCRIPT_BYTES_DO_NOT_LOG_" not in joined
    assert b"CANARY_AUDIO_TRANSCRIPT_BYTES_DO_NOT_LOG_".hex() not in joined


def test_core_upload_httpx_logs_redact_url_args_under_concurrent_debug(db):
    """Real httpx LogRecord.args carry httpx.URL; concurrent DEBUG uploads must redact."""
    box, owner, workspace = _seed(db)
    httpx_logger = logging.getLogger("httpx")
    before_level = httpx_logger.level
    before_handlers = list(httpx_logger.handlers)
    before_filters = list(httpx_logger.filters)
    stream = io.StringIO()
    capture = logging.StreamHandler(stream)
    capture.setLevel(logging.DEBUG)
    capture.setFormatter(logging.Formatter("%(message)s"))
    httpx_logger.addHandler(capture)
    httpx_logger.setLevel(logging.DEBUG)
    httpx_logger.disabled = False
    box_id = str(box.id)
    workspace_id = str(workspace.id)
    principal_id = str(owner.id)
    bind = db.get_bind()
    proxy_ids: list[str] = []
    try:
        for index in range(3):
            signed = _signed_blob_url(f"concurrent-{index}")
            assert isinstance(httpx.URL(signed), httpx.URL)
            assert "sig=" in signed and "sv=" in signed and "?" in signed
            receipt = UploadReceipt(
                authorization_receipt_id=uuid4(),
                object_id=uuid4(),
                additional_authenticated_data="e30",
                upload_url=signed,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            minted = proxy.mint_proxy_upload(
                db, receipt=receipt, box_id=box_id, workspace_id=workspace_id,
                session_id=str(uuid4()), principal_id=principal_id,
                proxy_origin="https://api.invented-cosmabot.test",
            )
            proxy_ids.append(minted.upload_url.rsplit("/", 1)[-1])

        transport = httpx.MockTransport(
            lambda request: httpx.Response(201, request=request)
        )

        def upload(proxy_id: str) -> None:
            # Each concurrent call uses its own session on the shared engine.
            with Session(bind) as session:
                proxy.stream_ciphertext_to_core(
                    session,
                    box_id=box_id,
                    workspace_id=workspace_id,
                    principal_id=principal_id,
                    proxy_id=proxy_id,
                    body=b"synthetic-ciphertext-bytes",
                    runtime=_Runtime(),
                    transport=transport,
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(upload, proxy_ids))
    finally:
        httpx_logger.removeHandler(capture)
        httpx_logger.setLevel(before_level)

    captured = stream.getvalue()
    assert "HTTP Request:" in captured
    for line in captured.splitlines():
        assert "sig=" not in line
        assert "sv=" not in line
        assert "?" not in line
    assert httpx_logger.level == before_level
    assert list(httpx_logger.handlers) == before_handlers
    assert list(httpx_logger.filters) == before_filters
    assert sum(
        getattr(item, "marker", None) == proxy.CoreUploadHttpxFilter.marker
        for item in httpx_logger.filters
    ) == 1


def test_httpx_query_filter_install_is_idempotent_across_reload():
    first = proxy.install_httpx_query_filter()
    second = proxy.install_httpx_query_filter()
    assert first is second
    reloaded = importlib.reload(proxy)
    third = reloaded.install_httpx_query_filter()
    fourth = reloaded.install_httpx_query_filter()
    assert third is fourth
    assert third is first
    httpx_logger = logging.getLogger("httpx")
    attached = [
        item for item in httpx_logger.filters
        if getattr(item, "marker", None) == reloaded.CoreUploadHttpxFilter.marker
    ]
    assert len(attached) == 1
    # Keep the module under the original import name for later tests in this process.
    importlib.reload(proxy)


def test_core_upload_query_redaction_is_scoped_to_blob_hosts():
    """Unrelated httpx URLs must keep operational query keys (request_id)."""
    blob = _signed_blob_url("scoped")
    api = (
        "https://fixture.invalid/connections/ehr/reads"
        "?mrn=000-TEST-123&request_id=req-synth-1"
    )
    assert isinstance(proxy.redact_core_upload_query(httpx.URL(blob)), httpx.URL)
    redacted_blob = proxy.redact_core_upload_query(blob)
    assert isinstance(redacted_blob, str)
    assert "sig=" not in redacted_blob and "?" not in redacted_blob
    assert proxy.redact_core_upload_query(api) == api
    assert proxy.redact_core_upload_query(httpx.URL(api)) == httpx.URL(api)
    line = f'HTTP Request: PUT {blob} "HTTP/1.1 201 Created"'
    scrubbed = proxy.redact_core_upload_query(line)
    assert isinstance(scrubbed, str)
    assert "sig=" not in scrubbed and "sv=" not in scrubbed
    other = f'HTTP Request: POST {api} "HTTP/1.1 200 OK"'
    assert proxy.redact_core_upload_query(other) == other
