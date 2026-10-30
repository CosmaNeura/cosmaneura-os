"""Native source/work organization available before a model or connector setup."""

from cosmas_os.adapters.open_visit import OpenVisitContext
from cosmas_os.ports.bot_capabilities import BotReply


def review(context, *, operational_rows=()):
    lines = ["Saved encounter overview"]
    citations = []
    visit = OpenVisitContext.supplied(context.question)
    if visit:
        lines.append("Open visit:")
        lines.append("• " + visit)
    if context.sources:
        lines.append("Sources to carry into the handoff:")
        for source in context.sources[:12]:
            excerpt = source.content[:450]
            lines.append(f"• {source.label} · revision {source.revision}: {excerpt}" +
                         ("… [excerpt; inspect the full source]" if len(source.content) > 450 else ""))
            citations.append(source)
        if len(context.sources) > 12:
            lines.append(f"{len(context.sources) - 12} additional sources are outside this overview.")
    elif visit:
        lines.append(OpenVisitContext.NOTES_GAP)
    else:
        lines.append(OpenVisitContext.MISSING)
    if context.linked_work or context.follow_ups:
        lines.append("Current work:")
        lines.extend(f"• {lane.replace('_', ' ')}: {state.replace('_', ' ')}" for lane, state in context.linked_work)
        lines.extend(f"• Follow-up due {item.due_date}: {item.label}" for item in context.follow_ups)
    else:
        lines.append("No linked work was supplied at this revision.")
    if operational_rows:
        lines.append("Next steps for saved work:")
        for row in operational_rows[:12]:
            evidence = row.get("evidence", {})
            lines.append("• " + row["kind"].replace("_", " ") + ": " + row["next_step"]["label"]
                + " · " + evidence.get("provenance", "current application observation").replace("_", " ")
                + " · " + evidence.get("external_outcome", "unverified").replace("_", " "))
    lines.extend(["Handoff checklist:",
        "• Give the receiving bot a concrete next action, the source version and the expected output.",
        "• Keep missing facts, conflicting summaries and planned actions unresolved until the source or reviewer resolves them.",
        "• Review the returned material; request edits against that version, then review the revision before signing off.",
        "This overview organizes saved sources and work. It does not create assignments or mark work complete."])
    return BotReply("\n".join(lines), tuple(citations))
