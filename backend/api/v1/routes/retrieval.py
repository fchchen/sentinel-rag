from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.auth import AuthContext, get_auth_context
from core.retrieval import RetrievalResultView, RetrievalRunSummaryView, get_retrieval_service

router = APIRouter(tags=["retrieval"])


class RetrievalSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    app_id: str = Field(min_length=1)


class RetrievalItemResponse(BaseModel):
    document_id: str
    rank: int
    score: int
    snippet: str


class RetrievalSearchResponse(BaseModel):
    retrieval_run_id: str
    items: list[RetrievalItemResponse]


class RetrievalRunSummaryResponse(BaseModel):
    id: str
    app_id: str
    query_text: str
    result_count: int


class RetrievalRunListResponse(BaseModel):
    items: list[RetrievalRunSummaryResponse]


@router.post("/retrieval/search", response_model=RetrievalSearchResponse)
async def search_retrieval(
    payload: RetrievalSearchRequest,
    context: AuthContext = Depends(get_auth_context),
    retrieval_service=Depends(get_retrieval_service),
) -> RetrievalSearchResponse:
    run = retrieval_service.retrieve(
        tenant_id=context.tenant_id,
        app_id=payload.app_id,
        query=payload.query,
    )
    return RetrievalSearchResponse(
        retrieval_run_id=run.id,
        items=[_to_item_response(item) for item in run.results],
    )


def _to_item_response(item: RetrievalResultView) -> RetrievalItemResponse:
    return RetrievalItemResponse(
        document_id=item.document_id,
        rank=item.rank,
        score=item.score,
        snippet=item.snippet,
    )


@router.get("/retrieval/runs", response_model=RetrievalRunListResponse)
async def list_retrieval_runs(
    context: AuthContext = Depends(get_auth_context),
    retrieval_service=Depends(get_retrieval_service),
) -> RetrievalRunListResponse:
    runs = retrieval_service.list_runs(tenant_id=context.tenant_id)
    return RetrievalRunListResponse(items=[_to_run_summary(run) for run in runs])


def _to_run_summary(run: RetrievalRunSummaryView) -> RetrievalRunSummaryResponse:
    return RetrievalRunSummaryResponse(
        id=run.id,
        app_id=run.app_id,
        query_text=run.query_text,
        result_count=run.result_count,
    )
