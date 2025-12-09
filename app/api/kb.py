from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from app.models.schemas import (
    DocumentListResponse,
    DocumentUploadResponse,
    KnowledgeDocument,
)
from app.services.kb_service import (
    get_documents,
    upload_document,
    delete_document,
    search_documents,
)

router = APIRouter()


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    workspace_id: str | None = Query(None, description="Workspace ID filter"),
):
    """List knowledge base documents."""
    try:
        documents = await get_documents(workspace_id=workspace_id)
        return DocumentListResponse(documents=documents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document_endpoint(
    file: UploadFile = File(...),
    workspace_id: str | None = Query(None, description="Workspace ID for the document"),
):
    """Upload a document to the workspace knowledge base."""
    allowed_extensions = ('.md', '.pdf', '.txt', '.docx')
    if not file.filename or not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"File must be one of: {', '.join(allowed_extensions)}"
        )

    try:
        contents = await file.read()
        document = await upload_document(
            filename=file.filename,
            contents=contents,
            workspace_id=workspace_id,
        )
        return DocumentUploadResponse(
            document=document,
            message="Document uploaded successfully."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{document_id}")
async def delete_document_endpoint(document_id: str):
    """Delete a workspace document."""
    try:
        success = await delete_document(document_id)
        if not success:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"message": "Document deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_documents_endpoint(
    query: str = Query(..., description="Search query"),
    limit: int = Query(10, description="Maximum number of results"),
):
    """Search knowledge base documents using semantic search."""
    try:
        results = await search_documents(query=query, limit=limit)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
