"""Journaled public lookups and explicit saving of source excerpts to existing evidence."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, tuple_

from cosmas_os.api.research_schemas import Save, Search, SourceRecord
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import WorkspaceEntry, _uuid
from cosmas_os.ports.research import ResearchUnavailable, research_digest
from cosmas_os.research_models import ResearchRun, ResearchSave


def observation(row, *, now=None):
    now = now or datetime.now(UTC)
    request = Search.model_validate_json(json.dumps(row.request)).model_dump(mode="json")
    if request != row.request or research_digest(request) != row.request_sha256:
        raise ValueError("research request integrity")
    if row.idempotency_key != request["idempotency_key"]:
        raise ValueError("research command identity")
    if not isinstance(row.results, list) or len(row.results) > 15:
        raise ValueError("research result limit")
    results = [SourceRecord.model_validate(value).model_dump(mode="json") for value in row.results]
    if (len({(v["source"], v["id"], v["version"]) for v in results}) != len(results)
            or len({v["sha256"] for v in results}) != len(results)
            or any(sum(value["source"] == source for value in results) > 5 for source in request["sources"])
            or any(v["source"] not in request["sources"]
                   or v["query_sha256"] != research_digest({"source": v["source"], "query": request["query"]}) for v in results)):
        raise ValueError("research source integrity")
    codes = {"source_unavailable", "source_timeout", "source_rate_limited", "invalid_source_response", "source_not_configured", "no_matching_record"}
    if (not isinstance(row.errors, list) or len(row.errors) > 3
            or any(type(error) is not dict or set(error) != {"source", "code"}
                   or error["source"] not in request["sources"] or error["code"] not in codes for error in row.errors)
            or len({error["source"] for error in row.errors}) != len(row.errors)):
        raise ValueError("research error integrity")
    if ((row.state == "completed" and row.errors)
            or (row.state == "partial" and (not row.errors or not results))
            or (row.state == "unavailable" and (not row.errors or results))
            or (row.state == "running" and (row.errors or results))):
        raise ValueError("research state integrity")
    state = row.state
    if state == "running" and (now - row.created_at).total_seconds() >= 35:
        state = "interrupted"
    return {"contract": "research.lookup.v1", "workspace_id": row.workspace_id,
            "run_id": row.id, "idempotency_key": row.idempotency_key,
            "request_sha256": row.request_sha256, "request": request,
            "bot": request["bot"], "topic": request["topic"], "query": request["query"],
            "sources": request["sources"], "created_at": row.created_at.isoformat(),
            "state": state, "results": results, "errors": row.errors}


def _run(s, box, owner, wid, *, key=None, run_id=None):
    ws._workspace(s, box, owner, wid)
    query = select(ResearchRun).where(ResearchRun.workspace_id == wid,
                                     ResearchRun.box_id == box, ResearchRun.owner_id == owner)
    query = query.where(ResearchRun.idempotency_key == key) if key is not None else query.where(ResearchRun.id == run_id)
    value = s.scalar(query)
    if value is None:
        raise ws.WorkspaceError("research_not_found", 404)
    return value


def resolve(s, box, owner, wid, *, key):
    return observation(_run(s, box, owner, wid, key=key))


def _cursor(value):
    if value is not None:
        try:
            parsed = UUID(value)
            if str(parsed) != value or parsed.version != 4:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ws.WorkspaceError("invalid_research_request", 422) from None
    return value


def history(s, box, owner, wid, *, bot, before=None):
    if _cursor(bot) is None:
        raise ws.WorkspaceError("invalid_research_request", 422)
    _cursor(before)
    ws._workspace(s, box, owner, wid)
    query = select(ResearchRun).where(
        ResearchRun.workspace_id == wid, ResearchRun.box_id == box,
        ResearchRun.owner_id == owner, ResearchRun.request["bot"].astext == bot,
    )
    if before is not None:
        anchor = s.scalar(query.where(ResearchRun.id == before))
        if anchor is None:
            raise ws.WorkspaceError("research_not_found", 404)
        observation(anchor)
        query = query.where(tuple_(ResearchRun.created_at, ResearchRun.id)
                            < (anchor.created_at, anchor.id))
    rows = s.scalars(query.order_by(ResearchRun.created_at.desc(), ResearchRun.id.desc()).limit(5)).all()
    return {"contract": "research.history.v1", "runs": [observation(row) for row in rows]}


def saved_history(s, box, owner, wid, *, bot, before=None):
    """Read verified existing packets; never resave evidence or perform source/model I/O."""
    if _cursor(bot) is None:
        raise ws.WorkspaceError("invalid_research_request", 422)
    _cursor(before)
    ws._workspace(s, box, owner, wid)
    query = select(ResearchSave, ResearchRun, WorkspaceEntry).join(
        ResearchRun, ResearchRun.id == ResearchSave.run_id,
    ).join(WorkspaceEntry, WorkspaceEntry.id == ResearchSave.entry_id).where(
        ResearchSave.workspace_id == wid, ResearchSave.box_id == box,
        ResearchRun.workspace_id == wid, ResearchRun.box_id == box,
        ResearchRun.owner_id == owner, ResearchRun.request["bot"].astext == bot,
        WorkspaceEntry.workspace_id == wid, WorkspaceEntry.box_id == box,
    )
    if before is not None:
        anchor = s.execute(query.where(ResearchSave.entry_id == before)).one_or_none()
        if anchor is None:
            raise ws.WorkspaceError("research_not_found", 404)
        _saved(s, anchor[0])
        query = query.where(WorkspaceEntry.revision < anchor[2].revision)
    rows = s.execute(query.order_by(WorkspaceEntry.revision.desc(), ResearchSave.id.desc()).limit(5)).all()
    packets = [{"query": run.request["query"], "saved": _saved(s, receipt)}
               for receipt, run, _ in rows]
    if len({packet["saved"]["entry_id"] for packet in packets}) != len(packets):
        raise ValueError("duplicate_saved_research_entry")
    return {"contract": "research.saved_history.v1", "workspace_id": wid, "bot": bot, "packets": packets}


def search(s, box, owner, wid, *, request, configured, port, check, reauthenticate):
    """Persist an immutable intent before I/O. Repeated keys only read that intent."""
    value = request.model_dump(mode="json")
    digest = research_digest(value)
    s.rollback()
    check()
    reauthenticate()
    w = ws._workspace(s, box, owner, wid, writing=True)
    prior = s.scalar(select(ResearchRun).where(ResearchRun.workspace_id == wid,
                                             ResearchRun.idempotency_key == value["idempotency_key"]))
    if prior is not None:
        if prior.request_sha256 != digest:
            raise ws.WorkspaceError("idempotency_conflict", 409)
        return observation(prior)
    version, bot, preferences = team.active_bot(s, box, owner, value["bot"], value["team_revision"])
    if preferences["role"] != "research":
        raise ws.WorkspaceError("research_bot_required", 409)
    if w.revision != value["expected_revision"]:
        raise ws.WorkspaceError("workspace_revision_conflict", 409)
    if s.scalar(select(func.count()).select_from(ResearchRun).where(ResearchRun.workspace_id == wid)) >= 100:
        raise ws.WorkspaceError("research_history_limit", 409)
    if not set(value["sources"]) <= configured:
        raise ws.WorkspaceError("research_source_not_configured", 409)
    row = ResearchRun(workspace_id=wid, box_id=box, owner_id=owner, agent_id=bot.agent_id,
                      idempotency_key=value["idempotency_key"], request=value,
                      request_sha256=digest, state="running", results=[], errors=[])
    s.add(row)
    check()
    s.commit()
    row_id = row.id
    s.rollback()
    results, errors = [], []

    def current():
        remaining = check()
        s.expire_all()
        reauthenticate()
        ws._workspace(s, box, owner, wid)
        team.active_bot(s, box, owner, value["bot"], value["team_revision"])
        s.rollback()
        return min(remaining, check())

    for source in value["sources"]:
        current()
        try:
            found = port.lookup(source, value["query"], check=current)
            if len(found) > 5:
                raise ResearchUnavailable("invalid_source_response")
            records = [SourceRecord.model_validate(record).model_dump(mode="json") for record in found]
            if any(record["source"] != source for record in records):
                raise ResearchUnavailable("invalid_source_response")
            results.extend(records)
        except ResearchUnavailable as error:
            allowed = {"source_unavailable", "source_timeout", "source_rate_limited",
                       "invalid_source_response", "source_not_configured", "no_matching_record"}
            errors.append({"source": source, "code": error.code if error.code in allowed else "source_unavailable"})
    current()
    # This owner lock shares the existing workspace write boundary. Offboarding
    # or changed bot configuration cannot publish a late lookup response.
    ws._workspace(s, box, owner, wid, writing=True)
    # The shared owner lock above conflicts with every team revision write.
    # Recheck this exact bot under that lock and retain it until settlement commits.
    _, current_bot, current_preferences = team.active_bot(s, box, owner, value["bot"], value["team_revision"])
    if current_preferences["role"] != "research":
        raise ws.WorkspaceError("research_bot_required", 409)
    row = s.scalar(select(ResearchRun).where(ResearchRun.id == row_id).with_for_update())
    if row is None or row.state != "running" or current_bot.agent_id != row.agent_id:
        raise ws.WorkspaceError("research_state_conflict", 409)
    row.results, row.errors = results, errors
    row.state = "partial" if errors and results else "unavailable" if errors else "completed"
    row.finished_at = datetime.now(UTC)
    output = observation(row)
    if len(json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()) > 131072:
        raise ws.WorkspaceError("research_result_too_large", 503)
    check()
    reauthenticate()
    s.commit()
    return output


def source_excerpt(records):
    blocks = []
    for record in records:
        SourceRecord.model_validate(record)
        blocks.append("\n".join([
            record["title"], record["url"],
            "Source: " + record["source"] + " / " + record["id"],
            "Retrieved: " + record["retrieved_at"],
            "Source updated: " + (record["source_updated_at"] or "Not supplied"),
            "Version: " + (record["version"] or "Not supplied"),
            "Excerpt shortened: " + ("Yes; open the source for full details" if record["truncated"] else "No"),
            "Content SHA-256: " + record["sha256"], record["excerpt"],
        ]))
    content = "Public research source excerpts. Source claims require clinician review.\n\n" + "\n\n---\n\n".join(blocks)
    if len(content) > 20000:
        raise ws.WorkspaceError("research_selection_too_large", 422)
    return content


def _saved(s, row):
    request = Save.model_validate_json(json.dumps(row.request)).model_dump(mode="json")
    if (request != row.request or research_digest(request) != row.request_sha256
            or request["idempotency_key"] != row.idempotency_key):
        raise ValueError("research save integrity")
    run = s.get(ResearchRun, row.run_id)
    if run is None or run.workspace_id != row.workspace_id or run.box_id != row.box_id:
        raise ValueError("research run integrity")
    observed = observation(run)
    records = {record["sha256"]: record for record in observed["results"]}
    if (observed["state"] not in {"completed", "partial"}
            or not set(request["source_hashes"]) <= records.keys()):
        raise ValueError("research selection integrity")
    entry = s.get(WorkspaceEntry, row.entry_id)
    if (entry is None or entry.workspace_id != row.workspace_id or entry.box_id != row.box_id
            or entry.actor_id != run.owner_id or entry.kind != "evidence"
            or entry.source_label != "Research · public source excerpts"
            or entry.idempotency_key != "research:" + row.id
            or entry.request_hash != row.request_sha256
            or entry.revision != request["expected_revision"] + 1
            or entry.content != source_excerpt([records[key] for key in request["source_hashes"]])):
        raise ValueError("research evidence integrity")
    return {"contract": "research.saved.v1", "workspace_id": row.workspace_id,
            "run_id": row.run_id, "idempotency_key": row.idempotency_key,
            "request_sha256": row.request_sha256, "request": row.request,
            "entry_id": entry.id, "entry_revision": entry.revision}


def resolve_save(s, box, owner, wid, run_id, *, key):
    _run(s, box, owner, wid, run_id=run_id)
    row = s.scalar(select(ResearchSave).where(ResearchSave.workspace_id == wid,
                                             ResearchSave.run_id == run_id,
                                             ResearchSave.idempotency_key == key))
    if row is None:
        raise ws.WorkspaceError("research_not_found", 404)
    return _saved(s, row)


def save(s, box, owner, wid, run_id, *, request, check, reauthenticate):
    check()
    reauthenticate()
    w = ws._workspace(s, box, owner, wid, writing=True)
    run = _run(s, box, owner, wid, run_id=run_id)
    value = request.model_dump(mode="json")
    digest = research_digest(value)
    prior = s.scalar(select(ResearchSave).where(ResearchSave.workspace_id == wid,
                                               ResearchSave.idempotency_key == value["idempotency_key"]))
    if prior:
        if prior.run_id != run_id or prior.request_sha256 != digest:
            raise ws.WorkspaceError("idempotency_conflict", 409)
        return _saved(s, prior)
    if w.revision != value["expected_revision"]:
        raise ws.WorkspaceError("workspace_revision_conflict", 409)
    if w.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit", 409)
    observed = observation(run)
    records = {record["sha256"]: record for record in observed["results"]}
    if observed["state"] not in {"completed", "partial"} or not set(value["source_hashes"]) <= records.keys():
        raise ws.WorkspaceError("research_selection_unavailable", 409)
    content = source_excerpt([records[key] for key in value["source_hashes"]])
    # Both the evidence and receipt commit together; recovery never recreates an entry.
    entry_id, receipt_id = _uuid(), _uuid()
    w.revision += 1
    entry = WorkspaceEntry(id=entry_id, workspace_id=wid, box_id=box, actor_id=owner,
                           revision=w.revision, kind="evidence", content=content,
                           source_label="Research · public source excerpts",
                           idempotency_key="research:" + receipt_id, request_hash=digest)
    s.add(entry)
    s.flush()
    receipt = ResearchSave(id=receipt_id, run_id=run_id, workspace_id=wid, box_id=box, entry_id=entry_id,
                           idempotency_key=value["idempotency_key"], request=value, request_sha256=digest)
    s.add(receipt)
    ws._audit(s, w, "entry_saved")
    check()
    reauthenticate()
    s.commit()
    return _saved(s, receipt)
