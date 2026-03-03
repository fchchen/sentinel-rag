from sqlalchemy import create_engine, inspect

from core.db import Base, seed_provider_configs


def test_provider_configs_table_can_be_created_and_seeded() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    Base.metadata.create_all(engine)
    seed_provider_configs(engine)

    tables = set(inspect(engine).get_table_names())
    assert "provider_configs" in tables
