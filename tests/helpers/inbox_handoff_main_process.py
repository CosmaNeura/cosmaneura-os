"""Owned signed Inbox fixture. Only its exact PostgreSQL socket is permitted."""

# ruff: noqa: E402
import json
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

root = Path(sys.argv[1]).resolve()
assert str(root).startswith("/Users/jw/Desktop/Cosmas/cosmas-beta-local-recovery-")
config = json.loads((root / "configuration.json").read_text())
_connect, _connect_ex, _dns = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo


def checked(sock, address):
    if sock.family != socket.AF_UNIX and (
        not isinstance(address, tuple) or address[:2] != ("127.0.0.1", 55479)
    ):
        raise PermissionError("Only the owned Inbox proof database is authorized")


def connect(sock, address):
    checked(sock, address)
    return _connect(sock, address)


def connect_ex(sock, address):
    checked(sock, address)
    return _connect_ex(sock, address)


def dns(host, port, *args, **kwargs):
    if (host, port) != ("127.0.0.1", 55479):
        raise PermissionError("No Inbox fixture external DNS is authorized")
    return _dns(host, port, *args, **kwargs)


socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
socket.getaddrinfo = dns

import uvicorn
from cryptography.hazmat.primitives import serialization

from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application.inbox_work import InboxReadGrant, InboxRegistry

key = serialization.load_pem_public_key((root / "public.pem").read_bytes())


class LocalKeys:
    def get_signing_keys(self, *, refresh):
        return [SimpleNamespace(key_id="invented-inbox-key", key=key)]


verifier = ClerkTokenVerifier(api.settings, jwks_client=LocalKeys(), start_background_refresh=True)
api._clerk_verifier = lambda: verifier
grants = [] if config.get("registry_removed") else [InboxReadGrant.model_validate(config["grant"])]
installed = InboxRegistry(grants)
app = api.app
app.dependency_overrides[api._inbox_registry] = lambda: lambda: installed


@app.middleware("http")
async def lose_committed_response(request, call_next):
    if request.method == "POST" and config.get("lose_before"):
        os._exit(88)
    response = await call_next(request)
    kind = request.url.path.rsplit("/", 1)[-1]
    marker = root / ("lost-" + kind)
    if (
        request.method == "POST"
        and response.status_code == 200
        and config.get("lose_kind") == kind
        and not marker.exists()
    ):
        with marker.open("x") as target:
            target.write("Committed Inbox response intentionally lost in owned local test.\n")
            target.flush()
            os.fsync(target.fileno())
        os._exit(87)
    return response


uvicorn.run(app, host="127.0.0.1", port=config["port"], log_level="warning")
