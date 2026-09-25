"""Selected public evidence only; no workspace snapshot or publisher/model I/O."""

from sqlalchemy import select

from cosmas_os.api.research_analysis_schemas import ResearchAnalysis
from cosmas_os.application import research
from cosmas_os.application import workspace as ws
from cosmas_os.models import WorkspaceEntry
from cosmas_os.ports.bot_capabilities import BotContext, SourcePassage
from cosmas_os.research_models import ResearchRun, ResearchSave

MAX_ENTRY_CHARACTERS = 5000
MAX_TOTAL_CHARACTERS = 15000
MAX_TOTAL_BYTES = 32768


def selection(value):
    """Validate again at the application boundary; retain exact ordered anchors."""
    try:
        return ResearchAnalysis.model_validate(value).model_dump(mode="json")
    except (ValueError, TypeError, RecursionError):
        raise ws.WorkspaceError("invalid_research_analysis", 422) from None


def build_context(s, workspace, settings, command):
    if settings["role"] != "research":
        raise ws.WorkspaceError("research_bot_required")
    selected = selection(command["research_analysis"])
    passages = []
    characters = byte_count = 0
    for anchor in selected["entries"]:
        # Only explicitly selected rows are read. Labels or an ordinary evidence
        # entry alone cannot establish a public-source retrieval/save proof.
        receipt = s.scalar(select(ResearchSave).where(
            ResearchSave.workspace_id == workspace.id,
            ResearchSave.box_id == workspace.box_id,
            ResearchSave.entry_id == anchor["entry_id"],
        ))
        try:
            if (receipt is None or receipt.workspace_id != workspace.id
                    or receipt.box_id != workspace.box_id
                    or receipt.entry_id != anchor["entry_id"]
                    or receipt.run_id != anchor["run_id"]
                    or receipt.request_sha256 != anchor["save_request_sha256"]):
                raise ValueError("research selection binding")
            run = s.get(ResearchRun, receipt.run_id)
            if (run is None or run.owner_id != workspace.owner_id
                    or run.box_id != workspace.box_id or run.workspace_id != workspace.id):
                raise ValueError("research selection ownership")
            proof = research._saved(s, receipt)
            entry = s.get(WorkspaceEntry, anchor["entry_id"])
            if (entry is None or proof["entry_id"] != anchor["entry_id"]
                    or proof["entry_revision"] != anchor["entry_revision"]
                    or entry.revision > workspace.revision
                    or proof["run_id"] != anchor["run_id"]
                    or proof["request_sha256"] != anchor["save_request_sha256"]):
                raise ValueError("research selection proof")
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, ws.WorkspaceError):
            raise ws.WorkspaceError("source_changed") from None
        characters += len(entry.content)
        byte_count += len(entry.content.encode("utf-8"))
        # The retained prepared-v1 adapter bounds each passage to 5,000 chars.
        # Refuse an oversized selection rather than silently omit consented text.
        if (len(entry.content) > MAX_ENTRY_CHARACTERS
                or characters > MAX_TOTAL_CHARACTERS or byte_count > MAX_TOTAL_BYTES):
            raise ws.WorkspaceError("research_analysis_too_large", 422)
        passages.append(SourcePassage(entry.id, entry.revision, entry.source_label,
                                      "evidence", entry.content))
    return BotContext(
        workspace_id=workspace.id, context_revision=workspace.revision,
        role="research", question=command["content"],
        response_style=settings["response_style"], sources=tuple(passages),
        linked_work=(), handoff_limit=0,
    )
