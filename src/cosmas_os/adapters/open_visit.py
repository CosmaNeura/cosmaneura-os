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
            "It is not a chart, medication list, diagnosis, or completed history. "
            "Name this visit in the answer. If saved notes, intake, or preparation are absent, "
            "say what is missing and that the clinician can save notebook notes or add a reference note."
        )

    @staticmethod
    def limit(draft_only=False):
        return 12000 if draft_only else 4000

    @staticmethod
    def notice(draft_only=False):
        limit = OpenVisitContext.limit(draft_only)
        return (
            "The open visit was left off this question because adding it would go over "
            f"{limit:,} characters. Shorten the question and ask again to include the visit."
        )

    @staticmethod
    def question(content, visit, *, draft_only=False):
        if not visit:
            return content
        block = "\n\n" + OpenVisitContext.MARK + visit
        limit = OpenVisitContext.limit(draft_only)
        if len(content) + len(block) <= limit:
            return content + block
        notice = "\n\n" + OpenVisitContext.notice(draft_only)
        if len(content) + len(notice) <= limit:
            return content + notice
        return content

    @staticmethod
    def supplied(question):
        mark = "\n\n" + OpenVisitContext.MARK
        if mark not in question:
            return None
        visit = question.rsplit(mark, 1)[1].strip()
        return visit or None

    @staticmethod
    def stated_omission(question):
        if OpenVisitContext.supplied(question):
            return None
        for draft_only in (False, True):
            notice = OpenVisitContext.notice(draft_only)
            if notice in question:
                return notice
        return None

    @staticmethod
    def omitted(content, visit, question, *, draft_only=False):
        if not visit or OpenVisitContext.supplied(question):
            return False
        block = "\n\n" + OpenVisitContext.MARK + visit
        return len(content) + len(block) > OpenVisitContext.limit(draft_only)

    @staticmethod
    def with_notice(response, content, visit, question, *, draft_only=False):
        if not OpenVisitContext.omitted(content, visit, question, draft_only=draft_only):
            return response
        notice = OpenVisitContext.notice(draft_only)
        if notice in response:
            return response
        if OpenVisitContext.MISSING in response:
            replaced = response.replace(OpenVisitContext.MISSING, notice, 1)
            if notice in replaced:
                return replaced
        combined = response + "\n\n" + notice
        if len(combined) > 20000:
            return response
        return combined
