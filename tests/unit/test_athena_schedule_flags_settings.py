"""C9 schedule Settings flags: defaults off; env/kwargs resolve to True.

C9 (#334) gates today's athena FHIR Encounter schedule on the same dual flags
as C8 — there is no separate schedule-only Settings field. The runtime in
``athena_fhir_schedule_runtime`` reads those flags via injected callables.
"""

from __future__ import annotations

from cosmas_os.config import Settings

# Exact names from config.py / ATHENA_FHIR_TODAY_SCHEDULE.md (C9 reused C8).
SCHEDULE_FLAG_FIELDS = (
    "workspace_ehr_read_enabled",
    "workspace_athena_fhir_sandbox_enabled",
)
SCHEDULE_FLAG_ENV = (
    "WORKSPACE_EHR_READ_ENABLED",
    "WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED",
)


def test_athena_schedule_flags_default_false_when_unset():
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue] -- BaseSettings runtime option.
    for name in SCHEDULE_FLAG_FIELDS:
        assert getattr(settings, name) is False


def test_athena_schedule_flags_resolve_true_when_kwargs_set():
    settings = Settings(  # pyright: ignore[reportCallIssue] -- BaseSettings runtime option.
        _env_file=None,
        workspace_ehr_read_enabled=True,
        workspace_athena_fhir_sandbox_enabled=True,
    )
    for name in SCHEDULE_FLAG_FIELDS:
        assert getattr(settings, name) is True


def test_athena_schedule_flags_resolve_true_from_env(monkeypatch):
    for env_name in SCHEDULE_FLAG_ENV:
        monkeypatch.setenv(env_name, "true")
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue] -- BaseSettings runtime option.
    for name in SCHEDULE_FLAG_FIELDS:
        assert getattr(settings, name) is True
