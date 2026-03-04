from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from core.db import (
    Document,
    DocumentChunk,
    RetrievalResult,
    RetrievalRun,
    bootstrap_schema,
    get_engine,
    sync_pgvector_chunk_features,
)
from core.embeddings import (
    build_chunks,
    cosine_similarity,
    deserialize_embedding,
    embed_text,
    normalize_terms,
    to_pgvector_literal,
)


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

    @staticmethod
    def native_vector_search_sql() -> str:
        return """
WITH ranked_chunks AS (
    SELECT
        d.id AS document_id,
        d.filename AS filename,
        d.created_at AS document_created_at,
        c.content_text AS chunk_text,
        ROW_NUMBER() OVER (
            PARTITION BY d.id
            ORDER BY
                (
                    COALESCE(1 - (c.embedding_pg <=> CAST(:query_vector AS vector)), 0.0) * 0.70
                ) +
                (
                    COALESCE(ts_rank_cd(c.fts_tsv, plainto_tsquery('simple', :query_text)), 0.0) * 0.30
                ) DESC,
                c.chunk_index ASC
        ) AS chunk_rank,
        (
            COALESCE(1 - (c.embedding_pg <=> CAST(:query_vector AS vector)), 0.0) * 0.70
        ) +
        (
            COALESCE(ts_rank_cd(c.fts_tsv, plainto_tsquery('simple', :query_text)), 0.0) * 0.25
        ) +
        (
            CASE
                WHEN position(lower(:query_text) in lower(d.filename)) > 0 THEN 0.05
                ELSE 0.0
            END
        ) AS blended_score
    FROM documents d
    LEFT JOIN document_chunks c ON c.document_id = d.id
    WHERE d.tenant_id = :tenant_id
      AND d.status = 'ACTIVE'
)
SELECT
    document_id,
    COALESCE(chunk_text, filename || ' matched query: ' || :query_text) AS snippet,
    CAST(
        GREATEST(
            1,
            LEAST(100, ROUND(COALESCE(blended_score, 0.0) * 100))
        ) AS INTEGER
    ) AS score
FROM ranked_chunks
WHERE chunk_rank = 1 OR chunk_rank IS NULL
ORDER BY score DESC, document_created_at ASC
""".strip()

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
            sync_pgvector_chunk_features(engine=self._engine, document_id=document.id)
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

            result_views = self._retrieve_ranked_results(
                session=session,
                tenant_id=tenant_id,
                run_id=run.id,
                query=query,
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

    def _retrieve_ranked_results(
        self,
        *,
        session: Session,
        tenant_id: str,
        run_id: str,
        query: str,
    ) -> list[RetrievalResultView]:
        if self._should_use_native_vector_search(query=query):
            return self._retrieve_native_ranked_results(
                session=session,
                tenant_id=tenant_id,
                run_id=run_id,
                query=query,
            )
        return self._retrieve_fallback_ranked_results(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            query=query,
        )

    def _should_use_native_vector_search(self, *, query: str) -> bool:
        return self._engine.dialect.name == "postgresql" and bool(query.strip())

    def _retrieve_native_ranked_results(
        self,
        *,
        session: Session,
        tenant_id: str,
        run_id: str,
        query: str,
    ) -> list[RetrievalResultView]:
        rows = session.execute(
            text(self.native_vector_search_sql()),
            {
                "tenant_id": tenant_id,
                "query_text": query,
                "query_vector": to_pgvector_literal(embed_text(query)),
            },
        ).mappings()

        result_views: list[RetrievalResultView] = []
        for index, row in enumerate(rows, start=1):
            score = int(row["score"])
            snippet = str(row["snippet"])
            document_id = str(row["document_id"])
            session.add(
                RetrievalResult(
                    retrieval_run_id=run_id,
                    document_id=document_id,
                    rank=index,
                    score=score,
                    snippet=snippet,
                )
            )
            result_views.append(
                RetrievalResultView(
                    document_id=document_id,
                    rank=index,
                    score=score,
                    snippet=snippet,
                )
            )
        return result_views

    def _retrieve_fallback_ranked_results(
        self,
        *,
        session: Session,
        tenant_id: str,
        run_id: str,
        query: str,
    ) -> list[RetrievalResultView]:
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
                    retrieval_run_id=run_id,
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
        return result_views

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
