"""The reusable lab must prove real persistence and failure outcomes, not prose."""

import json

import pytest
from lab.application import Application
from lab.cases import CLINIC
from lab.clinic import ClinicWorld, run_clinic
from lab.fax_sandbox import exercise_fax, synthetic_pdf
from lab.mail_sandbox import MailSandbox, exercise_mail
from lab.store import Store
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.config import settings
from cosmas_os.models import Decision, Operation


@pytest.fixture
def clinic(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    store = Store(tmp_path)
    app = Application(engine, CLINIC, lambda role, kind, **v: store.event("test", role, kind, **v))
    return app, store


@pytest.mark.parametrize("provider", ["microsoft", "google"])
@pytest.mark.parametrize("fault", ["normal", "read_timeout", "throttled", "token_expiry", "oversized", "revoked_during_read"])
def test_real_account_adapter_failure_and_recovery(clinic, provider, fault):
    app, _ = clinic
    result = exercise_mail(app, provider, fault)
    assert result["passed"], result
    assert result["requests"]


@pytest.mark.parametrize("fault", ["normal", "read_timeout", "throttled", "token_expiry", "oversized", "revoked_during_read"])
def test_google_calendar_failure_and_recovery(clinic, fault):
    result = exercise_mail(clinic[0], "google", fault, kind="calendar")
    assert result["passed"], result
    assert result["requests"]


def test_calendar_rejects_unrecognized_timezone_without_disclosure(clinic):
    result = exercise_mail(clinic[0], "microsoft", "invalid_timezone")
    assert result["passed"]
    assert result["checks"]["no_automatic_request_retry"]


@pytest.mark.parametrize("scenario", ["delivered", "failed", "partial", "lost_reply", "wrong_account"])
def test_real_f8_fax_receipts_survive_repeat_and_remain_honest(clinic, tmp_path, scenario):
    result = exercise_fax(clinic[0], tmp_path / "fax", scenario)
    assert result["passed"], result
    assert sum(call["method"] == "POST" for call in result["requests"]) == 1
    assert result["ticket"]["state"] == ("closed" if scenario == "delivered" else "approved")
    assert "invented-lab-secret" not in json.dumps(result)


@pytest.mark.parametrize("fault", ["none", "read_timeout", "lost_save_reply"])
def test_complete_clinic_uses_one_encounter_and_exact_generated_outputs(clinic, fault):
    app, store = clinic
    result = run_clinic(app, store, "clinic", None, fault, 3)
    assert result["passed"], result["failures"]
    assert len(result["artifacts"]) == 10
    assert len(result["handoff_receipts"]) == 3
    assert set(result["connector_reads"]) == {"mail", "calendar"}
    assert result["application"]["workspace_id"] == app.workspace
    events = [json.loads(line) for line in store.events.read_text().splitlines()]
    imported = {e["artifact_sha256"] for e in events if e["kind"] == "generated_output_imported"}
    assert imported == {a["sha256"] for a in result["artifacts"][:2]}
    review = next(e for e in events if e["kind"] == "message_edited_and_consent_resolved")
    assert review["role"] == "simulated_provider"
    assert review["original_draft_sha256"] == result["artifacts"][3]["sha256"]
    with Session(app.engine) as session:
        assert session.scalar(select(func.count()).select_from(Decision).where(Decision.box_id == app.box)) == 2
        assert session.scalar(select(func.count()).select_from(Operation).where(Operation.box_id == app.box)) == 2


def test_failed_generation_never_reaches_human_approval_or_delivery(clinic):
    class NoWorkModel:
        def reply(self, messages, tools):
            return {"role": "assistant", "content": "Done."}, {}

    app, store = clinic
    result = run_clinic(app, store, "failed-clinic", NoWorkModel(), "none", 3)
    assert result["passed"] is False
    with Session(app.engine) as session:
        assert session.scalar(select(func.count()).select_from(Decision).where(Decision.box_id == app.box)) == 0
        assert session.scalar(select(func.count()).select_from(Operation).where(Operation.box_id == app.box)) == 0


def test_account_tools_only_visible_and_callable_by_admitted_role(clinic):
    app, store = clinic
    mailbox = MailSandbox(app)
    try:
        world = ClinicWorld(store, "tools", CLINIC, app, mailbox=mailbox)
        assert world.tool_visible("visit_prep", "read_calendar")
        assert not world.tool_visible("scribe", "read_calendar")
        assert world.execute("scribe", "read_calendar", {})["error"] == "only_visit_prep_has_account_read_permission"
        assert world.execute("visit_prep", "read_calendar", {"account_id": "foreign"})["error"] == "invalid_tool_arguments"
        assert world.execute("chief", "send_email", {})["error"] == "unknown_tool"
        assert mailbox.calls == []
    finally:
        mailbox.close()


def test_generated_fax_document_has_consistent_pdf_offsets():
    raw = synthetic_pdf()
    xref = int(raw.split(b"startxref\n")[1].splitlines()[0])
    assert raw[xref:].startswith(b"xref\n0 6\n")
    for index, line in enumerate(raw[xref:].splitlines()[3:8], 1):
        assert raw[int(line.split()[0]):].startswith(f"{index} 0 obj".encode())
