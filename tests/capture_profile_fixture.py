"""Invented receiver-shaped profile fixture; no runtime implementation imports."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4


def profile_packet(session_id, *, channels=("microphone",), now=None):
    request = {"schema_version": "1.0", "profile_id": "visit-60m-v1", "channels": sorted(channels)}
    return {
        "schema_version": "1.0", "receipt_id": str(uuid4()), "session_id": str(session_id),
        "request": request,
        "request_sha256": hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "created_at": (now or datetime.now(UTC)).isoformat(),
        "maximum_aggregate_plaintext_bytes": 268435456,
        "maximum_chunks": 720, "maximum_chunks_per_channel": 360,
        "maximum_track_duration_ms": 3600000,
    }
