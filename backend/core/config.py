from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    postgres_dsn: str = "postgresql+psycopg://sentinel:localdev@localhost:5433/sentinel_rag"
    redis_url: str = "redis://localhost:6380/0"
    celery_broker_url: str = "redis://localhost:6380/0"
    celery_result_backend: str = "redis://localhost:6380/1"
    celery_task_always_eager: bool = False
    celery_task_max_retries: int = 2
    auth_verifier_mode: str = "local"
    entra_tenant_id: str = "local-tenant"
    entra_audience: str = "sentinel-rag-api"
    entra_jwt_issuer: str = "https://login.microsoftonline.com/local-tenant/v2.0"
    entra_jwt_signing_key: str | None = None
    entra_jwt_algorithm: str = "HS256"
    gateway_default_timeout_ms: int = 12000
    gateway_failure_cooldown_seconds: int = 30
    gateway_rate_limit_cooldown_seconds: int = 120
    malware_scanner_mode: str = "clamav"
    malware_scanner_host: str = "localhost"
    malware_scanner_port: int = 3310
    eval_sample_pct: int = 10
    eval_daily_budget_usd: float = 10.0
    tenant_monthly_budget_usd: float = 250.0
    eval_job_max_attempts: int = 3
    eval_job_retry_delay_seconds: int = 10
    bootstrap_schema_on_startup: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
