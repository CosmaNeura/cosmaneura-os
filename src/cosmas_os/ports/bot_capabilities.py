"""OS connector seams. Pending capabilities are descriptors, never implied grants.

Core's reserved preparation contract is real; the other service contracts below
are OS integration slots awaiting receiver agreement. No network client is
constructed by this registry.
"""

from dataclasses import dataclass
from typing import Protocol

TEMPLATE_VERSION = "provider-team-v7"
BASELINE_ROLES = ("scribe", "visit_prep", "follow_up", "chief")

# A skill selects an existing bounded path; it never creates an action grant.
CUSTOM_SKILLS = {
    "saved_context": {"label": "Saved context review", "state": "local", "connector": "Workspace", "contract": "workspace.read.v1"},
    "work_status": {"label": "Work status and receipts", "state": "local", "connector": "F-8", "contract": "workspace.work.read.v1"},
    "encounter_prep": {"label": "Saved intake and prior visit drafts", "state": "awaiting_connection", "connector": "Core", "contract": "core.encounter-context.v1"},
    "calendar_availability": {"label": "Calendar availability", "state": "awaiting_connection", "connector": "Scheduling", "contract": "scheduling.availability.v1"},
}
CUSTOM_SKILLS["inbox_review"] = {"label": "Reviewed Inbox drafts", "state": "awaiting_connection", "connector": "Private Inbox", "contract": "inbox.analysis.v1"}
CUSTOM_SKILLS["membership_review"] = {"label": "Membership and payment review", "state": "awaiting_connection", "connector": "Private practice work", "contract": "membership.analysis.v1"}
CUSTOM_BOT = {"name": "Custom bot", "initials": "Cb", "description": "A private coworker with a job you define.",
              "prompt": "Help me with my bot's job", "capabilities": []}


def supports_skill(settings, skill):
    if settings["role"] == "custom":
        return skill in CUSTOM_SKILLS and skill in settings.get("skills", ())
    return settings["role"] in {
        "saved_context": {"scribe", "visit_prep", "follow_up", "chief", "research"},
        "work_status": {"scribe", "visit_prep", "follow_up", "chief", "research"},
        "encounter_prep": {"scribe", "visit_prep"},
        "calendar_availability": {"follow_up"},
    }.get(skill, set())

ROLE_TEMPLATES = {
    "scribe": {
        "name": "Scribe",
        "initials": "Sc",
        "description": "Your notes, clearly kept.",
        "prompt": "Review my saved draft",
        "capabilities": [
            {
                "key": "workspace.notebook.read",
                "label": "Saved notebook review",
                "state": "local",
                "connector": "workspace",
                "contract": "workspace.read.v1",
            },
            {
                "key": "scribe.capture",
                "label": "Consented recording",
                "state": "awaiting_connection",
                "connector": "Scribe",
                "contract": None,
            },
            {
                "key": "scribe.transcript.read",
                "label": "Transcript & corrections",
                "state": "awaiting_connection",
                "connector": "Scribe",
                "contract": None,
            },
            {
                "key": "core.note.draft",
                "label": "SOAP draft generation",
                "state": "awaiting_connection",
                "connector": "Core",
                "contract": None,
            },
        ],
    },
    "visit_prep": {
        "name": "Visit Prep",
        "initials": "Vp",
        "description": "Context before the conversation.",
        "prompt": "Review the saved preparation",
        "capabilities": [
            {
                "key": "workspace.sources.review",
                "label": "Saved source review",
                "state": "local",
                "connector": "workspace",
                "contract": "workspace.read.v1",
            },
            {
                "key": "core.session_prep.read",
                "label": "Intake & encounter context",
                "state": "awaiting_connection",
                "connector": "Core",
                "contract": "session-prep.context.read@1.0.0",
            },
            {
                "key": "assistant.answer",
                "label": "AI questions & answers",
                "state": "awaiting_connection",
                "connector": "Model runtime",
                "contract": None,
            },
        ],
    },
    "follow_up": {
        "name": "Follow-up",
        "initials": "Fu",
        "description": "Keep the next step in sight.",
        "prompt": "Show my linked follow-up work",
        "capabilities": [
            {
                "key": "workspace.work.read",
                "label": "Linked work status",
                "state": "local",
                "connector": "F-8",
                "contract": "workspace.work.read.v1",
            },
            {
                "key": "followup.propose",
                "label": "Proposals in the Work tab",
                "state": "local",
                "connector": "F-8",
                "contract": "workspace.follow_up.v1",
            },
            {
                "key": "followup.local_receipts.read",
                "label": "Local delivery & human results",
                "state": "local",
                "connector": "F-8",
                "contract": "workspace.follow_up.v1",
            },
            {
                "key": "scheduling.coordinate",
                "label": "Scheduling coordination",
                "state": "awaiting_connection",
                "connector": "Scheduling",
                "contract": None,
            },
            {
                "key": "followup.deliver",
                "label": "Delivery & outcome receipts",
                "state": "awaiting_connection",
                "connector": "Secure messaging",
                "contract": None,
            },
        ],
    },
    "chief": {
        "name": "Chief",
        "initials": "Ch",
        "description": "A clear view of what is open.",
        "prompt": "Review this encounter's status",
        "capabilities": [
            {
                "key": "workspace.status.read",
                "label": "Encounter status review",
                "state": "local",
                "connector": "workspace",
                "contract": "workspace.read.v1",
            },
            {
                "key": "team.routines",
                "label": "Routines & quiet hours",
                "state": "awaiting_connection",
                "connector": "Durable scheduler",
                "contract": None,
            },
            {
                "key": "team.handoff",
                "label": "Accepted staff handoffs",
                "state": "awaiting_connection",
                "connector": "F-8",
                "contract": None,
            },
        ],
    },
}


ROLE_TEMPLATES["research"] = {
    "name": "Research", "initials": "Re",
    "description": "Evidence with sources you can check.",
    "prompt": "Compare the evidence in my saved sources",
    "capabilities": [
        {"key": "research.public.read", "label": "Public medical sources",
         "state": "awaiting_connection", "connector": "Public healthcare data",
         "contract": "research.lookup.v1"},
        {"key": "workspace.sources.review", "label": "Saved evidence review",
         "state": "local", "connector": "Workspace", "contract": "workspace.read.v1"},
    ],
}


@dataclass(frozen=True)
class SourcePassage:
    entry_id: str
    revision: int
    label: str
    kind: str
    content: str


@dataclass(frozen=True)
class FollowUpStatus:
    ticket_id: str
    state: str
    due_date: str
    source_changed: bool
    local_delivery_recorded: bool
    human_completion_recorded: bool

    @property
    def label(self) -> str:
        if self.state == "closed":
            return "completed · human recorded" if self.human_completion_recorded and self.local_delivery_recorded else "completion unverified"
        if self.state == "sent":
            return "local delivery recorded" if self.local_delivery_recorded else "delivery unverified"
        if self.state == "rejected":
            return "dismissed"
        if self.source_changed:
            return "source changed · needs a new reviewed proposal"
        return "approved · local delivery pending" if self.state == "approved" else "awaiting human approval"


@dataclass(frozen=True)
class BotContext:
    """Constructed only after private scope checks; evidence grants no authority."""

    workspace_id: str
    context_revision: int
    role: str
    question: str
    response_style: str
    sources: tuple[SourcePassage, ...]
    linked_work: tuple[tuple[str, str], ...]
    history: tuple[tuple[str, str], ...] = ()
    practice_context: str = ""
    handoff_roles: tuple[str, ...] = ()
    draft_only: bool = False
    follow_ups: tuple[FollowUpStatus, ...] = ()
    job_focus: str = ""
    working_preferences: str = ""
    handoff_targets: tuple[dict[str, str], ...] = ()
    skills: tuple[str, ...] = ()
    handoff_limit: int = 3


@dataclass(frozen=True)
class DraftBrief:
    role: str
    brief: str
    requirements: dict | None = None


@dataclass(frozen=True)
class BotReply:
    content: str
    citations: tuple[SourcePassage, ...]
    backend: str = "local_source_review_v1"
    input_tokens: int | None = None
    output_tokens: int | None = None
    handoffs: tuple[DraftBrief, ...] = ()
    response_sha256: str | None = None


class BotConnector(Protocol):
    def review(self, context: BotContext) -> BotReply: ...


class ConnectorUnavailable(Exception):
    pass


class ModelCallFailure(ConnectorUnavailable):
    """Closed call evidence; no provider message, source text or credential."""

    def __init__(self, *, dispatch="not_dispatched", outcome="connector_failure",
                 input_tokens=None, output_tokens=None, response_sha256=None):
        super().__init__("gpt41_unavailable")
        self.dispatch = dispatch
        self.outcome = outcome
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.response_sha256 = response_sha256


class PendingConnector:
    """Explicit placeholder for an in-flight backend capability."""

    def __init__(self, capability: str):
        self.capability = capability

    def review(self, context: BotContext) -> BotReply:
        raise ConnectorUnavailable(self.capability)
