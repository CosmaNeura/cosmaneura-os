"""Explicit local/private ASGI runner; never a default or production entrypoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url

from .config import EnrollmentSettings
from .private_clock_lab import (
    PostgresClockJournal,
    binding_value,
    create_clock_lab_app,
    private_directory,
    protected_read,
    unique_json,
)

CONTRACT = "enrollment-private-clock-runner.v1"
APP_ORIGIN = "https://onboarding.staging.cosmas.ai"
API_ORIGIN = "https://enrollment-api.staging.cosmas.ai"
REPOSITORY = Path(__file__).resolve().parents[3]


def require(value: bool) -> None:
    if not value:
        raise ValueError("private_clock_runner_configuration_invalid")


def read_input(path: Path) -> bytes:
    require(path.is_absolute() and path.resolve() == path and not path.is_relative_to(REPOSITORY))
    private_directory(path.parent)
    return protected_read(path)


def database_url(raw: str, *, role: str, database: str) -> URL:
    require(isinstance(raw, str) and bool(raw) and not any(c in raw for c in "\r\n\t"))
    url = make_url(raw)
    require(url.drivername == "postgresql+psycopg" and url.username == role
            and url.database == database and bool(url.password) and bool(url.host))
    if url.host in ("127.0.0.1", "localhost"):
        require(1 <= (url.port or 5432) <= 65535 and dict(url.query) in (
            {}, {"sslmode": "verify-full", "sslrootcert": "/etc/ssl/certs/ca-certificates.crt"}))
    else:
        host = (r"psql-cosmabot-enrollment-staging-[a-z0-9]{6,8}" if database == "cosmabot_enrollment"
                else r"psql-cbot-clock-stg-[a-z0-9]{6,8}")
        require(re.fullmatch(host + r"\.postgres\.database\.azure\.com", url.host or "") is not None
                and url.port in (None, 5432)
                and dict(url.query) == {"sslmode": "verify-full", "sslrootcert": "/etc/ssl/certs/ca-certificates.crt"})
    return url


def create_explicit_app(*, configuration_path: Path, binding_path: Path,
                        journal_url_path: Path) -> FastAPI:
    """Read already-qualified inputs; never prepare a binding/schema or change flags."""
    paths = (configuration_path, binding_path, journal_url_path)
    raw_inputs = {path: read_input(path) for path in paths}
    configuration = unique_json(raw_inputs[configuration_path])
    require(isinstance(configuration, dict) and set(configuration) == {
        "contract_version", "synthetic_only", "binding_sha256", "journal_role", "enrollment"})
    require(configuration["contract_version"] == CONTRACT and configuration["synthetic_only"] is True
            and configuration["journal_role"] in ("clock_journal_a", "clock_journal_b"))
    values = configuration["enrollment"]
    # BaseSettings must receive every field: ambient ENROLLMENT_* cannot supply
    # a missing credential, readiness flag, origin or production setting.
    require(isinstance(values, dict) and set(values) == set(EnrollmentSettings.model_fields))
    settings = EnrollmentSettings.model_validate(values, strict=True)
    binding = binding_value(unique_json(raw_inputs[binding_path]))
    require(configuration["binding_sha256"] == binding.sha256
            and binding.app_origin == APP_ORIGIN and binding.api_origin == API_ORIGIN
            and settings.provisioning_enabled is True)
    binding.check_settings(settings)
    enrollment_url = database_url(settings.database_url.get_secret_value(),
                                  role="enrollment_runtime", database="cosmabot_enrollment")
    journal_raw = raw_inputs[journal_url_path].decode("utf-8")
    if journal_raw.endswith("\n"):
        journal_raw = journal_raw[:-1]
    journal_url = database_url(journal_raw, role=configuration["journal_role"],
                              database="cosmabot_enrollment_clock_lab")
    require(journal_url.host == binding.journal_host
            and (journal_url.port or 5432) == binding.journal_port
            and journal_url.database != enrollment_url.database)
    engines = []
    try:
        for url in (enrollment_url, journal_url):
            engines.append(create_engine(url, pool_pre_ping=True, hide_parameters=True,
                                         connect_args={"connect_timeout": 10}))
        enrollment_engine, journal_engine = engines
        journal = PostgresClockJournal(journal_engine, binding)
        # No injected confirmation/admission port. The existing API factory
        # creates its real BoundWorkspaceConfirmer from this same service.
        app = create_clock_lab_app(settings, engine=enrollment_engine,
                                   binding_path=binding_path, journal=journal)
        require(all(read_input(path) == raw for path, raw in raw_inputs.items()))
        previous_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application):
            try:
                async with previous_lifespan(application):
                    yield
            finally:
                for engine in engines:
                    engine.dispose()

        app.router.lifespan_context = lifespan
        app.state.private_clock_runner_input_sha256 = {
            path.name: hashlib.sha256(raw).hexdigest() for path, raw in raw_inputs.items()}
        return app
    except Exception:
        for engine in engines:
            engine.dispose()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--journal-url-file", type=Path, required=True)
    parser.add_argument("--listen-host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--intent", choices=("RUN_PRIVATE_SYNTHETIC_CLOCK",), required=True)
    args = parser.parse_args()
    try:
        require(1 <= args.listen_port <= 65535)
        app = create_explicit_app(configuration_path=args.configuration,
                                  binding_path=args.binding, journal_url_path=args.journal_url_file)
        import uvicorn

        uvicorn.run(app, host=args.listen_host, port=args.listen_port, access_log=False, log_level="warning")
        return 0
    except Exception:
        print(json.dumps({"error": "private_clock_runner_unavailable"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
