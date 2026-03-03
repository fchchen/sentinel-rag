"""create baseline tables

Revision ID: 0001_create_provider_configs
Revises:
Create Date: 2026-03-03 17:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_create_provider_configs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_configs",
        sa.Column("provider", sa.String(length=64), primary_key=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("redacted_prompt", sa.Text(), nullable=False),
        sa.Column("response_redacted", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("policy_decision", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_app_id", "audit_logs", ["app_id"])
    op.create_index("ix_audit_logs_trace_id", "audit_logs", ["trace_id"])
    op.create_table(
        "policy_violations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("audit_log_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_log_id"], ["audit_logs.id"]),
    )
    op.create_index("ix_policy_violations_audit_log_id", "policy_violations", ["audit_log_id"])
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("keyword_signature", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_table(
        "retrieval_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_retrieval_runs_tenant_id", "retrieval_runs", ["tenant_id"])
    op.create_index("ix_retrieval_runs_app_id", "retrieval_runs", ["app_id"])
    op.create_table(
        "retrieval_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("retrieval_run_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["retrieval_run_id"], ["retrieval_runs.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
    )
    op.create_index("ix_retrieval_results_retrieval_run_id", "retrieval_results", ["retrieval_run_id"])
    op.create_index("ix_retrieval_results_document_id", "retrieval_results", ["document_id"])
    op.create_table(
        "model_invocations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("audit_log_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_log_id"], ["audit_logs.id"]),
    )
    op.create_index("ix_model_invocations_audit_log_id", "model_invocations", ["audit_log_id"])
    op.create_table(
        "eval_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("audit_log_id", sa.String(length=36), nullable=False),
        sa.Column("retrieval_run_id", sa.String(length=36), nullable=False),
        sa.Column("judge_version", sa.String(length=64), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("faithfulness_score", sa.Float(), nullable=False),
        sa.Column("hallucination_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("skip_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_log_id"], ["audit_logs.id"]),
        sa.ForeignKeyConstraint(["retrieval_run_id"], ["retrieval_runs.id"]),
    )
    op.create_index("ix_eval_results_audit_log_id", "eval_results", ["audit_log_id"])
    op.create_index("ix_eval_results_retrieval_run_id", "eval_results", ["retrieval_run_id"])
    op.create_table(
        "eval_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("audit_log_id", sa.String(length=36), nullable=False),
        sa.Column("retrieval_run_id", sa.String(length=36), nullable=False),
        sa.Column("completion_text", sa.Text(), nullable=False),
        sa.Column("policy_decision", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_log_id"], ["audit_logs.id"]),
        sa.ForeignKeyConstraint(["retrieval_run_id"], ["retrieval_runs.id"]),
    )
    op.create_index("ix_eval_jobs_tenant_id", "eval_jobs", ["tenant_id"])
    op.create_index("ix_eval_jobs_audit_log_id", "eval_jobs", ["audit_log_id"])
    op.create_index("ix_eval_jobs_retrieval_run_id", "eval_jobs", ["retrieval_run_id"])
    op.create_table(
        "eval_dead_letters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("task_name", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["eval_jobs.id"]),
    )
    op.create_index("ix_eval_dead_letters_job_id", "eval_dead_letters", ["job_id"])
    op.create_table(
        "tenant_quotas",
        sa.Column("tenant_id", sa.String(length=36), primary_key=True),
        sa.Column("daily_eval_budget_usd", sa.Float(), nullable=False),
        sa.Column("daily_eval_spend_usd", sa.Float(), nullable=False),
        sa.Column("monthly_llm_budget_usd", sa.Float(), nullable=False),
        sa.Column("monthly_llm_spend_usd", sa.Float(), nullable=False),
        sa.Column("eval_sample_pct", sa.Integer(), nullable=False),
        sa.Column("force_eval_relevance_threshold", sa.Float(), nullable=False),
        sa.Column("last_eval_reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tenant_quotas")
    op.drop_index("ix_eval_dead_letters_job_id", table_name="eval_dead_letters")
    op.drop_table("eval_dead_letters")
    op.drop_index("ix_eval_jobs_retrieval_run_id", table_name="eval_jobs")
    op.drop_index("ix_eval_jobs_audit_log_id", table_name="eval_jobs")
    op.drop_index("ix_eval_jobs_tenant_id", table_name="eval_jobs")
    op.drop_table("eval_jobs")
    op.drop_index("ix_eval_results_retrieval_run_id", table_name="eval_results")
    op.drop_index("ix_eval_results_audit_log_id", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index("ix_model_invocations_audit_log_id", table_name="model_invocations")
    op.drop_table("model_invocations")
    op.drop_index("ix_retrieval_results_document_id", table_name="retrieval_results")
    op.drop_index("ix_retrieval_results_retrieval_run_id", table_name="retrieval_results")
    op.drop_table("retrieval_results")
    op.drop_index("ix_retrieval_runs_app_id", table_name="retrieval_runs")
    op.drop_index("ix_retrieval_runs_tenant_id", table_name="retrieval_runs")
    op.drop_table("retrieval_runs")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_tenant_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_policy_violations_audit_log_id", table_name="policy_violations")
    op.drop_table("policy_violations")
    op.drop_index("ix_audit_logs_trace_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_app_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("provider_configs")
