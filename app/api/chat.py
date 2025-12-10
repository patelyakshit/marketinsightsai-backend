import logging
import os
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import StreamingResponse
from typing import Optional, Annotated

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db.database import get_db
from app.db.models import Folder, FolderFile
from app.models.schemas import (
    ChatRequest, ChatResponse, ImageGenerationRequest, ImageGenerationResponse,
    AIChatResponse, Store, TapestrySegment, MapAction, MapLocation,
    MarketingAction, MarketingActionType, MarketingRecommendation, MarketingPlatform,
)
from app.services.ai_service import (
    get_chat_response, get_chat_response_streaming, generate_image,
    detect_map_command, handle_map_command, handle_disambiguation_choice,
    detect_marketing_request, detect_approval_response, detect_report_request,
    detect_business_goal,
    generate_marketing_recommendation, build_marketing_response_text,
    generate_marketing_image
)
from app.services.tapestry_service import parse_tapestry_xlsx, generate_tapestry_report, generate_multi_store_report

router = APIRouter()

# In-memory store for uploaded data (shared with reports module)
_chat_stores: dict[str, Store] = {}

# Store pending disambiguation options for follow-up
_pending_disambiguation: dict[str, list[MapLocation]] = {}

# Store pending marketing recommendation for follow-up approval
_pending_marketing: dict[str, MarketingRecommendation] = {}

# Store pending report request (awaiting store selection or goal)
# Structure: {"latest": {"stage": "awaiting_stores" | "awaiting_goal", "stores": [...], "file_uploaded": bool}}
_pending_report: dict[str, dict] = {}


async def get_folder_files_context(folder_id: str, db: AsyncSession) -> tuple[str, list[str]]:
    """
    Load folder files and extract their content as context for AI.
    Returns (context_text, file_names).
    """
    import pandas as pd
    from io import BytesIO

    result = await db.execute(
        select(Folder)
        .where(Folder.id == folder_id)
        .options(selectinload(Folder.files))
    )
    folder = result.scalar_one_or_none()

    if not folder or not folder.files:
        return "", []

    context_parts = []
    file_names = []

    for file in folder.files:
        file_names.append(file.original_filename)
        file_type = file.file_type.value

        # Read file content based on type
        try:
            if not os.path.exists(file.file_path):
                continue

            if file_type in ['xlsx', 'xls']:
                # Parse Excel files
                with open(file.file_path, 'rb') as f:
                    df = pd.read_excel(BytesIO(f.read()), nrows=100)  # Limit rows
                    preview = df.to_string(max_rows=50, max_cols=10)
                    context_parts.append(f"**File: {file.original_filename}** (Excel)\n```\n{preview}\n```\n")
            elif file_type == 'csv':
                # Parse CSV files
                with open(file.file_path, 'rb') as f:
                    df = pd.read_csv(BytesIO(f.read()), nrows=100)
                    preview = df.to_string(max_rows=50, max_cols=10)
                    context_parts.append(f"**File: {file.original_filename}** (CSV)\n```\n{preview}\n```\n")
            elif file_type in ['txt', 'json']:
                # Read text files
                with open(file.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(10000)  # Limit to 10KB
                    context_parts.append(f"**File: {file.original_filename}** ({file_type.upper()})\n```\n{content}\n```\n")
            elif file_type == 'pdf':
                # Note: PDF parsing would require additional library like pypdf
                context_parts.append(f"**File: {file.original_filename}** (PDF) - Content preview not available")
            else:
                context_parts.append(f"**File: {file.original_filename}** - Binary file, content not available")
        except Exception as e:
            logger.warning(f"Error reading file {file.original_filename}: {e}")
            context_parts.append(f"**File: {file.original_filename}** - Error reading content")

    if not context_parts:
        return "", file_names

    context_text = "The following files are available in this folder for reference:\n\n" + "\n".join(context_parts)
    return context_text, file_names


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a message to the AI assistant."""
    try:
        response, sources = await get_chat_response(
            message=request.message,
            use_knowledge_base=request.use_knowledge_base
        )
        return ChatResponse(response=response, sources=sources)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/with-file", response_model=AIChatResponse)
async def chat_with_file(
    message: str = Form(..., max_length=10000),
    file: Optional[UploadFile] = File(None),  # File size is handled at server level
    store_id: Optional[str] = Form(None),
    action: Optional[str] = Form(None),
    goal: Optional[str] = Form(None),
    stores_json: Optional[str] = Form(None),
    pending_marketing_json: Optional[str] = Form(None),
    folder_id: Optional[str] = Form(None),  # Folder context for auto-including files
    db: AsyncSession = Depends(get_db),  # Database session for folder file access
):
    """
    AI chat that can handle file uploads and generate reports.

    - Upload a tapestry XLSX file to extract store data
    - Use action='generate_report' with store_id and optional goal to generate a report
    - Pass stores_json to restore stores from frontend state (handles server restarts)
    - Pass folder_id to include folder files as context for the AI
    """
    import json

    try:
        stores: list[Store] = []
        report_url: Optional[str] = None
        sources: list[str] = []
        folder_context = ""
        folder_file_names: list[str] = []

        # Load folder files context if folder_id is provided
        if folder_id:
            try:
                folder_context, folder_file_names = await get_folder_files_context(folder_id, db)
                if folder_file_names:
                    logger.debug(f"Loaded {len(folder_file_names)} files from folder {folder_id}: {folder_file_names}")
            except Exception as e:
                logger.warning(f"Error loading folder files: {e}")

        # Restore stores from frontend if provided (handles server restart case)
        if stores_json:
            try:
                stores_data = json.loads(stores_json)
                for store_data in stores_data:
                    # Handle both camelCase (from frontend) and snake_case field names
                    segments = []
                    for seg in store_data.get('segments', []):
                        segments.append(TapestrySegment(
                            code=seg.get('code', ''),
                            name=seg.get('name', ''),
                            household_share=seg.get('householdShare', seg.get('household_share', 0)),
                            household_count=seg.get('householdCount', seg.get('household_count', 0)),
                            life_mode=seg.get('lifeMode', seg.get('life_mode', '')),
                            life_stage=seg.get('lifeStage', seg.get('life_stage', '')),
                            description=seg.get('description'),
                            median_age=seg.get('medianAge', seg.get('median_age')),
                            median_household_income=seg.get('medianHouseholdIncome', seg.get('median_household_income')),
                            median_net_worth=seg.get('medianNetWorth', seg.get('median_net_worth')),
                            homeownership_rate=seg.get('homeownershipRate', seg.get('homeownership_rate')),
                        ))

                    store = Store(
                        id=store_data.get('id', ''),
                        name=store_data.get('name', ''),
                        address=store_data.get('address'),
                        store_number=store_data.get('storeNumber', store_data.get('store_number')),
                        drive_time=store_data.get('driveTime', store_data.get('drive_time')),
                        segments=segments,
                    )
                    _chat_stores[store.id] = store
            except Exception as e:
                logger.warning(f"Failed to restore stores from frontend: {e}")

        # Restore pending marketing recommendation from frontend (handles server restart)
        if pending_marketing_json:
            try:
                marketing_data = json.loads(pending_marketing_json)
                # Reconstruct the MarketingRecommendation
                suggested_platforms = []
                for p in marketing_data.get('suggestedPlatforms', marketing_data.get('suggested_platforms', [])):
                    if isinstance(p, str):
                        suggested_platforms.append(MarketingPlatform(p))
                    else:
                        suggested_platforms.append(p)

                recommendation = MarketingRecommendation(
                    store_id=marketing_data.get('storeId', marketing_data.get('store_id', '')),
                    store_name=marketing_data.get('storeName', marketing_data.get('store_name', '')),
                    headline=marketing_data.get('headline', ''),
                    body=marketing_data.get('body', ''),
                    hashtags=marketing_data.get('hashtags', []),
                    suggested_platforms=suggested_platforms if suggested_platforms else [MarketingPlatform.instagram],
                    visual_concept=marketing_data.get('visualConcept', marketing_data.get('visual_concept', '')),
                    segment_insights=marketing_data.get('segmentInsights', marketing_data.get('segment_insights', '')),
                    awaiting_approval=True,
                )
                _pending_marketing["latest"] = recommendation
            except Exception as e:
                logger.warning(f"Failed to restore pending marketing from frontend: {e}")

        # Handle pending report flow (two-step: store selection -> goal selection)
        if "latest" in _pending_report:
            pending = _pending_report["latest"]
            stage = pending.get("stage")

            # Stage 1: User responding with store selection
            if stage == "awaiting_stores":
                # Try to detect stores from the message
                is_all_stores = any(p in message.lower() for p in ['all stores', 'all of them', 'every store', 'all locations'])

                if is_all_stores:
                    # User wants all stores
                    selected_store_ids = list(_chat_stores.keys())
                    selected_store_names = [_chat_stores[sid].name for sid in selected_store_ids]
                else:
                    # Try to find store mentions using fuzzy matching
                    from app.services.ai_service import find_store_mentions_fuzzy
                    exact_match_ids, fuzzy_suggestions = find_store_mentions_fuzzy(message, _chat_stores)

                    if fuzzy_suggestions and not exact_match_ids:
                        # Got fuzzy matches - ask for confirmation
                        suggestion_lines = [f"- \"{fs.query}\" → Did you mean **{fs.store_name}**?" for fs in fuzzy_suggestions]
                        return AIChatResponse(
                            response=f"I'm not sure about the store name(s) you mentioned:\n\n" + "\n".join(suggestion_lines) + "\n\nPlease confirm or correct the store names.",
                            sources=[],
                            stores=list(_chat_stores.values()),
                        )

                    if not exact_match_ids:
                        # Couldn't find any stores
                        store_names = [s.name for s in _chat_stores.values()]
                        return AIChatResponse(
                            response=f"I couldn't find that store. Available stores are: {', '.join(store_names[:10])}{'...' if len(store_names) > 10 else ''}.\n\nPlease try again with the exact store name, or say \"all stores\" for a combined report.",
                            sources=[],
                            stores=list(_chat_stores.values()),
                        )

                    selected_store_ids = exact_match_ids
                    selected_store_names = [_chat_stores[sid].name for sid in selected_store_ids]

                # Update pending state to awaiting goal
                _pending_report["latest"] = {
                    "stage": "awaiting_goal",
                    "selected_store_ids": selected_store_ids,
                    "selected_store_names": selected_store_names,
                }

                # Ask for business goal
                stores_text = ", ".join(selected_store_names) if len(selected_store_names) <= 3 else f"{len(selected_store_names)} stores"
                response_msg = f"""Great! I'll generate a report for **{stores_text}**.

What's the **business goal** for this report? This helps me tailor the insights.

Options:
- **Standard** - General tapestry analysis with demographic insights
- **Instagram campaign** - Insights focused on visual content and Instagram audience targeting
- **Facebook campaign** - Community engagement and Facebook ad targeting
- **Newsletter** - Email marketing content ideas
- **Local marketing** - In-store promotions and local outreach
- **Promotions** - Discount and deal strategies

Just tell me your goal (e.g., "Instagram campaign" or "standard")!"""

                return AIChatResponse(
                    response=response_msg,
                    sources=[],
                    stores=list(_chat_stores.values()),
                )

            # Stage 2: User responding with business goal
            elif stage == "awaiting_goal":
                selected_store_ids = pending.get("selected_store_ids", [])
                selected_store_names = pending.get("selected_store_names", [])

                # Detect the business goal from the message
                is_goal, detected_goal = detect_business_goal(message)

                if not is_goal:
                    # Check for simple keywords as fallback
                    msg_lower = message.lower()
                    if any(kw in msg_lower for kw in ['standard', 'regular', 'normal', 'basic', 'general']):
                        detected_goal = "standard"
                    elif any(kw in msg_lower for kw in ['instagram', 'insta', 'ig']):
                        detected_goal = "instagram"
                    elif any(kw in msg_lower for kw in ['facebook', 'fb']):
                        detected_goal = "facebook"
                    elif any(kw in msg_lower for kw in ['newsletter', 'email']):
                        detected_goal = "newsletter"
                    elif any(kw in msg_lower for kw in ['local', 'in-store', 'community']):
                        detected_goal = "local_marketing"
                    elif any(kw in msg_lower for kw in ['promo', 'discount', 'sale', 'deal']):
                        detected_goal = "promotions"
                    elif any(kw in msg_lower for kw in ['linkedin']):
                        detected_goal = "linkedin"
                    elif any(kw in msg_lower for kw in ['ad', 'advertising', 'campaign', 'paid']):
                        detected_goal = "ad_campaign"
                    else:
                        # Default to standard if we can't detect
                        detected_goal = "standard"

                # Clear pending state
                del _pending_report["latest"]

                # Generate the report(s)
                if len(selected_store_ids) == 1:
                    # Single store report
                    store = _chat_stores.get(selected_store_ids[0])
                    if store:
                        report_url = await generate_tapestry_report(store, goal=detected_goal)
                        goal_text = detected_goal if detected_goal != "standard" else "standard"
                        response_msg = f"I've generated a **{goal_text}** tapestry report for **{store.name}**. The insights are tailored for your {goal_text} goals. You can view it in the preview panel or download it."
                        return AIChatResponse(
                            response=response_msg,
                            sources=["Esri Tapestry Segmentation"],
                            stores=list(_chat_stores.values()),
                            report_url=report_url,
                        )
                else:
                    # Multi-store report
                    stores_to_report = [_chat_stores[sid] for sid in selected_store_ids if sid in _chat_stores]
                    if stores_to_report:
                        report_url = await generate_multi_store_report(stores_to_report, goal=detected_goal)
                        goal_text = detected_goal if detected_goal != "standard" else "standard"
                        store_count = len(stores_to_report)
                        response_msg = f"I've generated a **{goal_text}** tapestry report for **{store_count} stores**. The report includes {store_count * 3} pages with insights tailored for your {goal_text} goals. You can view it in the preview panel or download it."
                        return AIChatResponse(
                            response=response_msg,
                            sources=["Esri Tapestry Segmentation"],
                            stores=list(_chat_stores.values()),
                            report_url=report_url,
                        )

                # Fallback if something went wrong
                return AIChatResponse(
                    response="I encountered an issue generating the report. Please try again.",
                    sources=[],
                    stores=list(_chat_stores.values()),
                )

        # Handle file upload
        if file and file.filename:
            if not file.filename.endswith(('.xlsx', '.xls')):
                return AIChatResponse(
                    response="Please upload an Excel file (.xlsx or .xls) containing your tapestry data.",
                    sources=[],
                    stores=[],
                )

            contents = await file.read()
            stores = await parse_tapestry_xlsx(contents)

            # Store for later use
            for store in stores:
                _chat_stores[store.id] = store

            # Check if user is asking to generate report along with upload
            message_lower = message.lower()
            is_report_with_upload = any(kw in message_lower for kw in [
                'generate report', 'create report', 'make report', 'tapestry report',
                'generate a report', 'create a report', 'make a report'
            ])

            if is_report_with_upload and len(stores) > 0:
                # Start two-step flow: ask for store selection
                store_names = [s.name for s in stores]
                store_list = "\n".join([f"- **{s.name}**" for s in stores[:10]])
                if len(stores) > 10:
                    store_list += f"\n- ... and {len(stores) - 10} more"

                # Set pending state for store selection
                _pending_report["latest"] = {
                    "stage": "awaiting_stores",
                    "file_uploaded": True,
                }

                example_store = stores[0].name if stores else "Store Name"
                response_msg = f"""I found **{len(stores)} store(s)** in your tapestry file:

{store_list}

Which store(s) would you like me to generate a report for?

You can specify:
- A single store by name (e.g., "{example_store}")
- Multiple stores (e.g., "{stores[0].name} and {stores[1].name if len(stores) > 1 else 'Store B'}")
- **All stores** for a combined report

Just let me know which one(s)!"""

                return AIChatResponse(
                    response=response_msg,
                    sources=[],
                    stores=stores,
                )

            # Regular upload without report request - show summary
            store_names = [s.name for s in stores]
            store_summaries = []
            for store in stores:
                top_segments = sorted(store.segments, key=lambda s: s.household_share, reverse=True)[:3]
                segments_info = ", ".join([f"{s.name} ({s.household_share:.1f}%)" for s in top_segments])
                store_summaries.append(f"**{store.name}**: Top segments are {segments_info}")

            ai_context = f"""The user uploaded a tapestry file containing data for {len(stores)} store(s): {', '.join(store_names)}.

Here's a summary of each store's top segments:
{chr(10).join(store_summaries)}

The user said: "{message}"

Respond naturally about what you found. Mention key insights from the data and suggest they can click on a store to generate a detailed report."""

            response, sources = await get_chat_response(
                message=ai_context,
                use_knowledge_base=True,
                folder_context=folder_context
            )

            return AIChatResponse(
                response=response,
                sources=sources,
                stores=stores,
            )

        # Handle report generation (from action parameter or natural language)
        report_store_ids = store_id  # Can be single ID or list
        report_goal = goal
        is_report_request = False
        is_all_stores = False

        # If no explicit action, check if message is a report request
        fuzzy_suggestions = []
        if not (action == "generate_report" and store_id):
            is_report_request, detected_store_ids, detected_goal, is_all_stores, fuzzy_suggestions = detect_report_request(message, _chat_stores)
            if is_report_request:
                report_store_ids = detected_store_ids
                report_goal = detected_goal or "generic"

        # Handle "all stores" request
        if is_report_request and is_all_stores:
            if not _chat_stores:
                return AIChatResponse(
                    response="I'd love to generate a report for all stores, but I need store data first. Please upload a tapestry file with store segment information.",
                    sources=[],
                    stores=[],
                )

            # Generate multi-store report for all stores
            all_stores = list(_chat_stores.values())
            report_url = await generate_multi_store_report(all_stores, goal=report_goal)

            store_count = len(all_stores)
            if report_goal and report_goal != "generic":
                response_msg = f"I've generated a {report_goal}-focused tapestry report for all {store_count} stores. The report includes {store_count * 3} pages (3 pages per store). You can view it in the preview panel or download it."
            else:
                response_msg = f"I've generated a combined tapestry report for all {store_count} stores. The report includes {store_count * 3} pages (3 pages per store). You can view it in the preview panel or download it."

            return AIChatResponse(
                response=response_msg,
                sources=["Esri Tapestry Segmentation"],
                stores=all_stores,
                report_url=report_url,
            )

        # If there are fuzzy suggestions (potential typos), ask for clarification
        if is_report_request and fuzzy_suggestions:
            # Build clarification message with suggestions
            suggestion_lines = []
            for fs in fuzzy_suggestions:
                suggestion_lines.append(f"- \"{fs.query}\" → Did you mean **{fs.store_name}**?")

            suggestions_text = "\n".join(suggestion_lines)

            # If we also have some exact matches, mention them
            matched_names = []
            if report_store_ids:
                if isinstance(report_store_ids, list):
                    matched_names = [_chat_stores[sid].name for sid in report_store_ids if sid in _chat_stores]
                elif report_store_ids in _chat_stores:
                    matched_names = [_chat_stores[report_store_ids].name]

            if matched_names:
                response_msg = f"I found **{', '.join(matched_names)}**, but I'm not sure about some other names you mentioned:\n\n{suggestions_text}\n\nPlease confirm or correct the store names, and I'll generate the report."
            else:
                response_msg = f"I couldn't find exact matches for the store names you mentioned. Did you mean:\n\n{suggestions_text}\n\nPlease confirm or let me know the correct store names."

            return AIChatResponse(
                response=response_msg,
                sources=[],
                stores=list(_chat_stores.values()) if _chat_stores else [],
            )

        # If report is requested but no store found, ask for clarification
        if is_report_request and not report_store_ids:
            if not _chat_stores:
                return AIChatResponse(
                    response="I'd love to generate a report, but I need store data first. Please upload a tapestry file with store segment information, then ask me to generate a report.",
                    sources=[],
                    stores=[],
                )
            else:
                store_names = [s.name for s in _chat_stores.values()]
                return AIChatResponse(
                    response=f"I'd be happy to generate a report! I found {len(store_names)} store(s) in your data: {', '.join(store_names[:5])}{'...' if len(store_names) > 5 else ''}.\n\nWhich store would you like a report for? You can:\n- Name a specific store\n- List multiple stores (e.g., \"Store A and Store B\")\n- Say \"all stores\" to generate a combined report",
                    sources=[],
                    stores=list(_chat_stores.values()),
                )

        # Handle multiple stores (list of IDs)
        if is_report_request and isinstance(report_store_ids, list) and len(report_store_ids) > 1:
            stores_to_report = []
            for sid in report_store_ids:
                store = _chat_stores.get(sid)
                if store:
                    stores_to_report.append(store)

            if not stores_to_report:
                return AIChatResponse(
                    response="I couldn't find those stores. Please upload your tapestry file first.",
                    sources=[],
                    stores=list(_chat_stores.values()) if _chat_stores else [],
                )

            # Generate multi-store report
            report_url = await generate_multi_store_report(stores_to_report, goal=report_goal)

            store_names = [s.name for s in stores_to_report]
            store_count = len(stores_to_report)
            if report_goal and report_goal != "generic":
                response_msg = f"I've generated a {report_goal}-focused tapestry report for {store_count} stores: {', '.join(store_names)}. The report includes {store_count * 3} pages (3 pages per store). You can view it in the preview panel or download it."
            else:
                response_msg = f"I've generated a combined tapestry report for {store_count} stores: {', '.join(store_names)}. The report includes {store_count * 3} pages (3 pages per store). You can view it in the preview panel or download it."

            return AIChatResponse(
                response=response_msg,
                sources=["Esri Tapestry Segmentation"],
                stores=list(_chat_stores.values()) if _chat_stores else [],
                report_url=report_url,
            )

        # Handle single store (original logic)
        single_store_id = report_store_ids[0] if isinstance(report_store_ids, list) else report_store_ids

        if (action == "generate_report" and single_store_id) or (single_store_id and is_report_request):
            store = _chat_stores.get(single_store_id)
            if not store:
                return AIChatResponse(
                    response="I couldn't find that store. Please upload your tapestry file first.",
                    sources=[],
                    stores=list(_chat_stores.values()) if _chat_stores else [],
                )

            # Pass the business goal to the report generator
            report_url = await generate_tapestry_report(store, goal=report_goal)

            # Build response message based on goal
            if report_goal and report_goal != "generic":
                response_msg = f"I've generated a {report_goal}-focused tapestry report for {store.name}. The insights are tailored to help with your {report_goal} goals. You can view it in the preview panel or download it."
            else:
                response_msg = f"I've generated the tapestry report for {store.name}. You can view it in the preview panel or download it."

            return AIChatResponse(
                response=response_msg,
                sources=["Esri Tapestry Segmentation"],
                stores=list(_chat_stores.values()) if _chat_stores else [],
                report_url=report_url,
            )

        # Check for marketing post requests
        is_marketing, store_ref, platform = detect_marketing_request(message, _chat_stores)

        if is_marketing:
            # Find the store to use
            store = None
            if store_ref:
                store = _chat_stores.get(store_ref)
            elif len(_chat_stores) == 1:
                store = list(_chat_stores.values())[0]

            if not store:
                return AIChatResponse(
                    response="I'd love to help create a marketing post, but I need store data first. Please upload a tapestry file with store segment information, then ask me to create a marketing post.",
                    sources=[],
                    stores=list(_chat_stores.values()) if _chat_stores else [],
                )

            # Generate marketing recommendation
            recommendation = await generate_marketing_recommendation(store, platform)

            # Store for follow-up approval
            _pending_marketing["latest"] = recommendation

            # Build response
            response_text = build_marketing_response_text(recommendation)

            return AIChatResponse(
                response=response_text,
                sources=["Esri Tapestry Segmentation"],
                stores=list(_chat_stores.values()) if _chat_stores else [],
                marketing_action=MarketingAction(
                    type=MarketingActionType.recommendation,
                    recommendation=recommendation,
                ),
            )

        # Check for marketing approval/platform selection (follow-up to recommendation)
        if "latest" in _pending_marketing:
            is_approval, selected_platform = detect_approval_response(message)

            if is_approval:
                recommendation = _pending_marketing["latest"]

                # Use selected platform or default to first suggested
                final_platform = selected_platform or recommendation.suggested_platforms[0]

                # Get the store if available
                store = _chat_stores.get(recommendation.store_id)

                # Clear pending state
                del _pending_marketing["latest"]

                # Generate the marketing image
                marketing_post = await generate_marketing_image(
                    recommendation=recommendation,
                    platform=final_platform,
                    store=store,
                )

                return AIChatResponse(
                    response=f"Your {final_platform.value.title()} marketing post for {recommendation.store_name} is ready! I've created a beautiful image based on your customer demographics. You can view it in the Studio panel, download it, or save it to your library.",
                    sources=["Esri Tapestry Segmentation", "Gemini Imagen 3"],
                    stores=list(_chat_stores.values()) if _chat_stores else [],
                    marketing_action=MarketingAction(
                        type=MarketingActionType.generate_image,
                        recommendation=recommendation,
                        platform=final_platform,
                        post=marketing_post,
                    ),
                )

        # Check for map navigation commands
        is_map_cmd, location_query = detect_map_command(message)

        if is_map_cmd and location_query:
            response_msg, map_action = await handle_map_command(location_query)

            # Store disambiguation options for potential follow-up
            if map_action and map_action.type.value == "disambiguate":
                _pending_disambiguation["latest"] = map_action.options

            return AIChatResponse(
                response=response_msg,
                sources=[],
                stores=list(_chat_stores.values()) if _chat_stores else [],
                map_action=map_action,
            )

        # Check if this might be a disambiguation response (number or location refinement)
        if "latest" in _pending_disambiguation:
            # Check if user is responding to disambiguation
            msg_stripped = message.strip()
            is_number = msg_stripped.isdigit()
            is_short_response = len(msg_stripped.split()) <= 3

            if is_number or is_short_response:
                response_msg, map_action = await handle_disambiguation_choice(
                    msg_stripped,
                    _pending_disambiguation["latest"]
                )

                if map_action and map_action.type.value == "zoom_to":
                    # Clear disambiguation state on successful choice
                    del _pending_disambiguation["latest"]

                    return AIChatResponse(
                        response=response_msg,
                        sources=[],
                        stores=list(_chat_stores.values()) if _chat_stores else [],
                        map_action=map_action,
                    )

        # Regular chat without file
        response, sources = await get_chat_response(
            message=message,
            use_knowledge_base=True,
            folder_context=folder_context
        )

        return AIChatResponse(
            response=response,
            sources=sources,
            stores=list(_chat_stores.values()) if _chat_stores else [],
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Log the full error for debugging
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"Error in chat_with_file: {str(e)}")
        logger.error(f"Traceback: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/image", response_model=ImageGenerationResponse)
async def generate_image_endpoint(request: ImageGenerationRequest):
    """Generate an image based on the prompt."""
    try:
        image_url, description = await generate_image(request.prompt)
        return ImageGenerationResponse(imageUrl=image_url, description=description)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stores")
async def get_chat_stores():
    """Get all stores uploaded via chat."""
    return {"stores": list(_chat_stores.values())}


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    Stream a chat response token by token.

    Returns a text/event-stream response with chunks of the AI response.
    The final chunk contains sources as JSON with __SOURCES__ prefix.
    """
    async def generate():
        try:
            async for chunk in get_chat_response_streaming(
                message=request.message,
                use_knowledge_base=request.use_knowledge_base
            ):
                # Send each chunk as a Server-Sent Event
                yield f"data: {chunk}\n\n"
        except Exception as e:
            yield f"data: Error: {str(e)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
