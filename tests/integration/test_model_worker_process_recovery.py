"""Kill an actual local worker after claim; recover without replaying its model work."""

import multiprocessing
import os
import signal
from datetime import timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from tests.integration.test_handoff_wakeup import prepared_case
from tests.integration.test_model_concurrency_recovery import children, counts, dispatch
from tests.integration.test_product_agent_tool_workflow import operational as operational

from cosmas_os.application import model_work as work
from cosmas_os.models import ModelWorkAdmission


def _claim_and_wait(database_url, case, admission_id, ready):
    # Spawn opens a fresh SQL connection: no inherited parent transactions.
    from pydantic import SecretStr

    from cosmas_os.application import provider_team as team

    team.runtime_settings.workspace_enabled = True
    team.runtime_settings.workspace_agent_tools_enabled = True
    team.runtime_settings.workspace_llm_backend = "azure_gpt41"
    team.runtime_settings.workspace_llm_api_key = SecretStr("invented-worker-crash-key")
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            claim = work.claim(session, case[0], case[1], admission_id)
        ready.send((claim.admission_id, claim.dispatch_id))
        ready.close()
        signal.pause()
    finally:
        engine.dispose()


def test_killed_worker_does_not_duplicate_claim_and_siblings_finish(engine, operational):
    case = prepared_case(engine)
    admissions = children(engine, case)
    before = counts(engine, case)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_claim_and_wait, args=(
        engine.url.render_as_string(hide_password=False), case, admissions[0], child
    ))
    process.start()
    child.close()
    try:
        assert parent.poll(20), "Worker must commit its claim before crash injection"
        admission, dispatch_id = parent.recv()
        assert admission == admissions[0]
        os.kill(process.pid, signal.SIGKILL)
        process.join(10)
        assert process.exitcode == -signal.SIGKILL
        with Session(engine) as session:
            row = session.get(ModelWorkAdmission, admission)
            assert row.state == "running" and row.dispatch_id == dispatch_id
            expires = row.lease_ends_at
            assert work.claim(session, case[0], case[1], admission) is None
        with Session(engine) as session:
            assert work.recover_expired(session, clock=lambda: expires + timedelta(seconds=1)) >= 1
        with Session(engine) as session:
            row = session.get(ModelWorkAdmission, admission)
            assert row.state == "unknown" and row.result_entry_id is None
            assert row.dispatch_id == dispatch_id
            assert work.claim(session, case[0], case[1], admission) is None
        assert counts(engine, case) == before
        calls = []

        def perform(claim):
            calls.append(claim.admission_id)
            return dispatch(engine, claim)

        def factory():
            return Session(engine)
        assert work.process_next(factory, dispatch=perform)
        assert work.process_next(factory, dispatch=perform)
        assert not work.process_next(factory, dispatch=perform)
        assert set(calls) == set(admissions[1:]) and len(calls) == 2
        with Session(engine) as session:
            rows = list(session.scalars(select(ModelWorkAdmission).where(
                ModelWorkAdmission.id.in_(admissions)
            )))
            assert sorted(row.state for row in rows) == ["completed", "completed", "unknown"]
            assert len({row.result_entry_id for row in rows if row.result_entry_id}) == 2
    finally:
        parent.close()
        if process.is_alive():
            process.kill()
            process.join(10)
        assert not process.is_alive()
