from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from core.audit import AuditService, get_audit_service
from core.documents import DocumentService, get_document_service
from core.evaluation import EvaluationService, get_evaluation_service
from core.policy import PolicyDecision
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
async def test_worker_process_persists_skipped_eval_reason() -> None:
    documents, retrieval, audit, evaluation = _services()
    documents.create_document(
        tenant_id=TENANT_A,
        filename="guide.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
        content_text="billing invoice reconciliation guide",
    )
    evaluation.upsert_quota(tenant_id=TENANT_A, eval_sample_pct=0, daily_eval_budget_usd=5.0)

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
        retrieval_run = retrieval.retrieve(
            tenant_id=TENANT_A,
            app_id="console",
            query="billing invoice",
        )
        audit_log_id = audit.record_gateway_call(
            tenant_id=TENANT_A,
            app_id="console",
            trace_id=str(uuid4()),
            raw_prompt="billing invoice",
            decision=PolicyDecision(
                decision="allow",
                rule_ids=[],
                severity="low",
                explanations=[],
                redacted_prompt=None,
            ),
            response_redacted="billing invoice summary",
            provider="azure_openai",
            model="gpt-4o-mini",
            prompt_tokens=4,
            completion_tokens=4,
        )
        evaluation.enqueue_gateway_evaluation(
            tenant_id=TENANT_A,
            audit_log_id=audit_log_id,
            retrieval_run_id=retrieval_run.id,
            completion="billing invoice summary",
            policy_decision=PolicyDecision(
                decision="allow",
                rule_ids=[],
                severity="low",
                explanations=[],
                redacted_prompt=None,
            ),
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
    finally:
        app.dependency_overrides.clear()

    assert process_response.status_code == 200
    assert process_response.json()["processed"] == 1
    assert eval_response.status_code == 200
    assert len(eval_response.json()["items"]) == 1
    assert eval_response.json()["items"][0]["status"] == "SKIPPED"
    assert eval_response.json()["items"][0]["skip_reason"] == "sampled_out"
