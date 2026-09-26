"""Committed PostgreSQL contention and final Inbox authority boundaries.

Every case provisions an invented practice and uses independent connections.
No shared browser fixture, provider, sender, or migration is used here.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from tests.integration.test_inbox_work import (
    ON,
    bound,
    inbox_case,
    ingest,
    review,
    snapshot,
)
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import inbox_work_schemas as schema
from cosmas_os.application import inbox_work as flow
from cosmas_os.application import services
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.inbox_models import InboxEvent, InboxItem, InboxSource
from cosmas_os.models import Principal
from cosmas_os.ports.vendor_connectors import digest
from cosmas_os.ports.vendor_inbox import SpruceInboxSnapshot


@pytest.fixture
def committed_inbox(engine, tmp_path):
    with Session(engine, expire_on_commit=False) as session:
        seed = services.provision_box(
            services.Container(session, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented Inbox concurrent practice",
        )
        vendor_factory = getattr(vendor_case, "__wrapped__", None)
        inbox_factory = getattr(inbox_case, "__wrapped__", None)
        assert callable(vendor_factory) and callable(inbox_factory)
        case = inbox_factory(session, vendor_factory(session, seed))
        assert isinstance(case, dict)
        session.commit()
    # This read occurs outside the provisioning transaction, not a savepoint.
    with Session(engine) as verifier:
        principal = verifier.get(Principal, case["actor"])
        assert principal is not None and principal.is_owner
    return case


def state(engine, case):
    with Session(engine) as session:
        counts: dict = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.owner_id == case["actor"])
            )
            for model in (InboxItem, InboxSource, InboxEvent)
        }
        counts["events"] = [
            {
                "id": event.id,
                "version": event.version,
                "origin": event.origin,
                "kind": event.kind,
                "receipt_sha256": event.receipt_sha256,
            }
            for event in session.scalars(
                select(InboxEvent)
                .where(InboxEvent.owner_id == case["actor"])
                .order_by(InboxEvent.version)
            )
        ]
        return counts


def proof(tmp_path, name, value):
    (tmp_path / (name + ".json")).write_text(json.dumps(value, indent=2, sort_keys=True))


def contend(engine, first_call, second_call, tmp_path):
    """Hold the first admission before commit and prove the second waits in PG."""
    paused, release, second_started = Event(), Event(), Event()
    pids = {}

    def apply(name, call):
        with Session(engine, expire_on_commit=False) as session:
            session.execute(text("SET LOCAL lock_timeout = '12s'"))
            session.execute(text("SET LOCAL statement_timeout = '15s'"))
            pids[name] = session.scalar(text("SELECT pg_backend_pid()"))
            if name == "first":

                def fence():
                    paused.set()
                    assert release.wait(12), "First admission was not released"

                session.info["inbox_final_authority"] = fence
            else:
                second_started.set()
            return call(session)

    blockers = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(apply, "first", first_call)
        try:
            assert paused.wait(10), "First admission never reached its final fence"
            second = pool.submit(apply, "second", second_call)
            assert second_started.wait(5), "Second PostgreSQL connection did not start"
            deadline = time.monotonic() + 5
            with Session(engine) as observer:
                while time.monotonic() < deadline:
                    blockers = observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["second"]}
                    )
                    if pids["first"] in blockers:
                        break
                    time.sleep(0.01)
            assert pids["first"] != pids["second"]
            assert pids["first"] in blockers, "Second admission did not contend on the first"
        finally:
            release.set()
        values = first.result(timeout=15), second.result(timeout=15)
    proof(tmp_path, "postgres-contention", {"pids": pids, "blockers": blockers})
    return values


def invoke(session, case, request):
    return flow.command(
        session,
        case["box"],
        case["actor"],
        request.item_id,
        "triage",
        request,
        registry=case["registry"],
        policy=ON,
    )


def resolver(case, request):
    return schema.Resolve(
        item_id=request.item_id,
        command_kind="triage",
        idempotency_key=request.idempotency_key,
        request_sha256=schema.request_digest(
            "triage", flow.scope(case["box"], case["actor"]), request
        ),
    )


def triage_request(session, case, item_id, key):
    return schema.Triage.model_validate(
        bound(
            session,
            case,
            item_id,
            idempotency_key=key,
            classification="administrative_review",
            due_date="2026-10-01",
            instructions="Invented local human classification; no external action.",
            human_disposition_required=True,
        )
    )


def test_same_grant_and_key_commit_one_source_and_exact_read_receipt(
    engine, committed_inbox, tmp_path
):
    case = committed_inbox
    source = snapshot(case)
    key = "same-read-" + str(uuid4())
    first, second = contend(
        engine,
        lambda session: ingest(session, case, source, key),
        lambda session: ingest(session, case, source, key),
        tmp_path,
    )
    assert first == second
    before = state(engine, case)
    assert [before[name] for name in ("inbox_items", "inbox_sources", "inbox_events")] == [1, 1, 1]
    with Session(engine) as session:
        assert ingest(session, case, source, key) == first
    assert state(engine, case) == before
    proof(tmp_path, "identical-read", {"receipt": first, "persisted": before})


def test_distinct_read_keys_retain_wire_observations_without_duplicate_source(
    engine, committed_inbox, tmp_path
):
    case = committed_inbox
    original = snapshot(case)
    incoming = SpruceInboxSnapshot.model_validate(
        {
            **original.model_dump(mode="python"),
            "observed_at": original.observed_at + timedelta(seconds=1),
            "item_response_sha256": digest("invented-new-wire", "item"),
            "conversation_response_sha256": digest("invented-new-wire", "conversation"),
        }
    )
    assert original.source_sha256 == incoming.source_sha256
    keys = ["distinct-read-" + str(uuid4()) for _ in range(2)]
    first, second = contend(
        engine,
        lambda session: ingest(session, case, original, keys[0]),
        lambda session: ingest(session, case, incoming, keys[1]),
        tmp_path,
    )
    assert [first["outcome"], second["outcome"]] == ["new", "same"]
    assert first["source_id"] == second["source_id"]
    assert first["id"] != second["id"]
    assert first["item_response_sha256"] != second["item_response_sha256"]
    before = state(engine, case)
    assert [before[name] for name in ("inbox_items", "inbox_sources", "inbox_events")] == [1, 1, 2]
    for source, key, receipt in zip((original, incoming), keys, (first, second), strict=True):
        with Session(engine) as session:
            assert ingest(session, case, source, key) == receipt
    assert state(engine, case) == before
    proof(tmp_path, "distinct-reads", {"receipts": [first, second], "persisted": before})


def test_competing_same_version_triage_has_one_admission_and_durable_stale_rejection(
    engine, committed_inbox, tmp_path
):
    case = committed_inbox
    with Session(engine, expire_on_commit=False) as session:
        item_id = ingest(session, case)["item_id"]
        review(session, case, item_id)
        requests = [
            triage_request(session, case, item_id, "competing-triage-" + str(uuid4()))
            for _ in range(2)
        ]
    assert requests[0].expected_version == requests[1].expected_version == 2
    first, second = contend(
        engine,
        lambda session: invoke(session, case, requests[0]),
        lambda session: invoke(session, case, requests[1]),
        tmp_path,
    )
    assert first["outcome"] == "recorded" and first["effect"]["state"] == "triaged"
    assert second["outcome"] == "rejected"
    assert second["rejection"] == "inbox_version_changed" and second["effect"] is None
    before = state(engine, case)
    assert before["inbox_events"] == 4
    assert [event["version"] for event in before["events"]] == [1, 2, 3, 4]
    for request, receipt in zip(requests, (first, second), strict=True):
        with Session(engine) as session:
            assert (
                flow.resolve(
                    session,
                    case["box"],
                    case["actor"],
                    resolver(case, request),
                    registry=case["registry"],
                    policy=ON,
                )
                == receipt
            )
            assert invoke(session, case, request) == receipt
    assert state(engine, case) == before
    proof(tmp_path, "competing-triage", {"receipts": [first, second], "persisted": before})


@pytest.mark.parametrize("operation", ["ingest", "triage"])
@pytest.mark.parametrize("authority", ["registry", "owner"])
def test_final_authority_loss_commits_no_new_evidence_or_private_receipt(
    engine, committed_inbox, tmp_path, operation, authority
):
    case = committed_inbox
    request = None
    if operation == "triage":
        with Session(engine, expire_on_commit=False) as session:
            item_id = ingest(session, case)["item_id"]
            review(session, case, item_id)
            request = triage_request(session, case, item_id, "final-triage-" + str(uuid4()))
    before = state(engine, case)
    exposed = failure = None
    fences = 0
    with Session(engine, expire_on_commit=False) as session:

        def fence():
            nonlocal fences
            fences += 1
            # The provisional immutable event has reached PostgreSQL, but it
            # must not survive the final authority refusal.
            provisional = session.scalar(
                select(func.count())
                .select_from(InboxEvent)
                .where(InboxEvent.owner_id == case["actor"])
            )
            assert provisional == before["inbox_events"] + 1
            if authority == "registry":
                case["registry_state"]["registry"] = flow.EMPTY_REGISTRY
            else:
                session.execute(
                    update(Principal).where(Principal.id == case["actor"]).values(is_owner=False)
                )
                flow.owner(session, case["box"], case["actor"])

        session.info["inbox_final_authority"] = fence
        try:
            exposed = (
                ingest(session, case) if operation == "ingest" else invoke(session, case, request)
            )
        except WorkspaceError as exc:
            failure = exc.code
        finally:
            session.rollback()
    after = state(engine, case)
    proof(
        tmp_path,
        "final-authority",
        {
            "operation": operation,
            "authority": authority,
            "failure": failure,
            "receipt_exposed": exposed is not None,
            "fences": fences,
            "before": before,
            "after": after,
        },
    )
    assert fences == 1
    assert failure == (
        "inbox_binding_unavailable" if authority == "registry" else "inbox_unavailable"
    )
    assert exposed is None
    assert after == before


@pytest.mark.parametrize(
    "operation", ["catalog", "detail", "history", "source", "resolve", "replay"]
)
def test_final_owner_check_discloses_no_private_source_or_recovered_receipt(
    engine, committed_inbox, tmp_path, operation
):
    case = committed_inbox
    with Session(engine, expire_on_commit=False) as session:
        initial = ingest(session, case)
        item_id, source_id = initial["item_id"], initial["source_id"]
        review(session, case, item_id)
        request = triage_request(session, case, item_id, "private-receipt-" + str(uuid4()))
        invoke(session, case, request)
    before = state(engine, case)
    exposed = failure = None
    fences = 0
    with Session(engine, expire_on_commit=False) as session:

        def fence():
            nonlocal fences
            fences += 1
            session.execute(
                update(Principal).where(Principal.id == case["actor"]).values(is_owner=False)
            )
            flow.owner(session, case["box"], case["actor"])

        session.info["inbox_final_authority"] = fence
        options = {"registry": case["registry"], "policy": ON}
        calls = {
            "catalog": lambda: flow.catalog(session, case["box"], case["actor"], **options),
            "detail": lambda: flow.detail(session, case["box"], case["actor"], item_id, **options),
            "history": lambda: flow.history(
                session, case["box"], case["actor"], item_id, **options
            ),
            "source": lambda: flow.read_source(
                session, case["box"], case["actor"], item_id, source_id, **options
            ),
            "resolve": lambda: flow.resolve(
                session, case["box"], case["actor"], resolver(case, request), **options
            ),
            "replay": lambda: invoke(session, case, request),
        }
        try:
            exposed = calls[operation]()
        except WorkspaceError as exc:
            failure = exc.code
        finally:
            session.rollback()
    after = state(engine, case)
    proof(
        tmp_path,
        "private-disclosure",
        {
            "operation": operation,
            "failure": failure,
            "value_exposed": exposed is not None,
            "fences": fences,
            "before": before,
            "after": after,
        },
    )
    assert fences == 1 and failure == "inbox_unavailable"
    assert exposed is None and after == before
