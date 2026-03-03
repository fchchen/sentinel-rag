from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.audit import get_audit_service
from core.auth import AuthContext, get_auth_context

router = APIRouter(tags=["metrics"])


class ProviderCostResponse(BaseModel):
    provider: str
    cost_usd: float


class CostSummaryResponse(BaseModel):
    total_cost_usd: float
    providers: list[ProviderCostResponse]


@router.get("/metrics/costs", response_model=CostSummaryResponse)
async def get_cost_summary(
    context: AuthContext = Depends(get_auth_context),
    audit_service=Depends(get_audit_service),
) -> CostSummaryResponse:
    summary = audit_service.cost_summary(tenant_id=context.tenant_id)
    return CostSummaryResponse(
        total_cost_usd=summary["total_cost_usd"],
        providers=[
            ProviderCostResponse(provider=item["provider"], cost_usd=item["cost_usd"])
            for item in summary["providers"]
        ],
    )
