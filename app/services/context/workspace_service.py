"""
Workspace Service

Implements "File System as Context" pattern from Manus AI.
Stores large observations externally, keeps only references in context window.
"""

import hashlib
import os
import uuid
from typing import Optional, Union

from sqlalchemy import select, delete

from app.utils.datetime_utils import utc_now
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionWorkspaceFile
from app.config import get_settings

settings = get_settings()

# Workspace storage directory
WORKSPACE_DIR = os.path.join(settings.reports_output_path, "workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)


def _compute_hash(content: Union[bytes, str]) -> str:
    """Compute SHA256 hash of content for deduplication."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _get_storage_path(session_id: str, reference_key: str) -> str:
    """Get the storage path for a workspace file."""
    session_dir = os.path.join(WORKSPACE_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    return os.path.join(session_dir, reference_key)


async def store_large_observation(
    db: AsyncSession,
    session_id: str,
    content: Union[bytes, str],
    reference_key: str,
    file_type: str = "observation",
    summary: Optional[str] = None,
    metadata: Optional[dict] = None
) -> SessionWorkspaceFile:
    """
    Store large content externally, keep only reference in context.

    Instead of:
        context = f"Web page content: {full_50k_char_page}"
    Do this:
        store_large_observation(session_id, full_page, "web_001.html", summary="Homepage of example.com")
        context = "Web page saved to workspace:web_001.html (Homepage of example.com)"

    Args:
        db: Database session
        session_id: Session ID
        content: Content to store (bytes or string)
        reference_key: Key to reference this file (e.g., "tapestry_001.xlsx")
        file_type: Type of file (xlsx, pdf, json, observation, etc.)
        summary: Brief description for context
        metadata: Additional metadata

    Returns:
        Created SessionWorkspaceFile record
    """
    # Compute hash for deduplication
    content_hash = _compute_hash(content)

    # Check if we already have this exact content
    result = await db.execute(
        select(SessionWorkspaceFile)
        .where(
            SessionWorkspaceFile.session_id == session_id,
            SessionWorkspaceFile.content_hash == content_hash
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Content already stored, just update the reference key if needed
        if existing.reference_key != reference_key:
            existing.reference_key = reference_key
            existing.summary = summary or existing.summary
            if metadata:
                existing.file_metadata = {**existing.file_metadata, **metadata}
            await db.commit()
            await db.refresh(existing)
        return existing

    # Store content to file system
    storage_path = _get_storage_path(session_id, reference_key)

    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    else:
        content_bytes = content

    with open(storage_path, "wb") as f:
        f.write(content_bytes)

    # Create database record
    workspace_file = SessionWorkspaceFile(
        id=str(uuid.uuid4()),
        session_id=session_id,
        reference_key=reference_key,
        file_type=file_type,
        storage_path=storage_path,
        content_hash=content_hash,
        size_bytes=len(content_bytes),
        summary=summary,
        file_metadata=metadata or {},
    )

    db.add(workspace_file)
    await db.commit()
    await db.refresh(workspace_file)

    return workspace_file


async def retrieve_workspace_file(
    db: AsyncSession,
    session_id: str,
    reference_key: str
) -> Optional[tuple[Union[bytes, str], dict]]:
    """
    Retrieve file content on-demand.

    Args:
        db: Database session
        session_id: Session ID
        reference_key: Reference key of the file

    Returns:
        Tuple of (content, metadata) or None if not found
    """
    result = await db.execute(
        select(SessionWorkspaceFile)
        .where(
            SessionWorkspaceFile.session_id == session_id,
            SessionWorkspaceFile.reference_key == reference_key
        )
    )
    workspace_file = result.scalar_one_or_none()

    if not workspace_file:
        return None

    if not workspace_file.storage_path or not os.path.exists(workspace_file.storage_path):
        return None

    # Read content
    with open(workspace_file.storage_path, "rb") as f:
        content = f.read()

    # Try to decode as text if it's a text type
    if workspace_file.file_type in ["observation", "txt", "json", "csv"]:
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError:
            pass  # Keep as bytes

    return content, workspace_file.file_metadata or {}


async def get_workspace_file(
    db: AsyncSession,
    session_id: str,
    reference_key: str
) -> Optional[SessionWorkspaceFile]:
    """
    Get workspace file record without content.

    Args:
        db: Database session
        session_id: Session ID
        reference_key: Reference key

    Returns:
        SessionWorkspaceFile or None
    """
    result = await db.execute(
        select(SessionWorkspaceFile)
        .where(
            SessionWorkspaceFile.session_id == session_id,
            SessionWorkspaceFile.reference_key == reference_key
        )
    )
    return result.scalar_one_or_none()


async def list_workspace_files(
    db: AsyncSession,
    session_id: str
) -> list[SessionWorkspaceFile]:
    """
    List all files in a session's workspace.

    Args:
        db: Database session
        session_id: Session ID

    Returns:
        List of SessionWorkspaceFile records
    """
    result = await db.execute(
        select(SessionWorkspaceFile)
        .where(SessionWorkspaceFile.session_id == session_id)
        .order_by(SessionWorkspaceFile.created_at.desc())
    )
    return list(result.scalars().all())


async def get_workspace_summary(
    db: AsyncSession,
    session_id: str
) -> str:
    """
    Generate a brief summary of workspace contents for context.

    Args:
        db: Database session
        session_id: Session ID

    Returns:
        Summary string for inclusion in context
    """
    files = await list_workspace_files(db, session_id)

    if not files:
        return ""

    lines = ["Available in workspace:"]
    for f in files:
        size_kb = (f.size_bytes or 0) / 1024
        summary_part = f" - {f.summary}" if f.summary else ""
        lines.append(f"- {f.reference_key} ({f.file_type}, {size_kb:.1f}KB){summary_part}")

    return "\n".join(lines)


async def get_workspace_references(
    db: AsyncSession,
    session_id: str
) -> list[str]:
    """
    Get list of workspace reference keys for context building.

    Args:
        db: Database session
        session_id: Session ID

    Returns:
        List of reference keys with summaries
    """
    files = await list_workspace_files(db, session_id)

    refs = []
    for f in files:
        if f.summary:
            refs.append(f"workspace:{f.reference_key} ({f.summary})")
        else:
            refs.append(f"workspace:{f.reference_key}")

    return refs


async def delete_workspace_file(
    db: AsyncSession,
    session_id: str,
    reference_key: str
) -> bool:
    """
    Delete a specific workspace file.

    Args:
        db: Database session
        session_id: Session ID
        reference_key: Reference key

    Returns:
        True if deleted, False if not found
    """
    result = await db.execute(
        select(SessionWorkspaceFile)
        .where(
            SessionWorkspaceFile.session_id == session_id,
            SessionWorkspaceFile.reference_key == reference_key
        )
    )
    workspace_file = result.scalar_one_or_none()

    if not workspace_file:
        return False

    # Delete file from filesystem
    if workspace_file.storage_path and os.path.exists(workspace_file.storage_path):
        try:
            os.remove(workspace_file.storage_path)
        except OSError:
            pass  # File might already be deleted

    # Delete database record
    await db.delete(workspace_file)
    await db.commit()

    return True


async def cleanup_workspace(
    db: AsyncSession,
    session_id: str
) -> int:
    """
    Remove all workspace files for a session.

    Called when session is deleted or expired.

    Args:
        db: Database session
        session_id: Session ID

    Returns:
        Number of files deleted
    """
    files = await list_workspace_files(db, session_id)

    # Delete files from filesystem
    for f in files:
        if f.storage_path and os.path.exists(f.storage_path):
            try:
                os.remove(f.storage_path)
            except OSError:
                pass

    # Try to remove session directory
    session_dir = os.path.join(WORKSPACE_DIR, session_id)
    if os.path.exists(session_dir):
        try:
            os.rmdir(session_dir)  # Only removes if empty
        except OSError:
            pass

    # Delete database records
    await db.execute(
        delete(SessionWorkspaceFile)
        .where(SessionWorkspaceFile.session_id == session_id)
    )
    await db.commit()

    return len(files)


async def store_api_response(
    db: AsyncSession,
    session_id: str,
    api_name: str,
    response_data: Union[dict, str, bytes],
    summary: Optional[str] = None
) -> SessionWorkspaceFile:
    """
    Convenience function to store API response data.

    Args:
        db: Database session
        session_id: Session ID
        api_name: Name of the API (e.g., "esri_geoenrich")
        response_data: Response data to store
        summary: Brief description

    Returns:
        Created SessionWorkspaceFile
    """
    import json
    from datetime import datetime

    # Generate reference key
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    reference_key = f"{api_name}_{timestamp}.json"

    # Serialize response
    if isinstance(response_data, (dict, list)):
        content = json.dumps(response_data, indent=2)
    elif isinstance(response_data, bytes):
        content = response_data
    else:
        content = str(response_data)

    return await store_large_observation(
        db=db,
        session_id=session_id,
        content=content,
        reference_key=reference_key,
        file_type="json",
        summary=summary or f"Response from {api_name}",
        metadata={"api": api_name, "timestamp": timestamp},
    )
