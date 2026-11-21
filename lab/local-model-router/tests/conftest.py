"""Fixtures for the lab-only local-model router tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from local_model_router.config import RouterConfig, load_config
from local_model_router.memory import MemorySnapshot

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config() -> RouterConfig:
    return load_config(ROOT / "config" / "router_config.json")


@pytest.fixture
def healthy_memory() -> MemorySnapshot:
    return MemorySnapshot(free_percent=40.0, swap_watchdog_tripped=False, gemma_12b_loaded=False)


@pytest.fixture
def fixtures_dir() -> Path:
    return ROOT / "fixtures"
