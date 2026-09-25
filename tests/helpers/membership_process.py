"""Signed local-only membership surface; no public/generic work routes are installed."""

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
        not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1", "localhost"}
    ):
        raise PermissionError("Only invented local membership proof is authorized")


def connect(sock, address):
    checked(sock, address)
    return _connect(sock, address)


def connect_ex(sock, address):
    checked(sock, address)
    return _connect_ex(sock, address)


def dns(host, *args, **kwargs):
    if host not in {"127.0.0.1", "::1", "localhost", None}:
        raise PermissionError("Only local DNS is authorized")
    return _dns(host, *args, **kwargs)


socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
socket.getaddrinfo = dns

import uvicorn
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI

from cosmas_os.api import app as api
from cosmas_os.api import membership_work_routes as routes
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application.membership_work import MembershipPolicy

key = serialization.load_pem_public_key((root / "public.pem").read_bytes())


class LocalKeys:
    def get_signing_keys(self, *, refresh):
        return [SimpleNamespace(key_id="invented-membership-key", key=key)]


verifier = ClerkTokenVerifier(api.settings, jwks_client=LocalKeys(), start_background_refresh=True)
api._clerk_verifier = lambda: verifier
app = FastAPI()
routes.register(
    app,
    api.get_session,
    api._identity,
    policy_dependency=lambda: MembershipPolicy(True, True),
    reauthenticate=api._finance_reauthenticate,
)


@app.get("/health")
def health():
    return {"fixture": "invented-membership-process"}


@app.middleware("http")
async def lose_committed_response(request, call_next):
    response = await call_next(request)
    kind = request.url.path.rsplit("/", 1)[-1]
    if kind == "membership-work":
        kind = "propose"
    marker = root / ("lost-" + kind)
    if (
        request.method == "POST"
        and response.status_code == 200
        and config.get("lose_kind") == kind
        and not marker.exists()
    ):
        with marker.open("x") as target:
            target.write("Committed response intentionally lost in owned local test.\n")
            target.flush()
            os.fsync(target.fileno())
        os._exit(87)
    return response


uvicorn.run(app, host="127.0.0.1", port=config["port"], log_level="warning")
