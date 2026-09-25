from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from cosmas_os.compact.execution import LostClaim, PostgresExecutor, database_now
from cosmas_os.compact.models import WorkerHeartbeat
from cosmas_os.compact.schema import (
    install_extension,
    one_box,
    require_local_engine,
    schema_is_current,
    worker_is_ready,
)
from cosmas_os.config import settings


def local_engine():
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=0,
        connect_args={
            "connect_timeout": 2,
            "options": "-c statement_timeout=5000 -c lock_timeout=1500",
        },
    )
    require_local_engine(engine)
    return engine


def prepare() -> None:
    from cosmas_os.application.seed import seed_synth_work_queue

    engine = local_engine()
    try:
        root = Path(__file__).resolve().parents[3]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        config.attributes["configure_logger"] = False
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            install_extension(connection)
        with Session(engine) as session:
            seed_synth_work_queue(session)
            one_box(session)
        print("Compact local database prepared; invented fixture only.", flush=True)
    finally:
        engine.dispose()


def worker() -> None:
    engine = local_engine()
    executor = PostgresExecutor(engine)
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    worker_id = str(uuid4())
    try:
        with Session(engine) as session:
            if not schema_is_current(session):
                raise RuntimeError("compact schema is not ready")
            box_id = one_box(session)
        # Dedicated DB connection owns the singleton lock for this process.
        # Claims are independently fenced even if a second process is attempted.
        with engine.connect() as lock:
            acquired = lock.scalar(
                text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                {"key": "compact-worker:" + box_id},
            )
            lock.commit()
            if not acquired:
                raise RuntimeError("compact worker is already running")
            try:
                while not stopped.is_set():
                    # Detect loss of the lock-owning DB session before proceeding.
                    lock.execute(text("SELECT 1"))
                    lock.commit()
                    with Session(engine) as session, session.begin():
                        if not schema_is_current(session):
                            raise RuntimeError("compact schema changed")
                        session.execute(
                            insert(WorkerHeartbeat)
                            .values(
                                box_id=box_id,
                                worker_id=worker_id,
                                observed_at=database_now(session),
                            )
                            .on_conflict_do_update(
                                index_elements=[WorkerHeartbeat.box_id],
                                set_={"worker_id": worker_id, "observed_at": database_now(session)},
                            )
                        )
                    try:
                        busy = executor.tick(box_id)
                    except LostClaim:
                        busy = False
                    stopped.wait(0.01 if busy else 0.25)
            finally:
                with Session(engine) as session, session.begin():
                    session.execute(
                        text(
                            "DELETE FROM compact_worker_heartbeats WHERE box_id = :box AND worker_id = :worker"
                        ),
                        {"box": box_id, "worker": worker_id},
                    )
                lock.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                    {"key": "compact-worker:" + box_id},
                )
                lock.commit()
    finally:
        engine.dispose()


def stop_children(children: list[subprocess.Popen]) -> None:
    for child in children:
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + 8
    for child in children:
        try:
            child.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def serve(host: str, port: int) -> int:
    engine = local_engine()
    engine.dispose()
    if not settings.compact_web_root:
        raise RuntimeError("compiled compact web bundle is required")
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    children: list[subprocess.Popen] = []
    try:
        children.append(
            subprocess.Popen([sys.executable, "-m", "cosmas_os.compact.runtime", "worker"])
        )
        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "cosmas_os.api.app:app",
                    "--host",
                    host,
                    "--port",
                    str(port),
                    "--no-access-log",
                ]
            )
        )
        while not stopped.wait(0.2):
            if any(child.poll() is not None for child in children):
                print("Compact child exited; stopping the paired runtime.", flush=True)
                return 1
        return 0
    finally:
        stop_children(children)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local synthetic compact proof only")
    parser.add_argument("mode", choices=["prepare", "worker", "serve", "check"])
    parser.add_argument("--host", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8008)
    args = parser.parse_args()
    try:
        if args.mode == "prepare":
            prepare()
        elif args.mode == "worker":
            worker()
        elif args.mode == "serve":
            return serve(args.host, args.port)
        else:
            engine = local_engine()
            try:
                with Session(engine) as session:
                    return 0 if worker_is_ready(session) else 1
            finally:
                engine.dispose()
        return 0
    except Exception:
        # No database URLs, message bodies, IDs or exception contents in logs.
        print(
            "Compact local runtime failed closed; check configuration and local readiness.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
