"""
Tapestry Report Service

This module handles parsing Esri Tapestry XLSX files and generating
lifestyle segmentation reports using Jinja2 templates.
"""

import logging
import io
import os
import re
import uuid
import base64
from datetime import datetime

logger = logging.getLogger(__name__)
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from app.models.schemas import Store, TapestrySegment
from app.services.ai_service import generate_business_insights, generate_segment_insight
from app.services.esri_service import get_segment_profile
from app.services.storage_service import upload_report, is_storage_enabled
from app.config import get_settings

# Optional PDF support - requires system libraries (pango, cairo)
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except OSError:
    WEASYPRINT_AVAILABLE = False

# Playwright fallback for PDF generation when WeasyPrint unavailable
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

settings = get_settings()

# Segment colors by letter (A-L) - Esri Tapestry official colors
SEGMENT_COLORS = {
    'A': '#155E81',
    'B': '#036473',
    'C': '#585182',
    'D': '#8C5182',
    'E': '#37733F',
    'F': '#557332',
    'G': '#01715D',
    'H': '#027373',
    'I': '#A88704',
    'J': '#847A28',
    'K': '#9B660F',
    'L': '#9A5527',
}

# Get backend directory for static files
BACKEND_DIR = Path(__file__).parent.parent.parent
TEMPLATES_DIR = BACKEND_DIR / "templates"
STATIC_DIR = BACKEND_DIR / "static"


def markdown_to_html(text: str) -> Markup:
    """Convert markdown formatting to HTML.

    Converts:
    - **text** or __text__ to <strong>text</strong>
    - *text* or _text_ to <em>text</em>

    Returns a Markup object that Jinja2 won't escape.
    """
    if not text:
        return Markup("")

    # Convert **text** and __text__ to <strong>text</strong>
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)

    # Convert *text* and _text_ to <em>text</em> (but not inside words)
    # Use negative lookbehind/lookahead to avoid matching in the middle of words
    text = re.sub(r'(?<!\w)\*([^*]+?)\*(?!\w)', r'<em>\1</em>', text)
    text = re.sub(r'(?<!\w)_([^_]+?)_(?!\w)', r'<em>\1</em>', text)

    return Markup(text)


def sanitize_filename(text: str) -> str:
    """Sanitize text for use in filenames.

    Removes or replaces characters that are not safe for filenames.
    """
    if not text:
        return "unknown"
    # Replace spaces with underscores, remove unsafe characters
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = re.sub(r'\s+', '_', text.strip())
    return text[:50]  # Limit length


def _get_jinja_env() -> Environment:
    """Create and configure Jinja2 environment."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    return env


def get_segment_image_base64(segment_code: str) -> str | None:
    """Get base64 encoded segment image for embedding in HTML/PDF.

    Args:
        segment_code: The segment code (e.g., 'A1', 'B2')

    Returns:
        Base64 data URI string or None if image not found
    """
    image_path = STATIC_DIR / "segment-images" / f"{segment_code}.png"

    if image_path.exists():
        image_data = image_path.read_bytes()
        b64_data = base64.b64encode(image_data).decode('utf-8')
        return f"data:image/png;base64,{b64_data}"
    return None


def get_logo_base64() -> str | None:
    """Get base64 encoded Location Matters logo for embedding in HTML/PDF.

    Returns:
        Base64 data URI string or None if logo not found
    """
    logo_path = STATIC_DIR / "LM-logo.svg"

    if logo_path.exists():
        logo_data = logo_path.read_bytes()
        b64_data = base64.b64encode(logo_data).decode('utf-8')
        return f"data:image/svg+xml;base64,{b64_data}"
    return None


def enrich_segment(segment: TapestrySegment) -> TapestrySegment:
    """Enrich a TapestrySegment with profile data from Esri.

    Populates name, description, demographics, and key traits.
    """
    profile = get_segment_profile(segment.code)
    if profile:
        segment.name = profile.name
        segment.life_mode = profile.life_mode
        segment.description = profile.description
        segment.median_age = profile.median_age
        segment.median_household_income = profile.median_household_income
        segment.median_net_worth = profile.median_net_worth
        segment.homeownership_rate = profile.homeownership_rate
    return segment


def enrich_store_segments(store: Store) -> Store:
    """Enrich all segments in a store with Esri profile data."""
    for segment in store.segments:
        enrich_segment(segment)
    return store


async def parse_tapestry_xlsx(contents: bytes) -> list[Store]:
    """Parse an Esri tapestry XLSX file and extract store data."""
    import re
    df = pd.read_excel(io.BytesIO(contents))

    # Pattern for segment codes (e.g., A1, B2, K4, G2, etc.)
    segment_code_pattern = re.compile(r'([A-L][1-8])')

    # Identify columns by matching common patterns
    store_id_col = None
    store_name_col = None
    segment_col = None
    segment_name_col = None
    share_col = None
    count_col = None
    life_mode_col = None
    life_stage_col = None
    drive_time_col = None

    for col in df.columns:
        col_lower = str(col).lower().strip()
        if col_lower in ['vpc id', 'store id', 'storeid', 'id', 'store_id']:
            store_id_col = col
        elif col_lower in ['center name', 'store name', 'storename', 'name', 'location']:
            store_name_col = col
        elif 'dominant' in col_lower and 'segment' in col_lower:
            segment_col = col
        elif 'segmentation name' in col_lower or col_lower == 'tapestry segmentation name':
            segment_name_col = col
        elif col_lower == 'percent' or col_lower == 'share' or '%' in col_lower:
            share_col = col
        elif col_lower == 'count' or col_lower == 'households' or col_lower == 'hh':
            count_col = col
        elif 'lifemode' in col_lower and 'group' in col_lower and 'description' not in col_lower:
            life_mode_col = col
        elif ('life stage' in col_lower or 'lifestage' in col_lower) and 'description' not in col_lower:
            life_stage_col = col
        elif 'drive' in col_lower and 'time' in col_lower:
            drive_time_col = col

    # Build stores from the data
    stores_dict: dict[str, Store] = {}

    for _, row in df.iterrows():
        # Get store identifier - prefer name, fall back to ID
        if store_name_col and pd.notna(row.get(store_name_col)):
            store_name = str(row[store_name_col]).strip()
        elif store_id_col and pd.notna(row.get(store_id_col)):
            store_name = f"Store {row[store_id_col]}"
        else:
            continue

        # Get store number from ID column
        store_number = None
        if store_id_col and pd.notna(row.get(store_id_col)):
            store_number = str(row[store_id_col]).strip()

        # Get drive time
        drive_time = None
        if drive_time_col and pd.notna(row.get(drive_time_col)):
            drive_time = str(row[drive_time_col]).strip()

        store_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, store_name))

        if store_id not in stores_dict:
            stores_dict[store_id] = Store(
                id=store_id,
                name=store_name,
                storeNumber=store_number,
                driveTime=drive_time,
                segments=[]
            )

        # Extract segment code from "Dominant Tapestry Segment" column
        if segment_col and pd.notna(row.get(segment_col)):
            segment_value = str(row[segment_col])
            match = segment_code_pattern.search(segment_value)
            if match:
                segment_code = match.group(1).upper()

                # Get segment name from dedicated column or parse from segment value
                if segment_name_col and pd.notna(row.get(segment_name_col)):
                    segment_name = str(row[segment_name_col])
                else:
                    # Extract name from "G2: Up and Coming Families" format
                    parts = segment_value.split(':', 1)
                    segment_name = parts[1].strip() if len(parts) > 1 else segment_code

                # Get household share and count
                share = float(row[share_col]) if share_col and pd.notna(row.get(share_col)) else 0
                count = int(row[count_col]) if count_col and pd.notna(row.get(count_col)) else 0

                # Get life mode and life stage
                life_mode = str(row[life_mode_col]).strip() if life_mode_col and pd.notna(row.get(life_mode_col)) else ""
                life_stage = str(row[life_stage_col]).strip() if life_stage_col and pd.notna(row.get(life_stage_col)) else ""

                segment = TapestrySegment(
                    code=segment_code,
                    name=segment_name,
                    householdShare=share,
                    householdCount=count,
                    lifeMode=life_mode,
                    lifeStage=life_stage,
                )
                stores_dict[store_id].segments.append(segment)

    # Enrich segments with additional profile data from Esri
    for store in stores_dict.values():
        enrich_store_segments(store)

    return list(stores_dict.values())


async def generate_tapestry_report(store: Store, goal: str | None = None) -> str:
    """Generate an HTML report for a store's tapestry data.

    Uses Jinja2 templates for clean separation of concerns.
    PDF is generated on-demand when downloading.

    Args:
        store: The store to generate a report for
        goal: Optional business goal to focus insights on

    Returns:
        URL path to the generated HTML report
    """
    # Ensure output directory exists
    os.makedirs(settings.reports_output_path, exist_ok=True)

    # Enrich store segments with Esri profile data
    enrich_store_segments(store)

    # Sort segments by household share and get top 5
    top_segments = sorted(
        store.segments,
        key=lambda s: s.household_share,
        reverse=True
    )[:5]

    # Generate business insights with enriched segment data
    # Use by_alias=False to get snake_case keys (household_share, not householdShare)
    segment_data = [s.model_dump(by_alias=False) for s in top_segments]
    insights, insights_title = await generate_business_insights(
        store_name=store.name,
        segments=segment_data,
        goal=goal,
    )

    # Generate segment-specific insights for each segment (task 6)
    segment_insights = {}
    for seg in top_segments:
        insight = await generate_segment_insight(
            segment_name=seg.name,
            segment_code=seg.code,
            segment_description=seg.description or "",
            life_mode=seg.life_mode,
            household_share=seg.household_share,
            goal=goal,
            store_name=store.name,  # Pass store name for business type detection
        )
        segment_insights[seg.code] = markdown_to_html(insight)

    # Convert markdown in insights to HTML
    insights = markdown_to_html(insights)

    # Calculate max share for chart scaling
    max_share = max(seg.household_share for seg in top_segments) if top_segments else 1

    # Get base64 encoded assets
    logo_base64 = get_logo_base64()
    segment_images = {seg.code: get_segment_image_base64(seg.code) for seg in top_segments}

    # Render template
    env = _get_jinja_env()
    template = env.get_template("reports/tapestry/report.html")

    html_content = template.render(
        store=store,
        segments=top_segments,
        insights=insights,
        insights_title=insights_title,
        segment_insights=segment_insights,
        max_share=max_share,
        segment_colors=SEGMENT_COLORS,
        segment_images=segment_images,
        logo_base64=logo_base64,
        total_pages=3,
    )

    # Generate unique filename: [store_number] - [store_name] - Lifestyle report by Locaition Matters
    store_num = store.store_number or "unknown"
    store_name_safe = sanitize_filename(store.name)
    report_filename = f"{store_num}_{store_name_safe}_Lifestyle_report_by_Locaition_Matters.html"

    # Upload to cloud storage (or save locally as fallback)
    report_url = await upload_report(html_content, report_filename)

    # Also save locally for fallback/caching
    os.makedirs(settings.reports_output_path, exist_ok=True)
    report_path = os.path.join(settings.reports_output_path, report_filename)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return report_url


async def generate_multi_store_report(
    stores: list[Store],
    goal: str | None = None
) -> str:
    """Generate an HTML report for multiple stores' tapestry data.

    Each store gets 3 pages in the combined report.

    Args:
        stores: List of stores to generate reports for
        goal: Optional business goal to focus insights on

    Returns:
        URL path to the generated HTML report
    """
    # Ensure output directory exists
    os.makedirs(settings.reports_output_path, exist_ok=True)

    # Get base64 encoded logo
    logo_base64 = get_logo_base64()

    # Prepare data for each store
    stores_data = []
    total_pages = len(stores) * 3  # 3 pages per store

    for idx, store in enumerate(stores):
        # Enrich store segments with Esri profile data
        enrich_store_segments(store)

        # Sort segments by household share and get top 5
        top_segments = sorted(
            store.segments,
            key=lambda s: s.household_share,
            reverse=True
        )[:5]

        # Generate business insights with enriched segment data
        # Use by_alias=False to get snake_case keys (household_share, not householdShare)
        segment_data = [s.model_dump(by_alias=False) for s in top_segments]
        insights, insights_title = await generate_business_insights(
            store_name=store.name,
            segments=segment_data,
            goal=goal,
        )

        # Generate segment-specific insights for each segment (task 6)
        segment_insights = {}
        for seg in top_segments:
            insight = await generate_segment_insight(
                segment_name=seg.name,
                segment_code=seg.code,
                segment_description=seg.description or "",
                life_mode=seg.life_mode,
                household_share=seg.household_share,
                goal=goal,
                store_name=store.name,  # Pass store name for business type detection
            )
            segment_insights[seg.code] = markdown_to_html(insight)

        # Convert markdown in insights to HTML
        insights = markdown_to_html(insights)

        # Calculate max share for chart scaling
        max_share = max(seg.household_share for seg in top_segments) if top_segments else 1

        # Get base64 encoded segment images
        segment_images = {seg.code: get_segment_image_base64(seg.code) for seg in top_segments}

        stores_data.append({
            'store': store,
            'segments': top_segments,
            'insights': insights,
            'insights_title': insights_title,
            'segment_insights': segment_insights,
            'max_share': max_share,
            'segment_images': segment_images,
            'start_page': idx * 3 + 1,  # 1-indexed page number
        })

    # Build report title
    if len(stores) == 1:
        report_title = stores[0].name
    elif len(stores) <= 3:
        report_title = " & ".join([s.name for s in stores])
    else:
        report_title = f"{len(stores)} Stores Combined Report"

    # Render template
    env = _get_jinja_env()
    template = env.get_template("reports/tapestry/multi_store_report.html")

    html_content = template.render(
        stores_data=stores_data,
        report_title=report_title,
        segment_colors=SEGMENT_COLORS,
        logo_base64=logo_base64,
        total_pages=total_pages,
    )

    # Generate unique filename: [store_number] - [store_name] - Lifestyle report by Locaition Matters
    if len(stores) == 1:
        store = stores[0]
        store_num = store.store_number or "unknown"
        store_name_safe = sanitize_filename(store.name)
        report_filename = f"{store_num}_-_{store_name_safe}_-_Lifestyle_report_by_Locaition_Matters.html"
    else:
        report_filename = f"Multi_Store_{len(stores)}_stores_-_Lifestyle_report_by_Locaition_Matters.html"

    # Upload to cloud storage (or save locally as fallback)
    report_url = await upload_report(html_content, report_filename)

    # Also save locally for fallback/caching
    os.makedirs(settings.reports_output_path, exist_ok=True)
    report_path = os.path.join(settings.reports_output_path, report_filename)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return report_url


def generate_pdf_from_html(html_path: str) -> bytes | None:
    """Generate PDF from an HTML file.

    Uses WeasyPrint if available (faster, better for production).
    Falls back to Playwright (browser-based) if WeasyPrint is unavailable.

    Args:
        html_path: Path to the HTML file

    Returns:
        PDF bytes if successful, None if no PDF generator is available
    """
    # Try WeasyPrint first (faster, better for production with system libs)
    if WEASYPRINT_AVAILABLE:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTML(string=html_content).write_pdf()

    # Fall back to Playwright (browser-based, works everywhere)
    if PLAYWRIGHT_AVAILABLE:
        return _generate_pdf_with_playwright(html_path)

    return None


def _generate_pdf_with_playwright(html_path: str) -> bytes | None:
    """Generate PDF using Playwright (headless Chromium).

    This is a fallback when WeasyPrint system libraries are unavailable.

    Args:
        html_path: Path to the HTML file

    Returns:
        PDF bytes if successful, None on error
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()

            # Load the HTML file
            file_url = f"file://{os.path.abspath(html_path)}"
            page.goto(file_url, wait_until="networkidle")

            # Generate PDF with print-friendly settings
            pdf_bytes = page.pdf(
                format="Letter",
                print_background=True,
                margin={
                    "top": "0",
                    "right": "0",
                    "bottom": "0",
                    "left": "0"
                }
            )

            browser.close()
            return pdf_bytes
    except Exception as e:
        logger.warning(f"Playwright PDF generation failed: {e}")
        return None
