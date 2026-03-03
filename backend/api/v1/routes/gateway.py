from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.audit import calculate_invocation_cost, get_audit_service
from core.auth import AuthContext, get_auth_context
from core.evaluation import get_evaluation_service
from core.eval_worker import get_eval_worker
from core.gateway import ProviderUnavailableError, get_gateway_service
from core.policy import PolicyDecision, get_policy_engine
from core.retrieval import RetrievalResultView, get_retrieval_service

router = APIRouter(tags=["gateway"])


class GatewayContext(BaseModel):
    tenant_id: UUID
    app_id: str
    trace_id: UUID | None = None


class GatewayRequest(BaseModel):
    prompt: str = Field(min_length=1)
    provider: str = Field(default="auto")
    max_tokens: int = Field(default=1000, gt=0, le=1000)
    context: GatewayContext


class GatewayRetrievalItem(BaseModel):
    document_id: str
    rank: int
    score: int
    snippet: str


class GatewayResponse(BaseModel):
    trace_id: UUID | None
    provider: str
    model: str
    completion: str
    redacted_completion: str
    policy_decision: PolicyDecision
    retrieval_run_id: str
    retrieval_context: list[GatewayRetrievalItem]


@router.post("/complete", response_model=GatewayResponse)
async def complete(
    request: GatewayRequest,
    auth_context: AuthContext = Depends(get_auth_context),
    gateway_service=Depends(get_gateway_service),
    policy_engine=Depends(get_policy_engine),
    audit_service=Depends(get_audit_service),
    retrieval_service=Depends(get_retrieval_service),
    evaluation_service=Depends(get_evaluation_service),
    eval_worker=Depends(get_eval_worker),
) -> GatewayResponse:
    decision = policy_engine.evaluate(request.prompt)
    if decision.decision == "block":
        audit_service.record_gateway_call(
            tenant_id=auth_context.tenant_id,
            app_id=request.context.app_id,
            trace_id=str(request.context.trace_id) if request.context.trace_id else None,
            raw_prompt=request.prompt,
            decision=decision,
            response_redacted=None,
            provider=None,
            model=None,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Prompt blocked by policy",
        )

    if evaluation_service.is_monthly_budget_exceeded(tenant_id=auth_context.tenant_id):
        audit_service.record_gateway_call(
            tenant_id=auth_context.tenant_id,
            app_id=request.context.app_id,
            trace_id=str(request.context.trace_id) if request.context.trace_id else None,
            raw_prompt=request.prompt,
            decision=decision,
            response_redacted=None,
            provider=None,
            model=None,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Tenant monthly budget exceeded",
        )

    retrieval_run = retrieval_service.retrieve(
        tenant_id=auth_context.tenant_id,
        app_id=request.context.app_id,
        query=request.prompt,
    )

    try:
        result = gateway_service.complete(request.provider, request.prompt)
    except ProviderUnavailableError as exc:
        audit_service.record_gateway_call(
            tenant_id=auth_context.tenant_id,
            app_id=request.context.app_id,
            trace_id=str(request.context.trace_id) if request.context.trace_id else None,
            raw_prompt=request.prompt,
            decision=decision,
            response_redacted=None,
            provider=None,
            model=None,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    redacted_completion = policy_engine.redact_for_persistence(result.completion)
    audit_log_id = audit_service.record_gateway_call(
        tenant_id=auth_context.tenant_id,
        app_id=request.context.app_id,
        trace_id=str(request.context.trace_id) if request.context.trace_id else None,
        raw_prompt=request.prompt,
        decision=decision,
        response_redacted=redacted_completion,
        provider=result.provider,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
    job_id = evaluation_service.enqueue_gateway_evaluation(
        tenant_id=auth_context.tenant_id,
        audit_log_id=audit_log_id,
        retrieval_run_id=retrieval_run.id,
        completion=redacted_completion,
        policy_decision=decision,
    )
    evaluation_service.record_model_spend(
        tenant_id=auth_context.tenant_id,
        cost_usd=calculate_invocation_cost(
            provider=result.provider,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        ),
    )
    eval_worker.dispatch_job(job_id)

    return GatewayResponse(
        trace_id=request.context.trace_id,
        provider=result.provider,
        model=result.model,
        completion=result.completion,
        redacted_completion=redacted_completion,
        policy_decision=decision,
        retrieval_run_id=retrieval_run.id,
        retrieval_context=[_to_retrieval_item(item) for item in retrieval_run.results],
    )


def _to_retrieval_item(item: RetrievalResultView) -> GatewayRetrievalItem:
    return GatewayRetrievalItem(
        document_id=item.document_id,
        rank=item.rank,
        score=item.score,
        snippet=item.snippet,
    )
