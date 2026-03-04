from contextlib import suppress

from celery import Task

from core.celery_app import celery_app
from core.config import settings
from core.evaluation import EvaluationService


def handle_task_failure(
    *,
    task_name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    exc: Exception,
    retry_count: int,
    evaluation_service: EvaluationService | None = None,
) -> None:
    service = evaluation_service or EvaluationService()
    job_id = _extract_job_id(task_name=task_name, args=args, kwargs=kwargs)
    worker_token = _extract_worker_token(task_name=task_name, args=args, kwargs=kwargs)
    with suppress(Exception):
        service.record_dead_letter(
            job_id=job_id,
            task_name=task_name,
            payload={"args": list(args), "kwargs": kwargs},
            error_message=str(exc),
            retry_count=retry_count,
        )
    if job_id is not None:
        with suppress(Exception):
            if worker_token is not None:
                service.mark_job_failed(job_id=job_id, worker_token=worker_token, error=str(exc))


class EvalTaskBase(Task):
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_jitter = True
    retry_kwargs = {"max_retries": settings.celery_task_max_retries}

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # type: ignore[override]
        handle_task_failure(
            task_name=self.name,
            args=tuple(args),
            kwargs=dict(kwargs),
            exc=exc,
            retry_count=self.request.retries,
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(name="sentinel_rag.process_eval_job", bind=True, base=EvalTaskBase)
def process_eval_job_task(self, job_id: int, worker_token: str) -> dict[str, object]:
    service = EvaluationService()
    result = service.process_job(job_id=job_id, worker_token=worker_token)
    return {
        "processed": 1 if result else 0,
        "job_id": job_id,
        "status": result.status if result else "missing",
        "task_id": self.request.id,
    }


@celery_app.task(name="sentinel_rag.process_pending_eval_jobs", bind=True, base=EvalTaskBase)
def process_pending_eval_jobs_task(self, limit: int = 10) -> dict[str, object]:
    service = EvaluationService()
    results = service.process_pending_jobs(limit=limit)
    return {"processed": len(results), "task_id": self.request.id}


def _extract_job_id(*, task_name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> int | None:
    if not task_name.endswith("process_eval_job"):
        return None
    if args and isinstance(args[0], int):
        return args[0]
    job_id = kwargs.get("job_id")
    if isinstance(job_id, int):
        return job_id
    return None


def _extract_worker_token(*, task_name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> str | None:
    if not task_name.endswith("process_eval_job"):
        return None
    if len(args) > 1 and isinstance(args[1], str):
        return args[1]
    worker_token = kwargs.get("worker_token")
    if isinstance(worker_token, str):
        return worker_token
    return None
