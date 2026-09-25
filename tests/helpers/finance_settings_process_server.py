"""Owned synthetic Stripe process harness; fixed host mapped only to loopback."""

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

configuration = json.loads(Path(sys.argv[2]).read_text())
root = Path(configuration["root"])
assert root.is_absolute() and str(root).startswith(
    "/Users/jw/Desktop/Cosmas/cosmas-beta-local-recovery-"
)
assert configuration["receiver_origin"].startswith("http://127.0.0.1:")


def append(name, value):
    with (root / name).open("a") as target:
        target.write(json.dumps(value, separators=(",", ":")) + "\n")
        target.flush()
        os.fsync(target.fileno())


if sys.argv[1] == "receiver":
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, data):
            raw = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def payment(self, operation, paid=False):
            return {
                "object": "payment_intent",
                "id": "pi_" + operation.replace("-", ""),
                "customer": "cus_Invented",
                "amount": 12500,
                "currency": "usd",
                "livemode": False,
                "status": "succeeded" if paid else "requires_confirmation",
                "amount_received": 12500 if paid else 0,
                "client_secret": "never-expose-this-secret",
            }

        def do_POST(self):
            from urllib.parse import parse_qs

            count = int(self.headers.get("content-length", "0"))
            assert 0 <= count <= 2048
            body = parse_qs(self.rfile.read(count).decode(), strict_parsing=True)
            operation = self.headers.get("Idempotency-Key")
            append(
                "receiver.jsonl",
                {
                    "method": "POST",
                    "path": self.path,
                    "operation": operation,
                    "body": body,
                    "version": self.headers.get("Stripe-Version"),
                    "invented_auth_matches": self.headers.get("Authorization")
                    == "Bearer sk_test_invented",
                },
            )
            while (root / "hold-response").exists():
                time.sleep(0.025)
            self.reply(self.payment(operation))

        def do_GET(self):
            if self.path == "/health":
                self.reply({"ready": True})
                return
            append("receiver.jsonl", {"method": "GET", "path": self.path})
            self.reply(self.payment(self.path.rsplit("/", 1)[-1].removeprefix("pi_"), paid=True))

    ThreadingHTTPServer(("127.0.0.1", configuration["receiver_port"]), Handler).serve_forever()
else:
    assert sys.argv[1] == "os"
    import httpx
    import uvicorn
    from cryptography.hazmat.primitives import serialization

    from cosmas_os.adapters.vendor_connectors.transport import Credential
    from cosmas_os.api import app as api
    from cosmas_os.api import finance_setup_routes
    from cosmas_os.api.auth import ClerkTokenVerifier
    from cosmas_os.application import finance_events, finance_settings, finance_work
    from cosmas_os.application.finance_settings_execution import FinanceSettingsExecution
    from cosmas_os.ports.vendor_connectors import ConnectionSelection

    key = serialization.load_pem_public_key((root / "public.pem").read_bytes())

    class LocalKeys:
        def get_signing_keys(self, *, refresh):
            return [SimpleNamespace(key_id="invented-process-key", key=key)]

    verifier = ClerkTokenVerifier(
        api.settings, jwks_client=LocalKeys(), start_background_refresh=False
    )
    api._clerk_verifier = lambda: verifier

    class LocalTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False)

        async def handle_async_request(self, request):
            append(
                "transport.jsonl",
                {"phase": "entered", "method": request.method, "host": request.url.host},
            )
            assert request.url.scheme == "https" and request.url.host == "api.stripe.com"
            assert request.url.port in (None, 443) and not request.url.query
            target = httpx.URL(configuration["receiver_origin"]).copy_with(path=request.url.path)
            # The sealed connector still chooses the documented vendor/path/body;
            # only this local harness maps its socket to our separate receiver.
            request.url = target
            try:
                return await self.inner.handle_async_request(request)
            except Exception as error:
                append(
                    "transport.jsonl",
                    {"phase": "error", "type": type(error).__name__, "detail": str(error)},
                )
                raise

        async def aclose(self):
            await self.inner.aclose()

    async def credentials(selection):
        import asyncio

        append("credentials.jsonl", {"connection_id": str(selection.connection_id)})
        while (root / "hold-credentials").exists():
            await asyncio.sleep(0.025)
        return Credential(
            selection_sha256=selection.commitment(),
            credential_ref=str(selection.credential_ref),
            secret="sk_test_invented",
        )

    policy = finance_work.FinancePolicy(enabled=True, io_enabled=True, events_enabled=True)
    installed = finance_settings.Catalog(
        (
            finance_settings.Installation(
                ConnectionSelection.model_validate(configuration["installation"]),
                "Invented installed Stripe sandbox",
            ),
        )
    )
    if not any(getattr(route, "path", None) == "/finance-setup" for route in api.app.routes):
        finance_setup_routes.register(
            api.app, api.get_session, api._identity, reauthenticate=api._vendor_reauthenticate
        )
    setup_policy = getattr(api, "_finance_setup_policy", finance_setup_routes.setup_policy)
    api.app.dependency_overrides[setup_policy] = lambda: finance_settings.FinanceSetupPolicy(
        enabled=True
    )
    api.app.dependency_overrides[finance_setup_routes.installed_catalog] = lambda: installed

    @api.app.middleware("http")
    async def drop_settings_reply(request, call_next):
        response = await call_next(request)
        if (
            request.url.path.startswith("/finance-setup/")
            and request.method == "POST"
            and request.headers.get("x-invented-drop-reply") == "1"
            and response.status_code == 200
        ):
            import asyncio

            append("committed-settings.jsonl", {"path": request.url.path})
            while True:
                await asyncio.sleep(0.025)
        return response

    def execution_factory(identity):
        return FinanceSettingsExecution(
            api.SessionLocal,
            credentials,
            policy=policy,
            transport=LocalTransport(),
            identity_current=identity,
            installed_catalog=lambda: installed,
        )

    route = finance_events.FinanceEventRoute(
        configuration["event_route"],
        configuration["connection_id"],
        b"invented-process-webhook",
    )
    api.app.dependency_overrides[api._finance_policy] = lambda: policy
    api.app.dependency_overrides[api._finance_execution_factory] = lambda: execution_factory
    api.app.dependency_overrides[api._finance_event_routes] = lambda: (
        lambda rid: route if rid == route.route_id else None
    )
    uvicorn.run(
        api.app,
        host="127.0.0.1",
        port=configuration["os_port"],
        log_level="warning",
        access_log=False,
    )
