"""CosmaBot ciphertext upload proxy: auth, size, synthetic-only, real-patient refuse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from cosmas_os.application import capture_upload_proxy as proxy
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    BoxContext,
    CaptureUploadProxy,
    EncounterWorkspace,
    PatientLink,
    Principal,
)
from cosmas_os.ports.capture_protocol import UploadReceipt


class _Runtime:
    clinic_approval_ref = None
    baa_evidence_ref = None
    phi_authorization_ref = None


def _seed(session: Session, *, recording_class: str = "synthetic"):
    box = BoxContext(display_name="Invented capture clinic")
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
        recording_class=recording_class,
    )
    session.add(patient)
    session.flush()
    appointment = AppointmentObservation(
        box_id=box.id, external_id="invented-" + str(uuid4()), source="synthetic",
        start_at=datetime.now(UTC), patient_label="Invented person",
        patient_link_id=patient.id, coverage_status="missing",
        recording_class=recording_class,
    )
    session.add(appointment)
    session.flush()
    workspace = EncounterWorkspace(
        box_id=box.id, owner_id=owner.id, appointment_id=appointment.id,
        patient_link_id=patient.id, create_key="upload-proxy-" + uuid4().hex,
    )
    session.add(workspace)
    session.commit()
    return box, owner, workspace, appointment


def _receipt(*, object_id=None, upload_url="https://cosmaneurastaginguploads.blob.core.windows.net/synth?sig=1"):
    return UploadReceipt(
        authorization_receipt_id=uuid4(),
        object_id=object_id or uuid4(),
        additional_authenticated_data="e30",
        upload_url=upload_url,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session


def test_mint_rewrites_blob_url_to_cosmabot_api_proxy(db):
    box, owner, workspace, _ = _seed(db)
    receipt = _receipt()
    rewritten = proxy.mint_proxy_upload(
        db, receipt=receipt, box_id=box.id, workspace_id=workspace.id,
        session_id=str(uuid4()), principal_id=owner.id,
        proxy_origin="https://api.staging.cosmas.ai",
    )
    assert rewritten.upload_url.startswith(
        f"https://api.staging.cosmas.ai/workspaces/{workspace.id}/capture/ciphertexts/"
    )
    assert "blob.core.windows.net" not in rewritten.upload_url
    proxy_id = rewritten.upload_url.rsplit("/", 1)[-1]
    row = db.get(CaptureUploadProxy, proxy_id)
    assert row is not None
    assert row.target_upload_url.startswith("https://cosmaneurastaginguploads.blob.core.windows.net/")
    assert str(row.authorization_receipt_id) == str(receipt.authorization_receipt_id)


def test_stream_requires_authz_match_and_size_limit(db):
    box, owner, workspace, _ = _seed(db)
    session_id = str(uuid4())
    rewritten = proxy.mint_proxy_upload(
        db, receipt=_receipt(), box_id=box.id, workspace_id=workspace.id,
        session_id=session_id, principal_id=owner.id,
        proxy_origin="https://api.staging.cosmas.ai",
    )
    proxy_id = rewritten.upload_url.rsplit("/", 1)[-1]
    runtime = _Runtime()

    with pytest.raises(ws.WorkspaceError, match="invalid_capture_request"):
        proxy.stream_ciphertext_to_core(
            db, box_id=box.id, workspace_id=workspace.id, principal_id=owner.id,
            proxy_id=proxy_id, body=b"", runtime=runtime,
        )
    with pytest.raises(ws.WorkspaceError, match="invalid_capture_request"):
        proxy.stream_ciphertext_to_core(
            db, box_id=box.id, workspace_id=workspace.id, principal_id=owner.id,
            proxy_id=proxy_id, body=b"x" * (proxy.MAX_CIPHERTEXT_BYTES + 1), runtime=runtime,
        )
    with pytest.raises(ws.WorkspaceError, match="capture_access_unavailable"):
        proxy.stream_ciphertext_to_core(
            db, box_id=box.id, workspace_id=workspace.id, principal_id=str(uuid4()),
            proxy_id=proxy_id, body=b"synthetic-ciphertext", runtime=runtime,
        )


def test_stream_puts_s2s_to_stored_blob_and_returns_201_path(db):
    box, owner, workspace, _ = _seed(db)
    rewritten = proxy.mint_proxy_upload(
        db, receipt=_receipt(), box_id=box.id, workspace_id=workspace.id,
        session_id=str(uuid4()), principal_id=owner.id,
        proxy_origin="https://api.staging.cosmas.ai",
    )
    proxy_id = rewritten.upload_url.rsplit("/", 1)[-1]
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), dict(request.headers), request.content))
        return httpx.Response(201, headers={"Cache-Control": "no-store"})

    transport = httpx.MockTransport(handler)
    proxy.stream_ciphertext_to_core(
        db, box_id=box.id, workspace_id=workspace.id, principal_id=owner.id,
        proxy_id=proxy_id, body=b"synthetic-audio-ciphertext",
        runtime=_Runtime(), transport=transport,
    )
    assert len(seen) == 1
    method, url, headers, content = seen[0]
    assert method == "PUT"
    assert "cosmaneurastaginguploads.blob.core.windows.net" in url
    assert headers.get("content-type") == "application/octet-stream"
    assert headers.get("x-ms-blob-type") == "BlockBlob"
    assert content == b"synthetic-audio-ciphertext"
    assert db.get(CaptureUploadProxy, proxy_id).consumed_at is not None


def test_real_patient_upload_refused_when_switch_off(db):
    box, owner, workspace, _ = _seed(db, recording_class="real")
    rewritten = proxy.mint_proxy_upload(
        db, receipt=_receipt(), box_id=box.id, workspace_id=workspace.id,
        session_id=str(uuid4()), principal_id=owner.id,
        proxy_origin="https://api.staging.cosmas.ai",
    )
    proxy_id = rewritten.upload_url.rsplit("/", 1)[-1]
    with pytest.raises(ws.WorkspaceError, match="real_patient_recording_refused"):
        proxy.stream_ciphertext_to_core(
            db, box_id=box.id, workspace_id=workspace.id, principal_id=owner.id,
            proxy_id=proxy_id, body=b"synthetic-audio-ciphertext",
            runtime=_Runtime(),
            transport=httpx.MockTransport(lambda r: httpx.Response(201)),
        )
