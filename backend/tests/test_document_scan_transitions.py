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
async def test_admin_can_apply_scan_result_transition() -> None:
    service = _document_service()
    document = service.create_document(
        tenant_id=TENANT_A,
        filename="invoice.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
    )

    async def override_document_service() -> DocumentService:
        return service

    app.dependency_overrides[get_document_service] = override_document_service
    try:
        response = await request(
            "POST",
            f"/api/v1/documents/{document.id}/scan-result",
            headers=auth_headers(roles=["admin"], tenant_id=TENANT_A),
            json_body={"result": "clean"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ACTIVE"


@pytest.mark.anyio
async def test_malware_scan_result_sets_quarantined_in_persisted_model() -> None:
    service = _document_service()
    document = service.create_document(
        tenant_id=TENANT_A,
        filename="bad.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
    )

    async def override_document_service() -> DocumentService:
        return service

    app.dependency_overrides[get_document_service] = override_document_service
    try:
        await request(
            "POST",
            f"/api/v1/documents/{document.id}/scan-result",
            headers=auth_headers(roles=["admin"], tenant_id=TENANT_A),
            json_body={"result": "malware"},
        )
        list_response = await request(
            "GET",
            "/api/v1/documents",
            headers=auth_headers(roles=["reader"], tenant_id=TENANT_A),
        )
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert items[0]["status"] == "QUARANTINED"


@pytest.mark.anyio
async def test_missing_document_scan_result_returns_404() -> None:
    service = _document_service()

    async def override_document_service() -> DocumentService:
        return service

    app.dependency_overrides[get_document_service] = override_document_service
    try:
        response = await request(
            "POST",
            "/api/v1/documents/missing-doc/scan-result",
            headers=auth_headers(roles=["admin"], tenant_id=TENANT_A),
            json_body={"result": "clean"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"
