from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from core.db import DocumentChunk, bootstrap_schema
from core.documents import DocumentService
from core.retrieval import RetrievalService


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bootstrap_schema(engine=engine)
    return engine


def test_document_content_is_chunked_on_create() -> None:
    engine = _engine()
    service = DocumentService(engine=engine)

    document = service.create_document(
        tenant_id="tenant-a",
        filename="billing-guide.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        content_text="billing invoice reconciliation procedure and escalation matrix",
    )

    with Session(engine) as session:
        chunks = session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == document.id).order_by(DocumentChunk.chunk_index)
        ).scalars().all()

    assert len(chunks) >= 2
    assert chunks[0].content_text


def test_retrieval_prefers_chunk_content_matches_over_filename_only() -> None:
    engine = _engine()
    document_service = DocumentService(engine=engine)
    retrieval_service = RetrievalService(engine=engine)

    strong = document_service.create_document(
        tenant_id="tenant-a",
        filename="general.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
        content_text="billing invoice reconciliation runbook",
    )
    weak = document_service.create_document(
        tenant_id="tenant-a",
        filename="billing-overview.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
        content_text="general company handbook and policy overview",
    )

    run = retrieval_service.retrieve(
        tenant_id="tenant-a",
        app_id="console",
        query="billing invoice",
    )

    assert [item.document_id for item in run.results] == [strong.id, weak.id]
