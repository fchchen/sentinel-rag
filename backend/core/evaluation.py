import json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.config import settings
from core.db import AuditLog, EvalDeadLetter, EvalJob, EvalResult, RetrievalResult, TenantQuota, get_engine
from core.policy import PolicyDecision
from core.retrieval import RetrievalResultView


@dataclass(frozen=True)
class EvalResultView:
    id: int
    retrieval_run_id: str
    judge_version: str
    relevance_score: float
    faithfulness_score: float
    hallucination_flag: bool
    status: str
    skip_reason: str | None


@dataclass(frozen=True)
class EvalJobView:
    id: int
    retrieval_run_id: str
    status: str
    attempt_count: int
    max_attempts: int
    last_error: str | None
    next_attempt_at: datetime | None


@dataclass(frozen=True)
class EvalDeadLetterView:
    id: int
    job_id: int | None
    task_name: str
    error_message: str
    retry_count: int
    created_at: datetime


@dataclass(frozen=True)
class QuotaView:
    tenant_id: str
    daily_eval_budget_usd: float
    daily_eval_spend_usd: float
    monthly_llm_budget_usd: float
    monthly_llm_spend_usd: float
    eval_sample_pct: int
    force_eval_relevance_threshold: float
    last_eval_reset_at: datetime


class EvaluationService:
    def __init__(
        self,
        engine: Engine | None = None,
        *,
        max_attempts: int | None = None,
        retry_delay_seconds: int | None = None,
    ) -> None:
        self._engine = engine or get_engine()
        self._max_attempts = max_attempts or settings.eval_job_max_attempts
        self._retry_delay_seconds = retry_delay_seconds if retry_delay_seconds is not None else settings.eval_job_retry_delay_seconds

    def enqueue_gateway_evaluation(
        self,
        *,
        tenant_id: str,
        audit_log_id: str,
        retrieval_run_id: str,
        completion: str,
        policy_decision: PolicyDecision,
    ) -> int:
        with Session(self._engine) as session:
            row = EvalJob(
                tenant_id=tenant_id,
                audit_log_id=audit_log_id,
                retrieval_run_id=retrieval_run_id,
                completion_text=completion,
                policy_decision=policy_decision.decision,
                status="PENDING",
                attempt_count=0,
                max_attempts=self._max_attempts,
                last_error=None,
                next_attempt_at=None,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

    def process_pending_jobs(self, *, limit: int = 10) -> list[EvalResultView]:
        processed: list[EvalResultView] = []
        with Session(self._engine) as session:
            rows = (
                session.query(EvalJob)
                .filter(
                    or_(
                        EvalJob.status == "PENDING",
                        (
                            (EvalJob.status == "RETRY")
                            & (
                                (EvalJob.next_attempt_at.is_(None))
                                | (EvalJob.next_attempt_at <= datetime.now(timezone.utc))
                            )
                        ),
                    )
                )
                .order_by(EvalJob.id.asc())
                .limit(limit)
                .all()
            )
            for job in rows:
                result = self._process_job_with_session(session=session, job=job)
                if result is not None:
                    processed.append(result)
            session.commit()
        return processed

    def process_job(self, *, job_id: int) -> EvalResultView | None:
        with Session(self._engine) as session:
            job = session.get(EvalJob, job_id)
            if job is None or not self._job_is_runnable(job):
                return None
            result = self._process_job_with_session(session=session, job=job)
            session.commit()
            return result

    def record_dispatch_failure(self, *, job_id: int, error: str) -> None:
        with Session(self._engine) as session:
            job = session.get(EvalJob, job_id)
            if job is None:
                return
            self._mark_job_retry_with_session(session=session, job=job, error=error)
            session.commit()

    def record_batch_dispatch_failure(self, *, limit: int, error: str) -> None:
        with Session(self._engine) as session:
            rows = (
                session.query(EvalJob)
                .filter(
                    or_(
                        EvalJob.status == "PENDING",
                        (
                            (EvalJob.status == "RETRY")
                            & (
                                (EvalJob.next_attempt_at.is_(None))
                                | (EvalJob.next_attempt_at <= datetime.now(timezone.utc))
                            )
                        ),
                    )
                )
                .order_by(EvalJob.id.asc())
                .limit(limit)
                .all()
            )
            for job in rows:
                self._mark_job_retry_with_session(session=session, job=job, error=error)
            session.commit()

    def evaluate_gateway_response(
        self,
        *,
        tenant_id: str,
        audit_log_id: str,
        retrieval_run_id: str,
        completion: str,
        retrieval_context: tuple[RetrievalResultView, ...],
        policy_decision: PolicyDecision,
    ) -> EvalResultView:
        with Session(self._engine) as session:
            result = self._evaluate_with_session(
                session=session,
                tenant_id=tenant_id,
                audit_log_id=audit_log_id,
                retrieval_run_id=retrieval_run_id,
                completion=completion,
                retrieval_context=retrieval_context,
                policy_decision=policy_decision,
            )
            session.commit()
            return result

    def upsert_quota(
        self,
        *,
        tenant_id: str,
        eval_sample_pct: int | None = None,
        daily_eval_budget_usd: float | None = None,
        daily_eval_spend_usd: float | None = None,
        monthly_llm_budget_usd: float | None = None,
        monthly_llm_spend_usd: float | None = None,
        force_eval_relevance_threshold: float | None = None,
        last_eval_reset_at: str | datetime | None = None,
    ) -> None:
        with Session(self._engine) as session:
            row = self._get_or_create_quota(session=session, tenant_id=tenant_id)
            if eval_sample_pct is not None:
                row.eval_sample_pct = eval_sample_pct
            if daily_eval_budget_usd is not None:
                row.daily_eval_budget_usd = daily_eval_budget_usd
            if daily_eval_spend_usd is not None:
                row.daily_eval_spend_usd = daily_eval_spend_usd
            if monthly_llm_budget_usd is not None:
                row.monthly_llm_budget_usd = monthly_llm_budget_usd
            if monthly_llm_spend_usd is not None:
                row.monthly_llm_spend_usd = monthly_llm_spend_usd
            if force_eval_relevance_threshold is not None:
                row.force_eval_relevance_threshold = force_eval_relevance_threshold
            if last_eval_reset_at is not None:
                row.last_eval_reset_at = self._coerce_now(last_eval_reset_at)
            row.updated_at = datetime.now(timezone.utc)
            session.commit()

    def get_quota(
        self,
        *,
        tenant_id: str,
        now: str | datetime | None = None,
    ) -> QuotaView:
        effective_now = self._coerce_now(now)
        with Session(self._engine) as session:
            row = self._get_or_create_quota(session=session, tenant_id=tenant_id)
            self._reset_daily_budget_if_needed(row=row, now=effective_now)
            session.commit()
            return self._to_quota_view(row)

    def is_monthly_budget_exceeded(
        self,
        *,
        tenant_id: str,
        now: str | datetime | None = None,
    ) -> bool:
        quota = self.get_quota(tenant_id=tenant_id, now=now)
        return quota.monthly_llm_spend_usd >= quota.monthly_llm_budget_usd

    def record_model_spend(
        self,
        *,
        tenant_id: str,
        cost_usd: float,
        now: str | datetime | None = None,
    ) -> None:
        effective_now = self._coerce_now(now)
        with Session(self._engine) as session:
            row = self._get_or_create_quota(session=session, tenant_id=tenant_id)
            self._reset_daily_budget_if_needed(row=row, now=effective_now)
            row.monthly_llm_spend_usd = round(row.monthly_llm_spend_usd + cost_usd, 6)
            row.updated_at = effective_now
            session.commit()

    def list_results(self, *, tenant_id: str) -> list[EvalResultView]:
        with Session(self._engine) as session:
            rows = (
                session.query(EvalResult, AuditLog)
                .join(AuditLog, EvalResult.audit_log_id == AuditLog.id)
                .filter(AuditLog.tenant_id == tenant_id)
                .order_by(EvalResult.id.desc())
                .all()
            )
            return [
                EvalResultView(
                    id=eval_row.id,
                    retrieval_run_id=eval_row.retrieval_run_id,
                    judge_version=eval_row.judge_version,
                    relevance_score=eval_row.relevance_score,
                    faithfulness_score=eval_row.faithfulness_score,
                    hallucination_flag=eval_row.hallucination_flag,
                    status=eval_row.status,
                    skip_reason=eval_row.skip_reason,
                )
                for eval_row, _ in rows
            ]

    def list_jobs(self, *, tenant_id: str) -> list[EvalJobView]:
        with Session(self._engine) as session:
            rows = (
                session.query(EvalJob)
                .filter(EvalJob.tenant_id == tenant_id)
                .order_by(EvalJob.id.desc())
                .all()
            )
            return [
                EvalJobView(
                    id=row.id,
                    retrieval_run_id=row.retrieval_run_id,
                    status=row.status,
                    attempt_count=row.attempt_count,
                    max_attempts=row.max_attempts,
                    last_error=row.last_error,
                    next_attempt_at=row.next_attempt_at,
                )
                for row in rows
            ]

    def list_dead_letters(self, *, tenant_id: str) -> list[EvalDeadLetterView]:
        with Session(self._engine) as session:
            rows = (
                session.query(EvalDeadLetter)
                .join(EvalJob, EvalDeadLetter.job_id == EvalJob.id)
                .filter(EvalJob.tenant_id == tenant_id)
                .order_by(EvalDeadLetter.id.desc())
                .all()
            )
            return [
                EvalDeadLetterView(
                    id=row.id,
                    job_id=row.job_id,
                    task_name=row.task_name,
                    error_message=row.error_message,
                    retry_count=row.retry_count,
                    created_at=row.created_at,
                )
                for row in rows
            ]

    def requeue_job(self, *, job_id: int, tenant_id: str) -> bool:
        with Session(self._engine) as session:
            job = (
                session.query(EvalJob)
                .filter(EvalJob.id == job_id, EvalJob.tenant_id == tenant_id)
                .one_or_none()
            )
            if job is None or job.status != "FAILED":
                return False
            job.status = "PENDING"
            job.attempt_count = 0
            job.last_error = None
            job.next_attempt_at = None
            session.commit()
            return True

    def mark_job_failed(self, *, job_id: int, error: str) -> None:
        with Session(self._engine) as session:
            job = session.get(EvalJob, job_id)
            if job is None:
                return
            job.status = "FAILED"
            job.last_error = error
            job.attempt_count = max(job.attempt_count, job.max_attempts)
            job.next_attempt_at = None
            session.commit()

    def record_dead_letter(
        self,
        *,
        job_id: int | None,
        task_name: str,
        payload: dict[str, object],
        error_message: str,
        retry_count: int,
    ) -> None:
        with Session(self._engine) as session:
            session.add(
                EvalDeadLetter(
                    job_id=job_id,
                    task_name=task_name,
                    payload_json=json.dumps(payload, default=str, separators=(",", ":")),
                    error_message=error_message,
                    retry_count=retry_count,
                )
            )
            session.commit()

    def _evaluate_with_session(
        self,
        *,
        session: Session,
        tenant_id: str,
        audit_log_id: str,
        retrieval_run_id: str,
        completion: str,
        retrieval_context: tuple[RetrievalResultView, ...],
        policy_decision: PolicyDecision,
    ) -> EvalResultView:
        quota = self._get_or_create_quota(session=session, tenant_id=tenant_id)
        self._reset_daily_budget_if_needed(row=quota, now=datetime.now(timezone.utc))
        relevance_score = round((retrieval_context[0].score / 100) if retrieval_context else 0.0, 2)
        force_eval = (
            policy_decision.decision != "allow"
            or relevance_score < quota.force_eval_relevance_threshold
        )
        if not force_eval and quota.daily_eval_spend_usd >= quota.daily_eval_budget_usd:
            return self._persist_result(
                session=session,
                audit_log_id=audit_log_id,
                retrieval_run_id=retrieval_run_id,
                relevance_score=relevance_score,
                faithfulness_score=0.0,
                hallucination_flag=False,
                status="SKIPPED",
                skip_reason="daily_budget_exceeded",
            )
        if not force_eval and quota.eval_sample_pct <= 0:
            return self._persist_result(
                session=session,
                audit_log_id=audit_log_id,
                retrieval_run_id=retrieval_run_id,
                relevance_score=relevance_score,
                faithfulness_score=0.0,
                hallucination_flag=False,
                status="SKIPPED",
                skip_reason="sampled_out",
            )

        faithfulness_score = round(self._faithfulness(completion, retrieval_context), 2)
        hallucination_flag = faithfulness_score < 0.5
        quota.daily_eval_spend_usd = round(quota.daily_eval_spend_usd + 0.01, 2)
        quota.updated_at = datetime.now(timezone.utc)
        return self._persist_result(
            session=session,
            audit_log_id=audit_log_id,
            retrieval_run_id=retrieval_run_id,
            relevance_score=relevance_score,
            faithfulness_score=faithfulness_score,
            hallucination_flag=hallucination_flag,
            status="COMPLETED",
            skip_reason=None,
        )

    def _process_job_with_session(
        self,
        *,
        session: Session,
        job: EvalJob,
    ) -> EvalResultView:
        job.status = "PROCESSING"
        session.flush()
        try:
            result = self._evaluate_with_session(
                session=session,
                tenant_id=job.tenant_id,
                audit_log_id=job.audit_log_id,
                retrieval_run_id=job.retrieval_run_id,
                completion=job.completion_text,
                retrieval_context=self._load_retrieval_context(
                    session=session,
                    retrieval_run_id=job.retrieval_run_id,
                ),
                policy_decision=PolicyDecision(
                    decision=job.policy_decision,
                    rule_ids=[],
                    severity="low",
                    explanations=[],
                    redacted_prompt=None,
                ),
            )
        except Exception as exc:
            self._mark_job_retry_with_session(session=session, job=job, error=str(exc))
            return None
        job.status = result.status
        job.last_error = None
        job.next_attempt_at = None
        return result

    def _mark_job_retry_with_session(
        self,
        *,
        session: Session,
        job: EvalJob,
        error: str,
    ) -> None:
        job.attempt_count += 1
        job.last_error = error
        if job.attempt_count >= job.max_attempts:
            job.status = "FAILED"
            job.next_attempt_at = None
            session.flush()
            return
        delay_seconds = self._retry_delay_seconds * (2 ** max(0, job.attempt_count - 1))
        job.status = "RETRY"
        job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        session.flush()

    def _job_is_runnable(self, job: EvalJob) -> bool:
        if job.status == "PENDING":
            return True
        if job.status != "RETRY":
            return False
        if job.next_attempt_at is None:
            return True
        next_attempt_at = job.next_attempt_at
        if next_attempt_at.tzinfo is None:
            next_attempt_at = next_attempt_at.replace(tzinfo=timezone.utc)
        return next_attempt_at <= datetime.now(timezone.utc)

    def _persist_result(
        self,
        *,
        session: Session,
        audit_log_id: str,
        retrieval_run_id: str,
        relevance_score: float,
        faithfulness_score: float,
        hallucination_flag: bool,
        status: str,
        skip_reason: str | None,
    ) -> EvalResultView:
        row = EvalResult(
            audit_log_id=audit_log_id,
            retrieval_run_id=retrieval_run_id,
            judge_version="heuristic_v1",
            relevance_score=relevance_score,
            faithfulness_score=faithfulness_score,
            hallucination_flag=hallucination_flag,
            status=status,
            skip_reason=skip_reason,
        )
        session.add(row)
        session.flush()
        return EvalResultView(
            id=row.id,
            retrieval_run_id=row.retrieval_run_id,
            judge_version=row.judge_version,
            relevance_score=row.relevance_score,
            faithfulness_score=row.faithfulness_score,
            hallucination_flag=row.hallucination_flag,
            status=row.status,
            skip_reason=row.skip_reason,
        )

    def _faithfulness(
        self,
        completion: str,
        retrieval_context: tuple[RetrievalResultView, ...],
    ) -> float:
        if not retrieval_context:
            return 0.0
        completion_terms = {term for term in completion.lower().replace(":", " ").replace(".", " ").split() if term}
        retrieval_terms: set[str] = set()
        for item in retrieval_context:
            retrieval_terms.update(
                term for term in item.snippet.lower().replace(":", " ").replace(".", " ").split() if term
            )
        if not completion_terms:
            return 0.0
        overlap = len(completion_terms & retrieval_terms)
        return min(1.0, overlap / max(1, len(completion_terms)))

    def _get_or_create_quota(self, *, session: Session, tenant_id: str) -> TenantQuota:
        row = session.get(TenantQuota, tenant_id)
        if row is None:
            row = TenantQuota(tenant_id=tenant_id)
            session.add(row)
            session.flush()
        return row

    def _reset_daily_budget_if_needed(self, *, row: TenantQuota, now: datetime) -> None:
        last_reset = row.last_eval_reset_at
        if last_reset.tzinfo is None:
            last_reset = last_reset.replace(tzinfo=timezone.utc)
        if last_reset.date() >= now.date():
            return
        row.daily_eval_spend_usd = 0.0
        row.last_eval_reset_at = now
        row.updated_at = now

    def _coerce_now(self, value: str | datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return value

    def _to_quota_view(self, row: TenantQuota) -> QuotaView:
        return QuotaView(
            tenant_id=row.tenant_id,
            daily_eval_budget_usd=row.daily_eval_budget_usd,
            daily_eval_spend_usd=row.daily_eval_spend_usd,
            monthly_llm_budget_usd=row.monthly_llm_budget_usd,
            monthly_llm_spend_usd=row.monthly_llm_spend_usd,
            eval_sample_pct=row.eval_sample_pct,
            force_eval_relevance_threshold=row.force_eval_relevance_threshold,
            last_eval_reset_at=row.last_eval_reset_at,
        )

    def _load_retrieval_context(
        self,
        *,
        session: Session,
        retrieval_run_id: str,
    ) -> tuple[RetrievalResultView, ...]:
        rows = (
            session.query(RetrievalResult)
            .filter(RetrievalResult.retrieval_run_id == retrieval_run_id)
            .order_by(RetrievalResult.rank.asc())
            .all()
        )
        return tuple(
            RetrievalResultView(
                document_id=row.document_id,
                rank=row.rank,
                score=row.score,
                snippet=row.snippet,
            )
            for row in rows
        )


@lru_cache(maxsize=1)
def _build_evaluation_service() -> EvaluationService:
    return EvaluationService()


async def get_evaluation_service() -> EvaluationService:
    return _build_evaluation_service()
