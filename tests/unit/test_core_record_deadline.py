import time
from contextlib import suppress
from types import SimpleNamespace

import pytest

from cosmas_os.application import core_record_deadline as module


def test_source_sql_and_commit_deadline_hooks_reapply_each_transaction(monkeypatch):
    hooks, calls = {}, []

    def listen(target, name, callback):
        hooks[(id(target), name)] = callback

    def remove(target, name, callback):
        assert hooks.pop((id(target), name)) is callback

    monkeypatch.setattr(module.event, "listen", listen)
    monkeypatch.setattr(module.event, "remove", remove)
    cursor = SimpleNamespace(
        execute=lambda sql: calls.append(sql), close=lambda: calls.append("closed")
    )
    connection = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        connection=SimpleNamespace(cursor=lambda: cursor),
    )
    session = SimpleNamespace(new=[], dirty=[], deleted=[])
    budget = module.RecordDeadline()
    with module.session_deadline(session, budget):
        hooks[(id(session), "after_begin")](session, None, connection)
        statement = hooks[(id(connection), "before_cursor_execute")]
        statement(connection, None, "SELECT private", None, None, False)
        assert calls[0].startswith("SET LOCAL statement_timeout = ")
        assert calls[1] == "SET LOCAL lock_timeout = 2000" and calls[2] == "closed"
        session.dirty.append(object())
        with pytest.raises(ValueError, match="record_write_not_allowed"):
            hooks[(id(session), "before_commit")](session)
        session.dirty.clear()
        hooks[(id(session), "before_commit")](session)
        budget.when = time.monotonic() - 1
        with pytest.raises(module.RecordDeadlineExceeded):
            statement(connection, None, "SELECT private", None, None, False)
        with pytest.raises(module.RecordDeadlineExceeded):
            hooks[(id(session), "before_commit")](session)
        assert len(calls) == 3
    assert hooks == {}


def test_cancelled_budget_never_invokes_new_async_operation():
    budget, calls = module.RecordDeadline(), []
    budget.cancel()

    async def operation():
        calls.append(1)

    with pytest.raises(module.RecordDeadlineExceeded):
        budget.run(operation)
    assert calls == []


def test_late_session_acquisition_refuses_hook_registration(monkeypatch):
    calls = []
    monkeypatch.setattr(module.event, "listen", lambda *args: calls.append(args))
    budget = module.RecordDeadline()
    budget.cancel()
    with pytest.raises(module.RecordDeadlineExceeded), suppress(AssertionError):
        with module.session_deadline(object(), budget):
            raise AssertionError("late work")
    assert calls == []
