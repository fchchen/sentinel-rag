from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.audit import AuditService
from core.db import EvalDeadLetter, EvalJob, bootstrap_schema
from core.evaluation import EvaluationService
from core.eval_tasks import handle_task_failure
from core.policy import PolicyDecision
from core.retrieval import RetrievalService


def test_dead_letter_records_task_failure_and_marks_job_failed() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    evaluation = EvaluationService(engine=engine)
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
    job_id = evaluation.enqueue_gateway_evaluation(
        tenant_id="tenant-a",
        audit_log_id=audit_log_id,
        retrieval_run_id=run.id,
        completion="billing invoice summary",
        policy_decision=decision,
    )

    handle_task_failure(
        task_name="sentinel_rag.process_eval_job",
        args=(job_id,),
        kwargs={},
        exc=RuntimeError("worker crashed"),
        retry_count=3,
        evaluation_service=evaluation,
    )

    with Session(engine) as session:
        job = session.get(EvalJob, job_id)
        dead_letters = session.execute(select(EvalDeadLetter)).scalars().all()

    assert job is not None
    assert job.status == "FAILED"
    assert job.last_error == "worker crashed"
    assert len(dead_letters) == 1
    assert dead_letters[0].job_id == job_id
    assert dead_letters[0].task_name == "sentinel_rag.process_eval_job"
    assert dead_letters[0].error_message == "worker crashed"
