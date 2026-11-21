"""JSONL metrics logger for amendment-6 fields."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

# Amendment 6 required fields on every coding metrics record.
AMENDMENT6_FIELDS = (
    "tokens",
    "vendor",
    "activity",
    "review_rounds",
    "fable_rejection_after_gates",
    "escalated",
    "merged_pr",
)


@dataclass(frozen=True)
class MetricsEvent:
    event: str
    vendor: str
    activity: str
    tokens: int = 0
    review_rounds: int = 0
    fable_rejection_after_gates: bool = False
    escalated: bool = False
    merged_pr: str | None = None
    job_id: str | None = None
    extra: dict[str, Any] | None = None

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ts"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        if payload["extra"] is None:
            del payload["extra"]
        else:
            payload.update(payload.pop("extra"))
        for field in AMENDMENT6_FIELDS:
            if field not in payload:
                raise ValueError(f"metrics record missing amendment-6 field: {field}")
        return payload


class MetricsLogger:
    def __init__(self, path: Path | None = None, stream: TextIO | None = None) -> None:
        self.path = path
        self.stream = stream
        self._events: list[dict[str, Any]] = []

    def log(self, event: MetricsEvent) -> dict[str, Any]:
        record = event.to_record()
        self._events.append(record)
        line = json.dumps(record, sort_keys=True) + "\n"
        if self.stream is not None:
            self.stream.write(line)
            self.stream.flush()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        return record

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def escalation_rate(self) -> float:
        if not self._events:
            return 0.0
        escalated = sum(1 for event in self._events if event.get("escalated"))
        return escalated / len(self._events)

    def fable_rejection_rate(self) -> float:
        gated = [
            event
            for event in self._events
            if event.get("event") in {"review", "coding_complete", "gate_pass"}
        ]
        if not gated:
            return 0.0
        rejected = sum(1 for event in gated if event.get("fable_rejection_after_gates"))
        return rejected / len(gated)


def assert_amendment6_fields(record: dict[str, Any]) -> None:
    missing = [field for field in AMENDMENT6_FIELDS if field not in record]
    if missing:
        raise AssertionError(f"Missing amendment-6 fields: {missing}")
