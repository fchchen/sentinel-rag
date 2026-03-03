import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from core.retrieval import RetrievalService, get_retrieval_service
from main import app
from tests.helpers import TENANT_A, auth_headers, request


@pytest.mark.anyio
async def test_reader_can_list_recent_retrieval_runs() -> None:
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
    service.retrieve(tenant_id=TENANT_A, app_id="console", query="show me the guide")

    async def override_retrieval() -> RetrievalService:
        return service

    app.dependency_overrides[get_retrieval_service] = override_retrieval
    try:
        response = await request(
            "GET",
            "/api/v1/retrieval/runs",
            headers=auth_headers(roles=["reader"], tenant_id=TENANT_A),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["result_count"] == 1
