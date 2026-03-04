from celery import Celery

from core.config import settings

celery_app = Celery(
    "sentinel_rag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["core.eval_tasks", "core.audit_tasks"],
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_store_eager_result=settings.celery_task_always_eager,
)
