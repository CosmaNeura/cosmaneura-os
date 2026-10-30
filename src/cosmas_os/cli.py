from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import typer
from pydantic import ValidationError
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
    typer.echo(f"env={settings.cosmas_env} database_configured={bool(settings.database_url)}")


@app.command("bootstrap-beta-identity")
def bootstrap_beta_identity_cmd(
    manifest_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    confirm_reviewed_human_deploy: bool = typer.Option(False, "--confirm-reviewed-human-deploy"),
    reserve_first_owner: bool = typer.Option(False, "--reserve-first-owner"),
) -> None:
    """Human-only bootstrap from an untracked, protected manifest file."""

    if not confirm_reviewed_human_deploy:
        raise typer.BadParameter("--confirm-reviewed-human-deploy is required")
    repository_root = Path(__file__).resolve().parents[2]
    resolved_manifest = manifest_path.resolve()
    if resolved_manifest == repository_root or repository_root in resolved_manifest.parents:
        raise typer.BadParameter("bootstrap manifest must remain outside the repository")
    if stat.S_IMODE(resolved_manifest.stat().st_mode) & 0o077:
        raise typer.BadParameter("bootstrap manifest permissions must be 0600 or stricter")

    from cosmas_os.application.beta_bootstrap import (
        BetaBootstrapManifest,
        bootstrap_beta_identity,
    )

    try:
        manifest = BetaBootstrapManifest.model_validate_json(
            resolved_manifest.read_text(encoding="utf-8")
        )
    except (UnicodeDecodeError, ValidationError):
        raise typer.BadParameter("bootstrap manifest is invalid") from None
    session = _session()
    try:
        if reserve_first_owner:
            from cosmas_os.application.practice_setup import reserve_first_owner as reserve
            reserve(session, settings, manifest)
            typer.echo("reviewed first-owner reservation complete; no owner access granted")
        else:
            bootstrap_beta_identity(session, settings, manifest)
            typer.echo("beta identity bootstrap complete")
    finally:
        session.close()


@app.command("bootstrap-standalone-synthetic-practice")
def bootstrap_standalone_synthetic_practice_cmd(
    manifest_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    phase: str = typer.Option(..., "--phase"),
    confirm_reviewed_synthetic_only: bool = typer.Option(False, "--confirm-reviewed-synthetic-only"),
) -> None:
    """Host-only reserve/seed of a fresh invented practice in an owned empty DB."""
    if not confirm_reviewed_synthetic_only or phase not in {"reserve", "seed"}:
        raise typer.BadParameter("reviewed synthetic confirmation and reserve/seed phase are required")
    from cosmas_os.application.standalone_practice import (
        StandalonePracticeError,
        StandalonePracticeManifest,
        reserve_standalone_practice,
        seed_standalone_practice,
    )

    repository_root = Path(__file__).resolve().parents[2]
    resolved = manifest_path.resolve()
    if manifest_path.is_symlink() or resolved == repository_root or repository_root in resolved.parents:
        raise typer.BadParameter("use a protected manifest outside the repository")
    try:
        descriptor = os.open(resolved, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        raise typer.BadParameter("manifest must be a protected regular file") from None
    with os.fdopen(descriptor, "rb") as opened:
        info = os.fstat(opened.fileno())
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_size > 32768):
            raise typer.BadParameter("manifest must be a regular file, at most 32768 bytes and mode 0600 or stricter")
        encoded = opened.read(32768)
        after = os.fstat(opened.fileno())
        if after.st_size != info.st_size or len(encoded) != info.st_size:
            raise typer.BadParameter("manifest changed while it was read")

    def unique_fields(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate manifest field")
            value[key] = item
        return value

    try:
        parsed = json.loads(encoded.decode("utf-8"), object_pairs_hook=unique_fields)
        manifest = StandalonePracticeManifest.model_validate(parsed)
    except (UnicodeDecodeError, ValueError, ValidationError):
        raise typer.BadParameter("standalone synthetic manifest is invalid") from None
    session = _session()
    try:
        operation = reserve_standalone_practice if phase == "reserve" else seed_standalone_practice
        typer.echo(json.dumps(operation(session, settings, manifest), sort_keys=True))
    except StandalonePracticeError as exc:
        raise typer.BadParameter(str(exc)) from None
    finally:
        session.close()


@app.command("seed-beta-synthetic")
def seed_beta_synthetic_cmd(
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
) -> None:
    """Human-run load of repository-owned invented fixtures into D3."""

    if not confirm_synthetic_only:
        raise typer.BadParameter("--confirm-synthetic-only is required")
    from cosmas_os.application.beta_bootstrap import seed_beta_synthetic_queue

    session = _session()
    try:
        seed_beta_synthetic_queue(session, settings)
        typer.echo("synthetic beta work queue ready")
    finally:
        session.close()


@app.command("verify-beta-bootstrap-state")
def verify_beta_bootstrap_state_cmd(
    manifest_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
) -> None:
    """Emit a stable, identifier-free readback of the reviewed beta bootstrap."""

    from cosmas_os.application.beta_bootstrap import (
        BOOTSTRAP_READBACK_CONTRACT,
        BetaBootstrapManifest,
        verify_beta_bootstrap_state,
    )

    failure = json.dumps(
        {"contract": BOOTSTRAP_READBACK_CONTRACT, "status": "failed"},
        sort_keys=True,
        separators=(",", ":"),
    )
    session: Session | None = None
    try:
        repository_root = Path(__file__).resolve().parents[2]
        resolved_manifest = manifest_path.resolve(strict=True)
        info = resolved_manifest.stat()
        if (
            not confirm_synthetic_only
            or not _acceptance_environment_is_synthetic_beta()
            or manifest_path.is_symlink()
            or resolved_manifest == repository_root
            or repository_root in resolved_manifest.parents
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise ValueError("invalid bootstrap readback input")
        manifest = BetaBootstrapManifest.model_validate_json(
            resolved_manifest.read_text(encoding="utf-8")
        )
        session = _session()
        evidence = verify_beta_bootstrap_state(session, settings, manifest)
    except Exception:  # noqa: BLE001 - never reflect identity, row, or manifest details
        typer.echo(failure, err=True)
        raise typer.Exit(1) from None
    finally:
        if session is not None:
            session.close()
    typer.echo(evidence.sanitized_json())


@app.command("prepare-beta-database")
def prepare_beta_database_cmd(
    confirm_forward_only: bool = typer.Option(False, "--confirm-forward-only"),
) -> None:
    """Manual D3 job: migrate and prove the non-admin runtime role."""

    from cosmas_os.application.database_preparation import (
        DATABASE_PREPARATION_CONTRACT,
        prepare_beta_database,
    )

    if not confirm_forward_only:
        raise typer.BadParameter("--confirm-forward-only is required")
    if os.environ.get("COSMAS_ENV") != "early_adopter_beta":
        typer.echo(
            json.dumps(
                {"contract": DATABASE_PREPARATION_CONTRACT, "status": "failed"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            err=True,
        )
        raise typer.Exit(1)
    admin_url = os.environ.get("DATABASE_ADMIN_URL", "")
    runtime_url = os.environ.get("DATABASE_URL", "")
    try:
        evidence = prepare_beta_database(admin_url, runtime_url)
    except Exception:  # noqa: BLE001 - never reflect driver errors or URLs to job logs
        typer.echo(
            json.dumps(
                {"contract": DATABASE_PREPARATION_CONTRACT, "status": "failed"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            err=True,
        )
        raise typer.Exit(1) from None
    typer.echo(evidence.sanitized_json())


@app.command("verify-beta-runtime")
def verify_beta_runtime_cmd(
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
    confirm_runtime_uami: bool = typer.Option(False, "--confirm-runtime-uami"),
) -> None:
    """Probe the live synthetic D3 data plane and emit sanitized evidence."""

    from cosmas_os.application.runtime_acceptance import (
        runtime_acceptance_failure_json,
        verify_beta_runtime,
    )

    if not confirm_synthetic_only or not confirm_runtime_uami:
        typer.echo(runtime_acceptance_failure_json(), err=True)
        raise typer.Exit(1)
    try:
        evidence = verify_beta_runtime(settings)
    except Exception:  # noqa: BLE001 - never reflect dependency details or configured values
        typer.echo(runtime_acceptance_failure_json(), err=True)
        raise typer.Exit(1) from None
    typer.echo(evidence.sanitized_json())


@app.command("fingerprint-beta-database")
def fingerprint_beta_database_cmd(
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
    confirm_read_only: bool = typer.Option(False, "--confirm-read-only"),
) -> None:
    """Emit a value-free fingerprint for guarded source/restore comparison."""

    from cosmas_os.application.database_fingerprint import (
        database_fingerprint_failure_json,
        fingerprint_beta_database,
    )

    if (
        not confirm_synthetic_only
        or not confirm_read_only
        or os.environ.get("COSMAS_ENV") != "early_adopter_beta"
        or os.environ.get("DATA_MODE") != "synthetic"
    ):
        typer.echo(database_fingerprint_failure_json(), err=True)
        raise typer.Exit(1)
    try:
        evidence = fingerprint_beta_database(
            os.environ.get("DATABASE_URL", ""),
            cosmas_env=os.environ.get("COSMAS_ENV", ""),
            data_mode=os.environ.get("DATA_MODE", ""),
        )
    except Exception:  # noqa: BLE001 - never reflect data, identifiers, or connection details
        typer.echo(database_fingerprint_failure_json(), err=True)
        raise typer.Exit(1) from None
    typer.echo(evidence.sanitized_json())


_ACCEPTANCE_STATE_MAX_BYTES = 16_384


@app.command("fingerprint-workspace-database")
def fingerprint_workspace_database_cmd(
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
    confirm_read_only: bool = typer.Option(False, "--confirm-read-only"),
) -> None:
    """Measure the full synthetic workspace snapshot without exposing row values."""
    from cosmas_os.application.workspace_fingerprint import (
        fingerprint_workspace_database,
        workspace_fingerprint_failure_json,
    )

    if not confirm_synthetic_only or not confirm_read_only:
        typer.echo(workspace_fingerprint_failure_json(), err=True)
        raise typer.Exit(1)
    try:
        evidence = fingerprint_workspace_database(
            os.environ.get("DATABASE_URL", ""),
            cosmas_env=os.environ.get("COSMAS_ENV", ""),
            data_mode=os.environ.get("DATA_MODE", ""),
        )
    except Exception:  # noqa: BLE001 - never expose credentials or database values
        typer.echo(workspace_fingerprint_failure_json(), err=True)
        raise typer.Exit(1) from None
    typer.echo(evidence.sanitized_json())


def _read_acceptance_state(path: Path | None) -> str:
    """Read exactly one bounded state input from a protected file or job env."""

    environment_state = os.environ.get("COSMAS_ACCEPTANCE_STATE")
    if (path is None) == (environment_state is None):
        raise ValueError("invalid acceptance state")
    if environment_state is not None:
        if not environment_state or len(environment_state.encode()) > _ACCEPTANCE_STATE_MAX_BYTES:
            raise ValueError("invalid acceptance state")
        return environment_state

    assert path is not None

    repository_root = Path(__file__).resolve().parents[2]
    resolved = path.resolve(strict=True)
    if path.is_symlink() or resolved == repository_root or repository_root in resolved.parents:
        raise ValueError("invalid acceptance state")
    file_stat = resolved.stat()
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != os.geteuid()
        or stat.S_IMODE(file_stat.st_mode) & 0o077
        or file_stat.st_size > _ACCEPTANCE_STATE_MAX_BYTES
    ):
        raise ValueError("invalid acceptance state")
    return resolved.read_text(encoding="utf-8")


def _acceptance_environment_is_synthetic_beta() -> bool:
    return (
        os.environ.get("COSMAS_ENV") == "early_adopter_beta"
        and os.environ.get("DATA_MODE") == "synthetic"
    )


@app.command("baseline-beta-workflow-acceptance")
def baseline_beta_workflow_acceptance_cmd(
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
    confirm_async_worker: bool = typer.Option(False, "--confirm-async-worker"),
) -> None:
    """Bind an opaque baseline to the one browser-reviewable synthetic ticket."""

    from cosmas_os.application.beta_acceptance import (
        WORKFLOW_ACCEPTANCE_CONTRACT,
        acceptance_failure_json,
        baseline_beta_workflow_acceptance,
        decode_acceptance_hmac_key,
    )

    session: Session | None = None
    if (
        not confirm_synthetic_only
        or not confirm_async_worker
        or not _acceptance_environment_is_synthetic_beta()
    ):
        typer.echo(acceptance_failure_json(WORKFLOW_ACCEPTANCE_CONTRACT), err=True)
        raise typer.Exit(1)
    try:
        hmac_key = decode_acceptance_hmac_key(os.environ.get("COSMAS_ACCEPTANCE_HMAC_KEY"))
        session = _session()
        state = baseline_beta_workflow_acceptance(session, settings, hmac_key)
    except Exception:  # noqa: BLE001 - never reflect database rows, IDs, or state-key details
        typer.echo(acceptance_failure_json(WORKFLOW_ACCEPTANCE_CONTRACT), err=True)
        raise typer.Exit(1) from None
    finally:
        if session is not None:
            session.close()
    typer.echo(state.sanitized_json())


@app.command("verify-beta-workflow-acceptance")
def verify_beta_workflow_acceptance_cmd(
    state_path: Path | None = typer.Argument(None, dir_okay=False),
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
    confirm_browser_complete: bool = typer.Option(False, "--confirm-browser-complete"),
) -> None:
    """Verify one browser approval and its asynchronous worker outcome."""

    from cosmas_os.application.beta_acceptance import (
        WORKFLOW_ACCEPTANCE_CONTRACT,
        acceptance_failure_json,
        decode_acceptance_hmac_key,
        verify_beta_workflow_acceptance,
    )

    session: Session | None = None
    if (
        not confirm_synthetic_only
        or not confirm_browser_complete
        or not _acceptance_environment_is_synthetic_beta()
    ):
        typer.echo(acceptance_failure_json(WORKFLOW_ACCEPTANCE_CONTRACT), err=True)
        raise typer.Exit(1)
    try:
        hmac_key = decode_acceptance_hmac_key(os.environ.get("COSMAS_ACCEPTANCE_HMAC_KEY"))
        state_json = _read_acceptance_state(state_path)
        session = _session()
        evidence = verify_beta_workflow_acceptance(session, settings, state_json, hmac_key)
    except Exception:  # noqa: BLE001 - never reflect database rows, IDs, or state-key details
        typer.echo(acceptance_failure_json(WORKFLOW_ACCEPTANCE_CONTRACT), err=True)
        raise typer.Exit(1) from None
    finally:
        if session is not None:
            session.close()
    typer.echo(evidence.sanitized_json())


@app.command("prepare-beta-purge-acceptance")
def prepare_beta_purge_acceptance_cmd(
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
    confirm_runtime_uami: bool = typer.Option(False, "--confirm-runtime-uami"),
) -> None:
    """Prepare one invented, due artifact for an authenticated browser purge."""

    from cosmas_os.application.beta_acceptance import (
        PURGE_ACCEPTANCE_CONTRACT,
        acceptance_failure_json,
        decode_acceptance_hmac_key,
        prepare_beta_purge_acceptance,
    )

    session: Session | None = None
    if (
        not confirm_synthetic_only
        or not confirm_runtime_uami
        or not _acceptance_environment_is_synthetic_beta()
    ):
        typer.echo(acceptance_failure_json(PURGE_ACCEPTANCE_CONTRACT), err=True)
        raise typer.Exit(1)
    try:
        hmac_key = decode_acceptance_hmac_key(os.environ.get("COSMAS_ACCEPTANCE_HMAC_KEY"))
        session = _session()
        state = prepare_beta_purge_acceptance(
            session,
            settings,
            hmac_key,
            managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID"),
            expected_managed_identity_client_id=os.environ.get(
                "EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID"
            ),
        )
    except Exception:  # noqa: BLE001 - never reflect database, Blob, identity, or key details
        typer.echo(acceptance_failure_json(PURGE_ACCEPTANCE_CONTRACT), err=True)
        raise typer.Exit(1) from None
    finally:
        if session is not None:
            session.close()
    typer.echo(state.sanitized_json())


@app.command("verify-beta-audit-replay")
def verify_beta_audit_replay_cmd(
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
    confirm_no_content_export: bool = typer.Option(False, "--confirm-no-content-export"),
) -> None:
    """Replay the live Box-scoped audit timeline and emit counts only."""

    from cosmas_os.application.beta_acceptance import (
        AUDIT_REPLAY_CONTRACT,
        acceptance_failure_json,
        verify_beta_audit_replay,
    )

    session: Session | None = None
    if (
        not confirm_synthetic_only
        or not confirm_no_content_export
        or not _acceptance_environment_is_synthetic_beta()
    ):
        typer.echo(acceptance_failure_json(AUDIT_REPLAY_CONTRACT), err=True)
        raise typer.Exit(1)
    try:
        session = _session()
        evidence = verify_beta_audit_replay(session, settings)
    except Exception:  # noqa: BLE001 - never reflect database rows or identifiers
        typer.echo(acceptance_failure_json(AUDIT_REPLAY_CONTRACT), err=True)
        raise typer.Exit(1) from None
    finally:
        if session is not None:
            session.close()
    typer.echo(evidence.sanitized_json())


@app.command("verify-beta-purge-acceptance")
def verify_beta_purge_acceptance_cmd(
    state_path: Path | None = typer.Argument(None, dir_okay=False),
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
    confirm_runtime_uami: bool = typer.Option(False, "--confirm-runtime-uami"),
    confirm_browser_complete: bool = typer.Option(False, "--confirm-browser-complete"),
) -> None:
    """Verify the tombstone plus exact-key recoverable Blob absence."""

    from cosmas_os.application.beta_acceptance import (
        PURGE_ACCEPTANCE_CONTRACT,
        acceptance_failure_json,
        decode_acceptance_hmac_key,
        verify_beta_purge_acceptance,
    )

    session: Session | None = None
    if (
        not confirm_synthetic_only
        or not confirm_runtime_uami
        or not confirm_browser_complete
        or not _acceptance_environment_is_synthetic_beta()
    ):
        typer.echo(acceptance_failure_json(PURGE_ACCEPTANCE_CONTRACT), err=True)
        raise typer.Exit(1)
    try:
        hmac_key = decode_acceptance_hmac_key(os.environ.get("COSMAS_ACCEPTANCE_HMAC_KEY"))
        state_json = _read_acceptance_state(state_path)
        session = _session()
        evidence = verify_beta_purge_acceptance(
            session,
            settings,
            state_json,
            hmac_key,
            managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID"),
            expected_managed_identity_client_id=os.environ.get(
                "EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID"
            ),
        )
    except Exception:  # noqa: BLE001 - never reflect database, Blob, identity, or key details
        typer.echo(acceptance_failure_json(PURGE_ACCEPTANCE_CONTRACT), err=True)
        raise typer.Exit(1) from None
    finally:
        if session is not None:
            session.close()
    typer.echo(evidence.sanitized_json())


@app.command("baseline-beta-offboarding-acceptance")
def baseline_beta_offboarding_acceptance_cmd(
    request_path: Path | None = typer.Argument(None, dir_okay=False),
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
    confirm_reviewed_target: bool = typer.Option(False, "--confirm-reviewed-target"),
) -> None:
    """Bind one private reviewed tester identity to an opaque offboarding challenge."""

    from cosmas_os.application.offboarding_acceptance import (
        baseline_beta_offboarding_acceptance,
        decode_offboarding_hmac_key,
        offboarding_failure_json,
    )

    session: Session | None = None
    if (
        not confirm_synthetic_only
        or not confirm_reviewed_target
        or not _acceptance_environment_is_synthetic_beta()
    ):
        typer.echo(offboarding_failure_json(), err=True)
        raise typer.Exit(1)
    try:
        hmac_key = decode_offboarding_hmac_key(os.environ.get("COSMAS_ACCEPTANCE_HMAC_KEY"))
        request_json = _read_acceptance_state(request_path)
        session = _session()
        state = baseline_beta_offboarding_acceptance(
            session,
            settings,
            request_json,
            hmac_key,
        )
    except Exception:  # noqa: BLE001 - never reflect identity, state, or key details
        typer.echo(offboarding_failure_json(), err=True)
        raise typer.Exit(1) from None
    finally:
        if session is not None:
            session.close()
    typer.echo(state.sanitized_json())


@app.command("verify-beta-offboarding-acceptance")
def verify_beta_offboarding_acceptance_cmd(
    state_path: Path | None = typer.Argument(None, dir_okay=False),
    confirm_synthetic_only: bool = typer.Option(False, "--confirm-synthetic-only"),
    confirm_browser_complete: bool = typer.Option(False, "--confirm-browser-complete"),
) -> None:
    """Verify app deactivation and the separate Clerk/browser evidence handoff."""

    from cosmas_os.application.offboarding_acceptance import (
        decode_offboarding_hmac_key,
        offboarding_failure_json,
        verify_beta_offboarding_acceptance,
    )

    session: Session | None = None
    if (
        not confirm_synthetic_only
        or not confirm_browser_complete
        or not _acceptance_environment_is_synthetic_beta()
    ):
        typer.echo(offboarding_failure_json(), err=True)
        raise typer.Exit(1)
    try:
        hmac_key = decode_offboarding_hmac_key(os.environ.get("COSMAS_ACCEPTANCE_HMAC_KEY"))
        verification_json = _read_acceptance_state(state_path)
        session = _session()
        evidence = verify_beta_offboarding_acceptance(
            session,
            settings,
            verification_json,
            hmac_key,
        )
    except Exception:  # noqa: BLE001 - never reflect identity, state, or key details
        typer.echo(offboarding_failure_json(), err=True)
        raise typer.Exit(1) from None
    finally:
        if session is not None:
            session.close()
    typer.echo(evidence.sanitized_json())


@app.command("delete-patient-records")
def delete_patient_records_cmd(
    patient_link_id: str = typer.Argument(..., help="Internal patient id"),
    actor_principal_id: str = typer.Option(..., "--actor"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Count or delete one patient's records. The practice owner is the admin."""

    from cosmas_os.application.patient_deletion import delete_patient_records, storage_roots
    from cosmas_os.application.services import Container
    from cosmas_os.domain.rules import AuthorizationError

    session = _session()
    try:
        container = Container(session)
        report = delete_patient_records(
            session,
            actor_principal_id=actor_principal_id,
            patient_link_id=patient_link_id,
            confirm=confirm,
            blob=container.blob,
            file_roots=storage_roots(container.blob),
        )
    except AuthorizationError:
        typer.echo("admin authority required", err=True)
        raise typer.Exit(1) from None
    except Exception:
        typer.echo("patient records could not be deleted", err=True)
        raise typer.Exit(1) from None
    finally:
        session.close()
    typer.echo(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    app()
