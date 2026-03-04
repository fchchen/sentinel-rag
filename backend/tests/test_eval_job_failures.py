from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.audit import AuditService
from core.db import EvalJob, bootstrap_schema
from core.evaluation import EvaluationService
from core.policy import PolicyDecision
from core.retrieval import RetrievalService


class _FailingEvaluationService(EvaluationService):
    def _evaluate_with_session(self, **kwargs):  # type: ignore[override]
        raise RuntimeError("judge timeout")


def _seed_job(service: EvaluationService, engine) -> int:
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
    return service.enqueue_gateway_evaluation(
        tenant_id="tenant-a",
        audit_log_id=audit_log_id,
        retrieval_run_id=run.id,
        completion="billing invoice summary",
        policy_decision=decision,
    )


def test_eval_job_retries_then_moves_to_failed_after_max_attempts() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    service = _FailingEvaluationService(engine=engine, max_attempts=2, retry_delay_seconds=0)
    job_id = _seed_job(service, engine)
    handle = service.get_dispatch_handle(job_id=job_id)

    assert handle is not None
    first = service.process_job(job_id=job_id, worker_token=handle.worker_token)
    second = service.process_job(job_id=job_id, worker_token=handle.worker_token)

    assert first is None
    assert second is None

    with Session(engine) as session:
        job = session.get(EvalJob, job_id)

    assert job is not None
    assert job.status == "FAILED"
    assert job.attempt_count == 2
    assert job.last_error == "judge timeout"
    assert job.next_attempt_at is None


def test_process_job_ignores_incorrect_worker_token() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    service = EvaluationService(engine=engine, retry_delay_seconds=0)
    job_id = _seed_job(service, engine)

    result = service.process_job(job_id=job_id, worker_token="wrong-token")

    assert result is None

    with Session(engine) as session:
        job = session.get(EvalJob, job_id)

    assert job is not None
    assert job.status == "PENDING"
    assert job.attempt_count == 0
