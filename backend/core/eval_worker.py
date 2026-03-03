from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Protocol

from celery.result import AsyncResult
from fastapi import Depends
from kombu.exceptions import OperationalError

from core.evaluation import EvaluationService, get_evaluation_service


@dataclass(frozen=True)
class EvalDispatchResult:
    mode: str
    queued: bool
    processed: int
    task_id: str | None


class EvalWorker(Protocol):
    def dispatch_job(self, job_id: int) -> EvalDispatchResult: ...

    def dispatch_pending(self, *, limit: int = 10) -> EvalDispatchResult: ...


class InlineEvalWorker:
    def __init__(self, evaluation_service: EvaluationService) -> None:
        self._evaluation_service = evaluation_service

    def dispatch_job(self, job_id: int) -> EvalDispatchResult:
        processed = 1 if self._evaluation_service.process_job(job_id=job_id) else 0
        return EvalDispatchResult(
            mode="inline",
            queued=False,
            processed=processed,
            task_id=None,
        )

    def dispatch_pending(self, *, limit: int = 10) -> EvalDispatchResult:
        processed = len(self._evaluation_service.process_pending_jobs(limit=limit))
        return EvalDispatchResult(
            mode="inline",
            queued=False,
            processed=processed,
            task_id=None,
        )


class CeleryEvalWorker:
    def __init__(
        self,
        *,
        submit_job: Callable[[int], AsyncResult] | None = None,
        submit_pending: Callable[[int], AsyncResult] | None = None,
        evaluation_service: EvaluationService | None = None,
    ) -> None:
        if submit_job is None or submit_pending is None:
            from core.eval_tasks import process_eval_job_task, process_pending_eval_jobs_task

            submit_job = submit_job or process_eval_job_task.delay
            submit_pending = submit_pending or process_pending_eval_jobs_task.delay

        self._submit_job = submit_job
        self._submit_pending = submit_pending
        self._evaluation_service = evaluation_service or EvaluationService()

    def dispatch_job(self, job_id: int) -> EvalDispatchResult:
        try:
            result = self._submit_job(job_id)
        except OperationalError as exc:
            self._evaluation_service.record_dispatch_failure(job_id=job_id, error=str(exc))
            return EvalDispatchResult(mode="celery", queued=False, processed=0, task_id=None)
        return EvalDispatchResult(mode="celery", queued=True, processed=0, task_id=result.id)

    def dispatch_pending(self, *, limit: int = 10) -> EvalDispatchResult:
        try:
            result = self._submit_pending(limit)
        except OperationalError as exc:
            self._evaluation_service.record_batch_dispatch_failure(limit=limit, error=str(exc))
            return EvalDispatchResult(mode="celery", queued=False, processed=0, task_id=None)
        return EvalDispatchResult(mode="celery", queued=True, processed=0, task_id=result.id)


@lru_cache(maxsize=1)
def _build_eval_worker() -> EvalWorker:
    return CeleryEvalWorker()


async def get_eval_worker() -> EvalWorker:
    return _build_eval_worker()


async def get_inline_eval_worker(
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
) -> EvalWorker:
    return InlineEvalWorker(evaluation_service)
