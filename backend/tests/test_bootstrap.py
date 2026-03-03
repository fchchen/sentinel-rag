from sqlalchemy import create_engine, inspect

from core.bootstrap import bootstrap_persistence


def test_bootstrap_persistence_initializes_schema_and_seeds_provider_configs() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    bootstrap_persistence(engine=engine)

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert {
        "provider_configs",
        "audit_logs",
        "policy_violations",
        "documents",
        "document_chunks",
        "eval_dead_letters",
        "eval_jobs",
        "eval_results",
        "tenant_quotas",
        "retrieval_runs",
        "retrieval_results",
        "model_invocations",
    } <= table_names
    rows = inspector.get_columns("provider_configs")
    assert {row["name"] for row in rows} >= {"provider", "model", "priority", "timeout_ms", "enabled"}
