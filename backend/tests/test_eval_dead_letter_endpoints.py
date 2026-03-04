from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from core.audit import AuditService, get_audit_service
from core.documents import DocumentService, get_document_service
from core.evaluation import EvaluationService, get_evaluation_service
from core.eval_tasks import handle_task_failure
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
async def test_admin_can_list_dead_letters_and_requeue_failed_job() -> None:
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
        job_id = jobs_response.json()["items"][0]["id"]
        handle = evaluation.get_dispatch_handle(job_id=job_id)
        assert handle is not None
        handle_task_failure(
            task_name="sentinel_rag.process_eval_job",
            args=(job_id, handle.worker_token),
            kwargs={},
            exc=RuntimeError("worker crashed"),
            retry_count=2,
            evaluation_service=evaluation,
        )

        dead_letter_response = await request(
            "GET",
            "/api/v1/evals/dead-letters",
            headers=auth_headers(roles=["admin"], tenant_id=TENANT_A),
        )
        requeue_response = await request(
            "POST",
            f"/api/v1/evals/jobs/{job_id}/requeue",
            headers=auth_headers(roles=["admin"], tenant_id=TENANT_A),
        )
        refreshed_jobs_response = await request(
            "GET",
            "/api/v1/evals/jobs",
            headers=auth_headers(roles=["admin"], tenant_id=TENANT_A),
        )
    finally:
        app.dependency_overrides.clear()

    assert dead_letter_response.status_code == 200
    assert len(dead_letter_response.json()["items"]) == 1
    assert dead_letter_response.json()["items"][0]["job_id"] == job_id
    assert f"\"args\":[{job_id},\"{handle.worker_token}\"]" in dead_letter_response.json()["items"][0]["payload_json"]
    assert dead_letter_response.json()["items"][0]["error_message"] == "worker crashed"
    assert requeue_response.status_code == 200
    assert requeue_response.json()["accepted"] is True
    assert refreshed_jobs_response.json()["items"][0]["status"] == "COMPLETED"
