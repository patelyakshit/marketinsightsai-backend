"""
Slides AI Service

AI-powered content generation for presentations.
Uses OpenAI to structure slide content from natural language requests.
"""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings
from app.services.slides_service import (
    SlideContent,
    SlideLayout,
    PresentationConfig,
    GeneratedPresentation,
    generate_presentation_from_content,
)

logger = logging.getLogger(__name__)
settings = get_settings()


async def generate_slides_from_prompt(
    prompt: str,
    context: Optional[dict] = None,
    theme: str = "default",
    max_slides: int = 15,
) -> GeneratedPresentation:
    """
    Generate a complete presentation from a natural language prompt.

    Args:
        prompt: User's description of what they want
        context: Optional context (tapestry data, store info, etc.)
        theme: Presentation theme
        max_slides: Maximum number of slides to generate

    Returns:
        GeneratedPresentation
    """
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    # Build context string
    context_str = ""
    if context:
        if "store_name" in context:
            context_str += f"\nStore/Location: {context['store_name']}"
        if "location" in context:
            context_str += f"\nAddress: {context['location']}"
        if "segments" in context:
            context_str += f"\nTapestry Segments: {json.dumps(context['segments'][:5])}"
        if "insights" in context:
            context_str += f"\nKey Insights: {context['insights']}"

    system_prompt = f"""You are an expert presentation designer. Generate a structured presentation based on the user's request.

Output a JSON object with:
{{
  "title": "Main presentation title",
  "subtitle": "Optional subtitle",
  "slides": [
    {{
      "layout": "title|section_header|bullet_points|two_column|quote|data_table",
      "title": "Slide title",
      "subtitle": "Optional subtitle",
      "bullet_points": ["Point 1", "Point 2"],  // for bullet_points layout
      "left_column": "Left content",  // for two_column layout
      "right_column": "Right content",  // for two_column layout
      "body": "Main text",  // for quote layout
      "data": {{"columns": ["Col1", "Col2"], "rows": [{{"Col1": "val", "Col2": "val"}}]}}  // for data_table
    }}
  ]
}}

Guidelines:
- Start with a title slide
- Use section headers to organize topics
- Keep bullet points concise (3-6 per slide)
- Include a closing/thank you slide
- Maximum {max_slides} slides
- Match the professional tone appropriate for business presentations
- If data is provided, visualize it with tables or charts
"""

    user_message = f"""Create a presentation for:

{prompt}
{context_str}

Generate {min(max_slides, 12)} slides that effectively communicate this content."""

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)

        # Build slide content objects
        slides = []
        for slide_data in result.get("slides", []):
            layout_str = slide_data.get("layout", "bullet_points")
            try:
                layout = SlideLayout(layout_str)
            except ValueError:
                layout = SlideLayout.BULLET_POINTS

            slides.append(SlideContent(
                layout=layout,
                title=slide_data.get("title", ""),
                subtitle=slide_data.get("subtitle"),
                body=slide_data.get("body"),
                bullet_points=slide_data.get("bullet_points", []),
                left_column=slide_data.get("left_column"),
                right_column=slide_data.get("right_column"),
                data=slide_data.get("data"),
                speaker_notes=slide_data.get("speaker_notes"),
            ))

        # Create configuration
        config = PresentationConfig(
            title=result.get("title", "Presentation"),
            subtitle=result.get("subtitle"),
            theme=theme,
        )

        return await generate_presentation_from_content(config, slides)

    except Exception as e:
        logger.error(f"AI slide generation error: {e}")
        raise


async def generate_tapestry_slides(
    store_name: str,
    location: str,
    segments: list[dict],
    theme: str = "default",
) -> GeneratedPresentation:
    """
    Generate a Tapestry analysis presentation using AI.

    Args:
        store_name: Store name
        location: Location/address
        segments: Tapestry segment data
        theme: Theme name

    Returns:
        GeneratedPresentation
    """
    # First, generate insights using AI
    from app.services.ai_service import generate_business_insights

    insights = await generate_business_insights(segments, store_name)

    # Use the structured generator
    from app.services.slides_service import generate_tapestry_presentation

    return await generate_tapestry_presentation(
        store_name=store_name,
        location=location,
        segments=segments,
        insights=insights,
        theme=theme,
    )


async def enhance_slides_with_ai(
    slides: list[SlideContent],
    enhancement_type: str = "professional",
) -> list[SlideContent]:
    """
    Enhance existing slide content using AI.

    Args:
        slides: Existing slide content
        enhancement_type: Type of enhancement ("professional", "engaging", "concise")

    Returns:
        Enhanced slides
    """
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    # Convert slides to JSON for AI processing
    slides_data = []
    for slide in slides:
        slides_data.append({
            "layout": slide.layout.value,
            "title": slide.title,
            "subtitle": slide.subtitle,
            "bullet_points": slide.bullet_points,
            "body": slide.body,
        })

    enhancement_prompts = {
        "professional": "Make the content more professional and business-appropriate. Use clear, impactful language.",
        "engaging": "Make the content more engaging and memorable. Add compelling hooks and transitions.",
        "concise": "Make the content more concise. Remove filler words and focus on key points.",
    }

    system_prompt = f"""You are a presentation editor. Enhance the following slides.
{enhancement_prompts.get(enhancement_type, enhancement_prompts['professional'])}

Return the same JSON structure with improved content."""

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(slides_data)}
            ],
            temperature=0.6,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        enhanced_data = result.get("slides", result) if isinstance(result, dict) else result

        # Rebuild slide content
        enhanced_slides = []
        for i, slide_data in enumerate(enhanced_data):
            if i < len(slides):
                # Preserve original layout if not specified
                layout = SlideLayout(slide_data.get("layout", slides[i].layout.value))
                enhanced_slides.append(SlideContent(
                    layout=layout,
                    title=slide_data.get("title", slides[i].title),
                    subtitle=slide_data.get("subtitle", slides[i].subtitle),
                    body=slide_data.get("body", slides[i].body),
                    bullet_points=slide_data.get("bullet_points", slides[i].bullet_points),
                    left_column=slide_data.get("left_column", slides[i].left_column),
                    right_column=slide_data.get("right_column", slides[i].right_column),
                    data=slides[i].data,  # Preserve data
                ))

        return enhanced_slides

    except Exception as e:
        logger.error(f"Slide enhancement error: {e}")
        return slides  # Return original on error
