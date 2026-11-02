"""Opt-in broker routes; callback inputs never reach diagnostics or persistence."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from typing import cast
from urllib.parse import parse_qsl

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from cosmas_os.api.google_connection_routes import HEADERS, GoogleConnectionBoundary
from cosmas_os.application.capture_deadline import run_in_threadpool
from cosmas_os.ports.google_callback_broker import (
    BROKER_HEADER,
    CALLBACK_PATH,
    REGISTER_PATH,
    Cancellation,
    GoogleBrokerError,
    ReceiptCheck,
    Registration,
    authenticate,
    decoded,
    encoded,
    signed,
)

from .google_callback_broker import GoogleBrokerIdentityPort, GoogleCallbackBroker


def install(app, settings, service, verifier, relay_port):
    if not settings.google_callback_broker_enabled or settings.google_broker_errors() or service is None or verifier is None:
        return None
    broker = GoogleCallbackBroker(service, cast(GoogleBrokerIdentityPort, verifier), relay_port)
    app.add_middleware(GoogleConnectionBoundary)

    async def body(request, model, purpose, *, bearer):
        if (request.scope.get("query_string") or request.headers.getlist("content-type") != ["application/json"]
                or request.headers.getlist("content-encoding") or len(request.headers.getlist(BROKER_HEADER)) != 1
                or len(request.headers.getlist("content-length")) > 1
                or len(request.headers.getlist("transfer-encoding")) > 1
                or request.headers.getlist("content-length") and request.headers.getlist("transfer-encoding")
                or len(request.headers.getlist("authorization")) != (1 if bearer else 0)):
            raise GoogleBrokerError("invalid_google_broker_request")
        raw = bytearray()
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 8192:
                    raise GoogleBrokerError("invalid_google_broker_request")
                raw.extend(chunk)
        value = decoded(bytes(raw), model)
        key = broker.key(value)
        authenticate(key, bytes(raw), purpose, value.nonce, request.headers[BROKER_HEADER], value.issued_at)
        return value, key

    @app.post(REGISTER_PATH)
    async def register(request: Request):
        try:
            value, key = await body(request, Registration, "registration", bearer=True)
            authorization = request.headers["authorization"]
            token = authorization[7:] if authorization.startswith("Bearer ") else ""
            if not token or len(token) > 8192 or not hmac.compare_digest(value.token_sha256, hashlib.sha256(token.encode()).hexdigest()):
                raise GoogleBrokerError("invalid_google_broker_request")
            if value.native_origin:
                human = await run_in_threadpool(verifier.verify_native_scoped, token, value.organization_id,
                    native_origin=value.native_origin)
            else:
                parties = ["https://" + value.practice_id + ".staging.cosmas.ai"]
                human = await run_in_threadpool(verifier.verify_scoped, token, value.organization_id, authorized_parties=parties)
            receipt = await run_in_threadpool(broker.register, human, value)
            raw = encoded(receipt)
            return Response(raw, media_type="application/json", headers={**HEADERS,
                BROKER_HEADER: signed(key, raw, "registration-result", value.nonce)})
        except Exception:
            return JSONResponse({"detail": "google_broker_unavailable"}, status_code=503, headers=HEADERS)

    @app.post(REGISTER_PATH + "/cancel")
    async def cancel(request: Request):
        try:
            value, key = await body(request, Cancellation, "cancellation", bearer=False)
            await run_in_threadpool(broker.cancel, value)
            raw = encoded({"canceled": True})
            return Response(raw, media_type="application/json", headers={**HEADERS,
                BROKER_HEADER: signed(key, raw, "cancellation-result", value.nonce)})
        except Exception:
            return JSONResponse({"detail": "google_broker_unavailable"}, status_code=503, headers=HEADERS)

    @app.post(REGISTER_PATH + "/check")
    async def check(request: Request):
        try:
            value,key = await body(request,ReceiptCheck,"check",bearer=False)
            receipt = await run_in_threadpool(broker.check,value)
            raw = encoded(receipt)
            return Response(raw,media_type="application/json",headers={**HEADERS,
                BROKER_HEADER:signed(key,raw,"check-result",value.nonce)})
        except Exception:
            return JSONResponse({"detail":"google_broker_unavailable"},status_code=503,headers=HEADERS)

    @app.get(CALLBACK_PATH)
    async def callback(request: Request):
        result = "failed"
        try:
            raw = request.scope.get("state", {}).pop("google_callback_query", b"")
            pairs = parse_qsl(raw.decode("ascii"), keep_blank_values=True, strict_parsing=True, max_num_fields=9)
            data = dict(pairs)
            if (len(pairs) != len(data) or set(data) - {"state", "code", "error", "error_description", "error_uri",
                    "authuser", "scope", "prompt", "hd", "iss"} or ("code" in data) == ("error" in data)
                    or data.get("iss", "https://accounts.google.com") != "https://accounts.google.com"):
                raise ValueError
            state = data.get("state", "")
            if len(state) != 43 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in state):
                raise ValueError
            code = data.get("code")
            if code is not None and (not 1 <= len(code) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in code)):
                raise ValueError
            result = await run_in_threadpool(broker.callback, state, data.get("code"), "error" in data)
        except Exception:
            pass
        message = ("Google connection complete. Return to CosmaBot to continue." if result == "complete"
            else "Return to CosmaBot to check your Google connection or start a new sign-in.")
        return Response("<!doctype html><title>CosmaBot</title><p>" + message + "</p>", media_type="text/html",
            headers={**HEADERS, "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"})
    return broker
