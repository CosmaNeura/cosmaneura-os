"""Callable account reads through existing handlers; human source reviews stay in UI.

The registry supplies the current authenticated identity. Account names, provider
URLs, token material and source content are never tool arguments. OAuth consent,
disconnect and human review handlers are deliberately absent from this allowlist.
"""

from dataclasses import replace
from typing import TYPE_CHECKING

from cosmas_os.api import google_calendar_schemas as calendar
from cosmas_os.api import google_message_schemas as message

if TYPE_CHECKING:
    from cosmas_os.api.plugin_catalog import Operation

GOOGLE_SESSION = "/connections/google/session"
MICROSOFT_SESSION = "/connections/microsoft/session"
GOOGLE_MESSAGES = "/connections/google/messages"
GOOGLE_CALENDAR = "/connections/google/calendar-summaries"
MESSAGE_HEADER = "X-Cosmas-Google-Messages"
CALENDAR_HEADER = "X-Cosmas-Google-Calendar"
OWNER = "current authenticated account owner and active Box membership"
FULL_MAIL = "https://www.googleapis.com/auth/gmail.readonly"
CALENDAR_READ = "https://www.googleapis.com/auth/calendar.events.readonly"
MESSAGE_TESTS = ("tests/unit/test_google_message.py", "tests/integration/test_google_message.py")
CALENDAR_TESTS = ("tests/unit/test_google_calendar_custody.py", "tests/integration/test_google_calendar.py")


def definitions() -> tuple["Operation", ...]:
    # Local import permits the catalog to extend these definitions after defining
    # Operation, without importing or executing provider adapters.
    from cosmas_os.api.plugin_catalog import Operation, command

    operations = [Operation(
        id="google.connection_status", plugin="google", title="Check the connected Google account",
        description="Read local account state and existing mail/calendar grants. This does not refresh tokens, read Google, or establish that a provider read succeeded.",
        path=GOOGLE_SESSION, header="X-Cosmas-Google-Connection",
        request={"type": "object", "additionalProperties": False,
                 "properties": {"action": {"type": "string", "const": "status"},
                                "include_capabilities": {"type": "boolean", "const": True}},
                 "required": ["action", "include_capabilities"]},
        permission=(OWNER,), health_check="connected account and existing sealed grants only; capability health remains unchecked",
        completion="local state, account and granted capability flags, including sign_in_required",
        recovery="check status again; explicit consent remains a human action in Connections",
        tests=("tests/unit/test_personal_connection_failure.py",), read_only=True, deadline_seconds=45,
    )]
    operations.extend((
        Operation(
            id="google.message_status", plugin="google", title="Check full-message access",
            description="Check local full-message grant and account state before selecting mail. A pending replacement sign-in withholds the earlier account; status does not contact Gmail.",
            path=GOOGLE_MESSAGES, header=MESSAGE_HEADER, request=message.Status.model_json_schema(),
            permission=(OWNER, "full-message feature enabled; explicit human consent required before a full-message read"),
            health_check="inspect full_mail_read and the currently selected account; connected alone is insufficient",
            completion="local state and full_mail_read flag only",
            recovery="check local status; complete missing consent through the human Connections flow",
            tests=MESSAGE_TESTS, read_only=True, deadline_seconds=45,
        ),
        Operation(
            id="google.list_messages", plugin="google", title="Observe recent email choices",
            description="Explicitly read up to 10 inbox headers and retain one immutable selection observation. Bodies and attachments are absent; a saved observation is separate from a reviewed encounter source.",
            path=GOOGLE_MESSAGES, header=MESSAGE_HEADER, request=message.ListMessages.model_json_schema(),
            permission=(OWNER, "explicit bounded read", "https://www.googleapis.com/auth/gmail.metadata"),
            health_check="only a validated observed receipt, including empty items, verifies this read",
            completion="saved list observation, read_id and source_sha256; more does not authorize page traversal",
            recovery="google.resolve_message with kind=list and the exact original idempotency key; unconfirmed is not success and must not trigger automatic dispatch",
            tests=MESSAGE_TESTS, public_read=True, deadline_seconds=45,
        ),
        Operation(
            id="google.read_message", plugin="google", title="Read one selected full email",
            description="Read one exact message from a retained observation. Complete plaintext is bounded to 5,000 characters; attachment, HTML-only, ambiguous or oversized mail requires human handling. No source review or encounter save is performed.",
            path=GOOGLE_MESSAGES, header=MESSAGE_HEADER, request=message.ReadMessage.model_json_schema(),
            permission=(OWNER, FULL_MAIL, "explicit human full-mail consent and selected retained observation/message",
                        "human review of patient and exact source required before encounter source save"),
            health_check="complete source requires current exact grant plus a validated complete read; needs_human is not complete",
            completion="saved read_id, source_sha256 and complete plaintext, or needs_human without partial content",
            recovery="google.resolve_message kind=message with the original key, then google.inspect_message by saved read_id; no automatic new provider request",
            tests=MESSAGE_TESTS, public_read=True, deadline_seconds=45,
        ),
        Operation(
            id="google.inspect_message", plugin="google", title="Reopen a retained email read",
            description="Read an existing selected-message receipt from PostgreSQL under current account authority. This performs no Gmail dispatch and does not restore revoked source access.",
            path=GOOGLE_MESSAGES, header=MESSAGE_HEADER, request=message.InspectMessage.model_json_schema(),
            permission=(OWNER, FULL_MAIL, "exact currently authorized read_id and grant binding"),
            health_check="current validated retained receipt only; missing, unconfirmed and inaccessible remain distinct",
            completion="saved read projection and source digest if current authority permits disclosure",
            recovery="repeat this read with the same read_id; retain masked results after revocation without provider retry",
            tests=MESSAGE_TESTS, read_only=True, deadline_seconds=45,
        ),
        Operation(
            id="google.resolve_message", plugin="google", title="Recover an email read response",
            description="Resolve the exact original list or selected-message key from retained database state. No provider read, token refresh, new selection or source review is dispatched.",
            path=GOOGLE_MESSAGES, header=MESSAGE_HEADER, request=message.ResolveMessage.model_json_schema(),
            permission=(OWNER, "exact original key and list/message kind; current grant binding"),
            health_check="observed/complete, unconfirmed and not_found are separate observations",
            completion="original durable read or truthful unconfirmed/not_found state only",
            recovery="retain the original key and uncertain outcome; a new explicit read is a separate intent",
            tests=MESSAGE_TESTS, read_only=True, deadline_seconds=45,
        ),
        Operation(
            id="google.calendar_status", plugin="google", title="Check calendar-summary access",
            description="Check the local current Google calendar grant without a provider request. This does not establish appointment availability or booking.",
            path=GOOGLE_CALENDAR, header=CALENDAR_HEADER, request=calendar.Status.model_json_schema(),
            permission=(OWNER, "calendar-summary feature enabled; separate explicit calendar grant required before a read"),
            health_check="inspect calendar_read on the current account; sign-in is insufficient",
            completion="local account state and calendar_read flag only",
            recovery="check status; obtain missing consent through the human Connections flow",
            tests=CALENDAR_TESTS, read_only=True, deadline_seconds=45,
        ),
        Operation(
            id="google.observe_calendar", plugin="google", title="Observe bounded calendar summaries",
            description="Read and retain up to 25 primary-calendar event summaries in the server-owned next-seven-day window. Descriptions, attendees, locations, page traversal and event writes are absent; all-day bounds remain dates.",
            path=GOOGLE_CALENDAR, header=CALENDAR_HEADER, request=calendar.Observe.model_json_schema(),
            permission=(OWNER, CALENDAR_READ, "explicit bounded primary-calendar read"),
            health_check="a validated observation verifies this read only; not-cancelled does not mean confirmed or available",
            completion="immutable observation_id, source_sha256, exact window and bounded events, including an empty result",
            recovery="google.resolve_calendar with the original key, then inspect the retained observation; no automatic redispatch",
            tests=CALENDAR_TESTS, public_read=True, deadline_seconds=45,
        ),
        Operation(
            id="google.inspect_calendar", plugin="google", title="Reopen a retained calendar observation",
            description="Read a saved calendar observation under current exact account authority, with no provider dispatch. Selecting and saving an event as an encounter source requires the existing human review UI.",
            path=GOOGLE_CALENDAR, header=CALENDAR_HEADER, request=calendar.Inspect.model_json_schema(),
            permission=(OWNER, CALENDAR_READ, "exact currently authorized observation_id and grant binding"),
            health_check="retained observation is historical evidence, not a fresh availability check",
            completion="validated retained observation and exact digest; revoked authority remains withheld",
            recovery="repeat by the same observation_id without calling Google again",
            tests=CALENDAR_TESTS, read_only=True, deadline_seconds=45,
        ),
        Operation(
            id="google.resolve_calendar", plugin="google", title="Recover a calendar read response",
            description="Resolve an original calendar observation key using PostgreSQL only. This cannot create a new observation, select an event, save a source or book an appointment.",
            path=GOOGLE_CALENDAR, header=CALENDAR_HEADER, request=calendar.Resolve.model_json_schema(),
            permission=(OWNER, "exact original observation key and current grant binding"),
            health_check="observed, unconfirmed and not_found are distinct; unconfirmed is not an empty calendar",
            completion="saved exact observation or truthful unconfirmed/not_found state only",
            recovery="retain the original key; any deliberate new observation requires a separate explicit intent",
            tests=CALENDAR_TESTS, read_only=True, deadline_seconds=45,
        ),
        Operation(
            id="google.inspect_saved_sources", plugin="google", title="Reopen human-reviewed encounter sources",
            description="Read the existing encounter workspace after the human has saved an exact email or calendar source in the review UI. Current source and saved bot work remain masked after lost authority. This read asserts no review and writes no source.",
            path="/workspaces/{workspace_id}", header="X-Cosmas-Model-Contract",
            request={"type": "object", "properties": {}, "additionalProperties": False},
            permission=(OWNER, "current encounter owner; human source review must already be saved",
                        "only currently authorized source content; no new grant or acceptance authority"),
            health_check="inspect saved source state and retained review/result evidence independently",
            completion="current server-projected workspace; withheld source/reply remains withheld",
            recovery="read this saved workspace after a lost source-save response; use the existing human UI and original journal key to resolve an unresolved save",
            tests=("tests/integration/test_google_full_workspace_server_lab.py",),
            read_only=True, method="GET", deadline_seconds=45,
        ),
        Operation(
            id="microsoft.connection_status", plugin="microsoft", title="Check the connected Microsoft account",
            description="Read local current account and connection state. Microsoft guest sign-in does not establish an Exchange mailbox, calendar capability or a successful Graph read.",
            path=MICROSOFT_SESSION, header="X-Cosmas-Microsoft-Connection", request=command("status"),
            permission=(OWNER,), health_check="account access only; verify mail and calendar with their own bounded reads",
            completion="local connection state; provider capability remains unchecked",
            recovery="check status; any consent or reconnection remains a human Connections action",
            tests=("tests/unit/test_personal_connection_failure.py",), read_only=True, deadline_seconds=45,
        ),
    ))
    for action, name, label, scope in (
        ("mail", "read_mail", "email headers", "Mail.Read"),
        ("calendar", "read_calendar", "calendar summaries", "Calendars.Read"),
    ):
        operations.append(Operation(
            id=f"microsoft.{name}", plugin="microsoft", title=f"Read Microsoft {label}",
            description=("Explicitly read up to 25 inbox headers; bodies and attachments are absent."
                         if action == "mail" else "Explicitly read up to 25 calendarView summaries in the server-owned next-seven-day window. No event writes or availability/booking assertion."),
            path=MICROSOFT_SESSION, header="X-Cosmas-Microsoft-Connection", request=command(action),
            permission=(OWNER, "explicit bounded read", scope, "current configured Entra tenant and exact delegated account grant"),
            health_check="only this validated Graph response establishes observed capability; sign-in is insufficient",
            completion="validated bounded response, including a confirmed empty result; no retained source-custody receipt",
            recovery="no database resolve handler exists for these reads; clear stale screen state and deliberately perform a new explicit bounded read",
            tests=("tests/unit/test_personal_connection_failure.py", "tests/integration/test_virtual_clinic_lab.py"),
            read_only=True, public_read=True, deadline_seconds=45,
        ))
    return tuple(replace(operation, agent_callable=True) for operation in operations)


def configured(operation: "Operation", settings, runtime) -> bool:
    """Configuration evidence only; no account lookup or provider probe is made."""
    if operation.plugin == "google":
        if operation.id == "google.inspect_saved_sources":
            return bool(getattr(settings, "workspace_available", False))
        if not (getattr(settings, "workspace_google_connection_enabled", False)
                and getattr(runtime, "google_connection", None) is not None):
            return False
        if operation.path == GOOGLE_MESSAGES:
            return bool(getattr(settings, "workspace_google_message_available", False))
        if operation.path == GOOGLE_CALENDAR:
            return bool(getattr(settings, "workspace_google_calendar_available", False))
        return True
    if operation.plugin == "microsoft":
        return bool(getattr(settings, "workspace_microsoft_connection_enabled", False)
                    and getattr(runtime, "microsoft_connection", None) is not None)
    return False
