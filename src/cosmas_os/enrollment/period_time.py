"""Business-period time port. Security and evidence freshness use wall time."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol


class PeriodTime(Protocol):
    def now(self) -> datetime: ...
