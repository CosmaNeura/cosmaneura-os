"""Aider/pytest/ruff harness planner. Builds commands; never runs a model in CI."""

from __future__ import annotations

from dataclasses import dataclass

from .config import HARDCODED_FORBIDDEN_AIDER_FLAGS, LaneConfig, RouterConfig


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
    num_predict: int | None = None
    timeout_seconds: int | None = None
    num_ctx: int | None = None


def build_aider_command(
    config: RouterConfig,
    *,
    model: str,
    message: str,
    files: list[str],
    follow_up: bool = False,
) -> list[str]:
    """Build an Aider argv. Never includes Codex full-access or bypass flags."""
    for path in files:
        if path.startswith("-"):
            raise ValueError(f"Forbidden file arg starting with '-': {path}")
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
    lane: LaneConfig | None = None,
) -> HarnessPlan:
    env = {"OLLAMA_API_BASE": config.ollama_api_base}
    num_predict = lane.num_predict if lane else None
    timeout_seconds = lane.timeout_seconds if lane else None
    num_ctx = lane.num_ctx if lane else None
    if num_predict is not None:
        env["OLLAMA_NUM_PREDICT"] = str(num_predict)
    if timeout_seconds is not None:
        env["OLLAMA_TIMEOUT_SECONDS"] = str(timeout_seconds)
    if num_ctx is not None:
        env["OLLAMA_NUM_CTX"] = str(num_ctx)

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
        num_predict=num_predict,
        timeout_seconds=timeout_seconds,
        num_ctx=num_ctx,
    )


def _flag_basename(part: str) -> str:
    """Lowercased text before '='."""
    return part.lower().split("=", 1)[0]


def _assert_no_forbidden_flags(cmd: list[str], config: RouterConfig) -> None:
    forbidden = set(HARDCODED_FORBIDDEN_AIDER_FLAGS) | set(config.forbidden_aider_flags)
    skip_next = False
    for part in cmd:
        if skip_next:
            # Exempt the --message value (may contain dashes).
            skip_next = False
            continue
        if part == "--message":
            skip_next = True
            continue
        if part.startswith("--message="):
            continue
        name = _flag_basename(part)
        if name in forbidden:
            raise ValueError(f"Forbidden Aider flag refused: {part}")
        # Also catch substring forms like --foo-full-access
        if "full-access" in name or name.endswith("-bypass") or name == "--bypass":
            raise ValueError(f"Forbidden Aider flag pattern refused: {part}")
