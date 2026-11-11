"""CosmaBot ciphertext upload proxy: browser → CosmaBot API → Core blob S2S.

Core authorize_upload still issues the Scribe/blob SAS URL. CosmaBot never
returns that URL to the browser (browser→blob would need Cosmas CORS). The
browser PUTs only to CosmaBot's own API origin; CosmaBot streams to the stored
target with httpx (no browser CORS). Synthetic audio/ciphertext only.

The proxy rewrite applies only when independent-beta Core capture is opted in
(workspace_capture_backend=core) AND workspace_capture_proxy_origin is
configured. Every other profile returns Core/Scribe upload URLs unchanged.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy.orm import Session

from cosmas_os.application import real_patient_recording as rpr
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    CaptureUploadProxy,
    EncounterWorkspace,
)
from cosmas_os.ports.capture_protocol import UploadReceipt

# Matches capture_protocol.Registration.ciphertext_size_bytes upper bound.
MAX_CIPHERTEXT_BYTES = 327_680

# httpx logs request URLs (including SAS query strings) on this logger.
_HTTPX_LOGGER_NAME = "httpx"
# Strip the entire query string from any http(s) URL span in a log line.
_HTTP_URL_QUERY = re.compile(r"(https?://[^\s?]+)\?[^\s]*", re.IGNORECASE)


def redact_core_upload_query(text: str) -> str:
    """Redact the whole query string from Core upload URLs in one log line.

    Used for every log line from the Core upload httpx client — not only sig=.
    """
    if not isinstance(text, str) or "?" not in text:
        return text
    return _HTTP_URL_QUERY.sub(r"\1", text)


class _CoreUploadHttpxFilter(logging.Filter):
    """Route httpx log msg/args through redact_core_upload_query."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_core_upload_query(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(
                redact_core_upload_query(arg) if isinstance(arg, str) else arg
                for arg in args
            )
        elif isinstance(args, dict):
            record.args = {
                key: redact_core_upload_query(value) if isinstance(value, str) else value
                for key, value in args.items()
            }
        elif isinstance(args, str):
            record.args = redact_core_upload_query(args)
        return True


def _loopback_host(hostname: str | None) -> bool:
    host = (hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _exact_proxy_origin(value: str) -> bool:
    """Production: exact HTTPS. Synth labs may use loopback HTTP."""
    parsed = urlparse(value)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
        or any(c.isspace() for c in value)
    ):
        return False
    if parsed.scheme == "https" and parsed.port in (None, 443):
        return True
    return parsed.scheme == "http" and _loopback_host(parsed.hostname)


def upload_proxy_rewrite_active(*, capture_backend: str, proxy_origin: str) -> bool:
    """True only for independent-beta Core capture opt-in with a configured proxy.

    Opt-in maps to workspace_capture_backend=core (VITE_WORKSPACE_CAPTURE_ENABLED /
    hosting core_capture). Proxy origin must be an exact CosmaBot API origin.
    Empty proxy keeps main upload URLs byte-for-byte (no 503 at authorize time).
    """
    if capture_backend != "core":
        return False
    return _exact_proxy_origin(proxy_origin)


def _allowed_target_upload_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.username or parsed.password or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    # Never proxy back into AssemblyAI/Recall; Core must have issued blob/HTTPS
    # (loopback HTTP is allowed only for local synth labs).
    if host == "assemblyai.com" or host.endswith(".assemblyai.com") or host == "recall.ai" or host.endswith(".recall.ai"):
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and _loopback_host(host)


def maybe_rewrite_authorize_upload(
    session: Session,
    *,
    receipt: UploadReceipt,
    box_id: str,
    workspace_id: str,
    session_id: str,
    principal_id: str,
    proxy_origin: str,
    capture_backend: str,
) -> UploadReceipt:
    """Rewrite authorize_upload only when independent-beta proxy opt-in is active."""
    if not upload_proxy_rewrite_active(
        capture_backend=capture_backend, proxy_origin=proxy_origin
    ):
        return receipt
    return mint_proxy_upload(
        session,
        receipt=receipt,
        box_id=box_id,
        workspace_id=workspace_id,
        session_id=session_id,
        principal_id=principal_id,
        proxy_origin=proxy_origin,
    )


def mint_proxy_upload(
    session: Session,
    *,
    receipt: UploadReceipt,
    box_id: str,
    workspace_id: str,
    session_id: str,
    principal_id: str,
    proxy_origin: str,
) -> UploadReceipt:
    """Replace Core's blob upload_url with a CosmaBot API proxy URL."""
    if not _exact_proxy_origin(proxy_origin):
        raise ws.WorkspaceError("capture_connection_required", 503)
    target = receipt.upload_url
    if not _allowed_target_upload_url(target):
        raise ws.WorkspaceError("capture_request_unconfirmed", 503)
    proxy_id = str(uuid4())
    row = CaptureUploadProxy(
        id=proxy_id,
        box_id=box_id,
        workspace_id=workspace_id,
        session_id=session_id,
        object_id=str(receipt.object_id),
        principal_id=principal_id,
        authorization_receipt_id=str(receipt.authorization_receipt_id),
        target_upload_url=target,
        expires_at=receipt.expires_at,
    )
    session.add(row)
    session.commit()
    origin = proxy_origin.rstrip("/")
    return receipt.model_copy(
        update={
            "upload_url": f"{origin}/workspaces/{workspace_id}/capture/ciphertexts/{proxy_id}",
        }
    )


def _refuse_real_patient(session: Session, *, box_id: str, workspace_id: str, runtime) -> None:
    workspace = session.get(EncounterWorkspace, workspace_id)
    if workspace is None or str(workspace.box_id) != box_id or not workspace.appointment_id:
        raise ws.WorkspaceError("capture_access_unavailable", 403)
    appointment = session.get(AppointmentObservation, workspace.appointment_id)
    if appointment is None:
        raise ws.WorkspaceError(rpr.REFUSED, 403)
    rpr.require_recording_start_allowed(
        session, box_id=box_id, appointment=appointment, runtime=runtime
    )


def stream_ciphertext_to_core(
    session: Session,
    *,
    box_id: str,
    workspace_id: str,
    principal_id: str,
    proxy_id: str,
    body: bytes,
    runtime,
    transport=None,
) -> None:
    """Authz + size + real-patient gate, then S2S PUT to the stored Core URL."""
    if len(body) == 0 or len(body) > MAX_CIPHERTEXT_BYTES:
        raise ws.WorkspaceError("invalid_capture_request", 422)
    try:
        UUID(proxy_id)
    except ValueError as exc:
        raise ws.WorkspaceError("capture_access_unavailable", 403) from exc
    row = session.get(CaptureUploadProxy, proxy_id)
    if (
        row is None
        or str(row.box_id) != box_id
        or str(row.workspace_id) != workspace_id
        or str(row.principal_id) != principal_id
    ):
        raise ws.WorkspaceError("capture_access_unavailable", 403)
    now = datetime.now(UTC)
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        raise ws.WorkspaceError("upload_authorization_expired", 409)
    if row.consumed_at is not None:
        raise ws.WorkspaceError("invalid_capture_request", 409)
    _refuse_real_patient(session, box_id=box_id, workspace_id=workspace_id, runtime=runtime)

    target = row.target_upload_url
    headers = {"Content-Type": "application/octet-stream"}
    host = (urlparse(target).hostname or "").lower()
    if host.endswith(".blob.core.windows.net"):
        headers["x-ms-blob-type"] = "BlockBlob"
    httpx_logger = logging.getLogger(_HTTPX_LOGGER_NAME)
    previous_level = httpx_logger.level
    query_filter = _CoreUploadHttpxFilter()
    httpx_logger.addFilter(query_filter)
    # INFO lines include the full request URL; keep this client at WARNING.
    httpx_logger.setLevel(logging.WARNING)
    try:
        with httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(30.0, connect=5.0),
        ) as client:
            response = client.put(target, content=body, headers=headers)
    except httpx.HTTPError as exc:
        raise ws.WorkspaceError("capture_request_unconfirmed", 503) from exc
    finally:
        httpx_logger.removeFilter(query_filter)
        httpx_logger.setLevel(previous_level)
    if response.status_code != 201:
        raise ws.WorkspaceError("capture_request_unconfirmed", 503)
    row.consumed_at = now
    session.commit()
