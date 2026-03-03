import json
import math
from dataclasses import dataclass


EMBEDDING_DIMENSIONS = 12


@dataclass(frozen=True)
class ChunkPayload:
    chunk_index: int
    content_text: str
    token_count: int
    keyword_signature: str
    embedding_json: str


def build_chunks(content_text: str) -> list[ChunkPayload]:
    words = [word for word in content_text.split() if word]
    if not words:
        return []

    chunk_size = 4
    overlap = 1
    chunks: list[ChunkPayload] = []
    index = 0
    chunk_index = 0
    while index < len(words):
        chunk_text = " ".join(words[index : index + chunk_size])
        chunks.append(
            ChunkPayload(
                chunk_index=chunk_index,
                content_text=chunk_text,
                token_count=len(chunk_text.split()),
                keyword_signature=" ".join(sorted(set(_normalize_terms(chunk_text)))),
                embedding_json=serialize_embedding(embed_text(chunk_text)),
            )
        )
        if index + chunk_size >= len(words):
            break
        index += chunk_size - overlap
        chunk_index += 1
    return chunks


def embed_text(text: str) -> tuple[float, ...]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for term in _normalize_terms(text):
        bucket = sum(ord(character) for character in term) % EMBEDDING_DIMENSIONS
        vector[bucket] += max(1.0, len(term) / 4)
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return tuple(0.0 for _ in range(EMBEDDING_DIMENSIONS))
    return tuple(round(value / magnitude, 6) for value in vector)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right:
        return 0.0
    return max(0.0, min(1.0, round(sum(a * b for a, b in zip(left, right, strict=False)), 6)))


def serialize_embedding(vector: tuple[float, ...]) -> str:
    return json.dumps(vector, separators=(",", ":"))


def deserialize_embedding(raw: str) -> tuple[float, ...]:
    values = json.loads(raw)
    return tuple(float(value) for value in values)


def normalize_terms(text: str) -> list[str]:
    return _normalize_terms(text)


def _normalize_terms(text: str) -> list[str]:
    cleaned = (
        text.lower()
        .replace("-", " ")
        .replace(".", " ")
        .replace(",", " ")
        .replace(":", " ")
        .replace("/", " ")
    )
    return [term for term in cleaned.split() if term]
