import logging
import re
import uuid
import base64
import os
from datetime import datetime

logger = logging.getLogger(__name__)
from difflib import SequenceMatcher
from openai import AsyncOpenAI
from google import genai
from google.genai import types
from app.config import get_settings
from app.services.kb_service import search_documents
from app.services.esri_service import (
    get_segment_context_for_ai,
    search_segments_by_name,
    get_all_segment_codes,
    geocode_location,
    get_segment_profile,
    SEGMENT_PROFILES,
)
from app.models.schemas import (
    MapAction, MapActionType, MapLocation,
    MarketingRecommendation, MarketingPost, MarketingPlatform,
    MarketingAction, MarketingActionType, Store, TapestrySegment
)

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

# Initialize Gemini client for image generation
gemini_client = None
if settings.google_api_key:
    gemini_client = genai.Client(api_key=settings.google_api_key)

# Ensure reports directory exists for generated images
GENERATED_IMAGES_DIR = os.path.join(settings.reports_output_path, "generated_images")
os.makedirs(GENERATED_IMAGES_DIR, exist_ok=True)


# Mapping of segment names to codes for detection (2025 ArcGIS Tapestry)
SEGMENT_NAME_TO_CODE = {
    # LifeMode A - Urban Threads
    "independent cityscapes": "A1",
    "city commons": "A2",
    "city strivers": "A3",
    "urban edge families": "A4",
    "forging opportunity": "A5",
    "hardscrabble road": "A6",
    # LifeMode B - Campus & Careers
    "dorms to diplomas": "B1",
    "metro renters": "B2",
    "young and restless": "B3",
    # LifeMode C - Singles Scene
    "single thrifties": "C1",
    "set to impress": "C2",
    "bright young professionals": "C3",
    "enterprising professionals": "C4",
    "laptops and lattes": "C5",
    "trendsetters": "C6",
    # LifeMode D - Progress & Prestige
    "metro fusion": "D1",
    "city lights": "D2",
    "urban villages": "D3",
    "up and coming families": "D4",
    "emerald city": "D5",
    # LifeMode E - Booming Economies
    "boomburbs": "E1",
    "professional pride": "E2",
    "savvy suburbanites": "E3",
    "soccer moms": "E4",
    "home improvement": "E5",
    "pleasantville": "E6",
    # LifeMode F - Flourishing Families
    "urban chic": "F1",
    "front porches": "F2",
    "middleburg": "F3",
    "rustbelt traditions": "F4",
    "midlife constants": "F5",
    # LifeMode G - Ageless Austerity
    "social security set": "G1",
    "the elders": "G2",
    "old and newcomers": "G3",
    # LifeMode H - Comfortable Decades
    "comfortable empty nesters": "H1",
    "golden years": "H2",
    "silver and gold": "H3",
    "senior sun seekers": "H4",
    # LifeMode I - Rustic Simplicity
    "down the road": "I1",
    "rural bypasses": "I2",
    "southern satellites": "I3",
    "diners and miners": "I4",
    "rooted rural": "I5",
    "heartland communities": "I6",
    "small town simplicity": "I7",
    # LifeMode J - Open Air
    "green acres": "J1",
    "salt of the earth": "J2",
    "the great outdoors": "J3",
    "prairie living": "J4",
    # LifeMode K - Settling In
    "parks and rec": "K1",
    "in style": "K2",
    "modest income homes": "K3",
    "traditional living": "K4",
    "family foundations": "K5",
    "exurbanites": "K6",
    "rural resort dwellers": "K7",
    "retirement communities": "K8",
    # LifeMode L - Affluent Estates
    "pacific heights": "L1",
    "downtown melting pot": "L2",
    "top tier": "L3",
}


# =============================================================================
# Fuzzy Matching for Store Names
# =============================================================================

class FuzzyMatch:
    """Represents a fuzzy match result for store name detection."""
    def __init__(self, query: str, store_id: str, store_name: str, score: float):
        self.query = query  # The original text the user typed
        self.store_id = store_id
        self.store_name = store_name
        self.score = score  # Similarity score 0-1


def fuzzy_match_store_name(query: str, store_name: str) -> float:
    """
    Calculate similarity between query and store name using SequenceMatcher.
    Returns a score between 0 and 1.
    """
    query_lower = query.lower().strip()
    store_lower = store_name.lower().strip()

    # Exact match
    if query_lower == store_lower:
        return 1.0

    # Check if query is contained in store name or vice versa
    if query_lower in store_lower or store_lower in query_lower:
        return 0.9

    # Use SequenceMatcher for fuzzy comparison
    return SequenceMatcher(None, query_lower, store_lower).ratio()


def find_store_mentions_fuzzy(
    message: str,
    available_stores: dict[str, "Store"],
    exact_threshold: float = 0.85,
    fuzzy_threshold: float = 0.5,
) -> tuple[list[str], list[FuzzyMatch]]:
    """
    Find store mentions in a message using both exact and fuzzy matching.
    IMPORTANT: Returns stores in the order they appear in the message.

    Args:
        message: User's message
        available_stores: Dict of store_id -> Store
        exact_threshold: Score threshold for exact matches (auto-accept)
        fuzzy_threshold: Score threshold for fuzzy matches (suggest to user)

    Returns:
        Tuple of (exact_match_ids, fuzzy_suggestions)
        - exact_match_ids: Store IDs that matched with high confidence, in message order
        - fuzzy_suggestions: FuzzyMatch objects for potential matches to confirm
    """
    message_lower = message.lower()
    matched_store_ids: set[str] = set()

    # Track matches with their position in the message for ordering
    # Each entry: (position, store_id, is_exact, fuzzy_match_or_none)
    matches_with_position: list[tuple[int, str, bool, FuzzyMatch | None]] = []

    # Remove common report-related words to isolate store name candidates
    report_keywords = [
        'generate', 'create', 'make', 'build', 'get', 'report', 'tapestry',
        'marketing', 'for', 'and', 'the', 'a', 'an', 'me', 'please', 'can',
        'you', 'could', 'would', 'with', 'about', 'on', 'all', 'stores'
    ]

    # Split by common delimiters (and, comma, etc.) but track positions
    # Use finditer to get positions
    delimiter_pattern = r'\s+(?:and|,)\s+|\s+&\s+'
    parts_with_pos: list[tuple[str, int]] = []

    last_end = 0
    for match in re.finditer(delimiter_pattern, message_lower):
        if last_end < match.start():
            parts_with_pos.append((message_lower[last_end:match.start()], last_end))
        last_end = match.end()
    if last_end < len(message_lower):
        parts_with_pos.append((message_lower[last_end:], last_end))

    for part, part_position in parts_with_pos:
        # Clean up the part
        words = part.split()
        # Filter out common keywords
        meaningful_words = [w for w in words if w not in report_keywords and len(w) > 2]
        if not meaningful_words:
            continue

        # Reconstruct potential store name candidate
        candidate = ' '.join(meaningful_words)
        if len(candidate) < 3:
            continue

        # First check for exact substring matches
        exact_found = False
        for store_id, store in available_stores.items():
            if store_id in matched_store_ids:
                continue

            store_name_lower = store.name.lower()
            if store_name_lower in part:
                matches_with_position.append((part_position, store_id, True, None))
                matched_store_ids.add(store_id)
                exact_found = True
                break

        if exact_found:
            continue

        # Check fuzzy match against all stores that weren't exactly matched
        best_match: FuzzyMatch | None = None
        best_score = 0.0
        best_store_id = None

        for store_id, store in available_stores.items():
            if store_id in matched_store_ids:
                continue

            score = fuzzy_match_store_name(candidate, store.name)

            # If it's a high-confidence match, treat as exact
            if score >= exact_threshold:
                matches_with_position.append((part_position, store_id, True, None))
                matched_store_ids.add(store_id)
                best_match = None  # Don't add to fuzzy suggestions
                break
            elif score >= fuzzy_threshold and score > best_score:
                best_score = score
                best_store_id = store_id
                best_match = FuzzyMatch(
                    query=candidate,
                    store_id=store_id,
                    store_name=store.name,
                    score=score
                )

        # Add fuzzy match if we found one and haven't already matched this store
        if best_match and best_store_id and best_store_id not in matched_store_ids:
            matches_with_position.append((part_position, best_store_id, False, best_match))
            # Don't add to matched_store_ids for fuzzy - user needs to confirm

    # Sort by position in message to preserve order
    matches_with_position.sort(key=lambda x: x[0])

    # Separate into exact matches and fuzzy suggestions, preserving order
    exact_matches: list[str] = []
    fuzzy_suggestions: list[FuzzyMatch] = []

    for _, store_id, is_exact, fuzzy_match in matches_with_position:
        if is_exact:
            exact_matches.append(store_id)
        elif fuzzy_match:
            fuzzy_suggestions.append(fuzzy_match)

    return exact_matches, fuzzy_suggestions


def detect_map_command(message: str) -> tuple[bool, str | None]:
    """
    Detect if user is asking for a map navigation command.

    Returns:
        Tuple of (is_map_command, location_query)
    """
    message_lower = message.lower().strip()

    # Patterns for map navigation commands
    zoom_patterns = [
        r"(?:zoom|go|navigate|fly|move|pan|show|take me|bring me|center)\s+(?:to|on|the map to|the map on|in on|map to)\s+(.+?)(?:\s+on the map)?$",
        r"(?:zoom|go|navigate|fly|move|pan|show|take me|bring me|center)\s+(?:the map\s+)?(?:to|on)\s+(.+)$",
        r"(?:show me|display|find|locate|search for|look at|focus on)\s+(.+?)(?:\s+on (?:the )?map)?$",
        r"(?:where is|where's)\s+(.+?)(?:\s+on (?:the )?map)?(?:\?)?$",
        r"(?:can you (?:show|zoom|go|navigate|fly) (?:me |to )?)?(.+?)(?:\s+on (?:the )?map)$",
    ]

    for pattern in zoom_patterns:
        match = re.search(pattern, message_lower, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            # Clean up common trailing words
            location = re.sub(r'\s*(?:please|now|quickly|for me|map|the map)$', '', location, flags=re.IGNORECASE)
            if location and len(location) > 1:
                return True, location

    # Check for simple location mentions with map context
    if any(word in message_lower for word in ['zoom', 'navigate', 'go to', 'show me', 'map']):
        # Extract potential location (capitalized words or quoted text)
        location_match = re.search(r'"([^"]+)"|\'([^\']+)\'', message)
        if location_match:
            location = location_match.group(1) or location_match.group(2)
            return True, location.strip()

    return False, None


async def handle_map_command(location_query: str) -> tuple[str, MapAction | None]:
    """
    Handle a map navigation command by geocoding the location.

    Args:
        location_query: The location to search for

    Returns:
        Tuple of (response_message, map_action)
    """
    results = await geocode_location(location_query, max_results=5)

    if not results:
        return (
            f"I couldn't find a location matching '{location_query}'. "
            "Could you please be more specific? For example, try including the state or country.",
            None
        )

    # If the top result has a very high score (>= 95), use it directly
    # This handles cases like "San Francisco, California" which should be unambiguous
    if results[0].score >= 95:
        result = results[0]
        location = MapLocation(
            name=result.address,
            longitude=result.location.get("x", 0),
            latitude=result.location.get("y", 0),
            zoom=12
        )
        return (
            f"Zooming to {result.address}.",
            MapAction(type=MapActionType.zoom_to, location=location, query=location_query)
        )

    # Filter high-confidence results (score > 80)
    good_results = [r for r in results if r.score > 80]

    if len(good_results) == 1:
        # Single clear match - zoom directly
        result = good_results[0]
        location = MapLocation(
            name=result.address,
            longitude=result.location.get("x", 0),
            latitude=result.location.get("y", 0),
            zoom=12
        )
        return (
            f"Zooming to {result.address}.",
            MapAction(type=MapActionType.zoom_to, location=location, query=location_query)
        )

    elif len(good_results) > 1:
        # Multiple matches - ask for disambiguation
        options = []
        option_text = []
        for i, result in enumerate(good_results[:5], 1):
            attrs = result.attributes
            city = attrs.get("City", "")
            region = attrs.get("Region", "")
            country = attrs.get("Country", "USA")

            display_name = result.address
            if city and region:
                display_name = f"{city}, {region}"
            elif city:
                display_name = f"{city}, {country}"

            options.append(MapLocation(
                name=result.address,
                longitude=result.location.get("x", 0),
                latitude=result.location.get("y", 0),
                zoom=12
            ))
            option_text.append(f"{i}. **{display_name}**")

        response = f"I found multiple locations matching '{location_query}':\n\n"
        response += "\n".join(option_text)
        response += "\n\nWhich one did you mean? Just say the number or be more specific (e.g., 'Dallas, Texas')."

        return (
            response,
            MapAction(type=MapActionType.disambiguate, options=options, query=location_query)
        )

    else:
        # Low confidence matches - still show options but mention uncertainty
        if results:
            result = results[0]
            location = MapLocation(
                name=result.address,
                longitude=result.location.get("x", 0),
                latitude=result.location.get("y", 0),
                zoom=12
            )
            return (
                f"I found '{result.address}' - is this the location you meant? Zooming there now.",
                MapAction(type=MapActionType.zoom_to, location=location, query=location_query)
            )
        return (
            f"I couldn't find a location matching '{location_query}'. Please try a more specific search.",
            None
        )


async def handle_disambiguation_choice(
    choice: str,
    options: list[MapLocation]
) -> tuple[str, MapAction | None]:
    """
    Handle user's choice from disambiguation options.

    Args:
        choice: User's choice (number or location name)
        options: List of previously offered options

    Returns:
        Tuple of (response_message, map_action)
    """
    choice = choice.strip().lower()

    # Check if it's a number
    try:
        num = int(choice)
        if 1 <= num <= len(options):
            location = options[num - 1]
            return (
                f"Zooming to {location.name}.",
                MapAction(type=MapActionType.zoom_to, location=location)
            )
    except ValueError:
        pass

    # Check if it matches any option name
    for option in options:
        if choice in option.name.lower():
            return (
                f"Zooming to {option.name}.",
                MapAction(type=MapActionType.zoom_to, location=option)
            )

    # Couldn't match - treat as new search
    return await handle_map_command(choice)


def detect_tapestry_query(message: str) -> list[str]:
    """
    Detect if user is asking about specific tapestry segments.

    Returns list of segment codes mentioned in the message.
    """
    codes = set()
    message_upper = message.upper()
    message_lower = message.lower()

    # Match 2025 segment codes like "A1", "A2", "B1", "L3", etc.
    pattern = r'\b([A-L][1-8])\b'
    code_matches = re.findall(pattern, message_upper)
    codes.update(code_matches)

    # Check for segment names
    for name, code in SEGMENT_NAME_TO_CODE.items():
        if name in message_lower:
            codes.add(code)

    # Check for general tapestry/segment queries that might benefit from search
    tapestry_keywords = ["tapestry", "segment", "lifemode", "life mode", "demographics"]
    if any(kw in message_lower for kw in tapestry_keywords) and not codes:
        # Search for potentially relevant segments
        search_results = search_segments_by_name(message, limit=3)
        for profile in search_results:
            codes.add(profile.code)

    return list(codes)


async def get_chat_response(
    message: str,
    use_knowledge_base: bool = True,
    folder_context: str = ""
) -> tuple[str, list[str]]:
    """Get a response from the AI assistant, optionally using knowledge base context."""
    sources: list[str] = []
    context = ""

    # Add folder files context if provided
    if folder_context:
        context += f"## Folder Files (Project Context)\n\n{folder_context}\n\n"
        sources.append("Folder Files")

    # Detect tapestry segment queries and add segment context
    segment_codes = detect_tapestry_query(message)
    if segment_codes:
        segment_context = get_segment_context_for_ai(segment_codes)
        if segment_context:
            context += f"## Tapestry Segment Information (from Esri)\n\n{segment_context}\n\n"
            sources.append("Esri Tapestry Segmentation")

    if use_knowledge_base:
        # Search for relevant documents from user-uploaded KB
        results = await search_documents(query=message, limit=5)
        if results:
            context_parts = []
            for doc in results:
                context_parts.append(f"### {doc['title']}\n{doc['content'][:1000]}")
                sources.append(doc['title'])
            if context_parts:
                context += "## Knowledge Base Documents\n\n" + "\n\n".join(context_parts)

    system_prompt = """You are a friendly, knowledgeable AI assistant for MarketInsightsAI - an autonomous AI agent platform for location intelligence.

Your personality:
- Conversational and warm, like a helpful colleague
- Expert in market analysis, demographics, and consumer behavior
- You explain complex concepts simply without being condescending
- You're proactive - suggest next steps and ask clarifying questions when helpful

Your capabilities:
- Analyze Esri Tapestry Segmentation data (60 lifestyle segments across 14 LifeMode groups)
- Help users understand their customer demographics and market composition
- Generate insights about store trade areas and customer profiles
- Answer questions about specific segments, demographics, and market trends

When users upload tapestry files:
- Acknowledge what you found in the data
- Highlight interesting insights (top segments, notable demographics)
- Suggest what they might want to do next (generate a report, compare stores, etc.)

Keep responses conversational and helpful. Use markdown formatting for readability when appropriate."""

    if context:
        system_prompt += f"\n\nHere is relevant context:\n\n{context}"

    if not client:
        # Return a mock response if no API key is configured
        return (
            "AI responses are not available. Please configure your OpenAI API key in the .env file.",
            sources
        )

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ],
        max_tokens=1000,
        temperature=0.7,
    )

    return response.choices[0].message.content or "", sources


from typing import AsyncGenerator


async def get_chat_response_streaming(
    message: str,
    use_knowledge_base: bool = True,
    folder_context: str = ""
) -> AsyncGenerator[str, None]:
    """
    Stream a response from the AI assistant token by token.

    Yields chunks of text as they're generated by the model.
    The final chunk will be the complete sources as JSON.
    """
    import json

    sources: list[str] = []
    context = ""

    # Add folder files context if provided
    if folder_context:
        context += f"## Folder Files (Project Context)\n\n{folder_context}\n\n"
        sources.append("Folder Files")

    # Detect tapestry segment queries and add segment context
    segment_codes = detect_tapestry_query(message)
    if segment_codes:
        segment_context = get_segment_context_for_ai(segment_codes)
        if segment_context:
            context += f"## Tapestry Segment Information (from Esri)\n\n{segment_context}\n\n"
            sources.append("Esri Tapestry Segmentation")

    if use_knowledge_base:
        # Search for relevant documents from user-uploaded KB
        results = await search_documents(query=message, limit=5)
        if results:
            context_parts = []
            for doc in results:
                context_parts.append(f"### {doc['title']}\n{doc['content'][:1000]}")
                sources.append(doc['title'])
            if context_parts:
                context += "## Knowledge Base Documents\n\n" + "\n\n".join(context_parts)

    system_prompt = """You are a friendly, knowledgeable AI assistant for MarketInsightsAI - an autonomous AI agent platform for location intelligence.

Your personality:
- Conversational and warm, like a helpful colleague
- Expert in market analysis, demographics, and consumer behavior
- You explain complex concepts simply without being condescending
- You're proactive - suggest next steps and ask clarifying questions when helpful

Your capabilities:
- Analyze Esri Tapestry Segmentation data (60 lifestyle segments across 14 LifeMode groups)
- Help users understand their customer demographics and market composition
- Generate insights about store trade areas and customer profiles
- Answer questions about specific segments, demographics, and market trends

When users upload tapestry files:
- Acknowledge what you found in the data
- Highlight interesting insights (top segments, notable demographics)
- Suggest what they might want to do next (generate a report, compare stores, etc.)

Keep responses conversational and helpful. Use markdown formatting for readability when appropriate."""

    if context:
        system_prompt += f"\n\nHere is relevant context:\n\n{context}"

    if not client:
        yield "AI responses are not available. Please configure your OpenAI API key."
        yield f"\n\n__SOURCES__:{json.dumps(sources)}"
        return

    # Use streaming API
    stream = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ],
        max_tokens=1000,
        temperature=0.7,
        stream=True,
    )

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

    # Send sources at the end with a marker
    yield f"\n\n__SOURCES__:{json.dumps(sources)}"


async def generate_image(prompt: str) -> tuple[str, str]:
    """Generate an image using Google Gemini Imagen 3."""
    if not gemini_client:
        return (
            "https://placehold.co/512x512/3b82f6/ffffff?text=Image+Generation",
            f"Image generation for: {prompt}. Configure Google API key for actual image generation."
        )

    try:
        # Generate image using Imagen 3
        response = gemini_client.models.generate_images(
            model=settings.gemini_image_model,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1",
                safety_filter_level="BLOCK_MEDIUM_AND_ABOVE",
            ),
        )

        if response.generated_images and len(response.generated_images) > 0:
            # Get the image data
            image_data = response.generated_images[0].image.image_bytes

            # Save to file
            image_id = str(uuid.uuid4())
            image_filename = f"{image_id}.png"
            image_path = os.path.join(GENERATED_IMAGES_DIR, image_filename)

            with open(image_path, "wb") as f:
                f.write(image_data)

            # Return URL path (will be served by static files)
            image_url = f"/api/reports/generated_images/{image_filename}"
            return (image_url, f"Generated image for: {prompt[:100]}...")

        return (
            "https://placehold.co/512x512/ef4444/ffffff?text=Generation+Failed",
            "Image generation returned no results."
        )

    except Exception as e:
        logger.error(f"Image generation error: {e}")
        return (
            "https://placehold.co/512x512/ef4444/ffffff?text=Error",
            f"Image generation failed: {str(e)}"
        )


async def generate_marketing_image(
    recommendation: MarketingRecommendation,
    platform: MarketingPlatform,
    store: Store | None = None,
) -> MarketingPost:
    """
    Generate a marketing image based on the recommendation and platform.

    Args:
        recommendation: The approved marketing recommendation
        platform: Target platform for aspect ratio and style
        store: Optional store for additional context

    Returns:
        MarketingPost with generated image URL
    """
    # Platform-specific settings for professional ad creatives
    platform_specs = {
        MarketingPlatform.instagram: {
            "aspect_ratio": "1:1",
            "dimensions": "1080x1080",
            "ad_style": """Create a professional Instagram advertisement creative with:
- Clean, modern design with strategic white space
- Bold headline text prominently displayed (large, readable font)
- Eye-catching hero image or product shot as background
- Brand-style color scheme with high contrast
- Optional: subtle call-to-action button design (e.g., "Shop Now", "Learn More")
- Professional typography hierarchy
- Instagram-optimized square format
Style: High-end brand advertisement, Lovart/Canva quality, polished graphic design""",
        },
        MarketingPlatform.linkedin: {
            "aspect_ratio": "16:9",
            "dimensions": "1200x627",
            "ad_style": """Create a professional LinkedIn advertisement creative with:
- Corporate, trustworthy design aesthetic
- Professional headline with business messaging
- Clean background with subtle gradient or professional imagery
- Business-appropriate color palette
- Thought leadership or B2B marketing style
- Optional: company branding elements
Style: Executive-level marketing, professional services aesthetic""",
        },
        MarketingPlatform.facebook: {
            "aspect_ratio": "16:9",
            "dimensions": "1200x630",
            "ad_style": """Create a professional Facebook advertisement creative with:
- Engaging, scroll-stopping design
- Clear headline and supporting text
- Warm, inviting color palette
- Community-focused imagery
- Social proof or lifestyle elements
- Clear call-to-action
Style: Facebook ad creative, engaging social media design""",
        },
        MarketingPlatform.twitter: {
            "aspect_ratio": "16:9",
            "dimensions": "1600x900",
            "ad_style": """Create a professional Twitter/X advertisement creative with:
- Bold, attention-grabbing design
- Punchy headline that works in timeline
- High contrast colors
- Minimal text, maximum impact
- Modern, trendy aesthetic
Style: Twitter ad creative, viral-worthy design""",
        },
    }

    spec = platform_specs.get(platform, platform_specs[MarketingPlatform.instagram])

    # Build expert-level prompt for ad creative generation
    image_prompt = f"""You are an expert {platform.value.title()} advertisement designer creating a professional ad creative.

BRAND/BUSINESS: {recommendation.store_name}
HEADLINE TO INCLUDE: "{recommendation.headline}"
TARGET AUDIENCE: Based on demographic analysis

DESIGN BRIEF:
{spec['ad_style']}

VISUAL DIRECTION:
{recommendation.visual_concept}

REQUIREMENTS:
- Generate a complete, ready-to-post advertisement image
- Include the headline text "{recommendation.headline}" as part of the design
- Professional graphic design quality (like Canva Pro or Adobe templates)
- High resolution, {spec['dimensions']} optimized
- Modern, trendy 2024-2025 design aesthetics
- Clean typography with excellent readability
- Cohesive color scheme that pops on social feeds

DO NOT include: watermarks, placeholder text, lorem ipsum, unfinished elements"""

    # Generate image using Gemini native image generation (Nano Banana Pro)
    image_url = None
    if gemini_client:
        try:
            # Use Gemini 2.5 Flash Image (Nano Banana) for image generation
            # Alternative: "gemini-3-pro-image-preview" (Nano Banana Pro) for higher quality
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash-exp-image-generation",
                contents=[image_prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )

            # Check if we got an image in the response
            image_saved = False
            if response.candidates and len(response.candidates) > 0:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        # Get the image data
                        image_data = part.inline_data.data
                        if isinstance(image_data, str):
                            image_data = base64.b64decode(image_data)

                        # Save to file
                        image_id = str(uuid.uuid4())
                        image_filename = f"marketing_{image_id}.png"
                        image_path = os.path.join(GENERATED_IMAGES_DIR, image_filename)

                        with open(image_path, "wb") as f:
                            f.write(image_data)

                        image_url = f"/api/reports/generated_images/{image_filename}"
                        image_saved = True
                        break

            if not image_saved:
                # Fallback: Try Imagen 4 if available
                try:
                    imagen_response = gemini_client.models.generate_images(
                        model="imagen-4.0-generate-001",
                        prompt=image_prompt,
                        config=types.GenerateImagesConfig(
                            number_of_images=1,
                            aspect_ratio=spec["aspect_ratio"],
                        ),
                    )

                    if imagen_response.generated_images and len(imagen_response.generated_images) > 0:
                        image_data = imagen_response.generated_images[0].image.image_bytes

                        image_id = str(uuid.uuid4())
                        image_filename = f"marketing_{image_id}.png"
                        image_path = os.path.join(GENERATED_IMAGES_DIR, image_filename)

                        with open(image_path, "wb") as f:
                            f.write(image_data)

                        image_url = f"/api/reports/generated_images/{image_filename}"
                except Exception as imagen_error:
                    logger.warning(f"Imagen 4 fallback failed: {imagen_error}")
                    image_url = "https://placehold.co/1080x1080/3b82f6/ffffff?text=Image+Generation+Unavailable"

        except Exception as e:
            logger.error(f"Marketing image generation error: {e}")
            image_url = "https://placehold.co/1080x1080/3b82f6/ffffff?text=Image+Generation+Error"
    else:
        image_url = "https://placehold.co/1080x1080/3b82f6/ffffff?text=Configure+Google+API+Key"

    # Create MarketingPost
    return MarketingPost(
        id=str(uuid.uuid4()),
        store_id=recommendation.store_id,
        store_name=recommendation.store_name,
        platform=platform,
        headline=recommendation.headline,
        body=recommendation.body,
        hashtags=recommendation.hashtags,
        image_url=image_url,
        image_prompt=image_prompt,
        is_generating=False,
        created_at=datetime.now(),
    )


async def generate_business_insights(
    store_name: str,
    segments: list[dict],
    demographics: dict | None = None,
    goal: str | None = None,
) -> tuple[str, str]:
    """
    Generate 'Unlocking Business Value' insights for a tapestry report.

    Args:
        store_name: Name of the store
        segments: List of segment data dicts
        demographics: Optional demographics data
        goal: Optional business goal to focus on (e.g., 'instagram', 'newsletter', etc.)

    Returns:
        Tuple of (insights_text, section_title)
    """
    if not client:
        return "Business insights are not available. Please configure your OpenAI API key.", "Unlocking Business Value"

    # Build detailed segment descriptions with Esri profile data
    segment_details = []
    for seg in segments[:5]:
        code = seg.get('code', '')
        name = seg.get('name', code)
        share = seg.get('household_share', 0)
        description = seg.get('description', '')
        life_mode = seg.get('life_mode', '')

        detail = f"- **{name} ({code})**: {share:.1f}% of households"
        if life_mode:
            detail += f"\n  LifeMode: {life_mode}"
        if description:
            detail += f"\n  Profile: {description[:300]}..."

        segment_details.append(detail)

    segment_descriptions = "\n\n".join(segment_details)

    # Build goal-specific focus prompt
    goal_focus = ""
    goal_title = "Unlocking Business Value"
    if goal and goal not in ("generic", "standard"):
        goal_focuses = {
            "marketing": {
                "title": "Marketing Strategy Insights",
                "focus": "Focus on: brand positioning, customer engagement strategies, messaging approaches, and target audience recommendations."
            },
            "advertising": {
                "title": "Advertising Strategy Insights",
                "focus": "Focus on: advertising channels, media consumption habits, ad placement strategies, and campaign messaging tactics."
            },
            "ad_campaign": {
                "title": "Ad Campaign Strategy",
                "focus": "Focus on: paid advertising channels, targeting parameters, ad creative direction, and campaign optimization for this demographic."
            },
            "instagram": {
                "title": "Instagram Campaign Insights",
                "focus": "Focus on: Instagram-specific content strategies, visual aesthetics that resonate with this demographic, optimal posting times, hashtag strategies, Reels vs Stories vs Feed recommendations, influencer partnership opportunities, and Instagram Shopping features if applicable."
            },
            "facebook": {
                "title": "Facebook Campaign Insights",
                "focus": "Focus on: Facebook ad targeting based on these demographics, community building strategies, Facebook Groups opportunities, event marketing, local awareness campaigns, and content formats (video, carousel, etc.) that work best for this audience."
            },
            "linkedin": {
                "title": "LinkedIn Campaign Insights",
                "focus": "Focus on: B2B messaging if applicable, professional networking opportunities, thought leadership content, LinkedIn ad targeting, and professional services positioning."
            },
            "newsletter": {
                "title": "Newsletter & Email Marketing Insights",
                "focus": "Focus on: email content themes, optimal send frequency, subject line strategies, personalization opportunities, segmentation strategies, and content types (educational, promotional, lifestyle) that resonate with this demographic."
            },
            "local_marketing": {
                "title": "Local Marketing Insights",
                "focus": "Focus on: in-store promotions, local community events, partnerships with nearby businesses, local SEO, Google Business Profile optimization, neighborhood-specific messaging, and local print/radio opportunities."
            },
            "promotions": {
                "title": "Promotional Strategy Insights",
                "focus": "Focus on: discount sensitivity of this demographic, optimal promotional timing, deal structures (BOGO, percentage off, bundles), loyalty program design, and promotional channels that reach this audience effectively."
            },
            "promotion": {
                "title": "Promotional Strategy Insights",
                "focus": "Focus on: discount sensitivity, promotional timing, deal-seeking behaviors, and promotional channel preferences."
            },
            "location": {
                "title": "Location Strategy Insights",
                "focus": "Focus on: site selection factors, trade area optimization, competitive positioning, and expansion opportunities."
            },
        }
        goal_data = goal_focuses.get(goal.lower(), {"title": f"{goal.title()} Strategy Insights", "focus": f"Focus on: {goal} strategies and recommendations."})
        goal_focus = f"\n\n{goal_data['focus']}"
        goal_title = goal_data['title']

    # Create a simple list of segment names for the opening sentence
    segment_names = [seg.get('name', seg.get('code', '')) for seg in segments[:5] if seg.get('name') or seg.get('code')]
    segment_names_text = ", ".join(segment_names[:3]) if segment_names else "diverse demographics"

    prompt = f"""Analyze the trade area for {store_name} and provide strategic business recommendations based on the TOP 5 lifestyle segments shown below.

TOP 5 LIFESTYLE SEGMENTS (these are the actual customers in this trade area):
{segment_descriptions}{goal_focus}

Write a cohesive paragraph (approximately 120 words) with specific, actionable tactics.

REQUIRED FORMAT:
1. Start with: "The trade area is driven by [reference the top segment names like {segment_names_text}], so focus on [key theme]."
2. Then provide 4-5 specific tactical recommendations covering: merchandise/product focus, marketing channels, community engagement, convenience/service improvements, and digital engagement

CRITICAL RULES:
- These segments ARE the customers - do NOT say "no segments" or suggest attracting different demographics
- Reference the actual segment names and their characteristics in your recommendations
- Be specific and tactical (e.g., "offer family-friendly merchandise and starter kits" not "consider expanding product range")
- Wrap 4-6 key phrases in <strong> tags for emphasis
- Write as one flowing paragraph, not bullet points
- NEVER mention lack of data or missing segments - work with what is provided
- NEVER use geographic references like "in the South", "in Michigan", "in Texas", "in the Midwest", etc. - the segment descriptions may mention regions but YOUR recommendations should be location-agnostic and applicable to THIS specific trade area regardless of where it is"""

    system_prompt = f"You are a retail location analytics expert specializing in {goal or 'marketing'} strategy. The segments provided ARE the top 5 customer segments in the trade area - always reference them by name and provide specific recommendations for serving these customers. Write approximately 120 words. IMPORTANT: Never use geographic region references (like 'in the South', 'in Michigan', 'in urban areas') - keep recommendations universally applicable to the lifestyle characteristics, not regional stereotypes."

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        max_tokens=300,
        temperature=0.7,
    )

    insights_text = response.choices[0].message.content or ""
    return insights_text, goal_title


async def generate_segment_insight(
    segment_name: str,
    segment_code: str,
    segment_description: str,
    life_mode: str | None = None,
    household_share: float = 0,
    goal: str | None = None,
) -> str:
    """
    Generate a concise AI insight specific to a single segment (50 words).

    Args:
        segment_name: Name of the segment
        segment_code: Segment code (e.g., 'A1')
        segment_description: Full segment description
        life_mode: LifeMode group name
        household_share: Percentage of households
        goal: Optional business goal to focus on

    Returns:
        Concise 50-word insight for this specific segment
    """
    if not client:
        return f"Insight for {segment_name}: Configure OpenAI API key for AI-generated insights."

    goal_context = ""
    if goal and goal not in ("generic", "standard"):
        goal_context = f"\nFocus area: {goal}"

    prompt = f"""Generate a brief, actionable business insight for targeting the "{segment_name}" ({segment_code}) demographic segment.

Segment profile: {segment_description[:400]}
LifeMode: {life_mode or 'N/A'}
Household share: {household_share:.1f}%{goal_context}

Write EXACTLY 50 words of specific, actionable advice for reaching and engaging this segment. Be direct and practical. Include one specific tactic or channel recommendation.

IMPORTANT: Do NOT use any geographic references like "in the South", "in Michigan", "in Texas", "in urban areas", etc. The segment description may mention regions, but your recommendation should focus on lifestyle characteristics and behaviors, not geographic locations."""

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "You are a concise retail marketing expert. Write exactly 50 words, no more, no less. Never mention specific geographic regions (states, regions like 'the South', cities) - focus only on lifestyle and behavioral characteristics."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=100,
        temperature=0.7,
    )

    return response.choices[0].message.content or f"Target {segment_name} customers with relevant messaging."


# =============================================================================
# Marketing Post Detection & Generation
# =============================================================================

# LifeMode to visual style mapping for image generation
LIFEMODE_VISUAL_STYLES = {
    "Urban Threads": {
        "style": "urban, diverse, city life, street style",
        "colors": "bold, vibrant, contrasting",
        "mood": "energetic, dynamic, authentic",
    },
    "Campus Connections": {
        "style": "youthful, academic, social, modern",
        "colors": "fresh, bright, casual",
        "mood": "aspirational, energetic, connected",
    },
    "Diverse Pathways": {
        "style": "multicultural, family-oriented, community",
        "colors": "warm, welcoming, diverse",
        "mood": "inclusive, hopeful, hardworking",
    },
    "Ambitious Singles": {
        "style": "professional, modern, tech-forward, minimalist",
        "colors": "sleek, sophisticated, clean",
        "mood": "ambitious, trendy, connected",
    },
    "Mixed Mosaic": {
        "style": "practical, family, suburban, value-conscious",
        "colors": "warm, earthy, approachable",
        "mood": "friendly, relatable, down-to-earth",
    },
    "Metro Mix": {
        "style": "cosmopolitan, multicultural, urban, dense",
        "colors": "rich, diverse, layered",
        "mood": "bustling, diverse, opportunity",
    },
    "Family Matters": {
        "style": "family-centric, growth, suburban homes",
        "colors": "warm, bright, family-friendly",
        "mood": "nurturing, aspirational, community",
    },
    "Suburban Style": {
        "style": "affluent, professional, family, polished",
        "colors": "clean, sophisticated, premium",
        "mood": "successful, quality-focused, established",
    },
    "Rural Rhythms": {
        "style": "rural, outdoor, authentic, traditional",
        "colors": "natural, earthy, rustic",
        "mood": "genuine, hardworking, peaceful",
    },
    "Golden Years": {
        "style": "retirement, leisure, comfortable, serene",
        "colors": "warm, soft, calming",
        "mood": "relaxed, fulfilled, active",
    },
    "Comfortable Cornerstone": {
        "style": "established, comfortable, suburban, stable",
        "colors": "classic, reliable, warm",
        "mood": "dependable, content, community-focused",
    },
    "Affluent Estates": {
        "style": "luxury, premium, exclusive, sophisticated",
        "colors": "elegant, rich, refined",
        "mood": "prestigious, aspirational, quality",
    },
}


def detect_marketing_request(
    message: str,
    available_stores: dict[str, Store] | None = None
) -> tuple[bool, str | None, MarketingPlatform | None]:
    """
    Detect if user is asking for marketing post creation.

    Args:
        message: User's message
        available_stores: Dict of store_id -> Store from uploaded data

    Returns:
        Tuple of (is_marketing_request, store_reference, platform)
    """
    message_lower = message.lower().strip()

    # Marketing request patterns
    marketing_patterns = [
        r"(?:create|make|generate|design|build)\s+(?:a\s+)?(?:marketing|social media|promotional?|ad|advertisement)\s+(?:post|content|image|creative)",
        r"(?:marketing|social media|promotional?)\s+(?:post|content|image|creative)\s+(?:for|about)",
        r"(?:instagram|linkedin|facebook|twitter|x)\s+(?:post|content|image|creative)",
        r"(?:post|content|image|creative)\s+(?:for|on)\s+(?:instagram|linkedin|facebook|twitter|x)",
        r"(?:create|make|generate)\s+(?:post|content|image)\s+for\s+(?:social media|marketing)",
    ]

    is_marketing = any(re.search(pattern, message_lower) for pattern in marketing_patterns)

    if not is_marketing:
        return False, None, None

    # Detect platform
    platform = None
    if "instagram" in message_lower:
        platform = MarketingPlatform.instagram
    elif "linkedin" in message_lower:
        platform = MarketingPlatform.linkedin
    elif "facebook" in message_lower:
        platform = MarketingPlatform.facebook
    elif "twitter" in message_lower or " x " in message_lower:
        platform = MarketingPlatform.twitter

    # Try to find store reference
    store_ref = None
    if available_stores:
        # Check for store name mentions
        for store_id, store in available_stores.items():
            if store.name.lower() in message_lower:
                store_ref = store_id
                break
            # Also check store number if available
            if store.store_number and store.store_number.lower() in message_lower:
                store_ref = store_id
                break

        # If no specific store found but only one store available, use it
        if not store_ref and len(available_stores) == 1:
            store_ref = list(available_stores.keys())[0]

    return True, store_ref, platform


def detect_report_request(
    message: str,
    available_stores: dict[str, Store] | None = None
) -> tuple[bool, list[str] | str | None, str | None, bool, list[FuzzyMatch]]:
    """
    Detect if user is asking for report generation.

    Args:
        message: User's message
        available_stores: Dict of store_id -> Store from uploaded data

    Returns:
        Tuple of (is_report_request, store_ids, goal, is_all_stores, fuzzy_suggestions)
        - store_ids can be a single store_id string, a list of store_ids, or None
        - is_all_stores indicates if user wants a report for all stores
        - fuzzy_suggestions: list of FuzzyMatch for potential typos to confirm with user
    """
    message_lower = message.lower().strip()

    # Report request patterns
    report_patterns = [
        r"(?:generate|create|make|build|get)\s+(?:a\s+)?(?:report|tapestry report|marketing report)",
        r"(?:report|tapestry report)\s+(?:for|about|on)",
        r"generate\s+(?:a\s+)?report\s+for",
        r"create\s+(?:a\s+)?report\s+for",
    ]

    is_report = any(re.search(pattern, message_lower) for pattern in report_patterns)

    if not is_report:
        return False, None, None, False, []

    # Detect goal/type from message
    goal = None
    if "marketing" in message_lower:
        goal = "marketing"
    elif "advertising" in message_lower or "ad" in message_lower:
        goal = "advertising"
    elif "promotion" in message_lower or "discount" in message_lower:
        goal = "promotions"
    else:
        goal = "generic"

    # Check for "all stores" patterns
    all_stores_patterns = [
        r"all\s+(?:the\s+)?stores",
        r"every\s+store",
        r"all\s+of\s+them",
        r"for\s+all",
        r"all\s+locations",
    ]
    is_all_stores = any(re.search(pattern, message_lower) for pattern in all_stores_patterns)

    if is_all_stores:
        return True, None, goal, True, []

    # Use fuzzy matching to find store mentions
    fuzzy_suggestions: list[FuzzyMatch] = []
    if available_stores:
        # Use the new fuzzy matching function
        exact_match_ids, fuzzy_suggestions = find_store_mentions_fuzzy(message, available_stores)

        # Also check store numbers (not handled by fuzzy matching)
        for sid, store in available_stores.items():
            if sid in exact_match_ids:
                continue
            if store.store_number:
                store_num_lower = store.store_number.lower()
                if store_num_lower in message_lower:
                    exact_match_ids.append(sid)
                elif re.search(rf'\b(?:store\s*)?#?{re.escape(store_num_lower)}\b', message_lower):
                    exact_match_ids.append(sid)

        # If multiple stores found, return them as a list
        if len(exact_match_ids) > 1:
            return True, exact_match_ids, goal, False, fuzzy_suggestions

        # If exactly one store found
        if len(exact_match_ids) == 1:
            return True, exact_match_ids[0], goal, False, fuzzy_suggestions

        # If no specific store found but only one store available, use it
        if not exact_match_ids and len(available_stores) == 1:
            return True, list(available_stores.keys())[0], goal, False, fuzzy_suggestions

    return True, None, goal, False, fuzzy_suggestions


def detect_business_goal(message: str) -> tuple[bool, str | None]:
    """
    Detect business goal from user message for report generation.

    Returns:
        Tuple of (is_goal_response, goal_type)
        goal_type can be: 'standard', 'instagram', 'facebook', 'linkedin', 'newsletter', 'email', 'ad_campaign', etc.
    """
    message_lower = message.lower().strip()

    # Standard/generic report
    standard_patterns = [
        r"standard\s*(?:report|tapestry)?",
        r"(?:just\s+)?(?:the\s+)?regular\s*(?:report)?",
        r"(?:just\s+)?(?:the\s+)?normal\s*(?:report)?",
        r"(?:just\s+)?(?:the\s+)?basic\s*(?:report)?",
        r"(?:general|generic)\s*(?:report)?",
        r"no\s*(?:specific\s+)?goal",
        r"default\s*(?:report)?",
    ]

    if any(re.search(p, message_lower) for p in standard_patterns):
        return True, "standard"

    # Instagram campaign
    instagram_patterns = [
        r"instagram\s*(?:ad|campaign|post|marketing)?",
        r"insta\s*(?:ad|campaign|post|marketing)?",
        r"ig\s*(?:ad|campaign|post|marketing)?",
    ]
    if any(re.search(p, message_lower) for p in instagram_patterns):
        return True, "instagram"

    # Facebook campaign
    facebook_patterns = [
        r"facebook\s*(?:ad|campaign|post|marketing)?",
        r"fb\s*(?:ad|campaign|post|marketing)?",
    ]
    if any(re.search(p, message_lower) for p in facebook_patterns):
        return True, "facebook"

    # LinkedIn campaign
    linkedin_patterns = [
        r"linkedin\s*(?:ad|campaign|post|marketing)?",
    ]
    if any(re.search(p, message_lower) for p in linkedin_patterns):
        return True, "linkedin"

    # Newsletter/Email
    newsletter_patterns = [
        r"newsletter",
        r"email\s*(?:campaign|marketing)?",
        r"e-?mail\s*(?:campaign|marketing)?",
    ]
    if any(re.search(p, message_lower) for p in newsletter_patterns):
        return True, "newsletter"

    # General ad campaign
    ad_patterns = [
        r"ad\s*campaign",
        r"advertising",
        r"paid\s*(?:ad|media|campaign)",
        r"digital\s*(?:ad|marketing)",
    ]
    if any(re.search(p, message_lower) for p in ad_patterns):
        return True, "ad_campaign"

    # Local marketing
    local_patterns = [
        r"local\s*marketing",
        r"local\s*(?:ad|campaign)",
        r"community\s*(?:outreach|marketing)",
    ]
    if any(re.search(p, message_lower) for p in local_patterns):
        return True, "local_marketing"

    # Promotions/Sales
    promo_patterns = [
        r"promot(?:ion|ional)",
        r"sale(?:s)?",
        r"discount",
        r"special\s*offer",
    ]
    if any(re.search(p, message_lower) for p in promo_patterns):
        return True, "promotions"

    return False, None


def detect_approval_response(message: str) -> tuple[bool, MarketingPlatform | None]:
    """
    Detect if user is approving a marketing recommendation or selecting a platform.

    Returns:
        Tuple of (is_approval, platform_selection)
    """
    message_lower = message.lower().strip()

    # Platform selection patterns
    platform_patterns = {
        MarketingPlatform.instagram: [r"\binstagram\b", r"\binsta\b", r"\big\b"],
        MarketingPlatform.linkedin: [r"\blinkedin\b"],
        MarketingPlatform.facebook: [r"\bfacebook\b", r"\bfb\b"],
        MarketingPlatform.twitter: [r"\btwitter\b", r"\bx\b"],
    }

    for platform, patterns in platform_patterns.items():
        if any(re.search(p, message_lower) for p in patterns):
            return True, platform

    # Approval patterns (without platform)
    approval_patterns = [
        r"^create\s*it\s*$",  # Exact "create it"
        r"^make\s*it\s*$",  # Exact "make it"
        r"^generate\s*it\s*$",  # Exact "generate it"
        r"^do\s*it\s*$",  # Exact "do it"
        r"(?:create|generate|make)\s+(?:it|the\s+image|the\s+post|this)",
        r"^(?:yes|yep|yeah|sure|ok|okay|absolutely|definitely)\s*[!.]?$",
        r"(?:looks?\s+)?(?:good|great|perfect|awesome|excellent)",
        r"^go\s*(?:ahead|for\s*it)\s*$",
        r"^approved?\s*$",
        r"(?:let'?s?\s+)?(?:create|generate|make|do)\s+(?:it|this|that)",
    ]

    is_approval = any(re.search(p, message_lower) for p in approval_patterns)

    return is_approval, None


async def generate_marketing_recommendation(
    store: Store,
    platform: MarketingPlatform | None = None
) -> MarketingRecommendation:
    """
    Generate marketing recommendations based on store segment data.

    Args:
        store: Store with segment data
        platform: Optional specific platform (if not set, suggests platforms)

    Returns:
        MarketingRecommendation with content ideas and visual concept
    """
    if not client:
        raise ValueError("OpenAI client not configured")

    # Get top segments with full profile data
    top_segments = sorted(store.segments, key=lambda s: s.household_share, reverse=True)[:5]

    # Build rich segment context
    segment_details = []
    primary_lifemode = None
    for i, seg in enumerate(top_segments):
        profile = get_segment_profile(seg.code)
        if profile:
            if i == 0:
                primary_lifemode = profile.life_mode
            income_str = f"${profile.median_household_income:,.0f}" if profile.median_household_income else "N/A"
            segment_details.append(
                f"- **{seg.name} ({seg.code})**: {seg.household_share:.1f}% of households\n"
                f"  LifeMode: {profile.life_mode}\n"
                f"  Median Age: {profile.median_age}, Median Income: {income_str}\n"
                f"  Profile: {profile.description[:200]}..."
            )

    # Get visual style based on primary LifeMode
    visual_style = LIFEMODE_VISUAL_STYLES.get(
        primary_lifemode,
        {"style": "professional, clean", "colors": "balanced", "mood": "positive"}
    )

    # Build the prompt
    platform_context = ""
    if platform:
        platform_specs = {
            MarketingPlatform.instagram: "Instagram (visual-first, lifestyle-focused, hashtag-driven, 1080x1080 square format)",
            MarketingPlatform.linkedin: "LinkedIn (professional tone, business-focused, longer copy acceptable, 1200x627 landscape)",
            MarketingPlatform.facebook: "Facebook (community-focused, shareable, engaging, 1200x630 landscape)",
            MarketingPlatform.twitter: "Twitter/X (concise, punchy, conversational, 1600x900 landscape)",
        }
        platform_context = f"\n\nTarget Platform: {platform_specs.get(platform, platform.value)}"

    prompt = f"""You are an expert social media advertising creative director, like the best designers at agencies creating viral ad campaigns.

Your task: Create a professional advertisement creative brief for {store.name} that will be used to generate a ready-to-post social media ad.

Store: {store.name}
{f"Location: {store.address}" if store.address else ""}

TARGET AUDIENCE ANALYSIS:
{chr(10).join(segment_details)}

Visual Style Guide (based on {primary_lifemode} LifeMode):
- Style: {visual_style['style']}
- Colors: {visual_style['colors']}
- Mood: {visual_style['mood']}{platform_context}

Create a complete advertisement creative brief with:

1. HEADLINE: A powerful, scroll-stopping headline (max 8 words) that would look great as text overlay on an ad
   - Should be bold, memorable, action-oriented
   - Think Nike, Apple, top brand ad copy

2. BODY: Compelling caption/post copy (40-80 words)
   - Speaks directly to the target demographic
   - Includes a clear value proposition
   - Ends with a soft call-to-action

3. HASHTAGS: 5-7 strategic hashtags
   - Mix of branded, industry, and trending tags

4. VISUAL_CONCEPT: DETAILED description of the ad creative design (THIS IS CRITICAL - be very specific):
   - Describe it as a DESIGNED AD, not just a photo
   - Specify: background style (gradient, solid color, lifestyle image, abstract)
   - Specify: color palette (exact colors that appeal to the demographic)
   - Specify: layout composition (where headline goes, any graphic elements)
   - Specify: mood and energy (luxurious, energetic, warm, professional)
   - Specify: any icons, shapes, or decorative elements
   - Example: "Modern gradient background from deep purple (#6B21A8) to vibrant pink (#EC4899), bold white sans-serif headline centered at top, minimalist lifestyle product shot in lower third, subtle geometric accent shapes, premium luxury feel"

5. SEGMENT_INSIGHTS: Why this creative approach resonates with these specific demographics (2 sentences)

Format your response EXACTLY as:
HEADLINE: [headline text]
BODY: [body text]
HASHTAGS: [#tag1 #tag2 ...]
VISUAL_CONCEPT: [detailed ad design description]
SEGMENT_INSIGHTS: [insights]"""

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "You are a world-class creative director at a top advertising agency. You create viral social media ad campaigns that combine stunning visuals with compelling copy. Your ad designs are professional, on-trend, and convert. Think Lovart, Canva Pro templates, professional ad agencies."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1000,
        temperature=0.8,
    )

    content = response.choices[0].message.content or ""

    # Parse the response
    headline = ""
    body = ""
    hashtags = []
    visual_concept = ""
    segment_insights = ""

    # Extract each section
    headline_match = re.search(r"HEADLINE:\s*(.+?)(?=\n(?:BODY|HASHTAGS|VISUAL|SEGMENT)|$)", content, re.IGNORECASE | re.DOTALL)
    if headline_match:
        headline = headline_match.group(1).strip()

    body_match = re.search(r"BODY:\s*(.+?)(?=\n(?:HASHTAGS|VISUAL|SEGMENT)|$)", content, re.IGNORECASE | re.DOTALL)
    if body_match:
        body = body_match.group(1).strip()

    hashtags_match = re.search(r"HASHTAGS:\s*(.+?)(?=\n(?:VISUAL|SEGMENT)|$)", content, re.IGNORECASE | re.DOTALL)
    if hashtags_match:
        hashtag_text = hashtags_match.group(1).strip()
        hashtags = [tag.strip() for tag in re.findall(r"#\w+", hashtag_text)]

    visual_match = re.search(r"VISUAL_CONCEPT:\s*(.+?)(?=\n(?:SEGMENT)|$)", content, re.IGNORECASE | re.DOTALL)
    if visual_match:
        visual_concept = visual_match.group(1).strip()

    insights_match = re.search(r"SEGMENT_INSIGHTS:\s*(.+?)$", content, re.IGNORECASE | re.DOTALL)
    if insights_match:
        segment_insights = insights_match.group(1).strip()

    # Determine suggested platforms if not specified
    suggested_platforms = [platform] if platform else [
        MarketingPlatform.instagram,
        MarketingPlatform.linkedin
    ]

    return MarketingRecommendation(
        store_id=store.id,
        store_name=store.name,
        headline=headline,
        body=body,
        hashtags=hashtags,
        suggested_platforms=suggested_platforms,
        visual_concept=visual_concept,
        segment_insights=segment_insights,
        awaiting_approval=True,
    )


def build_marketing_response_text(recommendation: MarketingRecommendation) -> str:
    """Build a formatted response text for a marketing recommendation."""
    platforms_str = ", ".join([p.value.title() for p in recommendation.suggested_platforms])

    return f"""Based on {recommendation.store_name}'s customer demographics, here's my marketing recommendation:

**{recommendation.headline}**

{recommendation.body}

{' '.join(recommendation.hashtags)}

---

**Why this works:** {recommendation.segment_insights}

**Visual Concept:** {recommendation.visual_concept}

**Suggested Platforms:** {platforms_str}

Would you like me to create this as an **Instagram** post, **LinkedIn** post, or another platform? Just let me know which platform, or say "create it" if you'd like me to pick the best one!"""


# ============== Context-Aware Chat (Phase 6) ==============


async def get_chat_response_with_context(
    message: str,
    context: str,
    session_state: "SessionState | None" = None,
    use_knowledge_base: bool = True,
    folder_context: str = "",
) -> tuple[str, list[str], dict]:
    """
    Get AI response using pre-built context with conversation history.

    This is the new context-aware version that:
    1. Uses stable system prompts for KV-cache optimization
    2. Includes conversation history from events
    3. Tracks token usage for cost monitoring

    Args:
        message: Current user message
        context: Pre-built context from context_builder_service
        session_state: Optional session state for stateful flows
        use_knowledge_base: Whether to search knowledge base
        folder_context: Additional folder file context

    Returns:
        Tuple of (response_text, sources, usage_dict)
    """
    from app.models.schemas import SessionState  # Import here to avoid circular

    sources: list[str] = []
    additional_context = ""

    # Add folder files context if provided
    if folder_context:
        additional_context += f"\n## Folder Files (Project Context)\n\n{folder_context}\n\n"
        sources.append("Folder Files")

    # Detect tapestry segment queries and add segment context
    segment_codes = detect_tapestry_query(message)
    if segment_codes:
        segment_context = get_segment_context_for_ai(segment_codes)
        if segment_context:
            additional_context += f"\n## Tapestry Segment Information (from Esri)\n\n{segment_context}\n\n"
            sources.append("Esri Tapestry Segmentation")

    # Search knowledge base if enabled
    if use_knowledge_base:
        results = await search_documents(query=message, limit=5)
        if results:
            context_parts = []
            for doc in results:
                context_parts.append(f"### {doc['title']}\n{doc['content'][:1000]}")
                sources.append(doc['title'])
            if context_parts:
                additional_context += "\n## Knowledge Base Documents\n\n" + "\n\n".join(context_parts)

    # Build final context (pre-built context + additional domain context)
    final_context = context
    if additional_context:
        final_context += additional_context

    if not client:
        return (
            "AI responses are not available. Please configure your OpenAI API key in the .env file.",
            sources,
            {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}
        )

    # Make API call
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": final_context},
            {"role": "user", "content": message}
        ],
        max_tokens=1000,
        temperature=0.7,
    )

    # Extract usage information
    usage = response.usage
    usage_dict = {
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
        "cached_tokens": 0,  # OpenAI doesn't report this directly yet
        "model": settings.openai_model,
    }

    # Try to get cached tokens if available (newer API versions)
    if hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
        cached = getattr(usage.prompt_tokens_details, 'cached_tokens', 0)
        usage_dict["cached_tokens"] = cached or 0

    return (
        response.choices[0].message.content or "",
        sources,
        usage_dict
    )
