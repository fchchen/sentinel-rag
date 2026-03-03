from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.v1.routes.audit import router as audit_router
from api.v1.routes.auth import router as auth_router
from api.v1.routes.documents import router as documents_router
from api.v1.routes.evals import router as evals_router
from api.v1.routes.gateway import router as gateway_router
from api.v1.routes.health import router as health_router
from api.v1.routes.metrics import router as metrics_router
from api.v1.routes.policy import router as policy_router
from api.v1.routes.retrieval import router as retrieval_router
from core.bootstrap import bootstrap_persistence_safely
from core.config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.bootstrap_schema_on_startup:
        await bootstrap_persistence_safely()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="sentinel-rag",
        version="0.1.0",
        description="Enterprise RAG governance gateway scaffold.",
        lifespan=lifespan,
    )
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(evals_router, prefix="/api/v1")
    app.include_router(metrics_router, prefix="/api/v1")
    app.include_router(policy_router, prefix="/api/v1")
    app.include_router(retrieval_router, prefix="/api/v1")
    app.include_router(gateway_router, prefix="/api/v1/gateway")
    return app


app = create_app()
