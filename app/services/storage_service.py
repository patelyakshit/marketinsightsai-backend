"""
Supabase Storage Service for cloud file storage.

Handles uploading and retrieving files from Supabase Storage.
Falls back to local filesystem if Supabase is not configured.
"""
import logging
import os
from typing import Optional
from supabase import create_client, Client
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Singleton Supabase client
_supabase_client: Optional[Client] = None


def get_supabase_client() -> Optional[Client]:
    """Get or create Supabase client singleton."""
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    if not settings.supabase_url or not settings.supabase_service_key:
        logger.warning("Supabase Storage not configured - using local filesystem")
        return None

    try:
        _supabase_client = create_client(
            settings.supabase_url,
            settings.supabase_service_key
        )
        logger.info("Supabase Storage client initialized")
        return _supabase_client
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        return None


def is_storage_enabled() -> bool:
    """Check if cloud storage is enabled and working."""
    return get_supabase_client() is not None


def _get_full_url(relative_path: str) -> str:
    """Get full URL for a relative path, using backend_url if configured."""
    if settings.backend_url:
        return f"{settings.backend_url.rstrip('/')}{relative_path}"
    return relative_path


async def upload_file(
    file_content: bytes,
    file_path: str,
    content_type: str = "application/octet-stream",
    bucket: Optional[str] = None
) -> Optional[str]:
    """
    Upload a file to Supabase Storage.

    Args:
        file_content: The file bytes to upload
        file_path: Path/name for the file in storage (e.g., "reports/report_123.html")
        content_type: MIME type of the file
        bucket: Storage bucket name (defaults to settings.supabase_storage_bucket)

    Returns:
        Public URL of the uploaded file, or None if upload failed
    """
    client = get_supabase_client()
    bucket_name = bucket or settings.supabase_storage_bucket

    if client is None:
        # Fallback: save to local filesystem
        return await _save_local(file_content, file_path)

    try:
        # Upload to Supabase Storage
        result = client.storage.from_(bucket_name).upload(
            path=file_path,
            file=file_content,
            file_options={"content-type": content_type, "upsert": "true"}
        )

        # Get public URL
        public_url = client.storage.from_(bucket_name).get_public_url(file_path)
        logger.info(f"File uploaded to Supabase: {file_path}")
        return public_url

    except Exception as e:
        logger.error(f"Failed to upload to Supabase Storage: {e}")
        # Fallback to local storage
        return await _save_local(file_content, file_path)


async def get_file(
    file_path: str,
    bucket: Optional[str] = None
) -> Optional[bytes]:
    """
    Download a file from Supabase Storage.

    Args:
        file_path: Path of the file in storage
        bucket: Storage bucket name

    Returns:
        File content as bytes, or None if not found
    """
    client = get_supabase_client()
    bucket_name = bucket or settings.supabase_storage_bucket

    if client is None:
        # Fallback: read from local filesystem
        return await _read_local(file_path)

    try:
        result = client.storage.from_(bucket_name).download(file_path)
        return result
    except Exception as e:
        logger.error(f"Failed to download from Supabase Storage: {e}")
        # Try local fallback
        return await _read_local(file_path)


def get_public_url(
    file_path: str,
    bucket: Optional[str] = None
) -> str:
    """
    Get the public URL for a file in storage.

    Args:
        file_path: Path of the file in storage
        bucket: Storage bucket name

    Returns:
        Public URL string
    """
    client = get_supabase_client()
    bucket_name = bucket or settings.supabase_storage_bucket

    if client is None:
        # Return local API endpoint with full URL if backend_url configured
        return _get_full_url(f"/api/reports/files/{file_path}")

    return client.storage.from_(bucket_name).get_public_url(file_path)


async def delete_file(
    file_path: str,
    bucket: Optional[str] = None
) -> bool:
    """
    Delete a file from Supabase Storage.

    Args:
        file_path: Path of the file in storage
        bucket: Storage bucket name

    Returns:
        True if deleted successfully
    """
    client = get_supabase_client()
    bucket_name = bucket or settings.supabase_storage_bucket

    if client is None:
        # Delete from local filesystem
        return await _delete_local(file_path)

    try:
        client.storage.from_(bucket_name).remove([file_path])
        logger.info(f"File deleted from Supabase: {file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete from Supabase Storage: {e}")
        return False


# Local filesystem fallback functions

async def _save_local(file_content: bytes, file_path: str) -> str:
    """Save file to local filesystem as fallback."""
    # Extract just the filename if it's a full path
    filename = os.path.basename(file_path)
    local_path = os.path.join(settings.reports_output_path, filename)

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    with open(local_path, 'wb') as f:
        f.write(file_content)

    logger.info(f"File saved locally: {local_path}")

    # Return full URL if backend_url is configured, otherwise relative path
    relative_path = f"/api/reports/files/{filename}"
    if settings.backend_url:
        return f"{settings.backend_url.rstrip('/')}{relative_path}"
    return relative_path


async def _read_local(file_path: str) -> Optional[bytes]:
    """Read file from local filesystem."""
    filename = os.path.basename(file_path)
    local_path = os.path.join(settings.reports_output_path, filename)

    if not os.path.exists(local_path):
        return None

    with open(local_path, 'rb') as f:
        return f.read()


async def _delete_local(file_path: str) -> bool:
    """Delete file from local filesystem."""
    filename = os.path.basename(file_path)
    local_path = os.path.join(settings.reports_output_path, filename)

    if os.path.exists(local_path):
        os.remove(local_path)
        return True
    return False


# Utility functions for specific file types

async def upload_report(
    html_content: str,
    filename: str
) -> str:
    """
    Upload an HTML report to storage.

    Args:
        html_content: HTML content as string
        filename: Report filename

    Returns:
        URL to access the report
    """
    file_path = f"reports/{filename}"
    url = await upload_file(
        file_content=html_content.encode('utf-8'),
        file_path=file_path,
        content_type="text/html"
    )
    return url or _get_full_url(f"/api/reports/files/{filename}")


async def upload_image(
    image_content: bytes,
    filename: str,
    content_type: str = "image/png"
) -> str:
    """
    Upload an image to storage.

    Args:
        image_content: Image bytes
        filename: Image filename
        content_type: MIME type (default: image/png)

    Returns:
        URL to access the image
    """
    file_path = f"images/{filename}"
    url = await upload_file(
        file_content=image_content,
        file_path=file_path,
        content_type=content_type
    )
    return url or _get_full_url(f"/api/reports/generated_images/{filename}")


async def upload_pdf(
    pdf_content: bytes,
    filename: str
) -> str:
    """
    Upload a PDF to storage.

    Args:
        pdf_content: PDF bytes
        filename: PDF filename

    Returns:
        URL to access the PDF
    """
    file_path = f"pdfs/{filename}"
    url = await upload_file(
        file_content=pdf_content,
        file_path=file_path,
        content_type="application/pdf"
    )
    return url or _get_full_url(f"/api/reports/files/{filename}")
