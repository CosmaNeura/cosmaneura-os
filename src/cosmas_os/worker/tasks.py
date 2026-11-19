from __future__ import annotations

from cosmas_os.application import independent_transcription as transcription
from cosmas_os.application import services as svc
from cosmas_os.db import make_engine, make_session_factory
from cosmas_os.worker.celery_app import celery_app

SessionLocal = make_session_factory(make_engine())


@celery_app.task(name="cosmas_os.execute_operation", bind=True, max_retries=5)
def execute_operation_task(self, operation_id: str) -> str:
    session = SessionLocal()
    try:
        c = svc.Container(session)
        op = svc.execute_operation(c, operation_id)
        return op.status
    except Exception as exc:  # noqa: BLE001
        # Retry reuses same operation_id
        raise self.retry(exc=exc, countdown=2) from exc
    finally:
        session.close()


@celery_app.task(name="cosmas_os.purge_independent_recording_audio")
def purge_independent_recording_audio_task(box_id: str | None = None) -> int:
    """Retention sweep for expired independent-transcription audio. No switch gate."""
    session = SessionLocal()
    try:
        c = svc.Container(session)
        receipts = transcription.purge_due_recording_audio(c, box_id=box_id, actor_id=None)
        return len(receipts)
    finally:
        session.close()
