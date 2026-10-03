"""Offline HTTP product-receipt qualification; no provider or real token."""

import json
import os
from copy import deepcopy
from uuid import UUID

import connector_acceptance as acceptance
import httpx
import pytest

SECRET = "invented-test-bearer-never-print"
CONTENT = "Invented private message café. No clinical recommendation."
AT = "2026-10-02T12:00:00.000000Z"


def identifier(number):
    return str(UUID(int=number))


def fixture():
    box, owner, wid = (identifier(n) for n in (1, 2, 3))
    note = {"id": identifier(4), "content": "Invented existing reviewed clinical note.",
            "content_hash": acceptance.payload_hash({"content": "Invented existing reviewed clinical note."}),
            "source_fingerprint": "a" * 64, "core_source": {"id": identifier(5), "sha256": "b" * 64},
            "review": {"id": identifier(6), "reviewed_by": owner}}
    workspace = {"id": wid, "note": {"latest": note}, "entries": [
        {"id": identifier(7), "kind": "google_message", "content": CONTENT, "google_source_state": "current"},
        {"id": identifier(8), "kind": "google_calendar", "content": "Invented selected event summary.", "calendar_source_state": "current"}]}
    metadata = {"kind": "mail", "account": {"label": "Invented account", "email": "invented@example.invalid"},
                "items": [{"id": "observed-one", "thread_id": "thread-one", "subject": "Invented café",
                           "sender": "invented@example.invalid", "received_at": AT, "is_read": False}],
                "more": False, "observed_at": AT}
    listed = {"read_id": identifier(10), "read_key": identifier(11), "kind": "list", "observation_id": identifier(10),
              "source_sha256": "c" * 64, "payload_sha256": acceptance.sha(acceptance.canonical(metadata)),
              "status": "observed", "message": None, "observation": metadata}
    message = {"message_id": "observed-one", "thread_id": "thread-one", "history_id": "42", "subject": "Invented café",
               "sender": "invented@example.invalid", "received_at": AT, "is_read": False, "observed_at": AT,
               "status": "complete", "content": CONTENT, "reason": None, "raw_sha256": "d" * 64,
               "content_sha256": acceptance.sha(CONTENT)}
    read = {"read_id": identifier(12), "read_key": identifier(13), "kind": "message", "observation_id": identifier(10),
            "source_sha256": "e" * 64, "payload_sha256": "f" * 64, "status": "complete", "message": message, "observation": None}
    observation = {"kind": "calendar", "account": metadata["account"], "items": [
        {"id": "event-one", "subject": "Invented date-only event", "starts_at": "2026-10-03", "ends_at": "2026-10-04",
         "all_day": True, "cancelled": False}], "more": True, "observed_at": AT,
        "window": {"starts_at": AT, "ends_at": "2026-10-09T12:00:00.000000Z"}}
    calendar = {"contract_version": 1, "observation_id": identifier(14), "observation_key": identifier(15),
                "source_sha256": "1" * 64, "payload_sha256": acceptance.sha(acceptance.canonical(observation)), "observation": observation}
    faxes = []
    for number, provider in enumerate(("spruce", "srfax", "documo", "efax"), 20):
        fax = {"contract_version": 1, "scope": {"box_id": box, "owner_id": owner, "workspace_id": wid},
               "ticket_id": identifier(number), "operation_id": identifier(number + 10), "revision_id": identifier(number + 20),
               "payload_hash": "2" * 64, "provider": provider, "state": "approved", "version": 1,
               "acceptance": "accepted", "dispatch": "response_observed", "transport": "pending", "result": "none",
               "verification": "pending", "conflicting_evidence": False, "source_current": True,
               "original_account_available": True, "responsible_id": owner, "status_label": "Delivery unconfirmed",
               "next_step": {"code": "check_existing_fax", "label": "Check the existing fax", "requires_human": True},
               "external_outcome": "spruce_posted_delivery_unconfirmed" if provider == "spruce" else "not_established",
               "observation_head": {"sequence": 0, "sha256": "3" * 64}, "evidence_sha256": "4" * 64,
               "last_recorded": None, "pages": None, "observed_at": AT}
        fax["sha256"] = acceptance.public_digest("cosmas-fax-status.v1", {k: v for k, v in fax.items() if k != "observed_at"})
        faxes.append(fax)
    selection = {"box_id": box, "owner_id": owner, "patient_link_id": identifier(50), "patient_id": identifier(51),
                 "practice_id": identifier(52), "expected_actor_id": identifier(53), "practitioner_id": identifier(54),
                 "location_id": identifier(55), "appointment_type_id": identifier(56)}
    intent = {"action": "book", "selection": selection, "expected": None,
              "slot": {"starts_at": "2026-10-03T12:00:00Z", "ends_at": "2026-10-03T12:30:00Z"},
              "google": {"provider": "google", "calendar_id": "primary", "connection_id": identifier(57),
                         "connected_at": "2026-10-01T12:00:00Z", "checked_at": AT}, "expires_at": "2026-10-02T12:04:00Z"}
    intent_hash = acceptance.AppointmentIntent.model_validate(intent).approval_hash()
    appointment = {"workspace_id": wid, "owner_id": owner, "ticket_id": identifier(60), "revision_id": identifier(61),
                   "payload_hash": intent_hash, "state": "pending_approval", "intent": intent,
                   "appointment_saved": False, "dispatch_started": False, "result": None}
    plan = {"contract_version": 1, "mode": "synthetic_fixture", "origin": "http://127.0.0.1:18766",
            "box_id": box, "owner_id": owner, "workspace_id": wid,
            "note": {k: note[k] for k in ("id", "content_hash", "source_fingerprint")},
            "messages": [{"read_id": v["read_id"], "kind": v["kind"], "source_sha256": v["source_sha256"],
                          "content_sha256": None if v["message"] is None else v["message"]["content_sha256"]} for v in (listed, read)],
            "calendar": [{"observation_id": calendar["observation_id"], "source_sha256": calendar["source_sha256"]}],
            "sources": [{"entry_id": e["id"], "kind": e["kind"], "content_sha256": acceptance.sha(e["content"])} for e in workspace["entries"]],
            "faxes": [{**{k: f[k] for k in ("ticket_id", "provider", "operation_id", "revision_id", "payload_hash")},
                       "status_sha256": f["sha256"]} for f in faxes],
            "appointments": [{k: appointment[k] for k in ("ticket_id", "revision_id", "payload_hash")}]}
    plan["note"].update(core_source_sha256=acceptance.sha(acceptance.canonical(note["core_source"])),
                        review_sha256=acceptance.sha(acceptance.canonical(note["review"])))
    root = "/workspaces/" + wid
    responses = {root: workspace, "/connections/google/messages:list": listed, "/connections/google/messages:message": read,
                 "/provider-team": {"recovery_scope": acceptance.payload_hash({"contract": "cosmas-private-drafts-v1", "box_id": box, "owner_id": owner})},
                 "/connections/google/calendar-summaries": calendar,
                 root + "/appointments/" + appointment["ticket_id"]: appointment}
    responses.update({root + "/vendor-work/" + f["ticket_id"] + "/status": f for f in faxes})
    return plan, responses


def response(value, **changes):
    raw = acceptance.canonical(value).encode()
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store", **changes}
    return httpx.Response(200, headers=headers, stream=httpx.ByteStream(raw))


def transport_for(plan, values, calls, alter=None):
    def handle(request):
        calls.append(request)
        assert request.url.host == "127.0.0.1" and request.url.port == 18766
        assert request.headers["authorization"] == "Bearer " + SECRET
        assert request.headers["accept"] == "application/json"
        assert request.headers["accept-encoding"] == "identity"
        assert "cookie" not in request.headers
        path = request.url.path
        assert not request.url.query
        key = path
        if path.startswith("/connections/google/"):
            assert request.method == "POST" and request.headers["content-type"] == "application/json"
            body = json.loads(request.content)
            assert body["action"] == "inspect"
            if path.endswith("messages"):
                assert request.headers["x-cosmas-google-messages"] == "1"
                assert set(body) == {"action", "read_id"}
                key += ":list" if body["read_id"] == plan["messages"][0]["read_id"] else ":message"
            else:
                assert request.headers["x-cosmas-google-calendar"] == "1"
                assert set(body) == {"action", "observation_id"}
        else:
            assert request.method == "GET" and not request.content
            if "/vendor-work/" in path:
                assert request.headers["x-cosmas-vendor-contract"] == "1"
        value = deepcopy(values[key])
        return alter(key, value, len(calls)) if alter else response(value)
    return httpx.MockTransport(handle)


def checked_run(plan, values, alter=None):
    calls = []
    report, code = acceptance.run(plan, SECRET, transport=transport_for(plan, values, calls, alter))
    encoded = acceptance.canonical(report)
    for private in (SECRET, CONTENT, "Invented café", "invented@example.invalid", "Invented existing reviewed clinical note."):
        assert private not in encoded
    return report, code, calls


def test_all_saved_receipts_note_coexistence_and_no_provider_requests():
    report, code, calls = checked_run(*fixture())
    assert code == 0 and report["clinical_note_unchanged"]
    assert len(report["checks"]) == 8 and len(calls) == report["product_requests"] == 11
    assert report["signed_human_scope_verified"]
    assert report["provider_read_requests"] == report["provider_write_requests"] == report["product_mutations"] == 0
    assert not report["live_provider_acceptance_established"]
    spruce = next(c for c in report["checks"] if c.get("provider") == "spruce")
    assert spruce["external_outcome"] == "spruce_posted_delivery_unconfirmed"
    calendar = next(c for c in report["checks"] if c["kind"] == "google_calendar_receipt")
    assert calendar["partial"] and not calendar["availability_established"]


@pytest.mark.parametrize("fault", ["scope", "human_scope", "content", "fax_scope", "fax_hash", "appointment_hash", "appointment_state", "note", "revoked", "source", "window", "extra", "header_thread", "completed_appointment"])
def test_changed_binding_refuses_without_retry_or_disclosure(fault):
    plan, values = fixture()
    root = "/workspaces/" + plan["workspace_id"]
    if fault == "scope":
        values[root]["id"] = identifier(999)
    elif fault == "human_scope":
        values["/provider-team"]["recovery_scope"] = "a" * 64
    elif fault == "content":
        values["/connections/google/messages:message"]["message"]["content"] += "changed"
    elif fault == "fax_scope":
        next(v for k, v in values.items() if "/vendor-work/" in k)["scope"]["owner_id"] = identifier(999)
    elif fault == "fax_hash":
        next(v for k, v in values.items() if "/vendor-work/" in k)["transport"] = "failed"
    elif fault == "appointment_hash":
        next(v for k, v in values.items() if "/appointments/" in k)["intent"]["selection"]["patient_id"] = identifier(999)
    elif fault == "appointment_state":
        next(v for k, v in values.items() if "/appointments/" in k)["state"] = SECRET
    elif fault == "note":
        values[root]["note"]["latest"]["content"] += "changed"
    elif fault in {"revoked", "source"}:
        entry = values[root]["entries"][0]
        entry["google_source_state"] = "unavailable" if fault == "revoked" else "current"
        entry["content"] = "" if fault == "revoked" else "changed"
    elif fault == "window":
        values["/connections/google/calendar-summaries"]["observation"]["window"]["ends_at"] = "2026-10-10T12:00:00Z"
    elif fault == "extra":
        values["/connections/google/messages:message"]["private_token"] = SECRET
    elif fault == "header_thread":
        values["/connections/google/messages:list"]["observation"]["items"][0]["thread_id"] = "bad\nthread"
    else:
        next(v for k, v in values.items() if "/appointments/" in k)["dispatch_started"] = True
    report, code, calls = checked_run(plan, values)
    assert code == 1 and "error" in report and len(calls) <= 10
    assert len({(c.method, str(c.url), c.content) for c in calls}) == len(calls)


@pytest.mark.parametrize("fault", ["redirect", "auth", "no_store", "compressed", "length", "growth", "duplicate_json", "invalid_json", "timeout"])
def test_http_failures_do_not_follow_retry_or_log_response(fault):
    plan, values = fixture()

    def alter(key, value, count):
        if fault == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.invalid/steal"}, stream=httpx.ByteStream(SECRET.encode()))
        if fault == "auth":
            return httpx.Response(403, stream=httpx.ByteStream(CONTENT.encode()))
        if fault == "no_store":
            return response(value, **{"Cache-Control": "public"})
        if fault == "compressed":
            return response(value, **{"Content-Encoding": "gzip"})
        if fault == "length":
            return response(value, **{"Content-Length": str(acceptance.MAX_WORKSPACE + 1)})
        if fault == "growth":
            return httpx.Response(200, headers={"Content-Type": "application/json", "Cache-Control": "no-store"},
                                  stream=httpx.ByteStream(b"x" * (acceptance.MAX_WORKSPACE + 1)))
        if fault in {"duplicate_json", "invalid_json"}:
            raw = b'{"id":"one","id":"two"}' if fault == "duplicate_json" else b'{"content":"' + CONTENT.encode()
            return httpx.Response(200, headers={"Content-Type": "application/json", "Cache-Control": "no-store"}, stream=httpx.ByteStream(raw))
        raise httpx.ReadTimeout(SECRET)

    report, code, calls = checked_run(plan, values, alter)
    assert code == 1 and len(calls) == report["product_requests"] == 1


def test_clinical_note_changes_between_saved_reads_are_detected():
    plan, values = fixture()

    def alter(key, value, count):
        if count == 11:
            value["note"]["latest"]["review"] = None
        return response(value)

    report, code, calls = checked_run(plan, values, alter)
    assert code == 1 and report["error"] == "clinical_note_changed" and len(calls) == 11


@pytest.mark.parametrize("change", [
    {"mode": "live_provider"}, {"contract_version": True}, {"origin": "http://api.example.invalid"},
    {"origin": "https://user:pass@example.invalid"}, {"origin": "https://example.invalid/path"},
    {"origin": "http://127.0.0.1:18766?url=evil"}, {"origin": "http://127.0.0.1:0"},
    {"origin": "http://127.0.0.1:18766\n"}, {"unexpected_action": "send"},
])
def test_unsafe_plan_refused_before_network(change):
    plan, values = fixture()
    plan.update(change)
    report, code, calls = checked_run(plan, values)
    assert code == 1 and report["product_requests"] == 0 and calls == []


def test_duplicate_selector_refused_before_network():
    plan, values = fixture()
    plan["messages"][1] = deepcopy(plan["messages"][0])
    report, code, calls = checked_run(plan, values)
    assert code == 1 and report["error"] == "duplicate_selector" and not calls


def test_stream_deadline_refuses_slow_progress_without_retry(monkeypatch):
    plan, values = fixture()
    ticks = iter((0.0, 16.0))
    monkeypatch.setattr(acceptance, "monotonic", lambda: next(ticks))
    report, code, calls = checked_run(plan, values)
    assert code == 1 and report["error"] == "receipt_read_unconfirmed" and len(calls) == 1


def test_multi_chunk_response_cannot_grow_past_limit():
    plan, _ = fixture()
    calls = []

    class Growing(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"content":"'
            yield b"x" * 80
            yield b"y" * 80

    def handle(request):
        calls.append(request)
        return httpx.Response(200, headers={"Content-Type": "application/json", "Cache-Control": "no-store"}, stream=Growing())

    client = acceptance.SavedReceiptClient(plan, SECRET, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(acceptance.Refused, match="response_limit"):
            client.read("/workspaces/" + plan["workspace_id"], maximum=128)
        assert len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize("token", ["token\nheader", "token space", "", "é", "x" * 16385])
def test_invalid_token_never_reaches_network(token):
    plan, _ = fixture()
    report, code = acceptance.run(plan, token, transport=httpx.MockTransport(lambda _: pytest.fail("no request authorized")))
    assert code == 1 and report["product_requests"] == 0 and report["error"] == "invalid_token_input"


def test_saved_needs_human_is_an_honest_incomplete_receipt():
    plan, values = fixture()
    plan["messages"][1]["content_sha256"] = None
    values["/connections/google/messages:message"].update(status="needs_human")
    values["/connections/google/messages:message"]["message"].update(status="needs_human", content=None, content_sha256=None, reason="attachment")
    report, code, _ = checked_run(plan, values)
    assert code == 0 and report["checks"][1]["status"] == "needs_human"


def test_fd_input_prints_only_safe_report(tmp_path, monkeypatch, capsys):
    plan, _ = fixture()
    path = tmp_path / "plan.json"
    path.write_text(acceptance.canonical(plan))
    read_fd, write_fd = os.pipe()
    os.write(write_fd, SECRET.encode())
    os.close(write_fd)
    monkeypatch.setattr(acceptance.sys, "argv", ["connector_acceptance.py", "--plan", str(path), "--token-fd", str(read_fd)])

    def fake_run(supplied, token):
        assert supplied == plan and token == SECRET
        return {"contract_version": 1, "qualification": "synthetic_fixture"}, 0

    monkeypatch.setattr(acceptance, "run", fake_run)
    try:
        assert acceptance.main() == 0
        assert json.loads(capsys.readouterr().out) == {"contract_version": 1, "qualification": "synthetic_fixture"}
    finally:
        os.close(read_fd)


def test_reviewed_inbound_fax_source_is_verified_without_reacquisition():
    plan, values = fixture()
    content = "Invented reviewed fax passage. No external treatment or delivery occurred."
    entry = {"id": identifier(70), "kind": "efax_inbound_source", "content": content, "fax_source_state": "current"}
    plan["sources"].append({"entry_id": entry["id"], "kind": entry["kind"], "content_sha256": acceptance.sha(content)})
    values["/workspaces/" + plan["workspace_id"]]["entries"].append(entry)
    report, code, calls = checked_run(plan, values)
    assert code == 0 and report["selected_source_count"] == 3
    assert report["clinical_note_unchanged"] and report["product_requests"] == 11
    assert report["provider_read_requests"] == report["provider_write_requests"] == 0
    assert content not in acceptance.canonical(report)
    assert not any("efax-inbound" in request.url.path for request in calls)


@pytest.mark.parametrize("fault", ["revoked", "changed", "missing", "duplicate"])
def test_inbound_fax_source_refuses_stale_changed_missing_or_ambiguous_evidence(fault):
    plan, values = fixture()
    content = "Invented reviewed fax passage"
    entry = {"id": identifier(70), "kind": "efax_inbound_source", "content": content, "fax_source_state": "current"}
    plan["sources"].append({"entry_id": entry["id"], "kind": entry["kind"], "content_sha256": acceptance.sha(content)})
    workspace = values["/workspaces/" + plan["workspace_id"]]
    workspace["entries"].append(entry)
    if fault == "revoked":
        entry["fax_source_state"] = "unavailable"
        entry["content"] = ""
    elif fault == "changed":
        entry["content"] += " changed"
    elif fault == "missing":
        workspace["entries"].remove(entry)
    else:
        workspace["entries"].append(dict(entry))
    report, code, calls = checked_run(plan, values)
    assert code == 1 and report["product_requests"] == 2
    assert report["provider_read_requests"] == report["provider_write_requests"] == 0
    assert content not in acceptance.canonical(report)
