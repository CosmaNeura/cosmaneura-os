"""Native Scribe lookup of supplied documentation; no generated clinical claims."""

from cosmas_os.ports.bot_capabilities import BotContext, BotReply

MAX_EXCERPT = 1800


def review_documentation(context: BotContext) -> BotReply:
    sources = list(context.sources)
    if not sources:
        return BotReply(
            "No saved documentation was supplied for this review. Add or share the transcript, "
            "preparation or jotted notes for this encounter, then try again. "
            "This does not tell me whether those services are connected.",
            (),
        )
    # Context admission already enforces the bot's source permissions and whole
    # Scribe packets. Do not silently discard transcripts in favor of scratchpad.
    limit = 4 if context.response_style == "brief" else 8
    selected = sources[-limit:]
    lines = [
        "Saved documentation for review",
        "These are quoted sources, not a generated or reviewed clinical note. "
        "Preserve the source's speaker, uncertainty and planned versus completed actions.",
    ]
    for index, source in enumerate(selected, 1):
        excerpt = source.content[:MAX_EXCERPT]
        lines.append(f"[{index}] {source.label} · revision {source.revision}\n{excerpt}")
        if len(excerpt) < len(source.content):
            lines.append("Excerpt only. Open the cited source for the remaining text before using it.")
    if len(selected) < len(sources):
        lines.append(f"Showing {len(selected)} of {len(sources)} supplied source passages. "
                     "Earlier passages are not shown here; review the full saved sources before finalizing a note.")
    lines.append("Next: use the cited source material to prepare or correct your draft. "
                 "Review of a transcript, review of a draft note and clinical sign-off are separate steps.")
    return BotReply("\n\n".join(lines), tuple(selected))
