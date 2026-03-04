from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.audit import AuditLogView, get_audit_service
from core.auth import AuthContext, require_human_user

router = APIRouter(tags=["audit"])


class AuditLogItemResponse(BaseModel):
    id: str
    tenant_id: str
    app_id: str
    trace_id: str | None
    provider: str | None
    model: str | None
    policy_decision: str
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogItemResponse]
    count: int


@router.get("/audit/logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    context: AuthContext = Depends(require_human_user),
    audit_service=Depends(get_audit_service),
) -> AuditLogListResponse:
    items = audit_service.list_logs(
        tenant_id=context.tenant_id,
        date_from=date_from,
        date_to=date_to,
    )
    return AuditLogListResponse(
        items=[_to_item_response(item) for item in items],
        count=len(items),
    )


def _to_item_response(item: AuditLogView) -> AuditLogItemResponse:
    return AuditLogItemResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        app_id=item.app_id,
        trace_id=item.trace_id,
        provider=item.provider,
        model=item.model,
        policy_decision=item.policy_decision,
        created_at=item.created_at,
    )
