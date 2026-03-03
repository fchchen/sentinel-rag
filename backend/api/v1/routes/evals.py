from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import AuthContext, Role, get_auth_context, require_role
from core.eval_worker import get_eval_worker
from core.evaluation import EvalDeadLetterView, EvalJobView, EvalResultView, get_evaluation_service

router = APIRouter(tags=["evals"])


class EvalItemResponse(BaseModel):
    id: int
    retrieval_run_id: str
    judge_version: str
    relevance_score: float
    faithfulness_score: float
    hallucination_flag: bool
    status: str
    skip_reason: str | None


class EvalListResponse(BaseModel):
    items: list[EvalItemResponse]


class EvalJobItemResponse(BaseModel):
    id: int
    retrieval_run_id: str
    status: str
    attempt_count: int
    max_attempts: int
    last_error: str | None
    next_attempt_at: datetime | None


class EvalJobListResponse(BaseModel):
    items: list[EvalJobItemResponse]


class EvalDeadLetterItemResponse(BaseModel):
    id: int
    job_id: int | None
    task_name: str
    error_message: str
    retry_count: int
    created_at: datetime


class EvalDeadLetterListResponse(BaseModel):
    items: list[EvalDeadLetterItemResponse]


class EvalWorkerResponse(BaseModel):
    mode: str
    queued: bool
    processed: int
    task_id: str | None


class EvalJobRequeueResponse(BaseModel):
    accepted: bool
    mode: str
    queued: bool
    processed: int
    task_id: str | None


@router.get("/evals", response_model=EvalListResponse)
async def list_evals(
    context: AuthContext = Depends(get_auth_context),
    evaluation_service=Depends(get_evaluation_service),
) -> EvalListResponse:
    items = evaluation_service.list_results(tenant_id=context.tenant_id)
    return EvalListResponse(items=[_to_eval_item(item) for item in items])


@router.get("/evals/jobs", response_model=EvalJobListResponse)
async def list_eval_jobs(
    context: AuthContext = Depends(require_role(Role.ADMIN)),
    evaluation_service=Depends(get_evaluation_service),
) -> EvalJobListResponse:
    items = evaluation_service.list_jobs(tenant_id=context.tenant_id)
    return EvalJobListResponse(items=[_to_eval_job_item(item) for item in items])


@router.get("/evals/dead-letters", response_model=EvalDeadLetterListResponse)
async def list_eval_dead_letters(
    context: AuthContext = Depends(require_role(Role.ADMIN)),
    evaluation_service=Depends(get_evaluation_service),
) -> EvalDeadLetterListResponse:
    items = evaluation_service.list_dead_letters(tenant_id=context.tenant_id)
    return EvalDeadLetterListResponse(items=[_to_eval_dead_letter_item(item) for item in items])


@router.post("/evals/process", response_model=EvalWorkerResponse)
async def process_evals(
    _: AuthContext = Depends(require_role(Role.ADMIN)),
    eval_worker=Depends(get_eval_worker),
) -> EvalWorkerResponse:
    result = eval_worker.dispatch_pending()
    return EvalWorkerResponse(
        mode=result.mode,
        queued=result.queued,
        processed=result.processed,
        task_id=result.task_id,
    )


@router.post("/evals/jobs/{job_id}/requeue", response_model=EvalJobRequeueResponse)
async def requeue_eval_job(
    job_id: int,
    context: AuthContext = Depends(require_role(Role.ADMIN)),
    evaluation_service=Depends(get_evaluation_service),
    eval_worker=Depends(get_eval_worker),
) -> EvalJobRequeueResponse:
    accepted = evaluation_service.requeue_job(job_id=job_id, tenant_id=context.tenant_id)
    if not accepted:
        return EvalJobRequeueResponse(
            accepted=False,
            mode="none",
            queued=False,
            processed=0,
            task_id=None,
        )
    result = eval_worker.dispatch_job(job_id)
    return EvalJobRequeueResponse(
        accepted=True,
        mode=result.mode,
        queued=result.queued,
        processed=result.processed,
        task_id=result.task_id,
    )


def _to_eval_item(item: EvalResultView) -> EvalItemResponse:
    return EvalItemResponse(
        id=item.id,
        retrieval_run_id=item.retrieval_run_id,
        judge_version=item.judge_version,
        relevance_score=item.relevance_score,
        faithfulness_score=item.faithfulness_score,
        hallucination_flag=item.hallucination_flag,
        status=item.status,
        skip_reason=item.skip_reason,
    )


def _to_eval_job_item(item: EvalJobView) -> EvalJobItemResponse:
    return EvalJobItemResponse(
        id=item.id,
        retrieval_run_id=item.retrieval_run_id,
        status=item.status,
        attempt_count=item.attempt_count,
        max_attempts=item.max_attempts,
        last_error=item.last_error,
        next_attempt_at=item.next_attempt_at,
    )


def _to_eval_dead_letter_item(item: EvalDeadLetterView) -> EvalDeadLetterItemResponse:
    return EvalDeadLetterItemResponse(
        id=item.id,
        job_id=item.job_id,
        task_name=item.task_name,
        error_message=item.error_message,
        retry_count=item.retry_count,
        created_at=item.created_at,
    )
