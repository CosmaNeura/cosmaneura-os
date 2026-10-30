"""The visit that is open, named for Chief without inventing a chart."""


class OpenVisitContext:
    """Identity of the encounter the clinician already opened.

    It is attached to Chief's question because a model source must be a saved
    workspace entry. The saved human message stays the clinician's own words.
    """

    MARK = "Open visit supplied with this request:\n"
    MISSING = (
        "No visit details or saved notes were supplied. Open a visit, or save notebook notes "
        "or add a reference note, and ask again."
    )
    NOTES_GAP = (
        "Saved notes, intake, and preparation were not supplied. Save notebook notes or add a "
        "reference note on this visit, then ask again."
    )

    @staticmethod
    def text(appointment):
        if appointment is None:
            return None
        label = " ".join(str(appointment.patient_label).split())
        if not label or len(label) > 200:
            return None
        if appointment.start_at is not None:
            when = f"Visit time: {appointment.start_at.isoformat()}."
        elif appointment.source_local_start is not None:
            when = (
                f"Visit time: {appointment.source_local_start.isoformat()} "
                "(practice local time; time zone was not supplied)."
            )
        else:
            when = "Visit time was not supplied."
        return (
            f"Open visit: {label}. {when} This is the visit that is open. "
            "It is not a chart, medication list, diagnosis, or completed history."
        )

    @staticmethod
    def question(content, visit, *, draft_only=False):
        if not visit:
            return content
        block = "\n\n" + OpenVisitContext.MARK + visit
        limit = 12000 if draft_only else 4000
        if len(content) + len(block) > limit:
            return content
        return content + block

    @staticmethod
    def supplied(question):
        mark = "\n\n" + OpenVisitContext.MARK
        if mark not in question:
            return None
        visit = question.rsplit(mark, 1)[1].strip()
        return visit or None
