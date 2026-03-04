from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from core.db import bootstrap_schema
from core.evaluation import EvaluationService
from core.policy import PolicyDecision
from core.retrieval import RetrievalResultView


def _service() -> EvaluationService:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    return EvaluationService(engine=engine)


def test_eval_skipped_when_sampled_out_reason_logged() -> None:
    service = _service()
    service.upsert_quota(tenant_id="tenant-a", eval_sample_pct=0)

    result = service.evaluate_gateway_response(
        tenant_id="tenant-a",
        audit_log_id="audit-1",
        retrieval_run_id="run-1",
        completion="stubbed completion",
        retrieval_context=(RetrievalResultView(document_id="doc-1", rank=1, score=90, snippet="guide"),),
        policy_decision=PolicyDecision(
            decision="allow",
            rule_ids=[],
            severity="low",
            explanations=[],
            redacted_prompt=None,
        ),
    )

    assert result.status == "SKIPPED"
    assert result.skip_reason == "sampled_out"


def test_eval_always_runs_on_low_relevance_score() -> None:
    service = _service()
    service.upsert_quota(tenant_id="tenant-a", eval_sample_pct=0, daily_eval_budget_usd=0.0)

    result = service.evaluate_gateway_response(
        tenant_id="tenant-a",
        audit_log_id="audit-1",
        retrieval_run_id="run-1",
        completion="stubbed completion",
        retrieval_context=(RetrievalResultView(document_id="doc-1", rank=1, score=10, snippet="guide"),),
        policy_decision=PolicyDecision(
            decision="allow",
            rule_ids=[],
            severity="low",
            explanations=[],
            redacted_prompt=None,
        ),
    )

    assert result.status == "COMPLETED"
    assert result.skip_reason is None


def test_daily_eval_spend_resets_after_midnight_utc() -> None:
    service = _service()
    service.upsert_quota(
        tenant_id="tenant-a",
        daily_eval_spend_usd=4.0,
        last_eval_reset_at="2026-03-02T23:59:00+00:00",
    )

    quota = service.get_quota(tenant_id="tenant-a", now="2026-03-03T00:01:00+00:00")

    assert quota.daily_eval_spend_usd == 0.0


def test_monthly_llm_spend_resets_when_utc_month_rolls_over() -> None:
    service = _service()
    service.upsert_quota(
        tenant_id="tenant-a",
        monthly_llm_spend_usd=9.0,
        month_bucket="2026-02-01",
    )

    quota = service.get_quota(tenant_id="tenant-a", now="2026-03-01T00:01:00+00:00")

    assert quota.monthly_llm_spend_usd == 0.0
