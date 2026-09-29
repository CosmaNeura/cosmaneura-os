"""Current authorized brief projections for one human's model request.

Core credentials remain in the reader closure. Refreshes run outside model SQL
transactions; context construction performs only local checks on that result.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid5

from cosmas_os.api.session_prep_analysis_schemas import SessionPrepAnalysis
from cosmas_os.application import workspace as ws
from cosmas_os.ports.bot_capabilities import SourcePassage

MAX_PASSAGE = 5000
MAX_SOURCES = 12
MAX_TOTAL = 30000


def selection(value):
    try:
        return SessionPrepAnalysis.model_validate(value).model_dump(mode="json")
    except (ValueError, TypeError, RecursionError):
        raise ws.WorkspaceError("invalid_session_prep_analysis", 422) from None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def anchor(value):
    """Fingerprint the exact display, including freshness and source coverage."""
    if (not isinstance(value, dict) or value.get("state") not in {"ready", "refreshing"}
            or not value.get("prepared_brief")):
        raise ws.WorkspaceError("session_prep_not_ready", 409)
    return selection({
        "version": 1, "consented": True,
        "brief_id": value.get("brief_id"), "brief_version": value.get("brief_version"),
        "snapshot_sha256": hashlib.sha256(canonical(value).encode()).hexdigest(),
    })


@dataclass
class Sources:
    """A route-owned reader; never restored from request JSON or a work row."""

    workspace_id: str
    box_id: str
    owner_id: str
    bot_address: str
    team_revision: int
    chosen: dict
    reader: Callable[[str], dict] = field(repr=False)
    value: dict | None = field(default=None, init=False, repr=False)
    phase: str | None = field(default=None, init=False)

    def __post_init__(self):
        self.chosen = selection(self.chosen)

    def refresh(self, phase):
        previous = self.phase
        self.value = None
        self.phase = "failed"
        if (phase, previous) not in {("before", None), ("after", "before")}:
            raise ws.WorkspaceError("session_prep_analysis_unavailable", 503)
        checked = self.reader(phase)
        if anchor(checked) != selection(self.chosen):
            raise ws.WorkspaceError("source_changed", 409)
        # Retain no mutable alias to transport/parser state across the model call.
        self.value = json.loads(canonical(checked))
        self.phase = phase

    def current(self, workspace, command, *, phase=None):
        if (
            self.value is None or self.phase not in {"before", "after"}
            or phase is not None and self.phase != phase
            or (workspace.id, workspace.box_id, workspace.owner_id,
                command["role"], command["team_revision"])
            != (self.workspace_id, self.box_id, self.owner_id,
                self.bot_address, self.team_revision)
            or selection(command.get("session_prep_analysis")) != selection(self.chosen)
            or anchor(self.value) != self.chosen
        ):
            raise ws.WorkspaceError("source_changed", 409)
        return json.loads(canonical(self.value))


def passages(value, workspace_id):
    """Preserve the whole chosen brief and its attribution within model bounds."""
    chosen = anchor(value)
    brief = value["prepared_brief"]
    included = [source for source in value["sources"] if source["included"]]
    numbers = {source["source_id"]: i for i, source in enumerate(included, 1)}

    def cited(item):
        refs = item["source_refs"]
        if not refs or any(ref not in numbers for ref in refs):
            raise ws.WorkspaceError("source_changed", 409)
        text = item.get("text", item.get("summary", ""))
        return text + " [" + ", ".join(str(numbers[ref]) for ref in refs) + "]"

    lineage = [
        "AI-prepared Session Prep brief; these are derived excerpts, not the underlying clinical notes.",
        f"Freshness: {value['freshness']}. Coverage: {value['completeness']}.",
        f"Prepared: {value['generated_at']}. Sources current through: {value['current_through']}.",
    ]
    for i, source in enumerate(included, 1):
        label = ("Finalized clinician note" if source["source_class"] == "clinician_finalized_note"
                 else "Patient-reported Visit Prep")
        lineage.append(f"[{i}] {label}; {source['source_at']}; source version {source['source_version']}.")
    for source in value["sources"]:
        if not source["included"]:
            lineage.append(
                f"Not included: {source['source_class']}; reason: {source['reason_code']}."
            )
    sections = [("Sources and freshness", lineage), ("Recap", [cited(brief["recap"])])]
    for key, label in (
        ("trajectory_and_material_changes", "Changes since prior visits"),
        ("talking_points", "Talking points"), ("open_threads", "Open threads"),
        ("cautions", "Cautions"), ("suggested_outline", "Suggested visit outline"),
    ):
        sections.append((label, [cited(item) for item in brief[key]]))
    if brief["patient_reported"]:
        sections.append(("Patient-reported preparation", [cited(brief["patient_reported"])]))
    sources = []
    for label, lines in sections:
        chunks = []
        for line in lines:
            if not line.strip() or "\0" in line or len(line) > MAX_PASSAGE:
                raise ws.WorkspaceError("session_prep_analysis_too_large", 422)
            if chunks and len(chunks[-1]) + len(line) + 1 <= MAX_PASSAGE:
                chunks[-1] += "\n" + line
            else:
                chunks.append(line)
        for i, content in enumerate(chunks):
            identity = f"session-prep:{chosen['snapshot_sha256']}:{label}:{i}"
            sources.append(SourcePassage(str(uuid5(UUID(workspace_id), identity)),
                chosen["brief_version"], f"Session Prep · {label} · v{chosen['brief_version']}",
                "session_prep", content))
    check_bounds(sources)
    return tuple(sources)


def check_bounds(sources):
    if (len(sources) > MAX_SOURCES or any(len(source.content) > MAX_PASSAGE for source in sources)
            or sum(len(source.content) for source in sources) > MAX_TOTAL):
        raise ws.WorkspaceError("session_prep_analysis_too_large", 422)


def build_context(session, workspace, version, settings, bot, command, *, phase):
    from cosmas_os.application import conversation, model_work
    from cosmas_os.ports.bot_capabilities import supports_skill

    if not supports_skill(settings, "encounter_prep") or not settings["include_evidence"]:
        raise ws.WorkspaceError("bot_source_unavailable", 409)
    sources = session.info.get("session_prep_analysis_sources")
    if not isinstance(sources, Sources):
        raise ws.WorkspaceError("source_changed", 409)
    value = sources.current(workspace, command, phase=phase)
    snapshot = model_work.project_workspace(session, ws.read(
        session, workspace.box_id, workspace.owner_id, workspace.id
    ))
    context = conversation.build_context(
        snapshot, version, settings, settings["role"], command["content"],
        agent_id=bot.agent_id, additional_sources=passages(value, workspace.id),
        session_prep_analysis=selection(command["session_prep_analysis"]),
    )
    check_bounds(context.sources)
    return context
