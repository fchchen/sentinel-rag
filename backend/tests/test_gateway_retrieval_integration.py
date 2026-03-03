from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from core.retrieval import RetrievalService, get_retrieval_service
from main import app
from tests.helpers import TENANT_A, auth_headers, request


def _retrieval_service() -> RetrievalService:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    service = RetrievalService(engine=engine)
    service.create_document(
        tenant_id=TENANT_A,
        filename="guide.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
    )
    return service


@pytest.mark.anyio
async def test_gateway_response_includes_retrieval_context_and_run_id() -> None:
    service = _retrieval_service()

    async def override_retrieval_service() -> RetrievalService:
        return service

    app.dependency_overrides[get_retrieval_service] = override_retrieval_service
    try:
        response = await request(
            "POST",
            "/api/v1/gateway/complete",
            headers=auth_headers(roles=["reader"], tenant_id=TENANT_A),
            json_body={
                "prompt": "show me the guide",
                "provider": "auto",
                "max_tokens": 200,
                "context": {"tenant_id": TENANT_A, "app_id": "console", "trace_id": str(uuid4())},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieval_run_id"]
    assert len(payload["retrieval_context"]) == 1
    assert "guide.pdf" in payload["retrieval_context"][0]["snippet"]
