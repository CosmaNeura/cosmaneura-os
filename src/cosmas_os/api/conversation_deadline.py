"""Own conversation dependencies across Core reads and model dispatch."""

from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.routing import Match

from cosmas_os.api.capture_deadline import CaptureBoundary


class ConversationMiddleware:
    def __init__(self, app, *, route):
        self.app, self.route = app, route

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.route.matches(scope)[0] != Match.FULL:
            return await self.app(scope, receive, send)

        def error(status):
            return JSONResponse(
                {"detail": "model_observation_unavailable"}, status_code=status,
                headers={"Cache-Control": "no-store"},
            )

        await CaptureBoundary(
            # Legacy deterministic callers return their bounded workspace.
            # Negotiated model receipts retain the schema's smaller 16 KiB cap.
            self.app, 120, max_response_bytes=12_000_000,
            error_factory=error,
        )(scope, receive, send)


def install_conversation_boundary(app):
    routes = [route for route in app.routes if isinstance(route, APIRoute)
              and route.path == "/workspaces/{workspace_id}/conversation"
              and route.methods == {"POST"}]
    if len(routes) != 1 or any(item.cls is ConversationMiddleware for item in app.user_middleware):
        raise ValueError("conversation route inventory changed")
    app.add_middleware(ConversationMiddleware, route=routes[0])
