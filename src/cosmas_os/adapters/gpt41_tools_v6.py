"""Compact provider delivery with full-source custody; v5 stays replayable."""

import hashlib
import re
from copy import deepcopy
from dataclasses import asdict, replace

from cosmas_os.adapters.gpt41 import (
    GPT41Connector,
    _bounded_context,
    _checked_envelope,
    _context,
    _preserved_record_order,
    decode_response,
)
from cosmas_os.adapters.gpt41_tools import (
    GPT41ToolsConnector,
    _body,
    _canonical,
    _digest,
    _json_unique,
)
from cosmas_os.ports.agent_tools import ToolSelection

CURRENT_PREPARED_CONTRACT = "cosmas-gpt41-prepared.v6"
EXCERPT_CHARS = 1000
TOTAL_EXCERPT_CHARS = 6000
COMPLETE_SOURCE_INSTRUCTIONS = "\nAll selected sources are supplied in full. Use them directly; exact handles are already in tool_selection. Avoid redundant list/read calls.\n"

DELIVERY_INSTRUCTIONS = """
The exact evidence handles are already in tool_selection: do not list them again just to learn their IDs.
The sources in this request are bounded excerpts. source_delivery states which excerpts are complete and which need an exact read_selected_source read for more detail. Use a complete supplied source directly; do not reread it merely to confirm its presence. Read a truncated source only if more detail is necessary. Never infer the omitted text.
The full-source hash binds the saved original; excerpt_sha256 binds only the displayed excerpt. A successful full-source read replaces only that excerpt in later requests, with its exact receipt-bearing tool result. No read widens the admitted sources, current authority or available actions.
decoder_source_windows defines the initial citation/quote window. A successful exact read_selected_source result makes that source's returned text available for citations and Scribe verbatim quotes, including an initially omitted source. No other tool adds clinical citations. Without a successful read, Scribe quotes must fit the actual displayed excerpt; never quote an unseen tail. Preserve missing, omitted or truncated evidence explicitly.
"""

SOURCE_HANDLE_INSTRUCTIONS = """
For read_selected_source arguments, copy entry_id, revision and sha256 together ONLY from tool_selection.sources. That sha256 is the full original source hash. Never calculate a hash from displayed text or copy a quote-window/excerpt diagnostic into a tool argument.
source_delivery and displayed_excerpt_windows describe supplied text lengths only; they are not additional tool handles. The full source remains available only through its exact tool_selection handle. A displayed_excerpt_windows prefix is the initial quote/citation limit until an exact full-source read succeeds.
"""

READ_ONLY_TURN_INSTRUCTIONS = """
The earlier prohibition on executing tools refers to external or action tools. This explicit operational contract permits only the four supplied server-scoped read-only functions: list_selected_sources, read_selected_source, read_saved_teammate_draft and read_current_operation_status. These reads grant no outside action, record change, approval, signature, public search or new access.
A read turn must contain only function calls, with assistant content null or empty. Do not include a preface or a JSON answer in a read turn. Return the original strict final JSON alone after the required reads have succeeded; read receipts do not change that answer contract.
"""

TASK_SOURCE_VERIFICATION_INSTRUCTIONS = """
For this private specialist assignment, Chief's task brief, goal, requirements, conversation and quoted passages do not establish that you have read the original source. They do not make omitted original text available or authorize verbatim source quotes, even if Chief already read that original.
If the task asks you to read or verify the full transcript or original source, fulfill that requirement before drafting: use read_selected_source with the exact tool_selection.sources handle for each relevant source marked excerpt or omitted in source_delivery. Do not treat facts or quotations copied into the goal as a substitute. Verify task facts against the received original, preserving disagreements and uncertainty rather than copying unsupported claims.
Use a source marked complete directly; do not reread it. Once an exact source read succeeds, its receipt-bearing result is the full supplied original; do not read it again. Scribe verbatim quotes must occur in a complete supplied source or that verified full-source result. Other specialist drafts must not claim a full-source review that did not occur. If required original text cannot be obtained within the existing tool limits, identify the missing verification; never imply it succeeded.
"""

TASK_READ_TURN_INSTRUCTIONS = """
If this assignment requires reading or verifying a full original marked excerpt or omitted, your next response must request read_selected_source with that relevant exact tool_selection.sources handle before drafting. Until the required original has been received, do not answer in JSON, add a preface or repeat Chief's task quotations in that read turn. After a successful exact receipt-bearing read, use the returned original and do not request it again. A complete supplied source needs no read.
"""


def _hash(content):
    return hashlib.sha256(content.encode()).hexdigest()


def _delivery(baseline, context):
    originals = {source.entry_id: source for source in context.sources}
    remaining, records = TOTAL_EXCERPT_CHARS, []
    from cosmas_os.application.scribe_source import require_complete_context

    # Reviewed transcript/summary packets are intentionally indivisible.
    # Preserve their entire existing bounded delivery; lazy reads cannot stand
    # in for the complete source required by the Scribe intake contract.
    require_complete_context(context.sources)
    # Keep the original decoder's order and source eligibility. Its newest
    # bounded sources lead the provider delivery, with omissions explicit.
    for source in baseline["sources"]:
        packet = bool(re.fullmatch(r"Reviewed Scribe snapshot · [a-f0-9]{64} · [1-9][0-9]*/[1-9][0-9]*", source["label"]))
        text = source["text"] if packet else source["text"][:min(EXCERPT_CHARS, remaining)]
        if not text:
            continue
        original = originals[source["source_id"]]
        records.append({**source, "text": text, "truncated": len(text) < len(original.content)})
        if not packet:
            remaining -= len(text)
    displayed = {source["source_id"]: source for source in records}
    manifest = []
    for original in context.sources:
        excerpt = displayed.get(original.entry_id)
        text = excerpt["text"] if excerpt else ""
        manifest.append({"entry_id": original.entry_id, "revision": original.revision,
            "sha256": _hash(original.content), "excerpt_chars": len(text),
            "excerpt_sha256": _hash(text), "delivery": "complete" if text == original.content
            else "excerpt" if text else "omitted"})
    windows = [{"entry_id": source["source_id"], "revision": source["revision"],
        "prefix_chars": len(source["text"]), "sha256": _hash(source["text"])}
        for source in records]
    return records, manifest, windows


def _compact_body(baseline, selection, context):
    body = _body(baseline, selection)
    sources, manifest, windows = _delivery(baseline, context)
    if all(item["delivery"] == "complete" for item in manifest):
        # Short notes and indivisible Scribe packets are already complete.
        # Avoid adding a redundant delivery manifest to their model prompts.
        body["messages"][2]["content"] += COMPLETE_SOURCE_INSTRUCTIONS
        return body, manifest
    content = _json_unique(body["messages"][1]["content"])
    content["sources"] = sources
    content["source_delivery"] = manifest
    content["decoder_source_windows"] = windows
    body["messages"][1]["content"] = _canonical(content)
    body["messages"][2]["content"] += DELIVERY_INSTRUCTIONS
    return body, manifest


def validate_prepared(envelope):
    if not isinstance(envelope, dict) or set(envelope) != {
        "contract", "decoder", "baseline", "body", "context", "tool_selection", "source_delivery",
    } or envelope.get("contract") != CURRENT_PREPARED_CONTRACT or (
        envelope.get("decoder") != "cosmas-gpt41-decoder.v6"
    ):
        raise ValueError("invalid compact operational envelope")
    context = _context(envelope["context"])
    # Original history/source bytes remain committed for current-input checks.
    # The old output decoder has its independently bounded history and sources.
    _bounded_context(replace(context, history=tuple((role, text[:3000]) for role, text in context.history)))
    baseline = GPT41Connector(lambda: "").prepare(context)
    _checked_envelope(envelope["baseline"])
    # JSONB reorders descriptor dictionaries but retains the saved provider
    # string. Use the original v4 reconstruction of those two known record
    # families, with exact values/body/schema comparisons still required.
    baseline["body"]["messages"][1]["content"] = _preserved_record_order(
        baseline["body"]["messages"][1]["content"],
        envelope["baseline"]["body"]["messages"][1]["content"])
    selection = ToolSelection.model_validate(envelope["tool_selection"]).model_dump()
    unhashed = {key: value for key, value in selection.items() if key != "sha256"}
    exact_sources = [{"entry_id": p.entry_id, "revision": p.revision, "sha256": _hash(p.content),
        "label": p.label, "kind": p.kind} for p in context.sources]
    if selection["sha256"] != _digest(unhashed) or selection["sources"] != exact_sources:
        raise ValueError("compact full-source selection changed")
    body, manifest = _compact_body(baseline, selection, context)
    if _canonical(envelope["baseline"]) != _canonical(baseline) or envelope["body"] != body or envelope["source_delivery"] != manifest:
        raise ValueError("compact delivery differs from exact preparation")
    if len(_canonical(envelope).encode()) > 2 * 1_048_576:
        raise ValueError("compact envelope exceeds bound")
    return envelope


class GPT41CompactToolsConnector(GPT41ToolsConnector):
    def _validate(self, envelope):
        return validate_prepared(envelope)

    def _request_body(self, envelope):
        body = super()._request_body(envelope)
        content = _json_unique(body["messages"][1]["content"])
        if "source_delivery" not in content:
            return body  # Complete sources keep the existing short fast path.
        # Keep the historical prepared body/manifest and its receipt hash
        # unchanged. Display diagnostics must not compete with full handles in
        # tool_selection, especially when a model copies a nearby sha256 field.
        content["source_delivery"] = [
            {key: value for key, value in record.items() if key not in {"sha256", "excerpt_sha256"}}
            for record in content["source_delivery"]
        ]
        content["displayed_excerpt_windows"] = [
            {key: value for key, value in record.items() if key != "sha256"}
            for record in content.pop("decoder_source_windows")
        ]
        body["messages"][1]["content"] = _canonical(content)
        body["messages"][2]["content"] = body["messages"][2]["content"].replace(
            "The full-source hash binds the saved original; excerpt_sha256 binds only the displayed excerpt.",
            "The exact full-source sha256 in tool_selection binds the saved original; displayed excerpt lengths are diagnostic only.",
        ).replace("decoder_source_windows", "displayed_excerpt_windows") + SOURCE_HANDLE_INSTRUCTIONS + READ_ONLY_TURN_INSTRUCTIONS
        if envelope["context"]["draft_only"]:
            # Delivery guidance applies only to this outbound request. Keep
            # saved v6 preparation and historical receipt commitments exact.
            body["messages"][2]["content"] += TASK_SOURCE_VERIFICATION_INSTRUCTIONS + TASK_READ_TURN_INSTRUCTIONS
        return body

    def prepare(self, context, tool_selection):
        baseline = GPT41Connector(lambda: "").prepare(context)
        selection = ToolSelection.model_validate(tool_selection).model_dump()
        body, manifest = _compact_body(baseline, selection, context)
        envelope = {"contract": CURRENT_PREPARED_CONTRACT, "decoder": "cosmas-gpt41-decoder.v6",
            "baseline": baseline, "body": body, "context": asdict(context),
            "tool_selection": selection, "source_delivery": manifest}
        validate_prepared(envelope)
        return envelope

    def _after_tool(self, body, envelope, checked, value):
        if checked["tool"] != "read_selected_source":
            return
        # Receipt identity/hash was checked by the shared bounded transport.
        # Independently bind the returned bytes to the original selected source
        # before removing an excerpt; other delivered evidence stays intact.
        data = value["data"]
        source = next((p for p in _context(envelope["context"]).sources
            if p.entry_id == checked["entry_id"] and p.revision == checked["revision"]
            and _hash(p.content) == checked["sha256"]), None)
        if source is None or data != {"entry_id": source.entry_id, "revision": source.revision,
            "sha256": _hash(source.content), "label": source.label, "kind": source.kind,
            "content": source.content}:
            raise ValueError("compact source read differs from admitted original")
        content = _json_unique(body["messages"][1]["content"])
        content["sources"] = [item for item in content["sources"] if item["source_id"] != source.entry_id]
        body["messages"][1]["content"] = _canonical(content)

    def _decode(self, envelope, data, body, **usage):
        # This v6 decoder derives eligibility from bytes actually supplied in
        # the initial request or an exactly verified receipt-bearing read.
        # Neither prepared baseline storage nor metadata handles alone grant
        # citation/quote eligibility. The v4 parser's schema stays unchanged.
        context = _context(envelope["context"])
        sources, _, _ = _delivery(envelope["baseline"], context)
        available = {source["source_id"]: source for source in sources}
        originals = {source.entry_id: source for source in context.sources}
        for message in body["messages"]:
            if message["role"] != "tool":
                continue
            result = _json_unique(message["content"])
            if result["tool"] != "read_selected_source":
                continue
            returned = result["data"]
            original = originals[returned["entry_id"]]
            available[original.entry_id] = {"source_id": original.entry_id,
                "revision": original.revision, "label": original.label, "kind": original.kind,
                "text": original.content, "truncated": False}
        decoded = deepcopy(envelope["baseline"])
        decoded["sources"] = [available[p.entry_id] for p in context.sources if p.entry_id in available]
        decoded["context"] = asdict(replace(context,
            sources=tuple(replace(p, content=available[p.entry_id]["text"])
                for p in context.sources if p.entry_id in available),
            history=_context(envelope["baseline"]["context"]).history))
        return decode_response(decoded, data, **usage)
