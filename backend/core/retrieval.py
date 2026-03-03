from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from core.db import Document, DocumentChunk, RetrievalResult, RetrievalRun, bootstrap_schema, get_engine
from core.embeddings import build_chunks, cosine_similarity, deserialize_embedding, embed_text, normalize_terms


@dataclass(frozen=True)
class RetrievalResultView:
    document_id: str
    rank: int
    score: int
    snippet: str


@dataclass(frozen=True)
class RetrievalRunView:
    id: str
    tenant_id: str
    app_id: str
    query_text: str
    results: tuple[RetrievalResultView, ...]


@dataclass(frozen=True)
class RetrievalRunSummaryView:
    id: str
    app_id: str
    query_text: str
    result_count: int


class RetrievalService:
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
        status: str,
        content_text: str | None = None,
    ) -> Document:
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
            session.refresh(document)
            return document

    def retrieve(self, *, tenant_id: str, app_id: str, query: str) -> RetrievalRunView:
        with Session(self._engine) as session:
            run = RetrievalRun(
                tenant_id=tenant_id,
                app_id=app_id,
                query_text=query,
            )
            session.add(run)
            session.flush()

            documents = (
                session.query(Document)
                .filter(Document.tenant_id == tenant_id, Document.status == "ACTIVE")
                .all()
            )
            chunk_map = self._load_chunks(session=session, documents=documents)
            ranked_documents = sorted(
                documents,
                key=lambda document: (-self._score_document(document, query, chunk_map.get(document.id, [])), document.created_at),
            )
            result_views: list[RetrievalResultView] = []
            for index, document in enumerate(ranked_documents, start=1):
                chunks = chunk_map.get(document.id, [])
                score = self._score_document(document, query, chunks)
                snippet = self._build_snippet(document=document, query=query, chunks=chunks)
                session.add(
                    RetrievalResult(
                        retrieval_run_id=run.id,
                        document_id=document.id,
                        rank=index,
                        score=score,
                        snippet=snippet,
                    )
                )
                result_views.append(
                    RetrievalResultView(
                        document_id=document.id,
                        rank=index,
                        score=score,
                        snippet=snippet,
                    )
                )

            session.commit()
            return RetrievalRunView(
                id=run.id,
                tenant_id=run.tenant_id,
                app_id=run.app_id,
                query_text=run.query_text,
                results=tuple(result_views),
            )

    def list_runs(self, *, tenant_id: str) -> list[RetrievalRunSummaryView]:
        with Session(self._engine) as session:
            runs = (
                session.query(RetrievalRun)
                .filter(RetrievalRun.tenant_id == tenant_id)
                .order_by(RetrievalRun.created_at.desc())
                .all()
            )
            summaries: list[RetrievalRunSummaryView] = []
            for run in runs:
                result_count = (
                    session.query(RetrievalResult)
                    .filter(RetrievalResult.retrieval_run_id == run.id)
                    .count()
                )
                summaries.append(
                    RetrievalRunSummaryView(
                        id=run.id,
                        app_id=run.app_id,
                        query_text=run.query_text,
                        result_count=result_count,
                    )
                )
            return summaries

    def _load_chunks(self, *, session: Session, documents: list[Document]) -> dict[str, list[DocumentChunk]]:
        if not documents:
            return {}
        document_ids = [document.id for document in documents]
        rows = (
            session.query(DocumentChunk)
            .filter(DocumentChunk.document_id.in_(document_ids))
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )
        chunk_map: dict[str, list[DocumentChunk]] = {document.id: [] for document in documents}
        for row in rows:
            chunk_map.setdefault(row.document_id, []).append(row)
        return chunk_map

    def _score_document(self, document: Document, query: str, chunks: list[DocumentChunk]) -> int:
        query_terms = set(normalize_terms(query))
        if not query_terms:
            return 1

        query_embedding = embed_text(query)
        best_chunk_score = 0.0
        for chunk in chunks:
            chunk_terms = set(chunk.keyword_signature.split())
            keyword_ratio = len(query_terms & chunk_terms) / max(1, len(query_terms))
            vector_ratio = cosine_similarity(query_embedding, deserialize_embedding(chunk.embedding_json))
            chunk_score = (vector_ratio * 0.7) + (keyword_ratio * 0.3)
            best_chunk_score = max(best_chunk_score, chunk_score)

        filename_terms = set(normalize_terms(document.filename))
        filename_ratio = len(query_terms & filename_terms) / max(1, len(query_terms))
        partial_ratio = min(
            1.0,
            sum(1 for term in query_terms if term in document.filename.lower()) / max(1, len(query_terms)),
        )
        hybrid_score = min(1.0, (best_chunk_score * 0.8) + (filename_ratio * 0.15) + (partial_ratio * 0.05))
        return max(1, min(100, round(hybrid_score * 100)))

    def _build_snippet(self, *, document: Document, query: str, chunks: list[DocumentChunk]) -> str:
        query_terms = set(normalize_terms(query))
        query_embedding = embed_text(query)
        if chunks:
            ranked_chunks = sorted(
                chunks,
                key=lambda chunk: self._score_chunk(chunk=chunk, query_terms=query_terms, query_embedding=query_embedding),
                reverse=True,
            )
            if ranked_chunks[0].content_text:
                return ranked_chunks[0].content_text
        return f"{document.filename} matched query: {query}"

    def _score_chunk(
        self,
        *,
        chunk: DocumentChunk,
        query_terms: set[str],
        query_embedding: tuple[float, ...],
    ) -> float:
        chunk_terms = set(chunk.keyword_signature.split())
        keyword_ratio = len(query_terms & chunk_terms) / max(1, len(query_terms))
        vector_ratio = cosine_similarity(query_embedding, deserialize_embedding(chunk.embedding_json))
        return (vector_ratio * 0.7) + (keyword_ratio * 0.3)


@lru_cache(maxsize=1)
def _build_retrieval_service() -> RetrievalService:
    return RetrievalService()


async def get_retrieval_service() -> RetrievalService:
    return _build_retrieval_service()
