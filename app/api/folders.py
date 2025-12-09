"""
Folder (Project) API endpoints.
Folders are persistent containers for files and chats (like ChatGPT Projects).
"""

import os
import uuid
import shutil
from typing import Annotated
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.db.models import Folder, FolderFile, FolderChat, FolderChatMessage, FolderFileType as DBFolderFileType
from app.api.deps import CurrentUser
from app.models.schemas import (
    FolderCreate,
    FolderUpdate,
    FolderResponse,
    FolderListResponse,
    FolderFileResponse,
    FolderChatResponse,
    FolderChatCreate,
    FolderChatMessageResponse,
    FolderChatMessageCreate,
    FolderFileType,
)
from app.config import get_settings

router = APIRouter(prefix="/folders", tags=["folders"])
settings = get_settings()

# File upload directory
UPLOAD_DIR = os.path.join(settings.reports_output_path, "folder_files")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_file_type(filename: str) -> DBFolderFileType:
    """Determine file type from extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    type_map = {
        "xlsx": DBFolderFileType.xlsx,
        "xls": DBFolderFileType.xlsx,
        "pdf": DBFolderFileType.pdf,
        "csv": DBFolderFileType.csv,
        "txt": DBFolderFileType.txt,
        "json": DBFolderFileType.json,
    }
    return type_map.get(ext, DBFolderFileType.other)


def db_file_to_response(file: FolderFile) -> FolderFileResponse:
    """Convert database FolderFile to response schema."""
    return FolderFileResponse(
        id=file.id,
        folder_id=file.folder_id,
        filename=file.filename,
        original_filename=file.original_filename,
        file_type=FolderFileType(file.file_type.value),
        file_size=file.file_size,
        content_preview=file.content_preview,
        metadata=file.metadata or {},
        created_at=file.created_at,
    )


def db_folder_to_response(folder: Folder, file_count: int = 0, chat_count: int = 0) -> FolderResponse:
    """Convert database Folder to response schema."""
    files = [db_file_to_response(f) for f in folder.files] if folder.files else []
    return FolderResponse(
        id=folder.id,
        user_id=folder.user_id,
        name=folder.name,
        description=folder.description,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        file_count=file_count or len(files),
        chat_count=chat_count,
        files=files,
    )


# ============== Folder CRUD ==============

@router.get("", response_model=FolderListResponse)
async def list_folders(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all folders for the current user."""
    # Get folders with file and chat counts
    result = await db.execute(
        select(Folder)
        .where(Folder.user_id == current_user.id)
        .options(selectinload(Folder.files))
        .order_by(Folder.updated_at.desc())
    )
    folders = result.scalars().all()

    # Get chat counts for each folder
    folder_responses = []
    for folder in folders:
        chat_count_result = await db.execute(
            select(func.count(FolderChat.id)).where(FolderChat.folder_id == folder.id)
        )
        chat_count = chat_count_result.scalar() or 0
        folder_responses.append(db_folder_to_response(folder, len(folder.files), chat_count))

    return FolderListResponse(folders=folder_responses)


@router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    folder_data: FolderCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a new folder."""
    folder = Folder(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=folder_data.name,
        description=folder_data.description,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)

    return db_folder_to_response(folder)


@router.get("/{folder_id}", response_model=FolderResponse)
async def get_folder(
    folder_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a specific folder."""
    result = await db.execute(
        select(Folder)
        .where(Folder.id == folder_id, Folder.user_id == current_user.id)
        .options(selectinload(Folder.files))
    )
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Get chat count
    chat_count_result = await db.execute(
        select(func.count(FolderChat.id)).where(FolderChat.folder_id == folder_id)
    )
    chat_count = chat_count_result.scalar() or 0

    return db_folder_to_response(folder, len(folder.files), chat_count)


@router.patch("/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: str,
    folder_data: FolderUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a folder."""
    result = await db.execute(
        select(Folder)
        .where(Folder.id == folder_id, Folder.user_id == current_user.id)
        .options(selectinload(Folder.files))
    )
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    if folder_data.name is not None:
        folder.name = folder_data.name
    if folder_data.description is not None:
        folder.description = folder_data.description

    folder.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(folder)

    return db_folder_to_response(folder)


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a folder and all its files."""
    result = await db.execute(
        select(Folder)
        .where(Folder.id == folder_id, Folder.user_id == current_user.id)
        .options(selectinload(Folder.files))
    )
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Delete files from disk
    for file in folder.files:
        try:
            if os.path.exists(file.file_path):
                os.remove(file.file_path)
        except Exception:
            pass

    await db.delete(folder)
    await db.commit()


# ============== Folder Files ==============

@router.post("/{folder_id}/files", response_model=FolderFileResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    folder_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    """Upload a file to a folder."""
    # Verify folder ownership
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Generate unique filename
    file_id = str(uuid.uuid4())
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else ""
    stored_filename = f"{file_id}.{ext}" if ext else file_id

    # Create folder-specific directory
    folder_dir = os.path.join(UPLOAD_DIR, folder_id)
    os.makedirs(folder_dir, exist_ok=True)

    file_path = os.path.join(folder_dir, stored_filename)

    # Save file
    content = await file.read()
    file_size = len(content)

    with open(file_path, "wb") as f:
        f.write(content)

    # Determine file type
    file_type = get_file_type(file.filename)

    # Create database record
    db_file = FolderFile(
        id=file_id,
        folder_id=folder_id,
        filename=stored_filename,
        original_filename=file.filename,
        file_type=file_type,
        file_size=file_size,
        file_path=file_path,
        metadata={},
    )
    db.add(db_file)

    # Update folder timestamp
    folder.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(db_file)

    return db_file_to_response(db_file)


@router.get("/{folder_id}/files", response_model=list[FolderFileResponse])
async def list_folder_files(
    folder_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all files in a folder."""
    # Verify folder ownership
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    result = await db.execute(
        select(FolderFile)
        .where(FolderFile.folder_id == folder_id)
        .order_by(FolderFile.created_at.desc())
    )
    files = result.scalars().all()

    return [db_file_to_response(f) for f in files]


@router.delete("/{folder_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    folder_id: str,
    file_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a file from a folder."""
    # Verify folder ownership
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Get file
    result = await db.execute(
        select(FolderFile).where(FolderFile.id == file_id, FolderFile.folder_id == folder_id)
    )
    file = result.scalar_one_or_none()

    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    # Delete from disk
    try:
        if os.path.exists(file.file_path):
            os.remove(file.file_path)
    except Exception:
        pass

    await db.delete(file)
    await db.commit()


# ============== Folder Chats ==============

@router.get("/{folder_id}/chats", response_model=list[FolderChatResponse])
async def list_folder_chats(
    folder_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all chats in a folder."""
    # Verify folder ownership
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    result = await db.execute(
        select(FolderChat)
        .where(FolderChat.folder_id == folder_id)
        .order_by(FolderChat.updated_at.desc())
    )
    chats = result.scalars().all()

    return [
        FolderChatResponse(
            id=chat.id,
            folder_id=chat.folder_id,
            title=chat.title,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            messages=[],  # Don't include messages in list view
        )
        for chat in chats
    ]


@router.post("/{folder_id}/chats", response_model=FolderChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    folder_id: str,
    chat_data: FolderChatCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a new chat in a folder."""
    # Verify folder ownership
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    chat = FolderChat(
        id=str(uuid.uuid4()),
        folder_id=folder_id,
        title=chat_data.title,
    )
    db.add(chat)

    # Update folder timestamp
    folder.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(chat)

    return FolderChatResponse(
        id=chat.id,
        folder_id=chat.folder_id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[],
    )


@router.get("/{folder_id}/chats/{chat_id}", response_model=FolderChatResponse)
async def get_chat(
    folder_id: str,
    chat_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a chat with all messages."""
    # Verify folder ownership
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    result = await db.execute(
        select(FolderChat)
        .where(FolderChat.id == chat_id, FolderChat.folder_id == folder_id)
        .options(selectinload(FolderChat.messages))
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    return FolderChatResponse(
        id=chat.id,
        folder_id=chat.folder_id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[
            FolderChatMessageResponse(
                id=msg.id,
                chat_id=msg.chat_id,
                role=msg.role,
                content=msg.content,
                image_url=msg.image_url,
                created_at=msg.created_at,
            )
            for msg in sorted(chat.messages, key=lambda m: m.created_at)
        ],
    )


@router.delete("/{folder_id}/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    folder_id: str,
    chat_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a chat from a folder."""
    # Verify folder ownership
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    result = await db.execute(
        select(FolderChat).where(FolderChat.id == chat_id, FolderChat.folder_id == folder_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await db.delete(chat)
    await db.commit()
