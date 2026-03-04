from pathlib import Path
import sys

from fastapi import Depends
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.audit import AuditService, get_audit_service
from core.config import settings
from core.db import bootstrap_schema
from core.documents import DocumentService, _build_document_service, get_document_service
from core.eval_worker import InlineEvalWorker, _build_eval_worker, get_eval_worker
from core.evaluation import EvaluationService, _build_evaluation_service, get_evaluation_service
from core.gateway import _build_gateway_service, _build_provider_client
from core.retrieval import RetrievalService, _build_retrieval_service, get_retrieval_service
from main import app


@pytest.fixture(autouse=True)
def disable_startup_bootstrap() -> None:
    original = settings.bootstrap_schema_on_startup
    original_eager = settings.celery_task_always_eager
    original_provider_mode = settings.gateway_provider_mode
    settings.bootstrap_schema_on_startup = False
    settings.celery_task_always_eager = True
    settings.gateway_provider_mode = "stub"
    try:
        yield
    finally:
        settings.bootstrap_schema_on_startup = original
        settings.celery_task_always_eager = original_eager
        settings.gateway_provider_mode = original_provider_mode


@pytest.fixture(autouse=True)
def use_in_memory_audit_service() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    service = AuditService(engine=engine)

    async def override_audit_service() -> AuditService:
        return service

    app.dependency_overrides[get_audit_service] = override_audit_service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_audit_service, None)


@pytest.fixture(autouse=True)
def use_in_memory_document_service() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    service = DocumentService(engine=engine)

    async def override_document_service() -> DocumentService:
        return service

    app.dependency_overrides[get_document_service] = override_document_service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_document_service, None)


@pytest.fixture(autouse=True)
def use_in_memory_retrieval_service() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    service = RetrievalService(engine=engine)

    async def override_retrieval_service() -> RetrievalService:
        return service

    app.dependency_overrides[get_retrieval_service] = override_retrieval_service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_retrieval_service, None)


@pytest.fixture(autouse=True)
def use_in_memory_evaluation_service() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    service = EvaluationService(engine=engine)

    async def override_evaluation_service() -> EvaluationService:
        return service

    async def override_eval_worker(
        evaluation_service: EvaluationService = Depends(get_evaluation_service),
    ) -> InlineEvalWorker:
        return InlineEvalWorker(evaluation_service)

    app.dependency_overrides[get_evaluation_service] = override_evaluation_service
    app.dependency_overrides[get_eval_worker] = override_eval_worker
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_evaluation_service, None)
        app.dependency_overrides.pop(get_eval_worker, None)


@pytest.fixture(autouse=True)
def clear_cached_services() -> None:
    _build_provider_client.cache_clear()
    _build_gateway_service.cache_clear()
    _build_document_service.cache_clear()
    _build_retrieval_service.cache_clear()
    _build_evaluation_service.cache_clear()
    _build_eval_worker.cache_clear()
    try:
        yield
    finally:
        _build_provider_client.cache_clear()
        _build_gateway_service.cache_clear()
        _build_document_service.cache_clear()
        _build_retrieval_service.cache_clear()
        _build_evaluation_service.cache_clear()
        _build_eval_worker.cache_clear()
