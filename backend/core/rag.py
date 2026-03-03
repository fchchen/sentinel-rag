from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import uuid4


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SCAN_FAILED = "SCAN_FAILED"
    SCAN_UNKNOWN = "SCAN_UNKNOWN"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    tenant_id: str
    filename: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus


class DocumentRegistry:
    def __init__(self) -> None:
        self._documents: dict[str, DocumentRecord] = {}

    def register_document(
        self,
        *,
        tenant_id: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
    ) -> DocumentRecord:
        document = DocumentRecord(
            id=str(uuid4()),
            tenant_id=tenant_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            status=DocumentStatus.PENDING,
        )
        self._documents[document.id] = document
        return document

    def apply_scan_result(self, document_id: str, result: str) -> DocumentRecord:
        document = self._documents[document_id]
        status = {
            "clean": DocumentStatus.ACTIVE,
            "timeout": DocumentStatus.SCAN_FAILED,
            "failed": DocumentStatus.SCAN_FAILED,
            "unknown": DocumentStatus.SCAN_UNKNOWN,
            "malware": DocumentStatus.QUARANTINED,
        }[result]
        updated = replace(document, status=status)
        self._documents[document_id] = updated
        return updated

    def retrievable_documents(self, *, tenant_id: str) -> list[DocumentRecord]:
        return [
            document
            for document in self._documents.values()
            if document.tenant_id == tenant_id and document.status is DocumentStatus.ACTIVE
        ]
