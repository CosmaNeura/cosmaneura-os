"""Explicit eFax inbound application invocations; no polling or automatic retry."""

from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from cosmas_os.adapters.efax_pdf_validation import validate_received_pdf
from cosmas_os.adapters.vendor_connectors.efax_inbound import EFaxInboundConnector
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.application import efax_inbound as ledger
from cosmas_os.efax_inbound_models import EFaxInboundGrant
from cosmas_os.ports.vendor_connectors import ConnectionSelection


class EFaxInboundExecution:
    """Host installs accounts explicitly; authenticated identity remains request-scoped."""

    def __init__(
        self,
        sessions: Callable[[], Session],
        installations: tuple[ledger.Installation, ...],
        credentials: Callable[[ConnectionSelection], Awaitable[Credential]],
        *,
        identity_current: Callable[[], Awaitable[bool]],
        enabled: Callable[[], bool],
        transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
    ):
        if (
            not callable(sessions)
            or not callable(credentials)
            or not callable(identity_current)
            or not callable(enabled)
            or any(type(item) is not ledger.Installation for item in installations)
        ):
            raise ValueError("Explicit inbound host configuration required")
        if len(installations) > 50 or len(
            {str(item.selection.connection_id) for item in installations}
        ) != len(installations):
            raise ValueError("Distinct bounded inbound accounts required")
        self._sessions, self.installations, self._credentials = (
            sessions,
            tuple(installations),
            credentials,
        )
        self._identity_current, self._enabled, self._transport_factory = (
            identity_current,
            enabled,
            transport_factory,
        )

    def current(self, session, supplied):
        if self._enabled() is not True:
            return False
        selected = (
            ConnectionSelection.model_validate(supplied.selection)
            if isinstance(supplied, EFaxInboundGrant)
            else supplied.selection
        )
        matches = [item for item in self.installations if item.selection == selected]
        if len(matches) != 1:
            return False
        match = matches[0]
        return match.metadata_enabled and (
            not isinstance(supplied, EFaxInboundGrant)
            or (
                match.label == supplied.label
                and match.metadata_enabled == supplied.metadata_enabled
                and (not supplied.image_enabled or match.image_enabled)
            )
        )

    async def _identity(self):
        if self._enabled() is not True or await self._identity_current() is not True:
            ledger.error("efax_inbound_unavailable", 403)

    async def _db(self, call):
        def scoped():
            with self._sessions() as session:
                return call(session)

        return await run_in_threadpool(scoped)

    def _connector(self, selection, authority, before=None):
        return EFaxInboundConnector(
            selection,
            self._credentials,
            enabled=self._enabled(),
            authorize=authority,
            before_image_dispatch=before,
            pdf_validator=validate_received_pdf,
            transport=self._transport_factory() if self._transport_factory else None,
        )

    async def observe(self, box, owner, request):
        await self._identity()
        result, intent = await self._db(
            lambda s: ledger.reserve_observation(
                s,
                box,
                owner,
                request.grant_id,
                key=request.idempotency_key,
                starts_at=request.starts_at,
                ends_at=request.ends_at,
                limit=request.limit,
                offset=request.offset,
                current=self.current,
            )
        )
        if intent is None:
            return result  # DB-only recovery; never reissue this observation request.

        async def authorize(wire, approval):
            await self._identity()
            return await self._db(lambda s: self._observation_current(s, intent, wire))

        connector = self._connector(intent.request.selection, authorize)
        try:
            snapshot = await connector.list_received(intent.request)
            await self._identity()
            return await self._db(
                lambda s: ledger.settle_observation(s, intent, snapshot, current=self.current)
            )
        except Exception:
            # A lost read reply is recovered by its retained ID. A new explicit
            # operator check may create a new bounded metadata request.
            return await self._db(
                lambda s: ledger.resolve_observation(
                    s, box, owner, key=request.idempotency_key, current=self.current
                )
            )

    def _observation_current(self, session, intent, wire):
        if wire != intent.request:
            return False
        ledger._grant(
            session, intent.box_id, intent.owner_id, intent.grant_id, current=self.current
        )
        return True

    async def acquire(self, box, owner, request):
        await self._identity()
        result, invocation = await self._db(
            lambda s: ledger.claim_image(
                s,
                box,
                owner,
                key=request.idempotency_key,
                ticket_id=request.ticket_id,
                revision_id=request.revision_id,
                expected_version=request.expected_version,
                approval_sha256=request.approval_sha256,
                current=self.current,
            )
        )
        if invocation is None:
            return result  # Permanent one-shot resource fence, including fresh processes.

        async def authorize(command, approval):
            await self._identity()
            if command != invocation.command or approval != invocation.approval:
                return False
            return await self._db(
                lambda s: ledger.authorize_invocation(s, invocation, current=self.current)
            )

        async def before(command, approval):
            if await authorize(command, approval) is not True:
                return False
            return await self._db(
                lambda s: ledger.mark_invocation(s, invocation, current=self.current)
            )

        connector = self._connector(invocation.command.selection, authorize, before)
        try:
            acquired = await connector.acquire_image(
                invocation.command, invocation.approval, invocation.snapshot
            )
            await self._db(
                lambda s: ledger.settle_image(s, invocation, acquired.receipt, acquired.document)
            )
        except Exception:
            # Never erase or retry a claimed/possibly-dispatched attempt.
            pass
        await self._identity()
        return await self._db(
            lambda s: ledger.resolve_image(
                s, box, owner, key=request.idempotency_key, current=self.current
            )
        )
