from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from context_router.db.session import get_session
from context_router.schemas.projects import (
    DocumentMappingCandidateListResponse,
    DocumentMappingCandidateResponse,
)
from context_router.services.document_mapping import (
    DocumentMappingError,
    list_document_candidates,
)

router = APIRouter(prefix="/api/document-mappings", tags=["document-mappings"])


@router.get("/candidates", response_model=DocumentMappingCandidateListResponse)
def mapping_candidates(
    session: Annotated[Session, Depends(get_session)],
) -> DocumentMappingCandidateListResponse:
    try:
        candidates = list_document_candidates(session)
    except DocumentMappingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentMappingCandidateListResponse(
        candidates=[
            DocumentMappingCandidateResponse(
                docs_path=candidate.docs_path,
                markdown_count=candidate.markdown_count,
                mapped_project_slug=candidate.mapped_project_slug,
            )
            for candidate in candidates
        ]
    )
