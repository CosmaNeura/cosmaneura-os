"""Fixed-origin eFax received metadata and explicitly approved image acquisition.

Image GET marks the provider fax downloaded/read. The product must commit its
one-shot F8 claim before dispatch; this adapter supplies no retry or queue.
https://consensus.stoplight.io/docs/fax-services/9f6168083b0ef-retrieve-a-fax-s-image
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from time import monotonic

import httpx

from cosmas_os.adapters.vendor_connectors.transport import Credential, parse_json
from cosmas_os.ports.efax_inbound import (
    MAX_IMAGE_BYTES,
    MAX_LIST_BYTES,
    MAX_PAGES,
    MAX_PDF_BYTES,
    Acquired,
    Failure,
    FaxMetadata,
    ImageApproval,
    ImageCommand,
    ImageReceipt,
    ListRequest,
    ListSnapshot,
)
from cosmas_os.ports.vendor_connectors import ConnectionSelection, digest

ORIGIN = "https://api.securedocex.com"


class EFaxInboundConnector:
    def __init__(
        self,
        selection: ConnectionSelection,
        credentials: Callable[[ConnectionSelection], Awaitable[Credential]],
        *,
        enabled: bool = False,
        authorize: Callable[..., Awaitable[bool]] | None = None,
        before_image_dispatch: Callable[..., Awaitable[bool]] | None = None,
        pdf_validator: Callable[[bytes], Awaitable[int]] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.selection = ConnectionSelection.model_validate(selection.model_dump(mode="python"))
        if (
            self.selection.vendor != "efax"
            or self.selection.environment != "production"
            or type(enabled) is not bool
            or not callable(credentials)
        ):
            raise Failure("unsupported_selection")
        self.credentials, self.enabled, self.authorize = credentials, enabled, authorize
        self.before_image_dispatch, self.pdf_validator = before_image_dispatch, pdf_validator
        self.transport, self.now = transport, now

    async def _authority(self, request, approval=None):
        if (
            not self.enabled
            or self.authorize is None
            or self.selection != request.selection
            or await self.authorize(request, approval) is not True
        ):
            raise Failure("authority_required")

    async def _headers(self):
        current = await self.credentials(self.selection)
        if (
            not isinstance(current, Credential)
            or current.selection_sha256 != self.selection.commitment()
            or current.credential_ref != str(self.selection.credential_ref)
        ):
            raise Failure("credential_changed")
        token = current.secret.get_secret_value()
        if not 1 <= len(token) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise Failure("credential_changed")
        return {
            "Authorization": "Bearer " + token,
            "user-id": self.selection.remote_account_id,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-store",
        }

    async def _get(self, path, headers, cap, params=None):
        deadline = monotonic() + 10
        async with asyncio.timeout(10):
            async with httpx.AsyncClient(
                transport=self.transport, trust_env=False, follow_redirects=False, timeout=10
            ) as client:
                async with client.stream(
                    "GET", ORIGIN + path, headers=headers, params=params
                ) as response:
                    if (
                        response.status_code != 200
                        or response.headers.get("content-encoding", "identity") != "identity"
                        or response.headers.get("content-type", "").split(";", 1)[0].lower()
                        != "application/json"
                        or sum(len(k) + len(v) for k, v in response.headers.raw) > 8192
                    ):
                        raise Failure("response_invalid")
                    raw = bytearray()
                    async for piece in response.aiter_bytes():
                        if monotonic() >= deadline or len(raw) + len(piece) > cap:
                            raise Failure("response_too_large")
                        raw.extend(piece)
                    length = response.headers.get("content-length")
                    if length is not None and (
                        not length.isascii() or not length.isdigit() or int(length) != len(raw)
                    ):
                        raise Failure("response_invalid")
        # The generic vendor parser intentionally has a lower cap for outbound
        # operations. Inbound image base64 has its independently bounded cap.
        from cosmas_os.adapters.vendor_connectors.efax_inbound_json import parse_image_json

        data = parse_image_json(bytes(raw)) if cap == MAX_IMAGE_BYTES else parse_json(bytes(raw))
        if monotonic() >= deadline:
            raise Failure("response_deadline")
        return data, hashlib.sha256(raw).hexdigest()

    async def list_received(self, request: ListRequest) -> ListSnapshot:
        request = ListRequest.model_validate(request.model_dump(mode="python"))
        if request.ends_at > self.now() + timedelta(seconds=5):
            raise Failure("request_invalid")
        await self._authority(request)
        headers = await self._headers()
        headers.update(
            {"pagination-limit": str(request.limit), "pagination-offset": str(request.offset)}
        )
        await self._authority(request)
        data, raw_hash = await self._get(
            "/faxes/received",
            headers,
            MAX_LIST_BYTES,
            params={
                "min_completed_timestamp": request.starts_at.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z"),
                "max_completed_timestamp": request.ends_at.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z"),
            },
        )
        if (
            type(data) is not dict
            or set(data) != {"first_record", "last_record", "faxes"}
            or type(data["faxes"]) is not list
        ):
            raise Failure("response_invalid")
        try:
            items = tuple(FaxMetadata.model_validate(item) for item in data["faxes"])
            values: dict[str, object] = dict(
                request=request,
                first_record=data["first_record"],
                last_record=data["last_record"],
                items=items,
                observed_at=self.now(),
                raw_sha256=raw_hash,
            )
            provisional = ListSnapshot.model_construct(_fields_set=set(values), **values)
            result = ListSnapshot.model_validate(
                {**values, "source_sha256": provisional.commitment()}
            )
        except ValueError:
            raise Failure("response_invalid") from None
        await self._authority(request)
        return result

    async def acquire_image(
        self, command: ImageCommand, approval: ImageApproval, snapshot: ListSnapshot
    ) -> Acquired:
        command = ImageCommand.model_validate(command.model_dump(mode="python"))
        approval = ImageApproval.model_validate(approval.model_dump(mode="python"))
        snapshot = ListSnapshot.model_validate(snapshot.model_dump(mode="python"))
        now = self.now()
        if (
            self.before_image_dispatch is None
            or command.selection != snapshot.request.selection
            or command.source_sha256 != snapshot.source_sha256
            or not any(item.fax_id == command.fax_id for item in snapshot.items)
            or not now - timedelta(minutes=5) <= snapshot.observed_at <= now + timedelta(seconds=5)
            or approval.operation_id != command.operation_id
            or approval.operator_id != command.selection.owner_id
            or approval.command_sha256 != command.commitment()
            or approval.selection_sha256 != command.selection.commitment()
            or not approval.approved_at <= now < approval.expires_at <= command.expires_at
            or not now < command.expires_at <= now + timedelta(minutes=5)
        ):
            raise Failure("approval_required")
        item = next(item for item in snapshot.items if item.fax_id == command.fax_id)
        if item.fax_status == "NOT_STORED" or not 1 <= item.pages <= MAX_PAGES:
            raise Failure("image_unavailable")
        initial = ImageReceipt(
            operation_id=command.operation_id,
            command_sha256=command.commitment(),
            selection_sha256=command.selection.commitment(),
            fax_id=command.fax_id,
            state="not_attempted",
            attempted=False,
            provider_read_state="unchanged_by_this_attempt",
            content_available=False,
            observed_at=now,
        )
        await self._authority(command, approval)
        headers = await self._headers()
        await self._authority(command, approval)
        uncertain = initial.model_copy(
            update={
                "state": "outcome_unconfirmed",
                "attempted": True,
                "provider_read_state": "may_have_changed",
                "observed_at": self.now(),
            }
        )
        try:
            # A false result proves no dispatch authorization. An exception can
            # follow a committed claim, so it retains uncertainty conservatively.
            if await self.before_image_dispatch(command, approval) is not True:
                return Acquired(initial, None)
        except Exception:
            return Acquired(uncertain, None)
        raw_hash = None
        try:
            data, raw_hash = await self._get(
                "/faxes/" + str(command.fax_id) + "/image",
                headers,
                MAX_IMAGE_BYTES,
                params={"desired_format": "PDF"},
            )
            if (
                type(data) is not dict
                or set(data) != {"fax_id", "file_name", "image"}
                or data["fax_id"] != str(command.fax_id)
            ):
                raise Failure("response_invalid")
            name, encoded = data["file_name"], data["image"]
            if (
                type(name) is not str
                or not 1 <= len(name) <= 128
                or name != name.strip()
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or "/" in name
                or "\\" in name
                or type(encoded) is not str
                or len(encoded) > ((MAX_PDF_BYTES + 2) // 3) * 4
            ):
                raise Failure("response_invalid")
            document = base64.b64decode(encoded.encode("ascii"), validate=True)
            if (
                base64.b64encode(document).decode("ascii") != encoded
                or not 1 <= len(document) <= MAX_PDF_BYTES
            ):
                raise Failure("document_needs_human")
            try:
                if self.pdf_validator is None:
                    raise Failure("validator_unavailable")
                pages = await self.pdf_validator(document)
                if type(pages) is not int or not 1 <= pages <= MAX_PAGES or pages != item.pages:
                    raise Failure("document_needs_human")
            except Exception:
                result = uncertain.model_copy(
                    update={
                        "state": "needs_human",
                        "response_sha256": raw_hash,
                        "provider_read_state": "endpoint_reported_download",
                        "observed_at": self.now(),
                    }
                )
                return Acquired(result, None)
            await self._authority(command, approval)
            if self.now() >= min(command.expires_at, approval.expires_at):
                raise Failure("authority_expired")
            doc_hash = hashlib.sha256(document).hexdigest()
            source = digest(
                "cosmas-efax-inbound-image.v1",
                {
                    "command_sha256": command.commitment(),
                    "list_source_sha256": snapshot.source_sha256,
                    "fax_id": str(command.fax_id),
                    "response_sha256": raw_hash,
                    "document_sha256": doc_hash,
                    "byte_length": len(document),
                    "pages": pages,
                },
            )
            result = uncertain.model_copy(
                update={
                    "state": "acquired",
                    "content_available": True,
                    "provider_read_state": "endpoint_reported_download",
                    "response_sha256": raw_hash,
                    "document_sha256": doc_hash,
                    "source_sha256": source,
                    "byte_length": len(document),
                    "pages": pages,
                    "observed_at": self.now(),
                }
            )
            return Acquired(result, document)
        except Exception:
            return Acquired(
                uncertain.model_copy(
                    update={"response_sha256": raw_hash, "observed_at": self.now()}
                ),
                None,
            )
