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
    evaluation = EvaluationService(engine=engine)
    return documents, retrieval, audit, evaluation


@pytest.mark.anyio
async def test_reader_can_list_eval_results_and_cost_metrics() -> None:
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
        pending_eval_response = await request(
            "GET",
            "/api/v1/evals",
            headers=auth_headers(roles=["reader"], tenant_id=TENANT_A),
        )
        process_response = await request(
            "POST",
            "/api/v1/evals/process",
            headers=auth_headers(roles=["admin"], tenant_id=TENANT_A),
        )
        eval_response = await request(
            "GET",
            "/api/v1/evals",
            headers=auth_headers(roles=["reader"], tenant_id=TENANT_A),
        )
        cost_response = await request(
            "GET",
            "/api/v1/metrics/costs",
            headers=auth_headers(roles=["reader"], tenant_id=TENANT_A),
        )
    finally:
        app.dependency_overrides.clear()

    assert gateway_response.status_code == 200
    assert pending_eval_response.status_code == 200
    assert process_response.status_code == 200
    assert eval_response.status_code == 200
    assert cost_response.status_code == 200
    assert len(pending_eval_response.json()["items"]) == 1
    assert process_response.json()["processed"] == 0
    assert len(eval_response.json()["items"]) == 1
    assert eval_response.json()["items"][0]["retrieval_run_id"] == gateway_response.json()["retrieval_run_id"]
    assert cost_response.json()["total_cost_usd"] > 0
