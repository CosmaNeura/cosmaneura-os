"""Personal Microsoft consent, callback and read-only data views."""

from typing import Literal
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from cosmas_os.adapters.microsoft_connection import CALLBACK_PATH
from cosmas_os.api.capture_deadline import CaptureBoundary
from cosmas_os.api.capture_schemas import read_capture_request
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool
from cosmas_os.ports.scribe_capture import ProtectedModel

PATH = "/connections/microsoft/session"
HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class MicrosoftCommand(ProtectedModel):
    action: Literal["status", "start", "disconnect", "mail", "calendar"]


class MicrosoftConnectionBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == CALLBACK_PATH:
            raw = scope.get("query_string", b"")
            scope["query_string"] = b""
            scope.setdefault("state", {})["microsoft_callback_query"] = (
                raw if len(raw) <= 8192 else b""
            )
        if (
            scope["type"] == "http"
            and scope["path"] in {CALLBACK_PATH, PATH}
            and scope["method"] != "OPTIONS"
        ):
            await CaptureBoundary(
                self.app,
                seconds=45,
                max_response_bytes=131072,
                error_factory=lambda status: JSONResponse(
                    {"detail": "microsoft_connection_unavailable"},
                    status_code=status,
                    headers=HEADERS,
                ),
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)


def router(*, runtime, identity_dependency, workspace_gate):
    routes = APIRouter()

    @routes.post(PATH, dependencies=[Depends(workspace_gate)])
    async def action(request: Request, identity=Depends(identity_dependency)):
        if (
            request.query_params
            or request.headers.getlist("x-cosmas-microsoft-connection") != ["1"]
            or request.headers.getlist("content-encoding")
        ):
            raise ws.WorkspaceError("invalid_microsoft_connection_request", 422)
        command = await read_capture_request(request, MicrosoftCommand, maximum_bytes=1024)
        service = runtime()
        if service is None:
            raise ws.WorkspaceError("microsoft_connection_unavailable", 404)
        try:
            result = await run_in_threadpool(getattr(service, command.action), identity)
        except ws.WorkspaceError:
            raise
        except Exception:
            return JSONResponse(
                {"detail": "microsoft_connection_unavailable"}, status_code=503, headers=HEADERS
            )
        return JSONResponse(result, headers=HEADERS)

    @routes.get(CALLBACK_PATH)
    async def callback(request: Request):
        service = runtime()
        if service is None:
            return JSONResponse(
                {"detail": "microsoft_connection_unavailable"}, status_code=404, headers=HEADERS
            )
        success = False
        try:
            raw = request.scope.get("state", {}).pop("microsoft_callback_query", b"")
            pairs = parse_qsl(
                raw.decode("ascii"), keep_blank_values=True, strict_parsing=True, max_num_fields=8
            )
            data = dict(pairs)
            if (
                len(pairs) != len(data)
                or set(data)
                - {"state", "code", "error", "error_description", "error_uri", "session_state"}
                or ("code" in data) == ("error" in data)
            ):
                raise ValueError
            success = await run_in_threadpool(
                service.callback, data.get("state"), data.get("code"), "error" in data
            )
        except Exception:
            pass
        return RedirectResponse(
            service.return_origin + ("/#microsoft-connected" if success else "/#microsoft-sign-in"),
            status_code=303,
            headers=HEADERS,
        )

    return routes
