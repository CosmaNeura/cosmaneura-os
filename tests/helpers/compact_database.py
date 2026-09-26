"""Committed compact tests in the checker's freshly owned, migrated database."""

from __future__ import annotations

import re
from contextlib import contextmanager

from sqlalchemy import text

MARKER_PREFIX = "cosmas-local-compact:"
LOCK = "1129272141, 1129270608"


def _require_marker(connection, token):
    marker = connection.scalar(text(
        "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
        "WHERE datname = current_database()"
    ))
    if marker != MARKER_PREFIX + token:
        raise RuntimeError("Compact fixture database is not owned by this checker invocation")


@contextmanager
def isolated_compact_database(engine, token):
    """Keep real commits visible; reset only the proven-owned synthetic Box graph."""
    url = engine.url
    if (url.drivername != "postgresql+psycopg"
            or url.host not in {"127.0.0.1", "localhost", "::1"}
            or url.database != "compact_test" or url.username != "compact_synth"
            or url.query or not isinstance(token, str)
            or re.fullmatch(r"[0-9a-f]{32}", token) is None):
        raise RuntimeError("Run compact fixtures through scripts/check-backend-local.py")
    # A session lock fences concurrent fixture processes while worker connections
    # remain free to commit. Autocommit avoids an idle transaction during tests.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as guard:
        _require_marker(guard, token)
        if not guard.scalar(text(f"SELECT pg_try_advisory_lock({LOCK})")):
            raise RuntimeError("Another compact fixture owns this database")
        try:
            if guard.scalar(text("SELECT count(*) FROM public.box_contexts")) != 0:
                raise RuntimeError("Compact fixture requires an empty owned database")
            try:
                yield
            finally:
                # Never erase data after an ownership mismatch, including one
                # introduced during the test. Preserve all migrated structures.
                _require_marker(guard, token)
                guard.exec_driver_sql("TRUNCATE TABLE public.box_contexts CASCADE")
        finally:
            guard.execute(text(f"SELECT pg_advisory_unlock({LOCK})"))
