from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from core.db import Base, ProviderConfig, seed_provider_configs


def test_provider_configs_table_can_be_created_and_seeded() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    Base.metadata.create_all(engine)
    seed_provider_configs(engine)

    tables = set(inspect(engine).get_table_names())
    assert "provider_configs" in tables


def test_seed_provider_configs_upgrades_legacy_gpt_4o_mini_defaults() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            ProviderConfig(
                provider="azure_openai",
                model="gpt-4o-mini",
                priority=1,
                timeout_ms=12000,
                enabled=True,
            )
        )
        session.add(
            ProviderConfig(
                provider="openai",
                model="gpt-4o-mini",
                priority=3,
                timeout_ms=12000,
                enabled=True,
            )
        )
        session.commit()

    seed_provider_configs(engine)

    with Session(engine) as session:
        rows = session.execute(
            select(ProviderConfig).where(ProviderConfig.provider.in_(("azure_openai", "openai")))
        ).scalars().all()

    assert {row.model for row in rows} == {"gpt-4.1-mini"}
