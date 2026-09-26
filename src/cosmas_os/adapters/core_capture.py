"""Dormant OS half of the proposed W8 Core binding contract; no live selection."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import ValidationError

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_capture import (
    CoreCaptureBindingSnapshot,
    CoreCaptureSelection,
    CoreInteractionCredential,
)

_PATH = "/service/v1/agent/scribe/capture-bindings/resolve"
_MAX_BYTES = 16_384


class HttpCoreCaptureBinding:
    def __init__(
        self, origin: str, workload_token: Callable[[], str], *,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        try:
            parsed = urlsplit(origin)
            valid = (
                parsed.scheme == "https" and bool(parsed.hostname)
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                and not any(c.isspace() for c in origin)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Core capture requires a configured HTTPS origin")
        self._origin = origin.rstrip("/")
        self._workload_token = workload_token
        self._now = now
        self._client = httpx.Client(transport=transport, timeout=10, follow_redirects=False, trust_env=False)

    def close(self) -> None:
        self._client.close()

    def resolve_binding(
        self, selection: CoreCaptureSelection, credential: CoreInteractionCredential
    ) -> CoreCaptureBindingSnapshot:
        if not isinstance(selection, CoreCaptureSelection) or not isinstance(credential, CoreInteractionCredential):
            raise ConnectorUnavailable("core_capture_scope_invalid")
        try:
            token = self._workload_token()
            if (
                not isinstance(token, str) or not 1 <= len(token) <= 8192
                or not token.isascii() or not token.isprintable() or any(c.isspace() for c in token)
            ):
                raise ValueError
        except Exception:
            raise ConnectorUnavailable("core_capture_identity_unavailable") from None
        nonce = uuid4()
        try:
            with self._client.stream("POST", self._origin + _PATH, json={
                "workspace_id": str(selection.workspace_id),
                "appointment_ref": selection.appointment_ref,
                "request_nonce": str(nonce),
            }, headers={
                "Authorization": "Bearer " + token,
                "X-Cosmaneura-Mount-Context": credential.mount_context_token.get_secret_value(),
                "X-Cosmaneura-Interaction-Ref": credential.interaction_ref,
                "X-Cosmaneura-Client-Turn-ID": str(credential.client_turn_id),
                "X-Cosmaneura-Capture-Version": "1",
                "Cache-Control": "no-store", "Accept": "application/json",
            }) as response:
                if response.status_code != 200:
                    if response.status_code in {401, 403, 404, 410}:
                        raise ConnectorUnavailable("core_capture_access_unavailable")
                    raise ConnectorUnavailable("core_capture_request_unconfirmed")
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                    or "no-store" not in {d.strip().lower() for d in response.headers.get("cache-control", "").split(",")}
                    or response.headers.get("x-cosmaneura-capture-version") != "1"
                ):
                    raise ConnectorUnavailable("core_capture_receipt_invalid")
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > _MAX_BYTES:
                        raise ConnectorUnavailable("core_capture_receipt_invalid")
                    data.extend(chunk)
                snapshot = CoreCaptureBindingSnapshot.model_validate(json.loads(data))
            try:
                now = self._now()
                if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                    raise ValueError
            except Exception:
                raise ConnectorUnavailable("core_capture_clock_unavailable") from None
            if (
                snapshot.workspace_id != selection.workspace_id
                or snapshot.appointment_ref != selection.appointment_ref
                or snapshot.actor_ref != selection.expected_actor_ref
                or snapshot.tenant_ref != selection.expected_tenant_ref
                or snapshot.request_nonce != nonce
                or not now - timedelta(seconds=30) <= snapshot.checked_at <= now + timedelta(seconds=5)
            ):
                raise ConnectorUnavailable("core_capture_scope_conflict")
            return snapshot
        except ConnectorUnavailable:
            raise
        except (ValidationError, ValueError, TypeError):
            raise ConnectorUnavailable("core_capture_receipt_invalid") from None
        except httpx.HTTPError:
            raise ConnectorUnavailable("core_capture_request_unconfirmed") from None
