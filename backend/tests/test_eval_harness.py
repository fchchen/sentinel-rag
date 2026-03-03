from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from core.audit import AuditService, get_audit_service
from core.db import EvalResult, bootstrap_schema
from core.evaluation import EvaluationService, get_evaluation_service
from core.retrieval import RetrievalService, get_retrieval_service
from main import app
from tests.helpers import TENANT_A, auth_headers, request


def _services() -> tuple[AuditService, RetrievalService, EvaluationService, object]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    retrieval = RetrievalService(engine=engine)
    retrieval.create_document(
        tenant_id=TENANT_A,
        filename="guide.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
    )
    audit = AuditService(engine=engine)
    evaluation = EvaluationService(engine=engine)
    return audit, retrieval, evaluation, engine


@pytest.mark.anyio
async def test_gateway_dispatches_eval_worker_and_persists_eval_result() -> None:
    audit, retrieval, evaluation, engine = _services()

    async def override_audit() -> AuditService:
        return audit

    async def override_retrieval() -> RetrievalService:
        return retrieval

    async def override_evaluation() -> EvaluationService:
        return evaluation

    app.dependency_overrides[get_audit_service] = override_audit
    app.dependency_overrides[get_retrieval_service] = override_retrieval
    app.dependency_overrides[get_evaluation_service] = override_evaluation
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

    with Session(engine) as session:
        eval_results = session.execute(select(EvalResult)).scalars().all()

    assert len(eval_results) == 1
    assert eval_results[0].retrieval_run_id == response.json()["retrieval_run_id"]
    assert eval_results[0].judge_version == "heuristic_v1"
