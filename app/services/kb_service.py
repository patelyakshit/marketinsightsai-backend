import uuid
from datetime import datetime
from pathlib import Path
from app.models.schemas import KnowledgeDocument, DocumentMetadata, DocumentCategory

# In-memory document store (would use database with pgvector in production)
_documents: dict[str, KnowledgeDocument] = {}


async def get_documents(
    workspace_id: str | None = None,
) -> list[KnowledgeDocument]:
    """Get knowledge base documents with optional filtering."""
    documents = list(_documents.values())

    if workspace_id:
        documents = [d for d in documents if d.workspace_id == workspace_id]

    return documents


async def upload_document(
    filename: str,
    contents: bytes,
    workspace_id: str | None = None,
) -> KnowledgeDocument:
    """Upload a document to the knowledge base."""
    content = contents.decode('utf-8', errors='ignore')

    # Determine category from file extension
    category = DocumentCategory.other
    if filename.endswith('.md'):
        category = DocumentCategory.other

    doc = KnowledgeDocument(
        id=str(uuid.uuid4()),
        workspaceId=workspace_id,
        title=Path(filename).stem.replace('-', ' ').title(),
        content=content,
        metadata=DocumentMetadata(category=category),
        createdAt=datetime.now(),
        updatedAt=datetime.now(),
    )

    _documents[doc.id] = doc
    return doc


async def delete_document(document_id: str) -> bool:
    """Delete a document from the knowledge base."""
    if document_id in _documents:
        del _documents[document_id]
        return True
    return False


async def search_documents(
    query: str,
    limit: int = 10,
) -> list[dict]:
    """Search documents using simple keyword matching.

    In production, this would use pgvector for semantic search.
    """
    results = []
    query_lower = query.lower()

    for doc in _documents.values():
        # Simple keyword matching (would use embeddings in production)
        score = 0
        if query_lower in doc.title.lower():
            score += 2
        if query_lower in doc.content.lower():
            score += 1

        if score > 0:
            results.append({
                'id': doc.id,
                'title': doc.title,
                'content': doc.content[:500],
                'score': score,
            })

    # Sort by score and limit
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:limit]
