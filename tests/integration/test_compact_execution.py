from __future__ import annotations

import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from cosmas_os.application import services as svc
from cosmas_os.application.seed import seed_synth_work_queue
from cosmas_os.compact.execution import Lease, LostClaim, PostgresExecutor
from cosmas_os.compact.models import SyntheticReceipt
from cosmas_os.compact.schema import install_extension, require_local_engine
from cosmas_os.config import settings
from cosmas_os.domain.enums import DecisionKind
from cosmas_os.domain.rules import DomainError
from cosmas_os.models import (
    ActionRevision,
    Decision,
    Operation,
    PatientLink,
    Principal,
    Ticket,
)


@pytest.fixture
def compact(monkeypatch):
    # Only a dedicated, newly provisioned local test DB; never the base fixture DB.
    url = os.environ.get("COMPACT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set COMPACT_TEST_DATABASE_URL for real PostgreSQL claim/recovery tests")
    for key, value in {
        "execution_backend": "postgres_local",
        "sync_worker": False,
        "cosmas_env": "synth_os",
        "data_mode": "synthetic",
        "auth_mode": "synth_headers",
        "blob_backend": "local",
        "database_url": url,
        "compact_web_root": None,
        "cors_allowed_origins": "http://127.0.0.1:8008",
    }.items():
        monkeypatch.setattr(settings, key, value)
    admin = create_engine(url)
    require_local_engine(admin)
    schema = "compact_test_" + uuid4().hex
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(
        url, connect_args={"options": f"-c search_path={schema} -c statement_timeout=5000"}
    )
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            install_extension(connection)
        with Session(engine) as session:
            seeded = seed_synth_work_queue(session)
            ticket = session.get(Ticket, seeded["ticket_id"])
            seeded["revision_id"] = ticket.current_revision_id
        yield engine, seeded
    finally:
        engine.dispose()
        with admin.begin() as connection:
            # Exact schema created above, never public or a user-supplied identifier.
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def approve(compact):
    engine, seeded = compact
    with Session(engine) as session:
        result = svc.decide(
            svc.Container(session),
            seeded["ticket_id"],
            seeded["owner_id"],
            DecisionKind.APPROVE,
            expected_revision_id=seeded["revision_id"],
        )
        return result["operation_id"]


def expire(engine, operation_id, *, due=False):
    with engine.begin() as connection:
        column = "next_attempt_at" if due else "lease_until"
        connection.execute(
            text(
                f"UPDATE compact_claims SET {column} = clock_timestamp() - interval '1 second' WHERE operation_id = :op"
            ),
            {"op": operation_id},
        )


def state(engine, operation_id):
    with Session(engine) as session:
        op = session.get(Operation, operation_id)
        return op.status, op.attempt_count


def test_pending_intent_survives_api_session_loss_without_broker(compact, monkeypatch):
    from cosmas_os.worker.tasks import execute_operation_task

    monkeypatch.setattr(
        execute_operation_task, "delay", lambda *_: pytest.fail("broker was called")
    )
    op_id = approve(compact)
    engine, seeded = compact
    assert state(engine, op_id) == ("pending", 0)
    assert PostgresExecutor(engine).tick(seeded["box_id"])
    assert state(engine, op_id) == ("succeeded", 1)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SyntheticReceipt)) == 1
        assert session.get(Ticket, seeded["ticket_id"]).state == "sent"
        retry = svc.decide(
            svc.Container(session), seeded["ticket_id"], seeded["owner_id"], DecisionKind.APPROVE
        )
        assert retry["operation_id"] == op_id
    assert not PostgresExecutor(engine).tick(seeded["box_id"])


def test_concurrent_claimers_only_one_wins(compact):
    engine, seeded = compact
    approve(compact)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(
            pool.map(lambda _: PostgresExecutor(engine).claim_next(seeded["box_id"]), range(8))
        )
    assert sum(claim is not None for claim in claims) == 1


def test_row_lock_skips_busy_work(compact):
    engine, seeded = compact
    op_id = approve(compact)
    with Session(engine) as session, session.begin():
        session.scalar(select(Operation).where(Operation.id == op_id).with_for_update())
        assert PostgresExecutor(engine).claim_next(seeded["box_id"]) is None


def test_expired_pre_dispatch_claim_is_recovered_and_old_token_is_fenced(compact):
    engine, seeded = compact
    op_id = approve(compact)
    first_worker = PostgresExecutor(engine)
    old = first_worker.claim_next(seeded["box_id"])
    expire(engine, op_id)
    new_worker = PostgresExecutor(engine)
    new = new_worker.claim_next(seeded["box_id"])
    assert old and new and old.token != new.token
    for method in (
        first_worker.begin_dispatch,
        first_worker.record_fake_effect,
        first_worker.finish,
        first_worker.retry_before_dispatch,
    ):
        with pytest.raises(LostClaim):
            method(old)
    new_worker.begin_dispatch(new)
    new_worker.record_fake_effect(new)
    new_worker.finish(new)
    assert state(engine, op_id) == ("succeeded", 2)


def test_crash_after_effect_before_ack_reconciles_durable_receipt(compact):
    engine, seeded = compact
    op_id = approve(compact)
    worker = PostgresExecutor(engine)
    lease = worker.claim_next(seeded["box_id"])
    worker.begin_dispatch(lease)
    worker.record_fake_effect(lease)
    # No finish: emulate process loss after the independently committed effect.
    expire(engine, op_id)
    restarted = PostgresExecutor(engine)
    restarted.tick(seeded["box_id"])
    assert state(engine, op_id) == ("succeeded", 1)
    with pytest.raises(LostClaim):
        worker.finish(lease)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SyntheticReceipt)) == 1


def test_sigkill_after_committed_effect_is_recovered_without_duplicate(compact):
    engine, seeded = compact
    op_id = approve(compact)
    with Session(engine) as session:
        schema = session.scalar(text("SELECT current_schema()"))
    child_env = os.environ | {
        "COSMAS_ENV": "synth_os",
        "DATA_MODE": "synthetic",
        "AUTH_MODE": "synth_headers",
        "BLOB_BACKEND": "local",
        "SYNC_WORKER": "false",
        "EXECUTION_BACKEND": "postgres_local",
        "DATABASE_URL": os.environ["COMPACT_TEST_DATABASE_URL"],
        "CORS_ALLOWED_ORIGINS": "http://127.0.0.1:8008",
        "COMPACT_WEB_ROOT": "",
        "COMPACT_CRASH_TEST_SCHEMA": schema,
        "COMPACT_CRASH_TEST_BOX": seeded["box_id"],
    }
    # No production fault-injection hook. The test-owned subprocess commits the
    # fake receipt in the isolated schema, then dies before acknowledging it.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os, signal
from sqlalchemy import create_engine
from cosmas_os.compact.execution import PostgresExecutor
engine = create_engine(os.environ['DATABASE_URL'], connect_args={
    'options': '-c search_path=' + os.environ['COMPACT_CRASH_TEST_SCHEMA']
})
worker = PostgresExecutor(engine)
lease = worker.claim_next(os.environ['COMPACT_CRASH_TEST_BOX'])
assert lease is not None
worker.begin_dispatch(lease)
worker.record_fake_effect(lease)
print('receipt committed', flush=True)
os.kill(os.getpid(), signal.SIGKILL)
""",
        ],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == -signal.SIGKILL, result.stderr
    assert result.stdout.strip() == "receipt committed"
    expire(engine, op_id)
    PostgresExecutor(engine).tick(seeded["box_id"])
    assert state(engine, op_id) == ("succeeded", 1)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SyntheticReceipt)) == 1


def test_crash_after_dispatch_without_receipt_remains_unknown_no_blind_retry(compact):
    engine, seeded = compact
    op_id = approve(compact)
    worker = PostgresExecutor(engine)
    lease = worker.claim_next(seeded["box_id"])
    worker.begin_dispatch(lease)
    expire(engine, op_id)
    for _ in range(4):
        PostgresExecutor(engine).tick(seeded["box_id"])
    assert state(engine, op_id) == ("unknown", 1)
    with pytest.raises(LostClaim):
        worker.record_fake_effect(lease)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SyntheticReceipt)) == 0


def test_pre_dispatch_retry_has_backoff_and_bounded_budget(compact):
    engine, seeded = compact
    op_id = approve(compact)
    worker = PostgresExecutor(engine, max_attempts=2)
    first = worker.claim_next(seeded["box_id"])
    worker.retry_before_dispatch(first)
    assert worker.claim_next(seeded["box_id"]) is None
    expire(engine, op_id, due=True)
    second = worker.claim_next(seeded["box_id"])
    worker.retry_before_dispatch(second)
    assert state(engine, op_id) == ("failed", 2)
    assert worker.claim_next(seeded["box_id"]) is None


@pytest.mark.parametrize(
    "fault",
    [
        "payload",
        "content",
        "target",
        "hash_and_payload",
        "invalidated",
        "decision",
        "agent_approver",
        "disabled_human",
        "box",
        "policy",
        "revoked_link",
        "external_channel",
    ],
)
def test_invalid_authority_never_records_effect(compact, fault):
    engine, seeded = compact
    op_id = approve(compact)
    other = None
    if fault == "box":
        with Session(engine) as session:
            other = svc.provision_box(svc.Container(session), "Other invented Box")
    with Session(engine) as session, session.begin():
        rev = session.get(ActionRevision, seeded["revision_id"])
        if fault == "payload":
            rev.payload = {**rev.payload, "body": "changed after approval"}
        elif fault == "content":
            rev.content = "changed independently"
        elif fault == "target":
            rev.target_ref = "patient_link:changed"
        elif fault == "hash_and_payload":
            from cosmas_os.domain.hashing import payload_hash

            rev.payload = {**rev.payload, "body": "changed with matching hash"}
            rev.content = rev.payload["body"]
            rev.payload_hash = payload_hash(rev.payload)
        elif fault == "invalidated":
            rev.invalidated = True
        elif fault == "decision":
            session.execute(
                text("DELETE FROM decisions WHERE action_revision_id = :id"), {"id": rev.id}
            )
        elif fault == "agent_approver":
            decision = session.scalar(select(Decision).where(Decision.action_revision_id == rev.id))
            decision.actor_principal_id = seeded["agents"]["chaser"]
        elif fault == "disabled_human":
            session.get(Principal, seeded["owner_id"]).state = "disabled"
        elif fault == "box":
            assert other is not None
            session.get(Ticket, seeded["ticket_id"]).box_id = other["box_id"]
        elif fault == "policy":
            rev.policy_version = "changed-policy"
        elif fault == "revoked_link":
            ticket = session.get(Ticket, seeded["ticket_id"])
            session.get(PatientLink, ticket.patient_link_id).state = "revoked"
        elif fault == "external_channel":
            rev.payload = {**rev.payload, "channel": "email"}
    PostgresExecutor(engine).tick(seeded["box_id"])
    assert state(engine, op_id)[0] == "failed"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SyntheticReceipt)) == 0


def test_wrong_box_and_legacy_executor_cannot_claim_or_execute(compact):
    engine, seeded = compact
    op_id = approve(compact)
    worker = PostgresExecutor(engine)
    assert worker.claim_next(str(uuid4())) is None
    lease = worker.claim_next(seeded["box_id"])
    with pytest.raises(LostClaim):
        worker.begin_dispatch(Lease(op_id, str(uuid4()), lease.token))
    with Session(engine) as session:
        with pytest.raises(DomainError, match="backend"):
            svc.execute_operation(svc.Container(session), op_id)


def test_receipt_mismatch_cannot_reconcile_or_resend(compact):
    engine, seeded = compact
    op_id = approve(compact)
    worker = PostgresExecutor(engine)
    lease = worker.claim_next(seeded["box_id"])
    worker.begin_dispatch(lease)
    worker.record_fake_effect(lease)
    with Session(engine) as session, session.begin():
        session.get(SyntheticReceipt, op_id).request_hash = "0" * 64
    worker.finish(lease)
    worker.tick(seeded["box_id"])
    assert state(engine, op_id) == ("unknown", 1)


def test_extension_migration_is_idempotent_and_leaves_core_head_unchanged(compact):
    engine, _ = compact
    with engine.begin() as connection:
        install_extension(connection)
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0002_external_identities"
        )
        assert connection.scalar(text("SELECT version FROM compact_schema_version")) == 1
        assert Path("src/cosmas_os/compact/schema.sql").is_file()
