from __future__ import annotations

from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from cosmas_os.compact.models import SchemaVersion, WorkerHeartbeat
from cosmas_os.config import settings
from cosmas_os.models import BoxContext
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION


def require_local_engine(engine: Engine) -> None:
    settings.validate_runtime_configuration()
    url = engine.url
    if (
        settings.execution_backend != "postgres_local"
        or url.drivername != "postgresql+psycopg"
        or url.host not in {"localhost", "127.0.0.1", "::1", "compact-db"}
        or url.database not in {"compact_test", "compact_demo"}
        or url.username != "compact_synth"
        or url.query
    ):
        raise RuntimeError("compact proof requires its dedicated local database")


def install_extension(connection: Connection) -> None:
    """Explicit preparation only; never called by API or worker startup."""
    require_local_engine(connection.engine)
    connection.exec_driver_sql(Path(__file__).with_name("schema.sql").read_text())
    version = connection.execute(
        text("SELECT version FROM compact_schema_version WHERE singleton = 1")
    ).scalar_one()
    if version != 1:
        raise RuntimeError("compact schema version mismatch")


def one_box(session: Session) -> str:
    boxes = session.scalars(select(BoxContext.id).limit(2)).all()
    if len(boxes) != 1:
        raise RuntimeError("compact runtime requires exactly one seeded synthetic Box")
    return boxes[0]


def schema_is_current(session: Session) -> bool:
    core = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    version = session.get(SchemaVersion, 1)
    return core == EXPECTED_SCHEMA_REVISION and version is not None and version.version == 1


def worker_is_ready(session: Session) -> bool:
    from cosmas_os.compact.execution import database_now

    if not schema_is_current(session):
        return False
    heartbeat = session.get(WorkerHeartbeat, one_box(session))
    if not heartbeat:
        return False
    age = (database_now(session) - heartbeat.observed_at).total_seconds()
    return 0 <= age <= 10
