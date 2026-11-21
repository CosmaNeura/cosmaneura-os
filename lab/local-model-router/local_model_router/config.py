"""Load router thresholds and lane settings from config (never hardcoded)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "router_config.json"


@dataclass(frozen=True)
class SizeBounds:
    max_files: int
    max_tokens: int


@dataclass(frozen=True)
class LaneConfig:
    name: str
    model: str
    task_types: tuple[str, ...]
    heavy: bool
    starting_size: str | None = None
    max_size: str | None = None
    num_predict: int | None = None
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class RouterConfig:
    raw: dict[str, Any]
    sizes: dict[str, SizeBounds]
    lanes: dict[str, LaneConfig]
    escalation_chain: tuple[str, ...]
    runs_per_cell_required: int
    step_up_after_consecutive_passes: int
    step_down_after_fable_rejections_in_window: int
    step_down_window: int
    min_free_percent: float
    unload_12b_before_heavy: bool
    long_log_token_threshold: int
    long_log_force_lane: str
    long_log_reason: str
    fable_review_required: bool
    fable_configurable: bool
    ollama_api_base: str
    aider_map_tokens: int
    max_attempts: int
    max_follow_ups: int
    forbidden_aider_flags: tuple[str, ...]
    metrics_jsonl_path: str
    azure_codex_mini_endpoint_env: str
    azure_gpt_5_3_codex_endpoint_env: str

    def lane_for_task(self, task_type: str) -> LaneConfig | None:
        for lane in self.lanes.values():
            if task_type in lane.task_types:
                return lane
        return None

    def size_fits(self, size_name: str, file_count: int, token_estimate: int) -> bool:
        bounds = self.sizes[size_name]
        return file_count <= bounds.max_files and token_estimate <= bounds.max_tokens

    def classify_size(self, file_count: int, token_estimate: int) -> str:
        """Return the smallest size label that fits the job."""
        ordered = sorted(
            self.sizes.items(),
            key=lambda item: (item[1].max_tokens, item[1].max_files, item[0]),
        )
        for name, bounds in ordered:
            if file_count <= bounds.max_files and token_estimate <= bounds.max_tokens:
                return name
        return ordered[-1][0]


def load_config(path: Path | None = None) -> RouterConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    sizes = {
        name: SizeBounds(max_files=int(body["max_files"]), max_tokens=int(body["max_tokens"]))
        for name, body in raw["sizes"].items()
    }
    lanes: dict[str, LaneConfig] = {}
    for name, body in raw["lanes"].items():
        lanes[name] = LaneConfig(
            name=name,
            model=str(body["model"]),
            task_types=tuple(body["task_types"]),
            heavy=bool(body.get("heavy", False)),
            starting_size=body.get("starting_size"),
            max_size=body.get("max_size"),
            num_predict=_optional_int(body.get("num_predict")),
            timeout_seconds=_optional_int(body.get("timeout_seconds")),
        )
    harness = raw["harness"]
    memory = raw["memory"]
    long_log = raw["long_log"]
    fable = raw["fable"]
    promotion = raw["promotion"]
    step_rules = raw["step_rules"]
    azure = raw["azure"]
    return RouterConfig(
        raw=raw,
        sizes=sizes,
        lanes=lanes,
        escalation_chain=tuple(raw["escalation_chain"]),
        runs_per_cell_required=int(promotion["runs_per_cell_required"]),
        step_up_after_consecutive_passes=int(step_rules["step_up_after_consecutive_passes"]),
        step_down_after_fable_rejections_in_window=int(
            step_rules["step_down_after_fable_rejections_in_window"]
        ),
        step_down_window=int(step_rules["step_down_window"]),
        min_free_percent=float(memory["min_free_percent"]),
        unload_12b_before_heavy=bool(memory["unload_12b_before_heavy"]),
        long_log_token_threshold=int(long_log["token_threshold"]),
        long_log_force_lane=str(long_log["force_lane"]),
        long_log_reason=str(long_log["reason"]),
        fable_review_required=bool(fable["review_required"]),
        fable_configurable=bool(fable["configurable"]),
        ollama_api_base=str(harness["ollama_api_base"]),
        aider_map_tokens=int(harness["aider_map_tokens"]),
        max_attempts=int(harness["max_attempts"]),
        max_follow_ups=int(harness["max_follow_ups"]),
        forbidden_aider_flags=tuple(harness["forbidden_aider_flags"]),
        metrics_jsonl_path=str(raw["metrics"]["jsonl_path"]),
        azure_codex_mini_endpoint_env=str(azure["codex_mini_endpoint_env"]),
        azure_gpt_5_3_codex_endpoint_env=str(azure["gpt_5_3_codex_endpoint_env"]),
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
