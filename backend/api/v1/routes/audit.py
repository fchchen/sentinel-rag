from fastapi import APIRouter, Depends

from core.auth import AuthContext, require_human_user

router = APIRouter(tags=["audit"])

_AUDIT_LOGS = [
    {
        "id": "log-1",
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "message": "Gateway request completed",
    },
    {
        "id": "log-2",
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "message": "Policy override requested",
    },
    {
        "id": "log-3",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
        "message": "Document upload quarantined",
    },
]


@router.get("/audit/logs")
async def list_audit_logs(
    context: AuthContext = Depends(require_human_user),
) -> dict[str, object]:
    items = [log for log in _AUDIT_LOGS if log["tenant_id"] == context.tenant_id]
    return {"items": items, "count": len(items)}
