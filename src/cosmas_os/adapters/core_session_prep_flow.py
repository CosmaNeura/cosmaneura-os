"""Use Core's canonical provider action before opening its preparation artifact."""

import json
from datetime import timedelta
from typing import Literal
from uuid import UUID

import httpx
from pydantic import AwareDatetime, Field, SecretStr

from cosmas_os.adapters.core_session_prep import (
    HttpCoreSessionPrep,
    _closed_object,
    _reject_constant,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_capture import (
    ActorRef,
    CoreCaptureSelection,
    CoreInteractionCredential,
    CoreMountToken,
    TenantRef,
)
from cosmas_os.ports.core_session_prep import CoreSessionPrepRead, CoreSessionPrepReceipt, Reference
from cosmas_os.ports.core_session_prep_flow import CoreSessionPrepContext
from cosmas_os.ports.scribe_capture import ProtectedModel


class _Resolved(ProtectedModel):
    surface: Literal["provider_assistant"]
    auth_tier: Literal["provider"]
    capabilities: tuple[str, ...] = Field(max_length=100)
    actor_id: ActorRef
    tenant_id: TenantRef


class _TurnReceipt(ProtectedModel):
    client_turn_id: UUID
    turn_ref: Reference
    phase: Literal["user_accepted", "final_response"]
    state: Literal["accepted", "completed"]
    recorded_at: AwareDatetime


class HttpCoreSessionPrepFlow(HttpCoreSessionPrep):
    def _context_request(self, path, body, headers, status, *, turn=None):
        try:
            with self._client.stream(
                "POST",
                self._origin + path,
                json=body,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Cache-Control": "no-store",
                    **headers,
                },
            ) as response:
                if response.status_code in {401, 403, 404, 410}:
                    raise ConnectorUnavailable("session_prep_access_unavailable")
                if response.status_code == 409:
                    raise ConnectorUnavailable("session_prep_request_conflict")
                if response.status_code != status:
                    raise ConnectorUnavailable("session_prep_request_unconfirmed")
                if (
                    response.headers.get("content-type", "").partition(";")[0].strip().lower()
                    != "application/json"
                    or "no-store"
                    not in {
                        v.strip().lower()
                        for v in response.headers.get("cache-control", "").split(",")
                    }
                    or response.headers.get("content-encoding", "identity").lower() != "identity"
                    or turn is not None
                    and response.headers.get("X-Cosmaneura-Client-Turn-ID") != str(turn)
                ):
                    raise ValueError
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=16384):
                    if len(raw) + len(chunk) > 16384:
                        raise ValueError
                    raw.extend(chunk)
                json.loads(raw, object_pairs_hook=_closed_object, parse_constant=_reject_constant)
                return bytes(raw), response.headers
        except ConnectorUnavailable:
            raise
        except httpx.HTTPError:
            raise ConnectorUnavailable("session_prep_request_unconfirmed") from None
        except (ValueError, TypeError, AttributeError, RecursionError):
            raise ConnectorUnavailable("session_prep_receipt_invalid") from None

    def exchange_context(self, selection, bearer: SecretStr):
        try:
            selection = CoreCaptureSelection.model_validate(
                selection.model_dump(mode="python"), strict=True
            )
            raw = bearer.get_secret_value()
            if (
                not 1 <= len(raw) <= 8192
                or not raw.isascii()
                or not raw.isprintable()
                or any(c.isspace() for c in raw)
            ):
                raise ValueError
            data, headers = self._context_request(
                "/embed/v1/context-tokens/exchange",
                {
                    "requested_surface": "provider_assistant",
                    "record_ref": selection.appointment_ref,
                },
                {"Authorization": "Bearer " + raw, "X-Cosmaneura-Embed-Version": "1.0"},
                201,
            )
            token = CoreMountToken.model_validate_json(data, strict=True)
            now = self._now()
            if (
                headers.get("X-Cosmaneura-Embed-Version") != "1.0"
                or not now - timedelta(seconds=30) <= token.issued_at <= now + timedelta(seconds=5)
                or not token.issued_at < token.refresh_after < token.expires_at
                or token.expires_at <= now
            ):
                raise ValueError
            return token
        except (ValueError, TypeError, AttributeError):
            raise ConnectorUnavailable("session_prep_context_invalid") from None

    def resolve_context(self, selection, token, client_turn_id):
        try:
            selection = CoreCaptureSelection.model_validate(
                selection.model_dump(mode="python"), strict=True
            )
            token = CoreMountToken.model_validate(token.model_dump(mode="python"), strict=True)
            if not isinstance(client_turn_id, UUID):
                raise ValueError
            if token.expires_at <= self._now():
                raise ValueError
            data, headers = self._context_request(
                "/service/v1/agent/mount-context/resolve",
                None,
                {
                    **self._workload_headers(),
                    "X-Cosmaneura-Mount-Context": token.context_token.get_secret_value(),
                    "X-Cosmaneura-Client-Turn-ID": str(client_turn_id),
                },
                200,
                turn=client_turn_id,
            )
            context = _Resolved.model_validate_json(data, strict=True)
            if (
                context.actor_id != selection.expected_actor_ref
                or context.tenant_id != selection.expected_tenant_ref
                or "session-prep:read" not in context.capabilities
            ):
                raise ValueError
            return CoreSessionPrepContext(
                credential=CoreInteractionCredential(
                    mount_context_token=token.context_token,
                    interaction_ref=headers["X-Cosmaneura-Interaction-Ref"],
                    client_turn_id=client_turn_id,
                ),
                context_snapshot_ref=headers["X-Cosmaneura-Session-Prep-Context"],
            )
        except (ValueError, TypeError, AttributeError, KeyError):
            raise ConnectorUnavailable("session_prep_context_invalid") from None

    def _write_turn(self, credential, body, key):
        data, headers = self._context_request(
            "/service/v1/agent/conversation-turns/write",
            body,
            {
                **self._workload_headers(),
                "X-Cosmaneura-Mount-Context": credential.mount_context_token.get_secret_value(),
                "X-Cosmaneura-Interaction-Ref": credential.interaction_ref,
                "X-Cosmaneura-Client-Turn-ID": str(credential.client_turn_id),
                "Idempotency-Key": key,
            },
            201,
            turn=credential.client_turn_id,
        )
        try:
            receipt = _TurnReceipt.model_validate_json(data, strict=True)
            if (
                receipt.client_turn_id != credential.client_turn_id
                or receipt.phase != body["phase"]
                or receipt.state
                != ("accepted" if body["phase"] == "user_accepted" else "completed")
                or receipt.recorded_at > self._now() + timedelta(seconds=5)
                or headers.get("Idempotency-Replayed") not in {"true", "false"}
            ):
                raise ValueError
            return receipt
        except (ValueError, TypeError, AttributeError):
            raise ConnectorUnavailable("session_prep_receipt_invalid") from None

    def accept_action(self, context):
        try:
            context = CoreSessionPrepContext.model_validate(
                context.model_dump(mode="python"), strict=True
            )
        except (ValueError, TypeError, AttributeError):
            raise ConnectorUnavailable("session_prep_scope_invalid") from None
        receipt = self._write_turn(
            context.credential,
            {
                "phase": "user_accepted",
                "ingress_kind": "provider_ui_action",
                "action_code": "session-prep.open",
                "message": {"content_type": "text/plain", "content": "Open Session Prep"},
            },
            "session-prep-open." + str(context.credential.client_turn_id),
        )
        return CoreSessionPrepRead(
            credential=context.credential,
            source_turn_ref=receipt.turn_ref,
            context_snapshot_ref=context.context_snapshot_ref,
            idempotency_key="session-prep-read." + str(context.credential.client_turn_id),
        )

    def complete_action(self, selection, result):
        try:
            selection = CoreSessionPrepRead.model_validate(
                selection.model_dump(mode="python"), strict=True
            )
            result = CoreSessionPrepReceipt.model_validate(
                result.model_dump(mode="python"), strict=True
            )
        except (ValueError, TypeError, AttributeError):
            raise ConnectorUnavailable("session_prep_scope_invalid") from None
        ready = result.result.state in {"ready", "refreshing"}
        receipt = self._write_turn(
            selection.credential,
            {
                "phase": "final_response",
                "outcome": "completed" if ready else "unavailable",
                "response": {
                    "content_type": "text/plain",
                    "content": {
                        "ready": "Session Prep is ready to review.",
                        "refreshing": "The previous Session Prep is available while it refreshes.",
                        "pending": "Session Prep is being prepared.",
                        "unavailable": "Session Prep is not currently available.",
                    }[result.result.state],
                },
                "presentation": {"mode": "standard", "suppress": [], "human_contact": None},
            },
            "session-prep-final." + str(selection.credential.client_turn_id),
        )
        if receipt.turn_ref != selection.source_turn_ref:
            raise ConnectorUnavailable("session_prep_receipt_invalid")
