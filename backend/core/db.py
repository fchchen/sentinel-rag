from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from core.config import settings


class Base(DeclarativeBase):
    pass


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    app_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    redacted_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class PolicyViolation(Base):
    __tablename__ = "policy_violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_log_id: Mapped[str] = mapped_column(ForeignKey("audit_logs.id"), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    keyword_signature: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    app_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class RetrievalResult(Base):
    __tablename__ = "retrieval_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    retrieval_run_id: Mapped[str] = mapped_column(ForeignKey("retrieval_runs.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)


class ModelInvocation(Base):
    __tablename__ = "model_invocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_log_id: Mapped[str] = mapped_column(ForeignKey("audit_logs.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_log_id: Mapped[str] = mapped_column(ForeignKey("audit_logs.id"), nullable=False, index=True)
    retrieval_run_id: Mapped[str] = mapped_column(ForeignKey("retrieval_runs.id"), nullable=False, index=True)
    judge_version: Mapped[str] = mapped_column(String(64), nullable=False)
    relevance_score: Mapped[float] = mapped_column(nullable=False)
    faithfulness_score: Mapped[float] = mapped_column(nullable=False)
    hallucination_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="COMPLETED")
    skip_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class EvalJob(Base):
    __tablename__ = "eval_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    audit_log_id: Mapped[str] = mapped_column(ForeignKey("audit_logs.id"), nullable=False, index=True)
    retrieval_run_id: Mapped[str] = mapped_column(ForeignKey("retrieval_runs.id"), nullable=False, index=True)
    completion_text: Mapped[str] = mapped_column(Text, nullable=False)
    policy_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class EvalDeadLetter(Base):
    __tablename__ = "eval_dead_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("eval_jobs.id"), nullable=True, index=True)
    task_name: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class TenantQuota(Base):
    __tablename__ = "tenant_quotas"

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    daily_eval_budget_usd: Mapped[float] = mapped_column(nullable=False, default=10.0)
    daily_eval_spend_usd: Mapped[float] = mapped_column(nullable=False, default=0.0)
    monthly_llm_budget_usd: Mapped[float] = mapped_column(nullable=False, default=250.0)
    monthly_llm_spend_usd: Mapped[float] = mapped_column(nullable=False, default=0.0)
    eval_sample_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    force_eval_relevance_threshold: Mapped[float] = mapped_column(nullable=False, default=0.4)
    last_eval_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


@dataclass(frozen=True)
class ProviderDefinition:
    provider: str
    model: str
    priority: int
    timeout_ms: int
    enabled: bool = True


DEFAULT_PROVIDER_CONFIGS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        provider="azure_openai",
        model="gpt-4o-mini",
        priority=1,
        timeout_ms=settings.gateway_default_timeout_ms,
    ),
    ProviderDefinition(
        provider="anthropic",
        model="claude-3-5-sonnet",
        priority=2,
        timeout_ms=15000,
    ),
    ProviderDefinition(
        provider="openai",
        model="gpt-4o-mini",
        priority=3,
        timeout_ms=settings.gateway_default_timeout_ms,
    ),
)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(settings.postgres_dsn)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def init_schema(engine: Engine | None = None) -> None:
    active_engine = engine or get_engine()
    Base.metadata.create_all(active_engine)
    reconcile_schema(engine=active_engine)


def reconcile_schema(engine: Engine | None = None) -> None:
    active_engine = engine or get_engine()
    inspector = inspect(active_engine)
    table_names = set(inspector.get_table_names())
    statements: list[str] = []

    if "document_chunks" in table_names:
        existing_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
        if "token_count" not in existing_columns:
            statements.append(
                "ALTER TABLE document_chunks ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0"
            )
        if "keyword_signature" not in existing_columns:
            statements.append(
                "ALTER TABLE document_chunks ADD COLUMN keyword_signature TEXT NOT NULL DEFAULT ''"
            )
        if "embedding_json" not in existing_columns:
            statements.append(
                "ALTER TABLE document_chunks ADD COLUMN embedding_json TEXT NOT NULL DEFAULT '[]'"
            )

    if "eval_results" in table_names:
        existing_columns = {column["name"] for column in inspector.get_columns("eval_results")}
        if "status" not in existing_columns:
            statements.append(
                "ALTER TABLE eval_results ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'COMPLETED'"
            )
        if "skip_reason" not in existing_columns:
            statements.append(
                "ALTER TABLE eval_results ADD COLUMN skip_reason VARCHAR(64)"
            )

    if "eval_jobs" in table_names:
        existing_columns = {column["name"] for column in inspector.get_columns("eval_jobs")}
        if "attempt_count" not in existing_columns:
            statements.append(
                "ALTER TABLE eval_jobs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
            )
        if "max_attempts" not in existing_columns:
            statements.append(
                "ALTER TABLE eval_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3"
            )
        if "last_error" not in existing_columns:
            statements.append(
                "ALTER TABLE eval_jobs ADD COLUMN last_error TEXT"
            )
        if "next_attempt_at" not in existing_columns:
            statements.append(
                "ALTER TABLE eval_jobs ADD COLUMN next_attempt_at TIMESTAMP"
            )

    if "tenant_quotas" in table_names:
        existing_columns = {column["name"] for column in inspector.get_columns("tenant_quotas")}
        if "monthly_llm_budget_usd" not in existing_columns:
            statements.append(
                "ALTER TABLE tenant_quotas ADD COLUMN monthly_llm_budget_usd FLOAT NOT NULL DEFAULT 250.0"
            )
        if "monthly_llm_spend_usd" not in existing_columns:
            statements.append(
                "ALTER TABLE tenant_quotas ADD COLUMN monthly_llm_spend_usd FLOAT NOT NULL DEFAULT 0.0"
            )
        if "last_eval_reset_at" not in existing_columns:
            statements.append(
                "ALTER TABLE tenant_quotas ADD COLUMN last_eval_reset_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )

    if not statements:
        return

    with active_engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def bootstrap_schema(engine: Engine | None = None) -> None:
    init_schema(engine=engine)
    seed_provider_configs(engine=engine)


def seed_provider_configs(engine: Engine | None = None) -> None:
    active_engine = engine or get_engine()
    with Session(active_engine) as session:
        existing = {
            config.provider
            for config in session.execute(select(ProviderConfig)).scalars().all()
        }
        for definition in DEFAULT_PROVIDER_CONFIGS:
            if definition.provider in existing:
                continue
            session.add(
                ProviderConfig(
                    provider=definition.provider,
                    model=definition.model,
                    priority=definition.priority,
                    timeout_ms=definition.timeout_ms,
                    enabled=definition.enabled,
                )
            )
        session.commit()


def load_provider_configs(engine: Engine | None = None) -> Sequence[ProviderDefinition]:
    active_engine = engine or get_engine()
    try:
        with Session(active_engine) as session:
            rows = session.execute(
                select(ProviderConfig).where(ProviderConfig.enabled.is_(True)).order_by(ProviderConfig.priority)
            ).scalars().all()
    except Exception:
        return DEFAULT_PROVIDER_CONFIGS

    if not rows:
        return DEFAULT_PROVIDER_CONFIGS

    return tuple(
        ProviderDefinition(
            provider=row.provider,
            model=row.model,
            priority=row.priority,
            timeout_ms=row.timeout_ms,
            enabled=row.enabled,
        )
        for row in rows
    )
