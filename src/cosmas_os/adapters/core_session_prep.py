"""Dedicated, bounded client for Core's existing Session Prep brief tool.

No capture credential fallback, automatic retry, model generation or source
selection lives here. Core validates the previously accepted provider UI turn.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_session_prep import CoreSessionPrepRead, CoreSessionPrepReceipt

MAX_RECEIPT_BYTES = 262_144
TOOL_PATH = "/service/v1/companion/session-prep/brief"


def _closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_session_prep_field")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("invalid_session_prep_number")


class HttpCoreSessionPrep:
    def __init__(
        self,
        origin: str,
        session_prep_token: Callable[[], str],
        *,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        try:
            parsed = urlsplit(origin)
            valid = (
                parsed.scheme == "https"
                and bool(parsed.hostname)
                and parsed.port in (None, 443)
                and not parsed.username
                and not parsed.password
                and parsed.path in ("", "/")
                and not parsed.query
                and not parsed.fragment
                and not any(character.isspace() for character in origin)
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("Core Session Prep requires a configured HTTPS origin")
        self._origin = origin.rstrip("/")
        self._token = session_prep_token
        self._now = now
        self._client = httpx.Client(
            transport=transport, timeout=15, trust_env=False, follow_redirects=False
        )

    def close(self):
        self._client.close()

    def _workload_headers(self):
        try:
            token = self._token()
            if (
                not isinstance(token, str)
                or not 1 <= len(token) <= 8192
                or not token.isascii()
                or not token.isprintable()
                or any(character.isspace() for character in token)
            ):
                raise ValueError
        except Exception:
            raise ConnectorUnavailable("session_prep_identity_unavailable") from None
        return {"Authorization": "Bearer " + token}

    def read_brief(self, selection: CoreSessionPrepRead) -> CoreSessionPrepReceipt:
        try:
            # A caller cannot bypass the port boundary with model_construct or
            # mutable input. No token acquisition occurs for an invalid request.
            selection = CoreSessionPrepRead.model_validate(
                selection.model_dump(mode="python"), strict=True
            )
        except (ValueError, TypeError, AttributeError):
            raise ConnectorUnavailable("session_prep_scope_invalid") from None
        workload = self._workload_headers()
        credential = selection.credential
        try:
            with self._client.stream(
                "POST",
                self._origin + TOOL_PATH,
                json={
                    "tool_name": "session-prep.context.read",
                    "tool_version": "1.0.0",
                    "subject_ref": None,
                    "arguments": {
                        "source_turn_ref": selection.source_turn_ref,
                        "context_snapshot_ref": selection.context_snapshot_ref,
                        "purpose": "session_prep",
                        "detail": "brief",
                    },
                },
                headers={
                    **workload,
                    "X-Cosmaneura-Mount-Context": credential.mount_context_token.get_secret_value(),
                    "X-Cosmaneura-Interaction-Ref": credential.interaction_ref,
                    "X-Cosmaneura-Client-Turn-ID": str(credential.client_turn_id),
                    "Idempotency-Key": selection.idempotency_key,
                    "Cache-Control": "no-store",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                if response.status_code in {401, 403, 404, 410}:
                    raise ConnectorUnavailable("session_prep_access_unavailable")
                if response.status_code == 409:
                    raise ConnectorUnavailable("session_prep_request_conflict")
                if response.status_code != 200:
                    raise ConnectorUnavailable("session_prep_request_unconfirmed")
                if (
                    response.headers.get("content-type", "").partition(";")[0].strip().lower()
                    != "application/json"
                    or "no-store"
                    not in {
                        value.strip().lower()
                        for value in response.headers.get("cache-control", "").split(",")
                    }
                    or response.headers.get("X-Cosmaneura-Client-Turn-ID")
                    != str(credential.client_turn_id)
                    or response.headers.get("Idempotency-Replayed") not in {"true", "false"}
                    or response.headers.get("Content-Encoding", "identity").lower() != "identity"
                ):
                    raise ValueError
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=16_384):
                    if len(raw) + len(chunk) > MAX_RECEIPT_BYTES:
                        raise ValueError
                    raw.extend(chunk)
                # Reject duplicate keys and non-JSON numbers before strict wire
                # validation; never echo rejected clinical text or HTTP bodies.
                json.loads(raw, object_pairs_hook=_closed_object, parse_constant=_reject_constant)
                result = CoreSessionPrepReceipt.model_validate_json(raw, strict=True)
            now = self._now()
            if (
                not isinstance(now, datetime)
                or now.tzinfo is None
                or now.utcoffset() is None
                or result.recorded_at > now + timedelta(seconds=5)
            ):
                raise ValueError
            return result
        except ConnectorUnavailable:
            raise
        except httpx.HTTPError:
            raise ConnectorUnavailable("session_prep_request_unconfirmed") from None
        except (ValueError, TypeError, AttributeError, RecursionError):
            raise ConnectorUnavailable("session_prep_receipt_invalid") from None
