"""Client wire compatibility, independent of account grants and service health."""

from starlette.responses import JSONResponse

PROTOCOL = "1"
HEADER = b"x-cosmas-workspace-protocol"
# These describe implemented wire contracts, not enabled vendors or permissions.
CONTRACTS = {
    "workspace": 1, "draft_recovery": 2, "team": 4, "activity": 2,
    "model": 1, "handoff_review": 2, "routine": 2, "practice_access": 1, "practice_members": 1,
    "vendor": 1, "vendor_setup": 1, "finance": 1, "finance_setup": 1,
    "portal_setup": 1, "portal_work": 1, "membership": 1, "inbox": 1,
    "inbox_handoff": 1, "core_record": 1, "core_connection": 1,
    "research": 1, "scheduling_login": 1, "google_connection": 1,
    "microsoft_connection": 1, "google_messages": 1, "google_calendar": 1,
    "ehr_reads": 1,
    "calendar_import": 1,
    "scheduling_patient": 1, "practice_setup": 1, "private_draft": 1, "private_recording": 1, "conversations": 1,
}
WORKSPACE_ROOTS = frozenset({
    "workspaces", "provider-team", "practice-work", "practice-access",
    "connections", "research", "portal-setup", "finance-setup",
    "vendor-settings", "inbox", "inbox-handoffs",
})
CALLBACKS = frozenset({
    "/connections/google/callback", "/connections/microsoft/callback",
    "/connections/scheduling/google/callback",
})


def required(runtime):
    return bool(runtime.workspace_hosted_enabled and runtime.workspace_draft_recovery_required)


def protected(scope):
    return (scope["type"] == "http" and scope["method"] != "OPTIONS"
            and scope["path"].partition("/")[2].partition("/")[0] in WORKSPACE_ROOTS
            and not (scope["method"] == "GET" and scope["path"] in CALLBACKS))


def compatibility(_session, runtime, _member, *, fence):
    fence()
    return {"contract_version": 1, "workspace_protocol": 1,
            "requests_require_protocol": required(runtime), "contracts": dict(CONTRACTS)}


class WorkspaceProtocolBoundary:
    def __init__(self, app, runtime):
        self.app = app
        self.runtime = runtime

    async def __call__(self, scope, receive, send):
        if not protected(scope):
            await self.app(scope, receive, send)
            return
        values = [value for key, value in scope["headers"] if key.lower() == HEADER]

        async def identified(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [
                    (key, value) for key, value in message.get("headers", [])
                    if key.lower() != HEADER
                ] + [(HEADER, PROTOCOL.encode())]}
            await send(message)

        # Do not read the body, authenticate, open a database or dispatch work first.
        if (values or required(self.runtime())) and values != [PROTOCOL.encode()]:
            await JSONResponse({"detail": "workspace_protocol_required"}, status_code=426,
                               headers={"Cache-Control": "no-store"})(scope, receive, identified)
            return
        await self.app(scope, receive, identified)
