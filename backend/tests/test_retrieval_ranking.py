from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from core.retrieval import RetrievalService


def test_retrieval_reranks_results_by_keyword_match_strength() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    service = RetrievalService(engine=engine)
    weak = service.create_document(
        tenant_id="tenant-a",
        filename="general-guide.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
    )
    strong = service.create_document(
        tenant_id="tenant-a",
        filename="billing-invoice-runbook.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
        status="ACTIVE",
    )

    run = service.retrieve(
        tenant_id="tenant-a",
        app_id="console",
        query="billing invoice",
    )

    assert [item.document_id for item in run.results] == [strong.id, weak.id]
    assert run.results[0].score > run.results[1].score
