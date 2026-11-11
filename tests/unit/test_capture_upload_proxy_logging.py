"""Upload proxy must never log audio, transcript, or ciphertext bodies."""

from __future__ import annotations

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


def test_stream_ciphertext_does_not_log_audio_or_transcript_content(db, caplog):
    box, owner, workspace = _seed(db)
    receipt = UploadReceipt(
        authorization_receipt_id=uuid4(),
        object_id=uuid4(),
        additional_authenticated_data="e30",
        upload_url="https://cosmaneurastaginguploads.blob.core.windows.net/synth?sig=1",
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


def test_core_upload_httpx_logs_never_contain_query_or_sig(db):
    box, owner, workspace = _seed(db)
    signed = (
        "https://cosmaneurastaginguploads.blob.core.windows.net/synth/object"
        "?sv=2025-01-05&sig=invented-secret-signature&se=2099-01-01T00:00:00Z"
    )
    assert "sig=" in signed and "?" in signed
    assert "?" not in proxy.redact_core_upload_query(signed)
    assert "sig=" not in proxy.redact_core_upload_query(signed)
    receipt = UploadReceipt(
        authorization_receipt_id=uuid4(),
        object_id=uuid4(),
        additional_authenticated_data="e30",
        upload_url=signed,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    minted = proxy.mint_proxy_upload(
        db, receipt=receipt, box_id=box.id, workspace_id=workspace.id,
        session_id=str(uuid4()), principal_id=owner.id,
        proxy_origin="https://api.invented-cosmabot.test",
    )
    proxy_id = minted.upload_url.rsplit("/", 1)[-1]
    seen = []
    # Attach directly to httpx: suite tests may set propagate=False on that logger.
    httpx_logger = logging.getLogger("httpx")
    stream = io.StringIO()
    capture = logging.StreamHandler(stream)
    capture.setLevel(logging.DEBUG)
    capture.setFormatter(logging.Formatter("%(message)s"))
    previous = (httpx_logger.level, httpx_logger.disabled, list(httpx_logger.handlers))

    def handler(request: httpx.Request) -> httpx.Response:
        # Emit while the Core upload client has the redaction filter installed.
        logging.getLogger("httpx").warning("core upload PUT %s", str(request.url))
        seen.append(str(request.url))
        return httpx.Response(201, request=request)

    transport = httpx.MockTransport(handler)
    httpx_logger.disabled = False
    httpx_logger.addHandler(capture)
    try:
        proxy.stream_ciphertext_to_core(
            db,
            box_id=box.id,
            workspace_id=workspace.id,
            principal_id=owner.id,
            proxy_id=proxy_id,
            body=b"synthetic-ciphertext-bytes",
            runtime=_Runtime(),
            transport=transport,
        )
    finally:
        httpx_logger.removeHandler(capture)
        httpx_logger.setLevel(previous[0])
        httpx_logger.disabled = previous[1]
    assert seen and "sig=" in seen[0]
    captured = stream.getvalue()
    assert captured.strip()
    for line in captured.splitlines():
        assert "sig=" not in line
        assert "?" not in line
