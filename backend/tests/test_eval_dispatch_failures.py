from uuid import uuid4

from kombu.exceptions import OperationalError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.audit import AuditService
from core.db import EvalJob, bootstrap_schema
from core.eval_worker import CeleryEvalWorker
from core.evaluation import EvaluationService
from core.policy import PolicyDecision
from core.retrieval import RetrievalService


def test_broker_dispatch_failure_marks_job_for_retry() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    service = EvaluationService(engine=engine, retry_delay_seconds=0)
    retrieval = RetrievalService(engine=engine)
    retrieval.create_document(
        tenant_id="tenant-a",
        filename="guide.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        status="ACTIVE",
        content_text="billing invoice reconciliation guide",
    )
    run = retrieval.retrieve(tenant_id="tenant-a", app_id="console", query="billing invoice")
    audit = AuditService(engine=engine)
    decision = PolicyDecision(
        decision="allow",
        rule_ids=[],
        severity="low",
        explanations=[],
        redacted_prompt=None,
    )
    audit_log_id = audit.record_gateway_call(
        tenant_id="tenant-a",
        app_id="console",
        trace_id=str(uuid4()),
        raw_prompt="billing invoice",
        decision=decision,
        response_redacted="billing invoice summary",
        provider="azure_openai",
        model="gpt-4o-mini",
        prompt_tokens=4,
        completion_tokens=4,
    )
    job_id = service.enqueue_gateway_evaluation(
        tenant_id="tenant-a",
        audit_log_id=audit_log_id,
        retrieval_run_id=run.id,
        completion="billing invoice summary",
        policy_decision=decision,
    )

    worker = CeleryEvalWorker(
        submit_job=lambda job_id, worker_token: (_ for _ in ()).throw(OperationalError("redis down")),
        submit_pending=lambda limit: (_ for _ in ()).throw(OperationalError("redis down")),
        evaluation_service=service,
    )

    result = worker.dispatch_job(job_id)

    assert result.mode == "celery"
    assert result.queued is False

    with Session(engine) as session:
        job = session.get(EvalJob, job_id)

    assert job is not None
    assert job.status == "RETRY"
    assert job.attempt_count == 1
    assert job.last_error == "redis down"
    assert job.next_attempt_at is not None
