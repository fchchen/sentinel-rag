from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from core.audit import AuditService, get_audit_service
from core.documents import DocumentService, get_document_service
from core.evaluation import EvaluationService, get_evaluation_service
from core.retrieval import RetrievalService, get_retrieval_service
from main import app
from tests.helpers import TENANT_A, auth_headers, request


def _services():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    documents = DocumentService(engine=engine)
    retrieval = RetrievalService(engine=engine)
    audit = AuditService(engine=engine)
    evaluation = EvaluationService(engine=engine, retry_delay_seconds=0)
    return documents, retrieval, audit, evaluation


@pytest.mark.anyio
async def test_admin_can_list_eval_jobs_with_retry_metadata() -> None:
    documents, retrieval, audit, evaluation = _services()
    documents.create_document(
        tenant_id=TENANT_A,
        filename="guide.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
        content_text="billing invoice reconciliation guide",
    )

    async def override_documents() -> DocumentService:
        return documents

    async def override_retrieval() -> RetrievalService:
        return retrieval

    async def override_audit() -> AuditService:
        return audit

    async def override_eval() -> EvaluationService:
        return evaluation

    app.dependency_overrides[get_document_service] = override_documents
    app.dependency_overrides[get_retrieval_service] = override_retrieval
    app.dependency_overrides[get_audit_service] = override_audit
    app.dependency_overrides[get_evaluation_service] = override_eval
    try:
        gateway_response = await request(
            "POST",
            "/api/v1/gateway/complete",
            headers=auth_headers(roles=["reader"], tenant_id=TENANT_A),
            json_body={
                "prompt": "billing invoice",
                "provider": "auto",
                "max_tokens": 200,
                "context": {"tenant_id": TENANT_A, "app_id": "console", "trace_id": str(uuid4())},
            },
        )
        assert gateway_response.status_code == 200

        jobs_response = await request(
            "GET",
            "/api/v1/evals/jobs",
            headers=auth_headers(roles=["admin"], tenant_id=TENANT_A),
        )
    finally:
        app.dependency_overrides.clear()

    assert jobs_response.status_code == 200
    items = jobs_response.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "COMPLETED"
    assert items[0]["attempt_count"] == 0
    assert items[0]["last_error"] is None
