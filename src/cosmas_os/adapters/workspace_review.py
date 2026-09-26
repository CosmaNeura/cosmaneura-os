"""Useful local read tools, not an LLM or a replacement clinical engine."""

import re
from dataclasses import replace

from cosmas_os.ports.bot_capabilities import BotContext, BotReply


class WorkspaceReviewConnector:
    def review(self, context: BotContext) -> BotReply:
        if context.role == "custom" and "work_status" in context.skills:
            work = self.review(replace(context, role="follow_up"))
            if "saved_context" not in context.skills or not context.sources:
                return work
            sources = self.review(replace(context, skills=()))
            return BotReply(sources.content + "\n\n" + work.content, sources.citations)
        if context.role == "follow_up":
            lines = [
                f"• {lane.replace('_', ' ')}: {state.replace('_', ' ')}"
                for lane, state in context.linked_work
            ]
            lines.extend(f"• Follow-up due {item.due_date}: {item.label}" for item in context.follow_ups)
            return BotReply(
                "Linked work at this revision:\n"
                + "\n".join(lines)
                + "\n\nLocal delivery is a synthetic receipt. A human-recorded completion is the human's attestation. This lookup takes no action."
                if lines
                else "There is no linked work in this encounter yet. Use the Work tab to link an existing record or propose a local follow-up from the reviewed note.",
                (),
            )
        if context.role == "chief":
            return BotReply(
                f"This encounter has {len(context.sources)} source item(s) available to me and {len(context.linked_work) + len(context.follow_ups)} work record(s).\n\n"
                + "\n".join(f"• Follow-up due {item.due_date}: {item.label}" for item in context.follow_ups)
                + "\n\n"
                "I can review this saved context. Background routines and staff handoffs are awaiting their backend connections; no background work has been started.",
                (),
            )
        sources = list(context.sources)
        if context.role == "scribe":
            sources = [s for s in sources if s.kind == "scratchpad"][-1:]
        else:
            words = set(re.findall(r"[a-z]{4,}", context.question.lower())) - {
                "this",
                "that",
                "what",
                "with",
                "have",
                "saved",
                "review",
                "preparation",
            }
            sources.sort(
                key=lambda s: (
                    len(words & set(re.findall(r"[a-z]{4,}", s.content.lower()))),
                    s.revision,
                ),
                reverse=True,
            )
        sources = sources[: 2 if context.response_style == "brief" else 4]
        if not sources:
            return BotReply(
                "I don't have any saved sources available for this review. Add a notebook entry or evidence, and check this bot's source settings. Live chart retrieval and AI answers are awaiting connection.",
                (),
            )
        return BotReply(
            "Here are the saved passages available for review. This is a local source lookup; it does not generate clinical advice or an AI answer.\n\n"
            + "\n\n".join(
                f"[{i}] {source.content[:900]}{'…' if len(source.content) > 900 else ''}"
                for i, source in enumerate(sources, 1)
            ),
            tuple(sources),
        )
