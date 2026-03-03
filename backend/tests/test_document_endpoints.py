import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from core.documents import DocumentService, get_document_service
from main import app
from tests.helpers import TENANT_A, auth_headers, request


def _document_service() -> DocumentService:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return DocumentService(engine=engine)


@pytest.mark.anyio
async def test_admin_can_upload_document_and_it_starts_pending() -> None:
    service = _document_service()

    async def override_document_service() -> DocumentService:
        return service

    app.dependency_overrides[get_document_service] = override_document_service
    try:
        response = await request(
            "POST",
            "/api/v1/documents",
            headers=auth_headers(roles=["admin"]),
            json_body={
                "filename": "runbook.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 4096,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "PENDING"
    assert payload["tenant_id"] == TENANT_A


@pytest.mark.anyio
async def test_reader_can_list_only_their_tenant_documents() -> None:
    service = _document_service()
    service.create_document(
        tenant_id=TENANT_A,
        filename="guide.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
    )
    service.create_document(
        tenant_id="22222222-2222-2222-2222-222222222222",
        filename="other.pdf",
        mime_type="application/pdf",
        size_bytes=2048,
    )

    async def override_document_service() -> DocumentService:
        return service

    app.dependency_overrides[get_document_service] = override_document_service
    try:
        response = await request(
            "GET",
            "/api/v1/documents",
            headers=auth_headers(roles=["reader"], tenant_id=TENANT_A),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["tenant_id"] == TENANT_A
