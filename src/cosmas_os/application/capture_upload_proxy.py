"""CosmaBot ciphertext upload proxy: browser → CosmaBot API → Core blob S2S.

Core authorize_upload still issues the Scribe/blob SAS URL. CosmaBot never
returns that URL to the browser (browser→blob would need Cosmas CORS). The
browser PUTs only to CosmaBot's own API origin; CosmaBot streams to the stored
target with httpx (no browser CORS). Synthetic audio/ciphertext only.

The proxy rewrite applies only when the explicit independent-beta opt-in
(workspace_capture_proxy_enabled / VITE_WORKSPACE_CAPTURE_ENABLED /
hosting core_capture) is on AND workspace_capture_proxy_origin is configured.
Every other profile returns Core/Scribe upload URLs unchanged.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import cast
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

_HTTPX_LOGGER_NAME = "httpx"
# Strip the entire query string from any http(s) URL span in a log line.
_HTTP_URL_QUERY = re.compile(r"(https?://[^\s?]+)\?[^\s]*", re.IGNORECASE)


def redact_core_upload_query(value: object) -> object:
    """Redact the whole query string from a Core upload URL value for logging.

    Handles httpx.URL (what httpx puts in LogRecord.args) and URL-shaped strings.
    Used for every log line from the Core upload httpx client — not only sig=.
    """
    if isinstance(value, httpx.URL):
        if not value.query:
            return value
        return value.copy_with(query=None)
    if not isinstance(value, str) or "?" not in value:
        return value
    return _HTTP_URL_QUERY.sub(r"\1", value)


class CoreUploadHttpxFilter(logging.Filter):
    """Rewrite httpx log msg/args so Core upload query strings never appear."""

    # Stable across importlib.reload so install stays idempotent.
    marker = "cosmas_os.capture_upload_proxy.query"

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            redacted = redact_core_upload_query(record.msg)
            if isinstance(redacted, str):
                record.msg = redacted
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(redact_core_upload_query(arg) for arg in args)
        elif isinstance(args, dict):
            record.args = {
                key: redact_core_upload_query(value) for key, value in args.items()
            }
        return True


def install_httpx_query_filter() -> CoreUploadHttpxFilter:
    """Attach exactly one CoreUploadHttpxFilter to the shared httpx logger.

    Idempotent: re-import / repeated calls never stack filters. Never changes
    logger level or handlers.
    """
    logger = logging.getLogger(_HTTPX_LOGGER_NAME)
    for existing in logger.filters:
        if getattr(existing, "marker", None) == CoreUploadHttpxFilter.marker:
            return cast(CoreUploadHttpxFilter, existing)
    attached = CoreUploadHttpxFilter()
    logger.addFilter(attached)
    return attached


# Install at import so every Core upload PUT is covered without per-call toggles.
install_httpx_query_filter()


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


def upload_proxy_rewrite_active(*, proxy_enabled: bool, proxy_origin: str) -> bool:
    """True only for explicit independent-beta opt-in with a configured proxy.

    Opt-in is workspace_capture_proxy_enabled (VITE_WORKSPACE_CAPTURE_ENABLED /
    hosting core_capture). Never inferred from workspace_capture_backend alone.
    Empty/invalid proxy keeps main upload URLs byte-for-byte (no 503 at authorize).
    """
    if not proxy_enabled:
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
    proxy_enabled: bool,
) -> UploadReceipt:
    """Rewrite authorize_upload only when independent-beta proxy opt-in is active."""
    if not upload_proxy_rewrite_active(
        proxy_enabled=proxy_enabled, proxy_origin=proxy_origin
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
    # Query redaction is the import-time httpx Filter — never toggle logger level.
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
    if response.status_code != 201:
        raise ws.WorkspaceError("capture_request_unconfirmed", 503)
    row.consumed_at = now
    session.commit()
