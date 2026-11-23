"""Injectable memory readers (Linux /proc + macOS vm_stat/sysctl) and Ollama checks."""

from __future__ import annotations

import json
import platform
import re
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

Ollama12bStatus = Literal["loaded", "not_loaded", "unknown"]


@dataclass(frozen=True)
class MemorySnapshot:
    free_percent: float
    swap_watchdog_tripped: bool
    gemma_12b_loaded: bool = False
    readable: bool = True
    ollama_12b_status: Ollama12bStatus = "not_loaded"


MemoryReader = Callable[[], MemorySnapshot]
CommandRunner = Callable[[list[str]], str]
HttpGetter = Callable[[str], dict[str, Any]]
OllamaChecker = Callable[[], Ollama12bStatus]


class MemoryReadError(RuntimeError):
    """Raised when platform memory cannot be read."""


def default_memory_reader(
    *,
    command_runner: CommandRunner | None = None,
    ollama_checker: OllamaChecker | None = None,
) -> MemorySnapshot:
    """Dispatch to macOS or Linux readers. Tests inject runners/checkers."""
    system = platform.system()
    try:
        if system == "Darwin":
            snapshot = macos_memory_reader(command_runner=command_runner)
        else:
            snapshot = linux_memory_reader()
    except (OSError, MemoryReadError, ValueError, subprocess.SubprocessError):
        return MemorySnapshot(
            free_percent=0.0,
            swap_watchdog_tripped=True,
            gemma_12b_loaded=False,
            readable=False,
            ollama_12b_status="unknown",
        )
    status: Ollama12bStatus
    if ollama_checker is not None:
        status = ollama_checker()
    else:
        status = probe_ollama_12b_status()
    return MemorySnapshot(
        free_percent=snapshot.free_percent,
        swap_watchdog_tripped=snapshot.swap_watchdog_tripped,
        gemma_12b_loaded=(status == "loaded"),
        readable=True,
        ollama_12b_status=status,
    )


def probe_ollama_12b_status(
    *,
    base_url: str = "http://127.0.0.1:11434",
    http_get: HttpGetter | None = None,
) -> Ollama12bStatus:
    """Connection-refused => not_loaded; any other Ollama error => unknown."""
    try:
        loaded = is_gemma_12b_loaded(base_url=base_url, http_get=http_get)
        return "loaded" if loaded else "not_loaded"
    except urllib.error.URLError as err:
        if _is_connection_refused(err):
            return "not_loaded"
        return "unknown"
    except (OSError, TimeoutError, json.JSONDecodeError, ValueError, urllib.error.HTTPError):
        return "unknown"


def _is_connection_refused(err: urllib.error.URLError) -> bool:
    reason = err.reason
    if isinstance(reason, ConnectionRefusedError):
        return True
    text = str(reason).lower()
    return "connection refused" in text or "errno 111" in text


def linux_memory_reader(meminfo_path: str = "/proc/meminfo") -> MemorySnapshot:
    meminfo = _parse_meminfo(meminfo_path)
    mem_total = meminfo.get("MemTotal", 0)
    mem_available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    if mem_total <= 0:
        raise MemoryReadError("MemTotal missing or zero")
    free_percent = 100.0 * float(mem_available) / float(mem_total)
    swap_total = meminfo.get("SwapTotal", 0)
    swap_free = meminfo.get("SwapFree", 0)
    swap_watchdog_tripped = swap_total > 0 and swap_free < max(1, swap_total // 20)
    return MemorySnapshot(
        free_percent=free_percent,
        swap_watchdog_tripped=swap_watchdog_tripped,
        readable=True,
    )


def macos_memory_reader(*, command_runner: CommandRunner | None = None) -> MemorySnapshot:
    """Parse `vm_stat` free pages and `sysctl vm.swapusage` for the swap watchdog."""
    runner = command_runner or _run_command
    vm_stat_text = runner(["vm_stat"])
    sysctl_text = runner(["sysctl", "vm.swapusage"])
    page_size = _parse_page_size(vm_stat_text)
    pages = _parse_vm_stat_pages(vm_stat_text)
    free_pages = pages.get("Pages free", 0) + pages.get("Pages speculative", 0)
    total_pages = free_pages
    for key in (
        "Pages active",
        "Pages inactive",
        "Pages wired down",
        "Pages occupied by compressor",
        "Pages purgeable",
    ):
        total_pages += pages.get(key, 0)
    if total_pages <= 0:
        raise MemoryReadError("vm_stat total pages unreadable")
    free_percent = 100.0 * float(free_pages) / float(total_pages)
    used_bytes, total_bytes = _parse_swapusage(sysctl_text)
    swap_watchdog_tripped = False
    if total_bytes > 0:
        free_bytes = max(0, total_bytes - used_bytes)
        swap_watchdog_tripped = free_bytes < max(1, total_bytes // 20)
    _ = page_size
    return MemorySnapshot(
        free_percent=free_percent,
        swap_watchdog_tripped=swap_watchdog_tripped,
        readable=True,
    )


def is_gemma_12b_loaded(
    *,
    base_url: str = "http://127.0.0.1:11434",
    http_get: HttpGetter | None = None,
) -> bool:
    """Return True if a gemma4:12b-family model is loaded in local Ollama."""
    models = list_loaded_ollama_models(base_url=base_url, http_get=http_get)
    return any(_is_12b_name(name) for name in models)


def list_loaded_ollama_models(
    *,
    base_url: str = "http://127.0.0.1:11434",
    http_get: HttpGetter | None = None,
) -> list[str]:
    getter = http_get or _http_get_json
    payload = getter(base_url.rstrip("/") + "/api/ps")
    models: list[str] = []
    for item in payload.get("models", []):
        name = item.get("name") or item.get("model") or ""
        if name:
            models.append(str(name))
    return models


def _is_12b_name(name: str) -> bool:
    lowered = name.lower()
    return "gemma4:12b" in lowered or "gemma4-12b" in lowered or lowered.startswith("gemma4:12b")


def _run_command(argv: list[str]) -> str:
    completed = subprocess.run(
        argv,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return completed.stdout


def _http_get_json(url: str) -> dict[str, Any]:
    if not url.startswith("http://127.0.0.1:") and not url.startswith("http://localhost:"):
        raise ValueError(f"Ollama check refused non-localhost URL: {url}")
    with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


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


def _parse_page_size(vm_stat_text: str) -> int:
    match = re.search(r"page size of\s+(\d+)\s+bytes", vm_stat_text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 16384


def _parse_vm_stat_pages(vm_stat_text: str) -> dict[str, int]:
    pages: dict[str, int] = {}
    for line in vm_stat_text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        digits = re.sub(r"[^\d]", "", raw)
        if digits:
            pages[key.strip()] = int(digits)
    return pages


def _parse_swapusage(text: str) -> tuple[int, int]:
    total_match = re.search(r"total\s*=\s*([\d.]+)([KMGT]?)", text, re.IGNORECASE)
    used_match = re.search(r"used\s*=\s*([\d.]+)([KMGT]?)", text, re.IGNORECASE)
    if not total_match:
        return 0, 0
    total = _to_bytes(float(total_match.group(1)), total_match.group(2))
    used = _to_bytes(float(used_match.group(1)), used_match.group(2)) if used_match else 0
    return used, total


def _to_bytes(value: float, unit: str) -> int:
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    return int(value * mult.get(unit.upper(), 1))
