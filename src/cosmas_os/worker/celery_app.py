from __future__ import annotations

from celery import Celery

from cosmas_os.config import settings

celery_app = Celery("cosmas_os", broker=settings.redis_url, include=["cosmas_os.worker.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    result_backend=None,
    task_ignore_result=True,
)
