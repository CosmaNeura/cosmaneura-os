"""Hardened CLI validators consume actual signed product responses, not copies.

All upstream setup is invented. The acceptance pass itself must do no provider
I/O or mutation. Fixtures retain real PostgreSQL custody and fresh HTTP sessions.
"""

import hashlib
import importlib.util
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from lab.fax_tools import FaxTools
from sqlalchemy.orm import Session
from tests.integration import test_google_calendar as calendar_test
from tests.integration import test_google_message as message_test
from tests.integration.test_fax_status import counts, saved
from tests.integration.test_fax_tools import prepared_fax
from tests.integration.test_hosted_appointment_proposals import capture_case as capture_case
from tests.integration.test_hosted_appointment_proposals import proposal_case as proposal_case
from tests.integration.test_hosted_appointment_proposals import proposed
from tests.integration.test_virtual_clinic_lab import clinic as clinic
from tests.integration.test_workspace_auth import signed_workspace as signed_workspace

from cosmas_os.api import app as api
from cosmas_os.application import google_calendar as calendar
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import ExternalIdentity

SPEC = importlib.util.spec_from_file_location("receipt_acceptance", Path(__file__).resolve().parents[2] / "scripts/connector_acceptance.py")
assert SPEC is not None and SPEC.loader is not None
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)
http_case = message_test.http_case


def plan_for(box, owner, snapshot):
    note = snapshot["note"]["latest"]
    assert note is not None and note["review"] is not None
    return {"contract_version": 1, "mode": "synthetic_fixture", "origin": "http://127.0.0.1:18766",
        "box_id": box, "owner_id": owner, "workspace_id": snapshot["id"],
        "note": {"id": note["id"], "content_hash": note["content_hash"], "source_fingerprint": note["source_fingerprint"],
            "core_source_sha256": acceptance.sha(acceptance.canonical(note["core_source"])) if note["core_source"] else None,
            "review_sha256": acceptance.sha(acceptance.canonical(note["review"]))},
        "messages": [], "calendar": [], "faxes": [], "appointments": [],
        "sources": [{"entry_id": e["id"], "kind": e["kind"], "content_sha256": hashlib.sha256(e["content"].encode()).hexdigest()}
            for e in snapshot["entries"] if e["kind"] in {"google_message", "google_calendar"}]}


def actual_transport(client, calls):
    def request(item):
        calls.append((item.method, item.url.path))
        assert item.url.host == "127.0.0.1" and not item.url.query
        response = client.request(item.method, item.url.path, headers=dict(item.headers), content=item.content)
        # The body and headers here are the exact protected product API output.
        return httpx.Response(response.status_code, headers=response.headers,
                              stream=httpx.ByteStream(response.content))
    return httpx.MockTransport(request)


def execute(client, plan, token):
    calls = []
    report, code = acceptance.run(plan, token, transport=actual_transport(client, calls))
    assert code == 0, report
    assert report["clinical_note_unchanged"] and report["signed_human_scope_verified"]
    assert report["provider_read_requests"] == report["provider_write_requests"] == report["product_mutations"] == 0
    assert not report["live_provider_acceptance_established"]
    assert token not in acceptance.canonical(report)
    return report, calls


def test_actual_signed_google_and_calendar_receipts_preserve_reviewed_note(http_case, monkeypatch):
    f, wid = http_case, http_case.workspace["id"]
    monkeypatch.setattr(f.configuration, "workspace_google_calendar_enabled", True)
    monkeypatch.setattr(team, "runtime_settings", f.configuration)
    state = ws.read(f.s, f.box, f.actor, wid)
    state = notes.save(f.s, f.box, f.actor, wid, expected=state["revision"], key=str(uuid4()),
        base_note_id=None, source_reply_id=None, content="Invented clinical note retained alongside independent Google sources.")["workspace"]
    note = state["note"]["latest"]
    notes.review(f.s, f.box, f.actor, wid, note["id"], expected=state["revision"], key=str(uuid4()),
        content_hash=note["content_hash"], source_hash=note["source_fingerprint"])
    headers = {**f.headers, "X-Cosmas-Draft-Recovery": "2", "X-Cosmas-Model-Contract": "1"}
    listed = f.client.post("/connections/google/messages", headers=headers,
        json={"action": "list", "idempotency_key": str(uuid4())})
    assert listed.status_code == 200
    listed = listed.json()
    read = f.client.post("/connections/google/messages", headers=headers, json={"action": "read", "idempotency_key": str(uuid4()),
        "observation_id": listed["observation_id"], "observation_sha256": listed["source_sha256"], "message_id": "invented-message"})
    assert read.status_code == 200
    read = read.json()
    snapshot = f.client.get("/workspaces/" + wid, headers=headers).json()
    selected = f.client.post("/workspaces/" + wid + "/google-messages/review", headers=headers,
        json={"expected_revision": snapshot["revision"], "idempotency_key": str(uuid4()), "read_id": read["read_id"],
            "source_sha256": read["source_sha256"], "reviewed_patient": True, "reviewed_exact_message": True,
            "reviewed_untrusted_source": True})
    assert selected.status_code == 200
    invented_calendar = calendar_test.InventedCalendar(f.s, f.binding.id, f.port.connected)
    original = invented_calendar.calendar_binding

    def binding(identity, *, session=None):
        assert session is not None
        invented_calendar.session = session
        return original(identity, session=session)

    monkeypatch.setattr(f.port, "calendar_binding", binding, raising=False)
    monkeypatch.setattr(f.port, "calendar_observation", invented_calendar.calendar_observation, raising=False)
    h = {**headers, "X-Cosmas-Google-Calendar": "1"}
    with calendar.install_binding_reader(lambda s, a: binding(calendar._scoped_identity(a), session=s)):
        observed = f.client.post("/connections/google/calendar-summaries", headers=h,
            json={"action": "observe", "idempotency_key": str(uuid4())})
        assert observed.status_code == 200
        observed = observed.json()
        event = observed["observation"]["items"][0]
        snapshot = f.client.get("/workspaces/" + wid, headers=headers).json()
        selected = f.client.post("/workspaces/" + wid + "/google-calendar/review", headers=h,
            json={"expected_revision": snapshot["revision"], "idempotency_key": str(uuid4()), "observation_id": observed["observation_id"],
                "observation_sha256": observed["source_sha256"], "event_id": event["id"], "event_sha256": calendar.event_hash(event),
                "reviewed_visit": True, "reviewed_exact_summary": True, "reviewed_untrusted_source": True})
        assert selected.status_code == 200
        snapshot = f.client.get("/workspaces/" + wid, headers=headers).json()
        plan = plan_for(f.box, f.actor, snapshot)
        plan["messages"] = [{"read_id": r["read_id"], "kind": r["kind"], "source_sha256": r["source_sha256"],
            "content_sha256": r["message"]["content_sha256"] if r["message"] else None} for r in (listed, read)]
        plan["calendar"] = [{"observation_id": observed["observation_id"], "source_sha256": observed["source_sha256"]}]
        before = (len(f.port.calls), len(invented_calendar.calls))
        monkeypatch.setattr(f.port, "mail", lambda *_: pytest.fail("acceptance must not list Google"))
        monkeypatch.setattr(f.port, "read_message", lambda *_: pytest.fail("acceptance must not read a body"))
        monkeypatch.setattr(f.port, "calendar_observation", lambda *_args, **_kw: pytest.fail("acceptance must not read calendar"))
        wrong_scope = {**plan, "owner_id": str(uuid4())}
        invalid, code = acceptance.run(wrong_scope, f.token(), transport=actual_transport(f.client, []))
        assert code == 1 and invalid["error"] == "signed_scope_changed" and invalid["product_requests"] == 1
        report, _ = execute(f.client, plan, f.token())
        assert len(report["checks"]) == 3 and report["selected_source_count"] == 2
        assert before == (len(f.port.calls), len(invented_calendar.calls))
        assert f.port.text not in acceptance.canonical(report) and event["subject"] not in acceptance.canonical(report)


def test_actual_signed_hosted_appointment_draft_requires_no_receiver_factory(proposal_case, monkeypatch):
    f = proposal_case
    item = proposed(f)
    headers = {**f.headers, "X-Cosmas-Draft-Recovery": "2", "X-Cosmas-Model-Contract": "1"}
    snapshot = f.client.get("/workspaces/" + f.wid, headers=headers)
    assert snapshot.status_code == 200
    plan = plan_for(f.box, f.owner, snapshot.json())
    plan["appointments"] = [{k: item[k] for k in ("ticket_id", "revision_id", "payload_hash")}]
    before = (len(f.receiver.calls), len(f.receiver.credentials))
    monkeypatch.setitem(api.app.dependency_overrides, api._scheduling_connection, lambda: pytest.fail("saved read cannot create scheduling port"))
    monkeypatch.setitem(api.app.dependency_overrides, api._appointment_connection, lambda: pytest.fail("saved read cannot create appointment port"))
    report, _ = execute(f.client, plan, f.token(azp="https://workspace.example.invalid"))
    assert report["checks"][0]["kind"] == "appointment_saved_proposal"
    assert before == (len(f.receiver.calls), len(f.receiver.credentials))


def test_actual_signed_four_fax_saved_receipts_never_create_execution_runtime(clinic, signed_workspace, tmp_path, monkeypatch):
    tools = FaxTools(clinic[0], tmp_path / "acceptance")
    f, subject = signed_workspace, "acceptance-fax-" + str(uuid4())
    monkeypatch.setattr(f.configuration, "beta_box_id", tools.app.box)
    with tools.sessions() as s:
        s.add(ExternalIdentity(box_id=tools.app.box, principal_id=tools.app.owner, provider="clerk",
            issuer=f.configuration.clerk_issuer, subject=subject, organization_id="org_invented",
            reviewed_by="Invented reviewer", evidence_ref="test:acceptance-fax"))
        s.commit()
    statuses = []
    for provider in ("spruce", "srfax", "documo", "efax"):
        ticket = prepared_fax(tools, provider)["detail"]["summary"]["ticket_id"]
        statuses.append(saved(tools, ticket))

    def requests():
        with Session(tools.app.engine, autoflush=False) as s:
            yield s

    monkeypatch.setitem(api.app.dependency_overrides, api.get_session, requests)
    monkeypatch.setitem(api.app.dependency_overrides, api._vendor_execution_factory,
        lambda: pytest.fail("saved acceptance cannot construct provider runtime"))
    headers = {"Authorization": "Bearer " + f.token(sub=subject), "X-Cosmas-Draft-Recovery": "2", "X-Cosmas-Model-Contract": "1"}
    snapshot = f.client.get("/workspaces/" + tools.app.workspace, headers=headers)
    assert snapshot.status_code == 200
    plan = plan_for(tools.app.box, tools.app.owner, snapshot.json())
    plan["faxes"] = [{**{k: v[k] for k in ("ticket_id", "provider", "operation_id", "revision_id", "payload_hash")},
        "status_sha256": v["sha256"]} for v in statuses]
    before, io_before = counts(tools), list(tools.calls)
    report, _ = execute(f.client, plan, f.token(sub=subject))
    assert len(report["checks"]) == 4 and all(v["external_outcome"] == "not_established" for v in report["checks"])
    assert before == counts(tools) and io_before == tools.calls
