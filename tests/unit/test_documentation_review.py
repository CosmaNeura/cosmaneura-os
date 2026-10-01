"""Native source review must retain transcripts and never invent completion."""

from dataclasses import replace

from tests.unit.test_core_scribe_bridge import reviewed_fixture

from cosmas_os.adapters.workspace_review import WorkspaceReviewConnector
from cosmas_os.application.scribe_source import packet_content, selection
from cosmas_os.ports.bot_capabilities import BotContext, SourcePassage


def context(sources=(), role="scribe", response_style="brief"):
    return BotContext("invented", 4, role, "Review this documentation", response_style, sources, ())


def test_native_scribe_retains_transcript_and_preparation_without_notebook():
    sources = (
        SourcePassage("transcript", 2, "Supplied transcript", "evidence",
            "Patient: No chest pain today. Clinician: Records are not yet reviewed. Plan: request records."),
        SourcePassage("prep", 3, "Derived Visit Prep", "session_prep",
            "Patient-reported concern. Confirm DOB when available; currently unknown."),
    )
    result = WorkspaceReviewConnector().review(context(sources))
    assert result.citations == sources
    assert all(source.content in result.content for source in sources)
    assert "revision 2" in result.content and "revision 3" in result.content
    assert "No saved documentation" not in result.content
    assert "not a generated or reviewed clinical note" in result.content
    assert result.handoffs == ()


def test_added_notebook_does_not_hide_available_transcript():
    sources = (SourcePassage("notebook", 1, "My notes", "scratchpad", "Request outside records."),
               SourcePassage("transcript", 2, "Transcript", "evidence", "No records were reviewed."))
    reply = WorkspaceReviewConnector().review(context(sources))
    assert reply.citations == sources and all(source.content in reply.content for source in sources)


def test_native_review_identifies_excerpt_and_omitted_sources_without_silence():
    sources = tuple(SourcePassage(str(i), i, "Invented source", "evidence", "Planned. " * 300) for i in range(1, 10))
    result = WorkspaceReviewConnector().review(context(sources))
    assert len(result.citations) == 4 and "Showing 4 of 9" in result.content
    assert result.content.count("Excerpt only.") == 4
    assert len(result.content) < 20000
    detailed = WorkspaceReviewConnector().review(replace(context(sources), response_style="detailed"))
    assert len(detailed.citations) == 8 and len(detailed.content) < 20000


def test_missing_sources_do_not_claim_services_disconnected():
    for role in ("scribe", "visit_prep"):
        result = WorkspaceReviewConnector().review(context(role=role))
        assert result.citations == () and "supplied" in result.content
        assert "awaiting connection" not in result.content and "not connected" not in result.content


def test_reviewed_translation_packet_retains_exact_segment_and_review_lineage():
    view = reviewed_fixture()
    selected = selection(view)
    content = packet_content(view, selected)
    assert view.working is not None
    segment = view.working.segments[0]
    assert str(segment.source_segment_id) in content
    assert f"source language: {segment.source_locale}; resolution: spanish_translation" in content
    assert str(segment.translation_id) in content and str(segment.translation_review_id) in content
    assert segment.content is not None
    assert segment.content in content and "continuity is unconfirmed" in content
