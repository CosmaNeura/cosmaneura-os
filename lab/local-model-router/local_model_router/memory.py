"""Injectable memory reader for heavy-model batch guards."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class MemorySnapshot:
    free_percent: float
    swap_watchdog_tripped: bool
    gemma_12b_loaded: bool = False


MemoryReader = Callable[[], MemorySnapshot]


def default_memory_reader() -> MemorySnapshot:
    """Read /proc/meminfo when available; tests inject a fake reader instead."""
    try:
        meminfo = _parse_meminfo("/proc/meminfo")
    except OSError:
        return MemorySnapshot(free_percent=100.0, swap_watchdog_tripped=False)
    mem_total = meminfo.get("MemTotal", 0)
    mem_available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    if mem_total <= 0:
        free_percent = 100.0
    else:
        free_percent = 100.0 * float(mem_available) / float(mem_total)
    swap_total = meminfo.get("SwapTotal", 0)
    swap_free = meminfo.get("SwapFree", 0)
    # Watchdog trip when a meaningful swap partition is nearly exhausted.
    swap_watchdog_tripped = swap_total > 0 and swap_free < max(1, swap_total // 20)
    return MemorySnapshot(
        free_percent=free_percent,
        swap_watchdog_tripped=swap_watchdog_tripped,
        gemma_12b_loaded=False,
    )


def _parse_meminfo(path: str) -> dict[str, int]:
    values: dict[str, int] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            parts = raw.strip().split()
            if not parts:
                continue
            try:
                values[key] = int(parts[0])
            except ValueError:
                continue
    return values
