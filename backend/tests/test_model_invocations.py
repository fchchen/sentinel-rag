from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from core.audit import AuditService, get_audit_service
from core.db import ModelInvocation, bootstrap_schema
from main import app
from tests.helpers import TENANT_A, auth_headers, request


def _audit_service() -> tuple[AuditService, object]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    return AuditService(engine=engine), engine


@pytest.mark.anyio
async def test_gateway_request_persists_model_invocation_cost() -> None:
    service, engine = _audit_service()

    async def override_audit_service() -> AuditService:
        return service

    app.dependency_overrides[get_audit_service] = override_audit_service
    try:
        response = await request(
            "POST",
            "/api/v1/gateway/complete",
            headers=auth_headers(roles=["reader"]),
            json_body={
                "prompt": "Summarize the latest retrieval batch",
                "provider": "auto",
                "max_tokens": 200,
                "context": {"tenant_id": TENANT_A, "app_id": "console", "trace_id": str(uuid4())},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200

    with Session(engine) as session:
        invocations = session.execute(select(ModelInvocation)).scalars().all()

    assert len(invocations) == 1
    assert invocations[0].provider == "azure_openai"
    assert invocations[0].prompt_tokens > 0
    assert invocations[0].completion_tokens > 0
    assert invocations[0].cost_usd > 0
