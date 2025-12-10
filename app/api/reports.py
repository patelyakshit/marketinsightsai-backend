import os
import httpx
import tempfile
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, Response
from app.models.schemas import TapestryUploadResponse, ReportGenerateRequest, ReportGenerateResponse
from app.services.tapestry_service import parse_tapestry_xlsx, generate_tapestry_report, generate_pdf_from_html
from app.config import get_settings

router = APIRouter()

# In-memory store for uploaded data (would use database in production)
_uploaded_stores: dict = {}


@router.post("/tapestry/upload", response_model=TapestryUploadResponse)
async def upload_tapestry_file(file: UploadFile = File(...)):
    """Upload an Esri tapestry XLSX file and parse store data."""
    if not file.filename or not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="File must be an Excel file (.xlsx or .xls)")

    try:
        contents = await file.read()
        stores = await parse_tapestry_xlsx(contents)

        # Store the parsed data for later use
        for store in stores:
            _uploaded_stores[store.id] = store

        return TapestryUploadResponse(
            stores=stores,
            message=f"Successfully parsed {len(stores)} stores from the file."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error parsing file: {str(e)}")


@router.post("/tapestry/generate", response_model=ReportGenerateResponse)
async def generate_report(request: ReportGenerateRequest):
    """Generate a tapestry report PDF for a specific store."""
    store_id = request.store_id

    if store_id not in _uploaded_stores:
        raise HTTPException(status_code=404, detail="Store not found. Please upload the tapestry file first.")

    try:
        store = _uploaded_stores[store_id]
        report_url = await generate_tapestry_report(store)

        return ReportGenerateResponse(
            reportUrl=report_url,
            message="Report generated successfully."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating report: {str(e)}")


@router.get("/tapestry/stores")
async def list_stores():
    """List all uploaded stores."""
    return {"stores": list(_uploaded_stores.values())}


@router.get("/files/{filename}")
async def get_report_file(filename: str, download: bool = False):
    """Serve generated report files (HTML for preview, PDF for download).

    Args:
        filename: The report file name
        download: If True, generates and returns PDF for download
    """
    settings = get_settings()
    file_path = os.path.join(settings.reports_output_path, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Report file not found")

    # If download requested and file is HTML, generate PDF on-the-fly
    if download and filename.endswith('.html'):
        pdf_content = generate_pdf_from_html(file_path)
        if pdf_content:
            pdf_filename = filename.replace('.html', '.pdf')
            return Response(
                content=pdf_content,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{pdf_filename}"'}
            )
        else:
            # Fallback to HTML download if PDF generation fails
            with open(file_path, 'rb') as f:
                content = f.read()
            return Response(
                content=content,
                media_type="text/html",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )

    # Determine content type based on extension
    if filename.endswith('.pdf'):
        media_type = "application/pdf"
    else:
        media_type = "text/html"

    # Read file content
    with open(file_path, 'rb') as f:
        content = f.read()

    # Set Content-Disposition based on download flag
    if download:
        disposition = f'attachment; filename="{filename}"'
    else:
        disposition = 'inline'

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": disposition}
    )


@router.get("/segment-images/{filename}")
async def get_segment_image(filename: str):
    """Serve segment images for reports.

    Images should be named like: D3.png, K8.png, etc.
    Place images in backend/static/segment-images/
    """
    # Get the directory where this file is located
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    images_dir = os.path.join(backend_dir, "static", "segment-images")
    file_path = os.path.join(images_dir, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Segment image not found")

    return FileResponse(file_path, media_type="image/png")


@router.get("/generated_images/{filename}")
async def get_generated_image(filename: str):
    """Serve AI-generated marketing images.

    These images are generated by Gemini Imagen 3 and stored
    in the reports/generated_images directory.
    """
    settings = get_settings()
    images_dir = os.path.join(settings.reports_output_path, "generated_images")
    file_path = os.path.join(images_dir, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Generated image not found")

    return FileResponse(file_path, media_type="image/png")


@router.get("/proxy-html")
async def proxy_html(url: str = Query(..., description="URL of HTML to proxy for iframe display")):
    """Proxy an HTML page from a URL for iframe display.

    This endpoint fetches HTML content from a given URL (e.g., Supabase Storage)
    and serves it with proper Content-Type headers for iframe rendering.

    Args:
        url: The URL of the HTML page to proxy

    Returns:
        HTML content with proper headers
    """
    # Validate URL - only allow Supabase and our own domain
    allowed_domains = ["supabase.co", "supabase.in", "localhost", "marketinsightsai"]
    is_allowed = any(domain in url for domain in allowed_domains)
    if not is_allowed:
        raise HTTPException(status_code=400, detail="URL domain not allowed")

    try:
        # Fetch HTML content from URL
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to fetch HTML: {response.status_code}"
                )
            html_content = response.text

        return Response(
            content=html_content,
            media_type="text/html",
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "X-Frame-Options": "SAMEORIGIN"
            }
        )

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout fetching HTML content")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error proxying HTML: {str(e)}")


@router.get("/convert-to-pdf")
async def convert_url_to_pdf(url: str = Query(..., description="URL of HTML to convert to PDF")):
    """Convert an HTML page from a URL to PDF.

    This endpoint fetches HTML content from a given URL (e.g., Supabase Storage)
    and converts it to PDF using WeasyPrint.

    Args:
        url: The URL of the HTML page to convert

    Returns:
        PDF file as attachment
    """
    # Validate URL - only allow Supabase and our own domain
    allowed_domains = ["supabase.co", "supabase.in", "localhost", "marketinsightsai"]
    is_allowed = any(domain in url for domain in allowed_domains)
    if not is_allowed:
        raise HTTPException(status_code=400, detail="URL domain not allowed")

    try:
        # Fetch HTML content from URL
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to fetch HTML: {response.status_code}"
                )
            html_content = response.text

        # Write to temp file for PDF generation
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_content)
            temp_path = f.name

        try:
            # Generate PDF
            pdf_content = generate_pdf_from_html(temp_path)

            if pdf_content:
                # Extract filename from URL
                filename = url.split('/')[-1].split('?')[0]
                pdf_filename = filename.replace('.html', '.pdf')

                return Response(
                    content=pdf_content,
                    media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{pdf_filename}"'}
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail="PDF generation failed - WeasyPrint may not be available"
                )
        finally:
            # Clean up temp file
            os.unlink(temp_path)

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout fetching HTML content")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error converting to PDF: {str(e)}")
