from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from core.db import Document, RetrievalResult, RetrievalRun, bootstrap_schema
from core.retrieval import RetrievalService


def _retrieval_service() -> tuple[RetrievalService, object]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    return RetrievalService(engine=engine), engine


def test_retrieval_run_and_results_are_persisted_for_active_documents() -> None:
    service, engine = _retrieval_service()

    active = service.create_document(
        tenant_id="tenant-a",
        filename="guide.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
    )
    service.create_document(
        tenant_id="tenant-a",
        filename="bad.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="QUARANTINED",
    )

    run = service.retrieve(
        tenant_id="tenant-a",
        app_id="console",
        query="show me the guide",
    )

    with Session(engine) as session:
        retrieval_runs = session.execute(select(RetrievalRun)).scalars().all()
        retrieval_results = session.execute(select(RetrievalResult)).scalars().all()
        documents = session.execute(select(Document)).scalars().all()

    assert run.id == retrieval_runs[0].id
    assert len(retrieval_runs) == 1
    assert len(retrieval_results) == 1
    assert retrieval_results[0].document_id == active.id
    assert len(documents) == 2
