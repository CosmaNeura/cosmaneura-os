"""Explicit local portal setup process; no live profiles or portal I/O."""

# Imports below the socket guard intentionally prevent pre-guard provider imports.
# ruff: noqa: E402
import hashlib
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


def connect(sock, address):
    if sock.family != socket.AF_UNIX and (
        not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1", "localhost"}
    ):
        raise PermissionError("Portal proof permits only loopback sockets")
    return _connect(sock, address)


def dns(host, *args, **kwargs):
    if host not in {"127.0.0.1", "::1", "localhost", None}:
        raise PermissionError("Portal proof permits only loopback DNS")
    return _dns(host, *args, **kwargs)


def connect_ex(sock, address):
    if sock.family != socket.AF_UNIX and (
        not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1", "localhost"}
    ):
        raise PermissionError("Portal proof permits only loopback sockets")
    return _connect_ex(sock, address)


socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
socket.getaddrinfo = dns

import uvicorn
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI
from tests.unit.test_vendor_portal_contract import SyntheticInMemoryPortal

from cosmas_os.adapters.vendor_connectors.portals import PortalBinding, PortalRegistry
from cosmas_os.api import app as api
from cosmas_os.api import portal_setup_routes
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import portal_setup as flow
from cosmas_os.ports.vendor_connectors import ConnectionSelection

key = serialization.load_pem_public_key((root / "public.pem").read_bytes())


class LocalKeys:
    def get_signing_keys(self, *, refresh):
        return [SimpleNamespace(key_id="invented-portal-process", key=key)]


verifier = ClerkTokenVerifier(api.settings, jwks_client=LocalKeys(), start_background_refresh=True)
api._clerk_verifier = lambda: verifier
api.settings.portal_setup_enabled = True
adapter = SyntheticInMemoryPortal()
catalog = flow.Catalog(
    PortalRegistry((PortalBinding(adapter.profile, adapter),)),
    (
        flow.Installation(
            ConnectionSelection.model_validate(config["selection"]),
            adapter.profile,
            "Invented portal",
        ),
    ),
)
app = FastAPI()
portal_setup_routes.register(app, api.get_session, api._identity)
app.dependency_overrides[portal_setup_routes.installed_catalog] = lambda: catalog


@app.get("/health")
def health():
    return {"ready": True, "portal_calls": len(adapter.effects), "production_profiles": 0}


class Fault:
    async def __call__(self, scope, receive, send):
        raw = bytearray()

        async def incoming():
            message = await receive()
            if message["type"] == "http.request":
                raw.extend(message.get("body", b""))
            return message

        async def outgoing(message):
            control = root / "fault.json"
            if (
                message["type"] == "http.response.start"
                and message["status"] == 200
                and control.exists()
            ):
                exact = json.loads(control.read_text())
                if (
                    scope.get("method") == "POST"
                    and scope.get("path") == exact["path"]
                    and hashlib.sha256(raw).hexdigest() == exact["body_sha256"]
                ):
                    control.replace(root / "fault-consumed.json")
                    with (root / "lost-response.json").open("x") as stream:
                        json.dump(
                            {
                                "path": scope["path"],
                                "body_sha256": exact["body_sha256"],
                                "after_handler_commit": True,
                            },
                            stream,
                        )
                        stream.flush()
                        os.fsync(stream.fileno())
                    os._exit(77)
            await send(message)

        await app(scope, incoming, outgoing)


uvicorn.run(Fault(), host="127.0.0.1", port=config["port"], log_level="warning", access_log=False)
