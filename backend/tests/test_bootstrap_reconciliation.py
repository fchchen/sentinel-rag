from sqlalchemy import create_engine, inspect

from core.bootstrap import bootstrap_persistence


def test_bootstrap_reconciles_new_columns_on_existing_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE document_chunks (
                id INTEGER PRIMARY KEY,
                document_id VARCHAR(36) NOT NULL,
                chunk_index INTEGER NOT NULL,
                content_text TEXT NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE eval_results (
                id INTEGER PRIMARY KEY,
                audit_log_id VARCHAR(36) NOT NULL,
                retrieval_run_id VARCHAR(36) NOT NULL,
                judge_version VARCHAR(64) NOT NULL,
                relevance_score FLOAT NOT NULL,
                faithfulness_score FLOAT NOT NULL,
                hallucination_flag BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE eval_jobs (
                id INTEGER PRIMARY KEY,
                tenant_id VARCHAR(36) NOT NULL,
                audit_log_id VARCHAR(36) NOT NULL,
                retrieval_run_id VARCHAR(36) NOT NULL,
                completion_text TEXT NOT NULL,
                policy_decision VARCHAR(32) NOT NULL,
                status VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE tenant_quotas (
                tenant_id VARCHAR(36) PRIMARY KEY,
                daily_eval_budget_usd FLOAT NOT NULL,
                daily_eval_spend_usd FLOAT NOT NULL,
                eval_sample_pct INTEGER NOT NULL,
                force_eval_relevance_threshold FLOAT NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )

    bootstrap_persistence(engine=engine)

    inspector = inspect(engine)
    document_chunk_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
    eval_job_columns = {column["name"] for column in inspector.get_columns("eval_jobs")}
    eval_result_columns = {column["name"] for column in inspector.get_columns("eval_results")}
    quota_columns = {column["name"] for column in inspector.get_columns("tenant_quotas")}

    assert {"token_count", "keyword_signature", "embedding_json"} <= document_chunk_columns
    assert {"attempt_count", "max_attempts", "last_error", "next_attempt_at"} <= eval_job_columns
    assert {"status", "skip_reason"} <= eval_result_columns
    assert {"monthly_llm_budget_usd", "monthly_llm_spend_usd", "last_eval_reset_at"} <= quota_columns
