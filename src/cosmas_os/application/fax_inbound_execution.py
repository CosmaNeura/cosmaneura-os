"""Installed fixed-origin read runtime; no account discovery or implicit activation."""

import asyncio
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from starlette.concurrency import run_in_threadpool

from cosmas_os.adapters.vendor_connectors.spruce_fax_inbound import SpruceFaxInbound
from cosmas_os.adapters.vendor_connectors.transport import ORIGINS, Credential
from cosmas_os.application import fax_inbound as ledger
from cosmas_os.application.fax_inbound_provider import adapter
from cosmas_os.ports.fax_inbound import MAX_METADATA_BYTES, MAX_PDF_BYTES


class Execution:
    def __init__(
        self,
        sessions,
        installations,
        credentials,
        *,
        identity_current,
        enabled=lambda: False,
        transport_factory=None,
    ):
        if (
            type(installations) is not tuple
            or len(installations) > 20
            or any(type(i) is not ledger.Installation for i in installations)
            or len({str(i.selection.connection_id) for i in installations}) != len(installations)
        ):
            raise ValueError("Distinct installed inbound accounts required")
        self.sessions, self.installations, self.credentials = sessions, installations, credentials
        self.identity_current, self.enabled, self.transport_factory = (
            identity_current,
            enabled,
            transport_factory,
        )

    def current(self, item):
        return self.enabled() is True and any(i == item for i in self.installations)

    async def _identity(self):
        if self.enabled() is not True or await self.identity_current() is not True:
            ledger.fail(status=403)

    async def _db(self, call):
        def scoped():
            with self.sessions() as s:
                return call(s)

        return await run_in_threadpool(scoped)

    async def _exchange(self, scope, plan, authorize, *, image=False, before=None):
        origin = ORIGINS.get((scope.selection.vendor, scope.selection.environment))
        if origin is None:
            ledger.fail("fax_inbound_not_configured")
        # Plans have already been rebuilt by a closed adapter from retained scope.
        async with asyncio.timeout(35):
            await self._identity()
            if await authorize() is not True:
                ledger.fail(status=403)
            credential = await self.credentials(scope.selection)
            if (
                type(credential) is not Credential
                or credential.selection_sha256 != scope.selection.commitment()
                or credential.credential_ref != str(scope.selection.credential_ref)
            ):
                ledger.fail("fax_inbound_account_changed", 403)
            secret = credential.secret.get_secret_value()
            if not 1 <= len(secret.encode()) <= 8192 or any(c in secret for c in "\r\n\x00"):
                ledger.fail("fax_inbound_not_configured")
            headers = {
                "Accept": "application/pdf" if image else "application/json",
                "Accept-Encoding": "identity",
            }
            content = None
            if scope.selection.vendor == "srfax":
                content = urlencode(
                    [
                        *plan.fields,
                        ("access_id", scope.selection.remote_account_id),
                        ("access_pwd", secret),
                    ]
                ).encode("ascii")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                if any(c.isspace() for c in secret):
                    ledger.fail("fax_inbound_not_configured")
                headers["Authorization"] = (
                    "Basic " if scope.selection.vendor == "documo" else "Bearer "
                ) + secret
            await self._identity()
            if await authorize() is not True:
                ledger.fail(status=403)
            maximum = (
                ((MAX_PDF_BYTES * 4 + 2) // 3 + 131072)
                if image and scope.selection.vendor == "srfax"
                else MAX_PDF_BYTES
                if image
                else MAX_METADATA_BYTES
            )
            if before is not None and await before() is not True:
                ledger.fail("fax_inbound_attempt_unavailable")
            async with httpx.AsyncClient(
                transport=self.transport_factory() if self.transport_factory else None,
                verify=True,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(30, connect=5),
            ) as client:
                async with client.stream(
                    plan.method, origin + plan.path, headers=headers, content=content
                ) as response:
                    if (
                        response.status_code != 200
                        or response.headers.get("content-encoding", "identity") != "identity"
                    ):
                        ledger.fail("fax_inbound_response_unconfirmed")
                    media = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    expected = (
                        "application/pdf"
                        if image and scope.selection.vendor == "documo"
                        else "application/json"
                    )
                    if media != expected:
                        ledger.fail("fax_inbound_response_unconfirmed")
                    data = bytearray()
                    async for part in response.aiter_bytes():
                        if len(data) + len(part) > maximum:
                            ledger.fail("fax_inbound_response_too_large")
                        data.extend(part)
            return bytes(data)

    async def observe(self, box, actor, request):
        await self._identity()
        result, intent = await self._db(
            lambda s: ledger.reserve_observation(
                s,
                box,
                actor,
                request.grant_id,
                key=request.idempotency_key,
                starts_at=request.starts_at,
                ends_at=request.ends_at,
                limit=request.limit,
                current=self.current,
            )
        )
        if intent is None:
            return result
        cid, gid, scope = intent

        async def authorize():
            await self._identity()
            return await self._db(
                lambda s: bool(ledger.grant_current(s, box, actor, gid, self.current))
            )

        try:
            raw = await self._exchange(
                scope, adapter(scope.selection.vendor).list_plan(scope), authorize
            )
            if scope.selection.vendor == "spruce":
                from cosmas_os.ports.fax_inbound import WirePlan

                parent = await self._exchange(
                    scope, WirePlan("GET", "/v1/conversations/" + scope.conversation_id), authorize
                )
                page = SpruceFaxInbound.parse(scope, raw, parent, datetime.now(UTC))
            else:
                page = adapter(scope.selection.vendor).parse(scope, raw)
            return await self._db(
                lambda s: ledger.settle_observation(
                    s, box, actor, intent, page, current=self.current
                )
            )
        except Exception:
            return await self._db(
                lambda s: ledger.resolve(
                    s, box, actor, key=request.idempotency_key, current=self.current
                )
            )

    async def acquire(self, box, actor, request):
        await self._identity()
        result, invocation = await self._db(
            lambda s: ledger.claim(
                s,
                box,
                actor,
                **request.model_dump(exclude={"idempotency_key"}),
                key=request.idempotency_key,
                current=self.current,
            )
        )
        if invocation is None:
            return result
        _, _, scope, fax, approval = invocation

        async def authorize():
            await self._identity()
            return await self._db(
                lambda s: ledger.authorize(s, box, actor, invocation, current=self.current)
            )

        try:
            provider = adapter(scope.selection.vendor)
            plan = provider.image_plan(scope, fax, approval, datetime.now(UTC))

            async def before():
                return await self._db(
                    lambda s: ledger.mark_dispatch(s, box, actor, invocation, current=self.current)
                )

            raw = await self._exchange(scope, plan, authorize, image=True, before=before)
            document = await provider.image(scope, fax, approval, datetime.now(UTC), raw)
            await self._db(
                lambda s: ledger.settle(s, box, actor, invocation, document, current=self.current)
            )
        except Exception:
            await self._db(
                lambda s: ledger.settle(s, box, actor, invocation, None, current=self.current)
            )
        return await self._db(
            lambda s: ledger.resolve(
                s, box, actor, key=request.idempotency_key, current=self.current
            )
        )
