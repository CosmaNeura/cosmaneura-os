"""Aider/pytest/ruff harness planner. Builds commands; never runs a model in CI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import HARDCODED_FORBIDDEN_AIDER_FLAGS, LaneConfig, RouterConfig

# Flags that build_aider_command is allowed to emit (allowlist).
ALLOWED_AIDER_FLAGS: frozenset[str] = frozenset(
    {
        "--model",
        "--map-tokens",
        "--message",
        "--timeout",
        "--model-settings-file",
    }
)
VALUE_TAKING_FLAGS: frozenset[str] = frozenset(
    {
        "--model",
        "--map-tokens",
        "--message",
        "--timeout",
        "--model-settings-file",
    }
)


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
    model_settings_text: str | None = None
    model_settings_path: str | None = None


def build_model_settings_yaml(*, model: str, num_predict: int | None, num_ctx: int | None) -> str:
    """Aider model-settings snippet carrying num_predict / num_ctx (not env vars)."""
    lines = [f"- name: ollama/{model}", "  extra_params:"]
    if num_predict is not None:
        lines.append(f"    num_predict: {int(num_predict)}")
    if num_ctx is not None:
        lines.append(f"    num_ctx: {int(num_ctx)}")
    lines.append("")
    return "\n".join(lines)


def build_aider_command(
    config: RouterConfig,
    *,
    model: str,
    message: str,
    files: list[str],
    follow_up: bool = False,
    timeout_seconds: int | None = None,
    model_settings_path: str | None = None,
) -> list[str]:
    """Build an Aider argv. Allowlisted flags only; never bypass/full-access."""
    for path in files:
        if path.startswith("-"):
            raise ValueError(f"Forbidden file arg starting with '-': {path}")
    cmd = [
        "aider",
        "--model",
        f"ollama/{model}",
        "--map-tokens",
        str(config.aider_map_tokens),
    ]
    if timeout_seconds is not None:
        cmd.extend(["--timeout", str(int(timeout_seconds))])
    if model_settings_path is not None:
        cmd.extend(["--model-settings-file", model_settings_path])
    cmd.extend(["--message", message, *files])
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
    model_settings_dir: Path | None = None,
) -> HarnessPlan:
    env = {"OLLAMA_API_BASE": config.ollama_api_base}
    num_predict = lane.num_predict if lane else None
    timeout_seconds = lane.timeout_seconds if lane else None
    num_ctx = lane.num_ctx if lane else None

    settings_text = build_model_settings_yaml(
        model=model, num_predict=num_predict, num_ctx=num_ctx
    )
    settings_path: str | None = None
    if model_settings_dir is not None:
        model_settings_dir.mkdir(parents=True, exist_ok=True)
        path = model_settings_dir / "aider-model-settings.yml"
        path.write_text(settings_text, encoding="utf-8")
        settings_path = str(path)

    attempt = build_aider_command(
        config,
        model=model,
        message=message,
        files=files,
        follow_up=False,
        timeout_seconds=timeout_seconds,
        model_settings_path=settings_path,
    )
    follow_up = build_aider_command(
        config,
        model=model,
        message=message,
        files=files,
        follow_up=True,
        timeout_seconds=timeout_seconds,
        model_settings_path=settings_path,
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
        model_settings_text=settings_text,
        model_settings_path=settings_path,
    )


def _flag_basename(part: str) -> str:
    """Lowercased text before '='."""
    return part.lower().split("=", 1)[0]


def _assert_no_forbidden_flags(cmd: list[str], config: RouterConfig) -> None:
    """Allowlist flags build_aider_command emits; reject any other '-' arg.

    Hard-coded denylist still applies (config may only add). Restored coverage for
    --bypass / --full-access / --codex-full-access and common sandbox bypass forms.
    """
    forbidden = set(HARDCODED_FORBIDDEN_AIDER_FLAGS) | set(config.forbidden_aider_flags)
    skip_next = False
    for part in cmd:
        if skip_next:
            skip_next = False
            continue
        if part == "aider":
            continue
        if not part.startswith("-"):
            continue
        name = _flag_basename(part)
        if name == "--message" or part.startswith("--message="):
            if part == "--message":
                skip_next = True
            continue
        if name in forbidden:
            raise ValueError(f"Forbidden Aider flag refused: {part}")
        lowered = name
        if (
            "full-access" in lowered
            or "bypass" in lowered
            or lowered in {"--yolo", "--full-auto"}
            or "dangerously" in lowered
        ):
            raise ValueError(f"Forbidden Aider flag pattern refused: {part}")
        if name not in ALLOWED_AIDER_FLAGS:
            raise ValueError(f"Non-allowlisted Aider flag refused: {part}")
        if name in VALUE_TAKING_FLAGS and "=" not in part:
            skip_next = True
