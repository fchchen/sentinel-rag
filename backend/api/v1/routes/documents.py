from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.auth import AuthContext, Role, get_auth_context, require_role
from core.documents import DocumentView, get_document_service

router = APIRouter(tags=["documents"])


class CreateDocumentRequest(BaseModel):
    filename: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    size_bytes: int = Field(gt=0)


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    filename: str
    mime_type: str
    size_bytes: int
    status: str


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]


class ScanResultRequest(BaseModel):
    result: str = Field(min_length=1)


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: CreateDocumentRequest,
    context: AuthContext = Depends(require_role(Role.ADMIN)),
    document_service=Depends(get_document_service),
) -> DocumentResponse:
    document = document_service.create_document(
        tenant_id=context.tenant_id,
        filename=payload.filename,
        mime_type=payload.mime_type,
        size_bytes=payload.size_bytes,
    )
    return _to_response(document)


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    context: AuthContext = Depends(get_auth_context),
    document_service=Depends(get_document_service),
) -> DocumentListResponse:
    items = document_service.list_documents(tenant_id=context.tenant_id)
    return DocumentListResponse(items=[_to_response(item) for item in items])


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    context: AuthContext = Depends(require_role(Role.ADMIN)),
    document_service=Depends(get_document_service),
) -> dict[str, str | bool]:
    deleted = document_service.delete_document(tenant_id=context.tenant_id, document_id=document_id)
    return {"deleted": deleted, "document_id": document_id}


@router.post("/documents/{document_id}/scan-result", response_model=DocumentResponse)
async def apply_scan_result(
    document_id: str,
    payload: ScanResultRequest,
    context: AuthContext = Depends(require_role(Role.ADMIN)),
    document_service=Depends(get_document_service),
) -> DocumentResponse:
    try:
        document = document_service.apply_scan_result(
            tenant_id=context.tenant_id,
            document_id=document_id,
            result=payload.result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_response(document)


def _to_response(document: DocumentView) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        tenant_id=document.tenant_id,
        filename=document.filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        status=document.status,
    )
