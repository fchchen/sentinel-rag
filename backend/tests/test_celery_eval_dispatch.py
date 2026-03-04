from core.eval_worker import CeleryEvalWorker


class _FakeAsyncResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeEvaluationService:
    def get_dispatch_handle(self, *, job_id: int):
        from core.evaluation import EvalJobDispatchHandle

        return EvalJobDispatchHandle(job_id=job_id, worker_token="worker-token")


def test_celery_eval_worker_returns_task_metadata_for_single_job() -> None:
    worker = CeleryEvalWorker(
        submit_job=lambda job_id, worker_token: _FakeAsyncResult(f"job-{job_id}"),
        submit_pending=lambda limit: _FakeAsyncResult(f"pending-{limit}"),
        evaluation_service=_FakeEvaluationService(),
    )

    result = worker.dispatch_job(41)

    assert result.mode == "celery"
    assert result.queued is True
    assert result.task_id == "job-41"
    assert result.processed == 0


def test_celery_eval_worker_returns_task_metadata_for_pending_batch() -> None:
    worker = CeleryEvalWorker(
        submit_job=lambda job_id, worker_token: _FakeAsyncResult(f"job-{job_id}"),
        submit_pending=lambda limit: _FakeAsyncResult(f"pending-{limit}"),
        evaluation_service=_FakeEvaluationService(),
    )

    result = worker.dispatch_pending(limit=5)

    assert result.mode == "celery"
    assert result.queued is True
    assert result.task_id == "pending-5"
    assert result.processed == 0
