from collections.abc import Iterator
from contextlib import suppress
from logging import getLogger
from typing import Any

from sqlalchemy.engine import Engine

from core.db import bootstrap_schema

logger = getLogger(__name__)


def bootstrap_persistence(engine: Engine | None = None) -> None:
    bootstrap_schema(engine=engine)


async def bootstrap_persistence_safely() -> None:
    with suppress(Exception):
        bootstrap_persistence()
    logger.debug("Persistence bootstrap attempted.")


def iter_bootstrap_steps() -> Iterator[str]:
    yield "init_schema"
    yield "seed_provider_configs"
