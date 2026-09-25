"""Direct SQL adversarial coverage for the private Inbox evidence ledger."""

import copy
from datetime import timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from tests.integration.test_inbox_work import (
    ON,
    bound,
    command,
    constraints,
    detail,
    ingest,
    result,
    review,
    snapshot,
    triage,
    verify,
)
from tests.integration.test_inbox_work import (
    inbox_case as inbox_case,
)
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import inbox_work as flow
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.inbox_models import InboxEvent, InboxItem, InboxSource
from cosmas_os.models import EncounterWorkspace, PatientLink, Principal
from cosmas_os.ports.vendor_connectors import digest


def source_insert(s, c, iid, mutate=None):
    value = snapshot(c, 1, text_="Next invented source").model_dump(mode="json")
    if mutate:
        mutate(value)
    value["source_sha256"] = digest(
        "cosmas-spruce-inbox-source.v1",
        {
            k: v
            for k, v in value.items()
            if k
            not in {
                "source_sha256",
                "observed_at",
                "item_response_sha256",
                "conversation_response_sha256",
            }
        },
    )
    return {
        "id": str(uuid4()),
        "item_id": iid,
        "box_id": c["box"],
        "owner_id": c["actor"],
        "sequence": 2,
        "source_sha256": value["source_sha256"],
        "snapshot": value,
        "snapshot_sha256": digest("cosmas-inbox-stored-snapshot.v1", value),
        "recorded_at": c["base_time"],
    }


@pytest.mark.parametrize(
    "field",
    [
        "trust",
        "text",
        "modified_at",
        "created_at",
        "observed_at",
        "conversation_archived",
        "item_response_sha256",
    ],
)
def test_rehashed_source_missing_required_field_is_refused_before_insert(
    session, inbox_case, field
):
    c = inbox_case
    iid = ingest(session, c)["item_id"]
    values = source_insert(session, c, iid, lambda value: value.pop(field))
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(insert(InboxSource).values(**values))
    assert len(flow.history(session, c["box"], c["actor"], iid)["sources"]) == 1


@pytest.mark.parametrize(
    "mode",
    [
        "unknown_key",
        "null_text",
        "null_flag",
        "missing_flag",
        "wrong_type",
        "duplicate_type",
        "control_text",
    ],
)
def test_rehashed_source_unsupported_shape_is_refused(session, inbox_case, mode):
    c = inbox_case
    iid = ingest(session, c)["item_id"]

    def mutate(v):
        if mode == "unknown_key":
            v["automatic_approval"] = True
        elif mode == "null_text":
            v["text"] = None
        elif mode == "null_flag":
            v["unsupported"]["attachments"] = None
        elif mode == "missing_flag":
            v["unsupported"].pop("buttons")
        elif mode == "wrong_type":
            v["unsupported"]["attachment_types"] = ["dangerousExecutable"]
        elif mode == "control_text":
            v["text"] = "forbidden\x01control"
        else:
            v["unsupported"].update(attachments=True, attachment_types=["document", "document"])

    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(insert(InboxSource).values(**source_insert(session, c, iid, mutate)))


def test_valid_source_without_read_receipt_cannot_commit(session, inbox_case):
    c = inbox_case
    iid = ingest(session, c)["item_id"]
    with (
        pytest.raises(DBAPIError, match="inbox source requires read receipt"),
        session.begin_nested(),
    ):
        session.execute(insert(InboxSource).values(**source_insert(session, c, iid)))
        constraints(session)


@pytest.mark.parametrize(
    "mode",
    [
        "source_update",
        "source_delete",
        "event_update",
        "event_delete",
        "item_identity",
        "head_tamper",
        "version_skip",
    ],
)
def test_immutable_source_receipt_and_projection_guards(session, inbox_case, mode):
    c = inbox_case
    x = ingest(session, c)
    iid = x["item_id"]
    with pytest.raises(DBAPIError), session.begin_nested():
        if mode == "source_update":
            session.execute(
                text(
                    'UPDATE inbox_sources SET snapshot=snapshot||\'{"trust":"trusted"}\'::jsonb WHERE item_id=:id'
                ),
                {"id": iid},
            )
        elif mode == "source_delete":
            session.execute(text("DELETE FROM inbox_sources WHERE item_id=:id"), {"id": iid})
        elif mode == "event_update":
            session.execute(
                text(
                    'UPDATE inbox_events SET response=response||\'{"outcome":"newer"}\'::jsonb WHERE item_id=:id'
                ),
                {"id": iid},
            )
        elif mode == "event_delete":
            session.execute(text("DELETE FROM inbox_events WHERE item_id=:id"), {"id": iid})
        elif mode == "item_identity":
            session.execute(
                text("UPDATE inbox_items SET grant_id=:g WHERE id=:id"),
                {"id": iid, "g": str(uuid4())},
            )
        elif mode == "head_tamper":
            session.execute(
                text("UPDATE inbox_items SET current_source_id=NULL WHERE id=:id"), {"id": iid}
            )
        else:
            session.execute(
                text("UPDATE inbox_items SET version=version+2 WHERE id=:id"), {"id": iid}
            )
        constraints(session)


def rehashed_event(s, c, iid, mode):
    prior = s.scalar(
        select(InboxEvent).where(InboxEvent.item_id == iid).order_by(InboxEvent.version.desc())
    )
    assert prior is not None
    data = {col.name: getattr(prior, col.name) for col in InboxEvent.__table__.columns}
    data = copy.deepcopy(data)
    data.update(id=str(uuid4()), version=prior.version + 1, idempotency_key="sql-" + str(uuid4()))
    data["request"]["idempotency_key"] = data["idempotency_key"]
    if data["origin"] == "read":
        if mode == "null_error":
            data["request"]["safe_error"] = None
        else:
            data["request"]["item_response_sha256"] = "f" * 64
        data["request_sha256"] = public.public_digest(
            "cosmas-inbox-ingest-request.v1", data["request"]
        )
        data["response"].update(
            id=data["id"],
            version=data["version"],
            request_sha256=data["request_sha256"],
            safe_error=data["request"]["safe_error"],
            item_response_sha256=data["request"]["item_response_sha256"],
        )
        domain = "cosmas-inbox-read-receipt.v1"
    else:
        data["request"]["expected_version"] = prior.version
        data["request_sha256"] = public.public_digest(
            "cosmas-inbox-request.v1",
            {
                "scope": flow.scope(c["box"], c["actor"]),
                "command_kind": data["kind"],
                "request": data["request"],
            },
        )
        data["response"].update(
            receipt_id=data["id"],
            request_sha256=data["request_sha256"],
            idempotency_key=data["idempotency_key"],
        )
        if mode == "null_outcome":
            data["response"]["outcome"] = None
        else:
            data["response"].update(outcome="rejected", effect=None, rejection=None)
        if data["response"]["effect"]:
            data["response"]["effect"]["version"] = data["version"]
        domain = "cosmas-inbox-receipt.v1"
    data["receipt_sha256"] = public.public_digest(domain, data["response"])
    s.execute(update(InboxItem).where(InboxItem.id == iid).values(version=data["version"]))
    return data


@pytest.mark.parametrize("mode", ["null_error", "failure_wire_hash"])
def test_rehashed_read_failure_cannot_erase_exception_with_null_or_wire_body(
    session, inbox_case, mode
):
    c = inbox_case
    iid = flow.read_failed(
        session,
        c["grant"],
        "first-failed-read",
        "response_invalid",
        registry=c["registry"],
        policy=ON,
    )["item_id"]
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(insert(InboxEvent).values(**rehashed_event(session, c, iid, mode)))


@pytest.mark.parametrize("mode", ["null_outcome", "null_rejection"])
def test_rehashed_human_null_outcomes_cannot_bypass_guard(session, inbox_case, mode):
    c = inbox_case
    iid = ingest(session, c)["item_id"]
    review(session, c, iid)
    expected = (
        "inbox admission lost source authority"
        if mode == "null_outcome"
        else "inbox rejection mismatch"
    )
    with pytest.raises(DBAPIError, match=expected), session.begin_nested():
        session.execute(insert(InboxEvent).values(**rehashed_event(session, c, iid, mode)))


def test_equivalent_created_timestamp_offset_accepts_newer_source(session, inbox_case):
    c = inbox_case
    ingest(session, c)
    v = snapshot(c, 1, text_="Newer same creation instant")
    v = v.model_copy(update={"created_at": v.created_at.astimezone(timezone(timedelta(hours=-4)))})
    v = v.model_copy(update={"source_sha256": v.snapshot_digest()})
    assert ingest(session, c, v)["outcome"] == "newer"
    constraints(session)


@pytest.mark.parametrize("whitespace", ["\n", "\u0085", "\u2003", "\u3000"])
def test_rehashed_whitespace_only_source_cannot_become_administrative(
    session, inbox_case, whitespace
):
    c = inbox_case
    iid = ingest(session, c, snapshot(c, text_=whitespace * 3))["item_id"]
    review(session, c, iid)
    triage(session, c, iid, "source_exception")
    with (
        pytest.raises(DBAPIError, match="inbox triage requires exact human review"),
        session.begin_nested(),
    ):
        data = rehashed_event(session, c, iid, "null_outcome")
        data["request"]["classification"] = "administrative_review"
        data["request_sha256"] = public.public_digest(
            "cosmas-inbox-request.v1",
            {
                "scope": flow.scope(c["box"], c["actor"]),
                "command_kind": "triage",
                "request": data["request"],
            },
        )
        row = session.get(InboxItem, iid)
        assert row is not None
        src = session.get(InboxSource, row.current_source_id)
        assert src is not None
        data["response"].update(
            outcome="recorded",
            rejection=None,
            request_sha256=data["request_sha256"],
            effect={
                "item_id": iid,
                "version": data["version"],
                "source_id": src.id,
                "source_sha256": src.source_sha256,
                "state": "triaged",
            },
        )
        data["receipt_sha256"] = public.public_digest("cosmas-inbox-receipt.v1", data["response"])
        session.execute(insert(InboxEvent).values(**data))


def test_older_arrival_cannot_clear_later_failed_read(session, inbox_case):
    c = inbox_case
    iid = ingest(session, c, snapshot(c, 10))["item_id"]
    flow.read_failed(
        session,
        c["grant"],
        "failed-latest-read",
        "reference_unavailable",
        registry=c["registry"],
        policy=ON,
    )
    assert ingest(session, c, snapshot(c, 1))["outcome"] == "older"
    assert detail(session, c, iid)["summary"]["read_issue"] == "reference_unavailable"
    constraints(session)


def test_future_version_rejection_remains_inert_when_version_advances(session, inbox_case):
    c = inbox_case
    iid = ingest(session, c)["item_id"]
    q = bound(
        session,
        c,
        iid,
        workspace_id=c["wid"],
        expected_workspace_revision=3,
        patient_link_id=c["correspondence"].patient_link_id,
        reviewed_patient=True,
        reviewed_exact_thread=True,
        reviewed_untrusted_source=True,
    )
    q["expected_version"] += 1
    rejected = command(session, c, iid, "review", q)
    assert rejected["rejection"] == "inbox_version_changed"
    assert command(session, c, iid, "review", q) == rejected
    assert detail(session, c, iid)["latest_review"] is None
    constraints(session)


def test_long_valid_vendor_ids_have_public_projection(session, inbox_case):
    c = inbox_case
    binding = c["grant"].binding.model_copy(
        update={"conversation_id": "c" * 255, "item_id": "i" * 255}
    )
    c["grant"] = c["grant"].model_copy(update={"binding": binding})
    c["registry_state"]["registry"] = flow.InboxRegistry([c["grant"]])
    iid = ingest(session, c)["item_id"]
    assert len(detail(session, c, iid)["source"]["conversation_id"]) == 255
    assert len(detail(session, c, iid)["source"]["item_reference"]) == 255
    constraints(session)


def test_changed_workspace_invalidates_current_human_chain(session, inbox_case):
    c = inbox_case
    iid = ingest(session, c)["item_id"]
    review(session, c, iid)
    t = triage(session, c, iid)
    w = session.get(EncounterWorkspace, c["wid"])
    w.revision += 1
    session.commit()
    assert not detail(session, c, iid)["summary"]["workspace_current"]
    assert result(session, c, iid, t)["outcome"] == "rejected"
    constraints(session)


@pytest.mark.parametrize("who", ["owner", "patient", "correspondence"])
def test_current_revocation_prevents_new_source_commit(session, inbox_case, who):
    c = inbox_case
    ingest(session, c)
    if who == "owner":
        session.get(Principal, c["actor"]).state = "revoked"
    elif who == "patient":
        session.get(PatientLink, c["correspondence"].patient_link_id).revoked_at = c["base_time"]
    else:
        c["correspondence"].revoked_at = c["base_time"]
    session.commit()
    with pytest.raises(WorkspaceError):
        ingest(session, c, snapshot(c, 1))


def test_reserved_result_and_verify_slots_stay_available(session, inbox_case):
    c = inbox_case
    iid = ingest(session, c)["item_id"]
    review(session, c, iid)
    for _ in range(93):
        assert triage(session, c, iid)["outcome"] == "recorded"
    d = detail(session, c, iid)
    assert d["summary"]["version"] == 95
    t = triage(session, c, iid)
    d = detail(session, c, iid)
    assert (
        d["summary"]["version"] == 96
        and d["availability"]["result"]
        and not d["availability"]["triage"]
    )
    r = result(session, c, iid, t)
    assert detail(session, c, iid)["availability"]["verify"]
    assert verify(session, c, iid, r)["outcome"] == "recorded"
    assert detail(session, c, iid)["summary"]["version"] == 98
    constraints(session)
