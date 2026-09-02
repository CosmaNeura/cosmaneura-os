from __future__ import annotations

import json
from pathlib import Path

import typer
from sqlalchemy.orm import Session

from cosmas_os.config import settings
from cosmas_os.db import make_engine, make_session_factory

app = typer.Typer(help="Cosmas OS local synthetic CLI")


def _session() -> Session:
    return make_session_factory(make_engine())()


@app.command("seed-synth")
def seed_synth_cmd() -> None:
    from cosmas_os.application.seed import seed_synth

    session = _session()
    try:
        result = seed_synth(session)
        typer.echo(json.dumps(result, indent=2))
    finally:
        session.close()


@app.command("demo-artifact-chase")
def demo_cmd() -> None:
    from cosmas_os.application.seed import run_demo

    session = _session()
    try:
        result = run_demo(session)
        typer.echo(json.dumps(result, indent=2))
    finally:
        session.close()


@app.command("dump-openapi")
def dump_openapi(out: Path = Path("openapi.json")) -> None:
    from cosmas_os.api.app import app as fastapi_app

    out.write_text(json.dumps(fastapi_app.openapi(), indent=2), encoding="utf-8")
    typer.echo(f"wrote {out}")


@app.command("info")
def info() -> None:
    typer.echo(f"env={settings.cosmas_env} db={settings.database_url}")


if __name__ == "__main__":
    app()
