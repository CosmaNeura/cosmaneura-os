from __future__ import annotations

import csv
import io
import secrets
from datetime import UTC, datetime
from pathlib import Path

from cosmas_os.ports import (
    AuthSubject,
    BlobRepresentationAbsence,
    NotifyReceipt,
    NotifyRequest,
    ScheduleAppointment,
)


class FakeAuthAdapter:
    def __init__(self, subjects: dict[str, AuthSubject] | None = None) -> None:
        self._subjects = subjects or {}

    def register(self, subject: AuthSubject) -> None:
        self._subjects[subject.principal_id] = subject

    def get_subject(self, subject_id: str) -> AuthSubject:
        if subject_id not in self._subjects:
            raise KeyError(f"unknown subject {subject_id}")
        return self._subjects[subject_id]


class CsvScheduleAdapter:
    def import_appointments(self, csv_text: str) -> list[ScheduleAppointment]:
        reader = csv.DictReader(io.StringIO(csv_text))
        out: list[ScheduleAppointment] = []
        for row in reader:
            start = datetime.fromisoformat(row["start_at"].replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            out.append(
                ScheduleAppointment(
                    external_id=row["external_id"],
                    start_at=start,
                    patient_label=row["patient_label"],
                    source=row.get("source", "csv"),
                )
            )
        return out


class FakeNotifyAdapter:
    """Deterministic in-memory notify sink. Idempotent by operation_id."""

    def __init__(
        self, *, fail_once_ops: set[str] | None = None, unknown_ops: set[str] | None = None
    ) -> None:
        self.sent: dict[str, NotifyReceipt] = {}
        self.attempts: dict[str, int] = {}
        self.fail_once_ops = fail_once_ops or set()
        self.unknown_ops = unknown_ops or set()

    def send(self, request: NotifyRequest) -> NotifyReceipt:
        self.attempts[request.operation_id] = self.attempts.get(request.operation_id, 0) + 1
        if request.operation_id in self.sent:
            return self.sent[request.operation_id]
        if request.operation_id in self.unknown_ops:
            receipt = NotifyReceipt(
                external_reference=f"unk-{request.operation_id}",
                status="unknown",
            )
            # Do not cache as success — caller marks UNKNOWN
            return receipt
        if request.operation_id in self.fail_once_ops and self.attempts[request.operation_id] == 1:
            raise RuntimeError("simulated transport failure before ack")
        receipt = NotifyReceipt(
            external_reference=f"fake-{request.operation_id}",
            status="succeeded",
        )
        self.sent[request.operation_id] = receipt
        return receipt


class LocalBlobAdapter:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._tokens: dict[str, str] = {}

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        meta = path.with_suffix(path.suffix + ".meta")
        meta.write_text(content_type, encoding="utf-8")
        return key

    def get_bytes(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def delete(self, key: str) -> None:
        path = self.root / key
        if path.exists():
            path.unlink()
        meta = path.with_suffix(path.suffix + ".meta")
        if meta.exists():
            meta.unlink()

    def probe_recoverable_absence(self, key: str) -> BlobRepresentationAbsence:
        path = self.root / key
        meta = path.with_suffix(path.suffix + ".meta")
        absent = not path.exists() and not meta.exists()
        return BlobRepresentationAbsence(
            current_absent=absent,
            versions_absent=absent,
            snapshots_absent=absent,
            deleted_absent=absent,
        )

    def issue_upload_token(self, artifact_id: str) -> str:
        token = secrets.token_urlsafe(24)
        self._tokens[token] = artifact_id
        return token

    def consume_upload_token(self, token: str) -> str:
        if token not in self._tokens:
            raise KeyError("invalid upload token")
        return self._tokens.pop(token)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class InjectableClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance_days(self, days: int) -> None:
        from datetime import timedelta

        self._now = self._now + timedelta(days=days)

    def set(self, now: datetime) -> None:
        self._now = now
