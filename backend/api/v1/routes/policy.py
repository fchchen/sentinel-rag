from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.auth import AuthContext, Role, require_role

router = APIRouter(tags=["policy"])


class PolicyOverrideRequest(BaseModel):
    rule_id: str = Field(min_length=1)
    justification: str = Field(min_length=1)


@router.post("/policy/overrides")
async def create_policy_override(
    payload: PolicyOverrideRequest,
    context: AuthContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, str]:
    return {
        "status": "approved",
        "rule_id": payload.rule_id,
        "requested_by": context.user_id,
        "justification": payload.justification,
    }
