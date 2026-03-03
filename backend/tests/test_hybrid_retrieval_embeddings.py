from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.db import DocumentChunk
from core.documents import DocumentService
from core.retrieval import RetrievalService


def test_chunk_embeddings_persist_and_hybrid_ranking_prefers_content_match() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    documents = DocumentService(engine=engine)
    retrieval = RetrievalService(engine=engine)

    strong = documents.create_document(
        tenant_id="tenant-a",
        filename="operations-notes.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
        content_text="service account encryption policy for billing exports and audit review",
    )
    weak = documents.create_document(
        tenant_id="tenant-a",
        filename="encryption-overview.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
        content_text="team retrospective and roadmap planning notes",
    )

    with Session(engine) as session:
        chunks = (
            session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == strong.id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )

    assert chunks
    assert all(chunk.token_count > 0 for chunk in chunks)
    assert all(chunk.embedding_json for chunk in chunks)
    assert any("policy" in chunk.keyword_signature for chunk in chunks)

    run = retrieval.retrieve(
        tenant_id="tenant-a",
        app_id="console",
        query="service account encryption policy",
    )

    assert [item.document_id for item in run.results] == [strong.id, weak.id]
    assert run.results[0].score > run.results[1].score
