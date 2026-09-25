"""Staff sign-in UI actions and a query-redacting Google return boundary."""

import json
from typing import Annotated, Literal
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ConfigDict, Field, TypeAdapter

from cosmas_os.adapters.scheduling_google_login import CALLBACK_PATH
from cosmas_os.api.capture_deadline import CaptureBoundary
from cosmas_os.api.capture_schemas import _unique_object
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool
from cosmas_os.ports.scheduling_enrollment import EnrollmentCommand
from cosmas_os.ports.scribe_capture import ProtectedModel

HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class SchedulingLoginCommand(ProtectedModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["status", "start", "disconnect"]


COMMAND_ADAPTER=TypeAdapter(Annotated[SchedulingLoginCommand | EnrollmentCommand,Field(discriminator="action")])


async def read_session_command(request: Request) -> SchedulingLoginCommand | EnrollmentCommand:
    try:
        if any(len(request.headers.getlist(name))!=1 for name in ("authorization","content-type")) or request.headers["content-type"].split(";",1)[0].strip().lower()!="application/json" or request.query_params or request.headers.getlist("content-encoding"):
            raise ValueError
        data=bytearray()
        async for part in request.stream():
            if len(data)+len(part)>2048:
                raise ValueError
            data.extend(part)
        return COMMAND_ADAPTER.validate_python(json.loads(bytes(data).decode("utf-8"),object_pairs_hook=_unique_object))
    except (ValueError,TypeError,UnicodeError,RecursionError):
        raise ws.WorkspaceError("invalid_scheduling_sign_in_request",422) from None


class SchedulingCallbackBoundary:
    """Remove OAuth query material before application/access logging sees it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == CALLBACK_PATH:
            raw = scope.get("query_string", b"")
            scope["query_string"] = b""
            scope.setdefault("state", {})["scheduling_callback_query"] = (
                raw if len(raw) <= 8192 else b""
            )
        if (
            scope["type"] == "http"
            and scope["path"] in {CALLBACK_PATH, "/connections/scheduling/session"}
            and scope["method"] != "OPTIONS"
        ):
            await CaptureBoundary(
                self.app,
                seconds=45 if scope["path"] == CALLBACK_PATH else 18,
                max_response_bytes=69632,
                error_factory=lambda status: JSONResponse(
                    {"detail": "scheduling_sign_in_unavailable"},
                    status_code=status,
                    headers=HEADERS,
                ),
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)


def router(*, runtime, identity_dependency, workspace_gate, scheduling_gate):
    routes = APIRouter()

    @routes.post(
        "/connections/scheduling/session",
        dependencies=[Depends(workspace_gate), Depends(scheduling_gate)],
    )
    async def session_action(request: Request, identity=Depends(identity_dependency)):
        if (
            request.query_params
            or request.headers.getlist("x-cosmas-scheduling-login") != ["1"]
            or request.headers.getlist("content-encoding")
        ):
            raise ws.WorkspaceError("invalid_scheduling_sign_in_request", 422)
        command = await read_session_command(request)
        service = runtime()
        if service is None:
            raise ws.WorkspaceError("scheduling_sign_in_unavailable", 404)
        try:
            if isinstance(command,EnrollmentCommand):
                enrollment=getattr(service,"enrollment",None)
                if enrollment is None:
                    raise ws.WorkspaceError("scheduling_sign_in_unavailable",404)
                result=await run_in_threadpool(enrollment.execute,identity,command)
            else:
                result = await run_in_threadpool(getattr(service, command.action), identity)
        except ws.WorkspaceError:
            raise
        except Exception:
            return JSONResponse(
                {"detail": "scheduling_sign_in_unavailable"}, status_code=503, headers=HEADERS
            )
        return JSONResponse(result, headers=HEADERS)

    @routes.get(CALLBACK_PATH)
    async def callback(request: Request):
        service = runtime()
        if service is None:
            return JSONResponse(
                {"detail": "scheduling_sign_in_unavailable"}, status_code=404, headers=HEADERS
            )
        success = False
        try:
            raw = request.scope.get("state", {}).pop("scheduling_callback_query", b"")
            pairs = parse_qsl(
                raw.decode("ascii"), keep_blank_values=True, strict_parsing=True, max_num_fields=12
            )
            data = dict(pairs)
            allowed = {
                "state",
                "code",
                "error",
                "scope",
                "authuser",
                "prompt",
                "hd",
                "error_description",
                "error_uri",
            }
            if (
                len(data) != len(pairs)
                or set(data) - allowed
                or ("code" in data) == ("error" in data)
            ):
                raise ValueError
            success = await run_in_threadpool(
                service.callback, data.get("state"), data.get("code"), "error" in data
            )
        except Exception:
            pass
        target = service.return_origin + (
            "/#scheduling-connected" if success else "/#scheduling-sign-in"
        )
        return RedirectResponse(target, status_code=303, headers=HEADERS)

    return routes
