"""Aider/pytest/ruff harness planner. Builds commands; never runs a model in CI."""

from __future__ import annotations

from dataclasses import dataclass

from .config import RouterConfig


@dataclass(frozen=True)
class HarnessPlan:
    env: dict[str, str]
    aider_attempt: list[str]
    pytest_cmd: list[str]
    ruff_cmd: list[str]
    aider_follow_up: list[str]
    escalate_after_follow_up: bool
    max_attempts: int
    max_follow_ups: int


def build_aider_command(
    config: RouterConfig,
    *,
    model: str,
    message: str,
    files: list[str],
    follow_up: bool = False,
) -> list[str]:
    """Build an Aider argv. Never includes Codex full-access or bypass flags."""
    cmd = [
        "aider",
        "--model",
        f"ollama/{model}",
        "--map-tokens",
        str(config.aider_map_tokens),
        "--message",
        message,
        *files,
    ]
    if follow_up:
        cmd.extend(["--message", "Follow-up: fix remaining pytest/ruff failures only."])
    _assert_no_forbidden_flags(cmd, config)
    return cmd


def build_harness_plan(
    config: RouterConfig,
    *,
    model: str,
    message: str,
    files: list[str],
) -> HarnessPlan:
    env = {"OLLAMA_API_BASE": config.ollama_api_base}
    attempt = build_aider_command(
        config,
        model=model,
        message=message,
        files=files,
        follow_up=False,
    )
    follow_up = build_aider_command(
        config,
        model=model,
        message=message,
        files=files,
        follow_up=True,
    )
    return HarnessPlan(
        env=env,
        aider_attempt=attempt,
        pytest_cmd=["pytest", "-q"],
        ruff_cmd=["ruff", "check", "."],
        aider_follow_up=follow_up,
        escalate_after_follow_up=True,
        max_attempts=config.max_attempts,
        max_follow_ups=config.max_follow_ups,
    )


def _assert_no_forbidden_flags(cmd: list[str], config: RouterConfig) -> None:
    forbidden = set(config.forbidden_aider_flags)
    for part in cmd:
        if part in forbidden:
            raise ValueError(f"Forbidden Aider flag refused: {part}")
        # Also refuse substring forms that look like bypass/full-access.
        lowered = part.lower()
        if "full-access" in lowered or "bypass" in lowered:
            raise ValueError(f"Forbidden Aider flag pattern refused: {part}")
