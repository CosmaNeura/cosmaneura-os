"""The compact fixture must not reset an unowned or concurrently used database."""

from contextlib import AbstractContextManager

import pytest
from sqlalchemy.engine import make_url
from tests.helpers.compact_database import MARKER_PREFIX, isolated_compact_database

TOKEN = "0123456789abcdef0123456789abcdef"
URL = "postgresql+psycopg://compact_synth:invented@127.0.0.1:55439/compact_test"


class Guard(AbstractContextManager):
    def __init__(self, *, marker=MARKER_PREFIX + TOKEN, locked=True, boxes=0):
        self.marker, self.locked, self.boxes = marker, locked, boxes
        self.statements = []

    def __exit__(self, *_):
        pass

    def execution_options(self, **options):
        assert options == {"isolation_level": "AUTOCOMMIT"}
        return self

    def scalar(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "shobj_description" in sql:
            return self.marker
        if "pg_try_advisory_lock" in sql:
            return self.locked
        assert "count(*) FROM public.box_contexts" in sql
        return self.boxes

    def execute(self, statement):
        self.statements.append(str(statement))

    def exec_driver_sql(self, statement):
        self.statements.append(statement)


class Engine:
    def __init__(self, url=URL, **options):
        self.url, self.guard = make_url(url), Guard(**options)
        self.connected = False

    def connect(self):
        self.connected = True
        return self.guard


@pytest.mark.parametrize("url", [
    URL.replace("127.0.0.1", "database.example.invalid"),
    URL.replace("compact_test", "compact_demo"),
    URL.replace("compact_synth", "postgres"),
    URL.replace("postgresql+psycopg", "postgresql+psycopg2"),
    URL + "?options=-csearch_path=other",
])
def test_fixture_refuses_wrong_database_before_connecting(url):
    engine = Engine(url)
    with pytest.raises(RuntimeError, match="check-backend-local"):
        with isolated_compact_database(engine, TOKEN):
            pytest.fail("unowned fixture entered")
    assert not engine.connected


@pytest.mark.parametrize("token", [None, "", "not-a-checker-token"])
def test_fixture_requires_fresh_checker_token(token):
    engine = Engine()
    with pytest.raises(RuntimeError, match="check-backend-local"):
        with isolated_compact_database(engine, token):
            pytest.fail("unowned fixture entered")
    assert not engine.connected


@pytest.mark.parametrize("options", [
    {"marker": None},
    {"marker": MARKER_PREFIX + "f" * 32},
    {"locked": False},
    {"boxes": 1},
])
def test_fixture_preserves_unowned_busy_or_nonempty_database(options):
    engine = Engine(**options)
    with pytest.raises(RuntimeError):
        with isolated_compact_database(engine, TOKEN):
            pytest.fail("unsafe fixture entered")
    assert not any(sql.startswith("TRUNCATE") for sql in engine.guard.statements)


def test_fixture_checks_ownership_again_before_teardown():
    engine = Engine()
    with pytest.raises(RuntimeError, match="not owned"):
        with isolated_compact_database(engine, TOKEN):
            engine.guard.marker = None
    assert not any(sql.startswith("TRUNCATE") for sql in engine.guard.statements)
    assert "pg_advisory_unlock" in engine.guard.statements[-1]


@pytest.mark.parametrize("fails", [False, True])
def test_fixture_cleans_owned_rows_and_unlocks_after_success_or_failure(fails):
    engine = Engine()
    try:
        with isolated_compact_database(engine, TOKEN):
            if fails:
                raise ValueError("test failure")
    except ValueError:
        assert fails
    assert engine.guard.statements.count("TRUNCATE TABLE public.box_contexts CASCADE") == 1
    assert "pg_advisory_unlock" in engine.guard.statements[-1]
