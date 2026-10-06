"""Owned local HTTP recipient for completed administrative-action qualification.

This is an explicit provider/recipient substitute. It implements only the
documented Spruce secure-message paths used by the real product adapter; it is
never installed in a real provider runtime and accepts no external destination.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import httpx

MAX_BYTES = 1_048_576
SYNTHETIC_CREDENTIAL = "invented-completed-action-only"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                     sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class CompletedActionSandbox:
    """Independent receiver receipts, distinct from provider queue acceptance."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        self.lock = threading.Lock()
        self.items = {}
        self.posts = 0
        self.reads = 0
        self.server = None
        self.thread = None

    def _append(self, name, value):
        path = self.root / name
        with path.open("a") as file:
            file.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
            file.flush()
            os.fsync(file.fileno())

    def receipt(self, operation_id):
        with self.lock:
            return json.loads(json.dumps(self.items[operation_id]["receiver"]))

    def counters(self):
        with self.lock:
            return {"submission_requests": self.posts, "receiver_items": len(self.items), "status_reads": self.reads}

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def reply(self, status, value):
                raw = json.dumps(value, separators=(",", ":")).encode()
                self.send_response(status)
                for key, value in {"Content-Type": "application/json", "Content-Length": str(len(raw)),
                                   "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def authenticated(self):
                return self.headers.get("Authorization") == "Bearer " + SYNTHETIC_CREDENTIAL

            def do_POST(self):
                if not self.authenticated():
                    return self.reply(401, {"error": "synthetic_account_required"})
                if not re.fullmatch(r"/v1/internalendpoints/[A-Za-z0-9_=+-]+/conversations", self.path):
                    return self.reply(404, {"error": "fixed_path_required"})
                try:
                    size = int(self.headers["Content-Length"])
                    if not 0 < size <= MAX_BYTES or self.headers.get("Content-Type") != "application/json":
                        raise ValueError
                    raw = self.rfile.read(size)
                    value = json.loads(raw)
                    operation = self.headers["s-idempotency-key"]
                    if str(UUID(operation)) != operation or UUID(operation).version != 4:
                        raise ValueError
                    destination = value["destination"]["secureEndpoint"]
                    message = value["message"]
                    if (set(value) != {"destination", "message"} or set(value["destination"]) != {"secureEndpoint"}
                            or set(destination) != {"contactId", "deliveryMethod"}
                            or not destination["contactId"].startswith("virtual_")
                            or destination["deliveryMethod"] != "only_conversations_matching_internal_endpoint"
                            or message["internal"] is not False or set(message) != {"body", "internal"}
                            or len(message["body"]) != 1 or message["body"][0]["type"] != "text"):
                        raise ValueError
                    content = message["body"][0]["value"]
                    if not isinstance(content, str) or not 1 <= len(content) <= 4000:
                        raise ValueError
                except (ValueError, KeyError, TypeError):
                    return self.reply(422, {"error": "closed_synthetic_message_required"})
                with owner.lock:
                    owner.posts += 1
                    if operation in owner.items:
                        owner._append("duplicate-submissions.jsonl", {"operation_id": operation,
                            "body_sha256": hashlib.sha256(raw).hexdigest()})
                        return self.reply(409, {"error": "duplicate_submission"})
                    now = datetime.now(UTC).isoformat()
                    request_id = "request_" + operation.replace("-", "")
                    item_id = "item_" + operation.replace("-", "")
                    receipt = {"contract": "cosmabot.virtual-receiver-receipt.v1", "id": str(uuid4()),
                        "operation_id": operation, "request_id": request_id, "item_id": item_id,
                        "recipient": destination["contactId"], "state": "received", "observed_at": now,
                        "content": content, "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "wire_sha256": hashlib.sha256(raw).hexdigest(), "synthetic_only": True}
                    receipt["sha256"] = digest(receipt)
                    owner.items[operation] = {"receiver": receipt, "request": value}
                    owner._append("receiver.jsonl", receipt)
                    owner._append("publisher.jsonl", {"operation_id": operation, "request_id": request_id,
                        "state": "accepted", "wire_sha256": receipt["wire_sha256"], "observed_at": now})
                return self.reply(200, {"requestId": request_id})

            def do_GET(self):
                if self.path == "/health":
                    return self.reply(200, {"ready": True, "synthetic_only": True})
                if not self.authenticated():
                    return self.reply(401, {"error": "synthetic_account_required"})
                if not re.fullmatch(r"/v1/conversationItems/item_[0-9a-f]{32}", self.path):
                    return self.reply(404, {"error": "fixed_path_required"})
                item_id = self.path.rsplit("/", 1)[1]
                with owner.lock:
                    item = next((value["receiver"] for value in owner.items.values()
                                 if value["receiver"]["item_id"] == item_id), None)
                    if item is None:
                        return self.reply(404, {"error": "unknown_reference"})
                    owner.reads += 1
                    owner._append("reads.jsonl", {"item_id": item_id, "receiver_receipt_id": item["id"],
                                                 "observed_at": datetime.now(UTC).isoformat()})
                return self.reply(200, {"conversationItem": {"id": item_id, "requestId": item["request_id"],
                    "direction": "outbound", "isInternalNote": False}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return "http://127.0.0.1:" + str(self.server.server_port)

    def close(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=3)
        (self.root / "CLEANUP.json").write_text(json.dumps({"listener_closed": True,
            "thread_stopped": self.thread is None or not self.thread.is_alive(),
            "counters": self.counters()}, indent=2) + "\n")


class SandboxVendorTransport(httpx.AsyncBaseTransport):
    """Map a fixed provider origin to the one owned receiver; real socket I/O."""

    def __init__(self, origin):
        parsed = httpx.URL(origin)
        if parsed.scheme != "http" or parsed.host != "127.0.0.1" or parsed.port is None or parsed.path != "/":
            raise ValueError("owned_loopback_origin_required")
        self.origin = parsed
        self.inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False)

    async def handle_async_request(self, request):
        if (request.url.scheme != "https" or request.url.host != "api.sprucehealth.com"
                or request.url.port not in (None, 443) or request.url.query
                or not ((request.method == "POST" and re.fullmatch(
                    r"/v1/internalendpoints/[A-Za-z0-9_%=+-]+/conversations", request.url.path))
                    or (request.method == "GET" and re.fullmatch(r"/v1/conversationItems/item_[0-9a-f]{32}", request.url.path)))):
            raise httpx.ConnectError("sandbox_fixed_vendor_path_required")
        request.url = self.origin.copy_with(path=request.url.path)
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()
