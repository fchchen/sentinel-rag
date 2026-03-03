from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import pytest

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
async def test_reader_can_search_retrieval_api_and_get_stored_context() -> None:
    service = _retrieval_service()

    async def override_retrieval_service() -> RetrievalService:
        return service

    app.dependency_overrides[get_retrieval_service] = override_retrieval_service
    try:
        response = await request(
            "POST",
            "/api/v1/retrieval/search",
            headers=auth_headers(roles=["reader"], tenant_id=TENANT_A),
            json_body={"query": "show me the guide", "app_id": "console"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieval_run_id"]
    assert len(payload["items"]) == 1
    assert payload["items"][0]["document_id"]
    assert "guide.pdf" in payload["items"][0]["snippet"]
