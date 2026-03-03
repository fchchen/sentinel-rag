from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.auth import AuthContext, get_auth_context
from core.config import settings
from core.tokens import encode_local_token

router = APIRouter(tags=["auth"])


class DemoAuthResponse(BaseModel):
    access_token: str
    token_type: str
    tenant_id: str
    roles: list[str]


@router.post("/auth/demo", response_model=DemoAuthResponse)
async def issue_demo_token() -> DemoAuthResponse:
    if settings.auth_verifier_mode != "local":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo auth is only available in local mode",
        )

    tenant_id = "11111111-1111-1111-1111-111111111111"
    roles = ["admin", "reader"]
    return DemoAuthResponse(
        access_token=encode_local_token(
            subject="local-demo-user",
            tenant_id=tenant_id,
            roles=roles,
            audience=settings.entra_audience,
            tenant=settings.entra_tenant_id,
        ),
        token_type="Bearer",
        tenant_id=tenant_id,
        roles=roles,
    )


@router.get("/auth/me")
async def get_current_user(
    context: AuthContext = Depends(get_auth_context),
) -> dict[str, str | list[str]]:
    return {
        "user_id": context.user_id,
        "tenant_id": context.tenant_id,
        "roles": [role.value for role in context.roles],
    }
