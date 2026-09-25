"""Owned synthetic-only process harness; never accepts a remote destination."""

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

        def do_POST(self):
            import hashlib

            count = int(self.headers.get("content-length", "0"))
            assert 0 <= count <= 16777216
            raw = self.rfile.read(count)
            operation = self.headers.get("s-idempotency-key")
            append(
                "receiver.jsonl",
                {
                    "method": "POST",
                    "path": self.path,
                    "operation": operation,
                    "body_sha256": hashlib.sha256(raw).hexdigest(),
                    "content_type": self.headers.get("content-type"),
                    "invented_auth_matches": self.headers.get("Authorization")
                    == "Bearer invented-process-token",
                },
            )
            while (root / "hold-response").exists():
                time.sleep(0.025)
            self.reply({"requestId": "request_" + operation.replace("-", "")})

        def do_GET(self):
            if self.path == "/health":
                self.reply({"ready": True})
                return
            append("receiver.jsonl", {"method": "GET", "path": self.path})
            item = self.path.rsplit("/", 1)[-1]
            self.reply(
                {
                    "conversationItem": {
                        "id": item,
                        "requestId": "request_" + item.removeprefix("item_"),
                        "direction": "outbound",
                        "isInternalNote": False,
                    }
                }
            )

    ThreadingHTTPServer(("127.0.0.1", configuration["receiver_port"]), Handler).serve_forever()
else:
    assert sys.argv[1] == "os"
    import httpx
    import uvicorn
    from cryptography.hazmat.primitives import serialization

    from cosmas_os.adapters.vendor_connectors.transport import Credential
    from cosmas_os.api import app as api
    from cosmas_os.api.auth import ClerkTokenVerifier
    from cosmas_os.application import vendor_events, vendor_execution

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
            assert request.url.scheme == "https" and request.url.host == "api.sprucehealth.com"
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
            secret="invented-process-token",
        )

    def execution_factory(identity):
        return vendor_execution.VendorExecution(
            api.SessionLocal, credentials, transport=LocalTransport(), identity_current=identity
        )

    api.app.dependency_overrides[api._vendor_execution_factory] = lambda: execution_factory
    route = vendor_events.EventRoute(
        configuration["event_route"],
        configuration["connection_id"],
        "spruce",
        b"invented-process-webhook",
    )
    api.app.dependency_overrides[api._vendor_event_routes] = lambda: (
        lambda family, rid: route if (family, rid) == ("spruce", route.route_id) else None
    )
    uvicorn.run(
        api.app,
        host="127.0.0.1",
        port=configuration["os_port"],
        log_level="warning",
        access_log=False,
    )
