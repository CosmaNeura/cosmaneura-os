"""Receipt-bound task briefs stored in the existing immutable admission JSON."""

import hashlib
import json

from cosmas_os.ports.task_brief import TaskRequirements

ALLOWED_ACTIONS = ("prepare_private_draft",)


def source_versions(context):
    return [
        {
            "entry_id": item.entry_id,
            "revision": item.revision,
            "label": item.label,
            "kind": item.kind,
            "sha256": hashlib.sha256(item.content.encode()).hexdigest(),
        }
        for item in context.sources
    ]


def prepare(brief, context, origin):
    requirements = TaskRequirements.model_validate(brief.requirements).model_dump()
    value = {
        "version": 1,
        "goal": brief.brief,
        **requirements,
        "source_versions": source_versions(context),
        "allowed_actions": list(ALLOWED_ACTIONS),
        "depends_on": {"entry_id": origin.id, "revision": origin.revision},
    }
    validate(value, context, goal=brief.brief, origin_id=origin.id)
    return value


def validate(value, context, *, goal, origin_id):
    fields = {
        "version",
        "goal",
        "missing_facts",
        "expected_output",
        "completion_criteria",
        "independent",
        "source_versions",
        "allowed_actions",
        "depends_on",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid task brief")
    if (
        len(context.sources) > 12
        or any(len(source.content) > 5000 for source in context.sources)
        or sum(len(source.content) for source in context.sources) > 30000
    ):
        raise ValueError("task sources must fit completely in the model input")
    TaskRequirements.model_validate({key: value[key] for key in TaskRequirements.model_fields})
    dependency = value["depends_on"]
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["goal"] != goal
        or not isinstance(goal, str)
        or not 1 <= len(goal.strip()) <= 4000
        or value["allowed_actions"] != list(ALLOWED_ACTIONS)
        or value["source_versions"] != source_versions(context)
        or not isinstance(dependency, dict)
        or set(dependency) != {"entry_id", "revision"}
        or dependency["entry_id"] != origin_id
        or type(dependency["revision"]) is not int
        or dependency["revision"] < 1
        or len(json.dumps(value, ensure_ascii=False).encode()) > 32768
    ):
        raise ValueError("task brief source or authority mismatch")
    if len(question(value)) > 12000:
        raise ValueError("task brief exceeds model input bound")


def question(value):
    facts = (
        "\n".join("- " + item for item in value["missing_facts"])
        or "- None identified by Chief; verify against the supplied sources."
    )
    sources = (
        "\n".join(
            f"- {s['entry_id']} · revision {s['revision']} · sha256 {s['sha256']}"
            for s in value["source_versions"]
        )
        or "- No saved source passages supplied."
    )
    criteria = "\n".join("- " + item for item in value["completion_criteria"])
    return (
        f"Goal\n{value['goal']}\n\nExpected output\n{value['expected_output']}"
        f"\n\nMissing or unconfirmed facts to preserve\n{facts}\n\nExact source versions\n{sources}"
        f"\n\nCompletion requirements\n{criteria}\n\nAllowed actions\nPrepare a private draft for clinician review only. "
        "No public search, external action, approval or clinical eligibility determination. "
        "Use the supplied source versions; identify unresolved facts and cite the evidence used. "
        "Unknown speakers and continuity warnings remain unresolved unless the source explicitly resolves them. "
        "This task may run independently after Chief's saved assignment. Do not assume any sibling task has finished. "
        "A saved draft establishes only that draft preparation completed; it does not establish that clinical care or external work occurred."
    )


def projection(s, assignment, row):
    """Describe immutable admitted evidence, never synthesize a current grant."""
    from sqlalchemy import select

    from cosmas_os.adapters.gpt41 import _context
    from cosmas_os.application.model_work import digest
    from cosmas_os.application.workspace import WorkspaceError
    from cosmas_os.models import ModelWorkAdmission, WorkspaceEntry, WorkspaceReply

    if row is None or "task_brief" not in row.request_body:
        parent = s.scalar(
            select(ModelWorkAdmission).where(
                ModelWorkAdmission.request_entry_id == assignment.origin_entry_id
            )
        )
        if parent and parent.envelope_contract in {"cosmas-gpt41-prepared.v4", "cosmas-gpt41-prepared.v5"}:
            return {"task_brief_unavailable": True}
        return {}
    try:
        context = _context(row.prepared_envelope["context"])
        task = row.request_body["task_brief"]
        validate(task, context, goal=assignment.brief, origin_id=assignment.origin_entry_id)
        expected_question = question(task)
        if "revision_request" in row.request_body:
            from cosmas_os.application.handoff_revision import revision_question
            from cosmas_os.models import EncounterWorkspace

            expected_question += revision_question(s, s.get(EncounterWorkspace, assignment.workspace_id),
                                                   row.request_body["revision_request"])
        if (
            row.workspace_id != assignment.workspace_id
            or context.workspace_id != assignment.workspace_id
            or context.role != assignment.recipient_role
            or row.box_id != assignment.box_id
            or row.owner_id != assignment.owner_id
            or row.agent_id != assignment.recipient_agent_id
            or row.envelope_sha256 != digest(row.prepared_envelope)
            or context.question != expected_question
        ):
            raise ValueError("task receipt mismatch")
    except (ValueError, TypeError, KeyError, WorkspaceError):
        return {"task_brief_unavailable": True}
    output = {"task_brief": task}
    if row.state == "completed" and row.result_entry_id == row.request_entry_id:
        entry = s.get(WorkspaceEntry, row.result_entry_id)
        reply = s.get(WorkspaceReply, row.result_entry_id)
        if (
            entry
            and reply
            and entry.workspace_id == assignment.workspace_id
            and reply.workspace_id == assignment.workspace_id
            and reply.owner_id == assignment.owner_id
            and reply.agent_id == assignment.recipient_agent_id
        ):
            output["completion_evidence"] = {
                "kind": "saved_private_draft",
                "entry_id": entry.id,
                "revision": entry.revision,
                "sha256": hashlib.sha256(reply.content.encode()).hexdigest(),
                "source_versions": [
                    source
                    for source in task["source_versions"]
                    if any(
                        cited["entry_id"] == source["entry_id"]
                        and cited["revision"] == source["revision"]
                        for cited in reply.citations
                    )
                ],
            }
    return output
