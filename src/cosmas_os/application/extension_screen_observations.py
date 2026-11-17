"""Selector observations are evidence, never approvals or system-of-record actions."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class ScreenObservation:
    id: str
    box_id: str
    principal_id: str
    payload: str
    payload_sha256: str


class ObservationStore(Protocol):
    def append(self, observation: ScreenObservation) -> None: ...


def observe(store: ObservationStore, box_id: str, principal_id: str, rows: list[dict[str, str]],
            recheck_identity: Callable[[], None]) -> dict[str, str]:
    payload = json.dumps({"rows": rows}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    observation = ScreenObservation(str(uuid4()), box_id, principal_id, payload,
                                    hashlib.sha256(payload.encode("utf-8")).hexdigest())
    # Access can be revoked between reading the screen and committing evidence.
    recheck_identity()
    store.append(observation)
    return {"observation_id": observation.id, "payload_sha256": observation.payload_sha256,
            "stub_prep": f"Synthetic prep stub: {len(rows)} invented appointments observed.\nRead only; review the fixture before using this text."}
