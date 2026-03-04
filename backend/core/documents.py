from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.orm import Session

from core.db import Document, DocumentChunk, bootstrap_schema, get_engine, sync_pgvector_chunk_features
from core.embeddings import build_chunks


@dataclass(frozen=True)
class DocumentView:
    id: str
    tenant_id: str
    filename: str
    mime_type: str
    size_bytes: int
    status: str


class DocumentService:
    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or get_engine()
        bootstrap_schema(engine=self._engine)

    def create_document(
        self,
        *,
        tenant_id: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        status: str = "PENDING",
        content_text: str | None = None,
    ) -> DocumentView:
        with Session(self._engine) as session:
            document = Document(
                tenant_id=tenant_id,
                filename=filename,
                mime_type=mime_type,
                size_bytes=size_bytes,
                status=status,
            )
            session.add(document)
            session.flush()
            for chunk in build_chunks(content_text or ""):
                session.add(
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=chunk.chunk_index,
                        content_text=chunk.content_text,
                        token_count=chunk.token_count,
                        keyword_signature=chunk.keyword_signature,
                        embedding_json=chunk.embedding_json,
                    )
                )
            session.commit()
            sync_pgvector_chunk_features(engine=self._engine, document_id=document.id)
            session.refresh(document)
            return self._to_view(document)

    def list_documents(self, *, tenant_id: str) -> list[DocumentView]:
        with Session(self._engine) as session:
            rows = (
                session.query(Document)
                .filter(Document.tenant_id == tenant_id)
                .order_by(Document.created_at.desc())
                .all()
            )
            return [self._to_view(row) for row in rows]

    def delete_document(self, *, tenant_id: str, document_id: str) -> bool:
        with Session(self._engine) as session:
            row = (
                session.query(Document)
                .filter(Document.id == document_id, Document.tenant_id == tenant_id)
                .one_or_none()
            )
            if row is None:
                return True
            session.delete(row)
            session.commit()
            return True

    def apply_scan_result(self, *, tenant_id: str, document_id: str, result: str) -> DocumentView:
        status_map = {
            "clean": "ACTIVE",
            "timeout": "SCAN_FAILED",
            "failed": "SCAN_FAILED",
            "unknown": "SCAN_UNKNOWN",
            "malware": "QUARANTINED",
        }
        if result not in status_map:
            raise ValueError("Unsupported scan result")

        with Session(self._engine) as session:
            row = (
                session.query(Document)
                .filter(Document.id == document_id, Document.tenant_id == tenant_id)
                .one_or_none()
            )
            if row is None:
                raise NoResultFound("Document not found")
            row.status = status_map[result]
            session.commit()
            session.refresh(row)
            return self._to_view(row)

    def _to_view(self, document: Document) -> DocumentView:
        return DocumentView(
            id=document.id,
            tenant_id=document.tenant_id,
            filename=document.filename,
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            status=document.status,
        )


@lru_cache(maxsize=1)
def _build_document_service() -> DocumentService:
    return DocumentService()


async def get_document_service() -> DocumentService:
    return _build_document_service()
