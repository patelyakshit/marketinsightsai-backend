"""
Landing Page Service

Generate and deploy marketing landing pages from AI-generated content.
Creates HTML landing pages that can be:
- Downloaded as HTML files
- Deployed to static hosting (future: Vercel, Netlify)

Features:
- AI-powered content generation
- Multiple templates
- Responsive design
- Image integration
- SEO optimization
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.utils.datetime_utils import utc_now

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Output directory
OUTPUT_DIR = Path(settings.reports_output_path) / "landing_pages"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class LandingPageSection:
    """A section of the landing page."""
    section_type: str  # hero, features, testimonial, cta, about, contact
    headline: str
    subheadline: Optional[str] = None
    body: Optional[str] = None
    items: list[dict] = field(default_factory=list)  # For features, testimonials
    image_url: Optional[str] = None
    cta_text: Optional[str] = None
    cta_url: Optional[str] = None


@dataclass
class LandingPageConfig:
    """Configuration for landing page generation."""
    title: str
    business_name: str
    tagline: str
    primary_color: str = "#155E81"
    secondary_color: str = "#36B37E"
    font_family: str = "Inter, system-ui, sans-serif"
    template: str = "modern"  # modern, minimal, bold


@dataclass
class GeneratedLandingPage:
    """Result of landing page generation."""
    page_id: str
    filename: str
    filepath: str
    html_content: str
    created_at: datetime
    config: LandingPageConfig
    sections: list[LandingPageSection]


# =============================================================================
# Templates
# =============================================================================

MODERN_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{meta_description}">
    <title>{title}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: {font_family};
            line-height: 1.6;
            color: #333;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }}
        /* Hero Section */
        .hero {{
            background: linear-gradient(135deg, {primary_color} 0%, {secondary_color} 100%);
            color: white;
            padding: 100px 0;
            text-align: center;
        }}
        .hero h1 {{
            font-size: 3rem;
            font-weight: 700;
            margin-bottom: 20px;
        }}
        .hero p {{
            font-size: 1.25rem;
            opacity: 0.9;
            max-width: 600px;
            margin: 0 auto 30px;
        }}
        .btn {{
            display: inline-block;
            padding: 15px 40px;
            border-radius: 8px;
            font-weight: 600;
            text-decoration: none;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }}
        .btn-primary {{
            background: white;
            color: {primary_color};
        }}
        .btn-secondary {{
            background: {secondary_color};
            color: white;
        }}
        /* Features Section */
        .features {{
            padding: 80px 0;
            background: #f9fafb;
        }}
        .features h2 {{
            text-align: center;
            font-size: 2.5rem;
            margin-bottom: 50px;
            color: {primary_color};
        }}
        .features-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 30px;
        }}
        .feature-card {{
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }}
        .feature-card h3 {{
            font-size: 1.25rem;
            margin-bottom: 10px;
            color: {primary_color};
        }}
        .feature-icon {{
            font-size: 2rem;
            margin-bottom: 15px;
        }}
        /* About Section */
        .about {{
            padding: 80px 0;
        }}
        .about-content {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 50px;
            align-items: center;
        }}
        .about h2 {{
            font-size: 2rem;
            margin-bottom: 20px;
            color: {primary_color};
        }}
        /* CTA Section */
        .cta {{
            background: {primary_color};
            color: white;
            padding: 80px 0;
            text-align: center;
        }}
        .cta h2 {{
            font-size: 2.5rem;
            margin-bottom: 20px;
        }}
        .cta p {{
            font-size: 1.25rem;
            opacity: 0.9;
            margin-bottom: 30px;
        }}
        /* Footer */
        footer {{
            background: #1a1a2e;
            color: white;
            padding: 40px 0;
            text-align: center;
        }}
        footer p {{
            opacity: 0.7;
        }}
        /* Responsive */
        @media (max-width: 768px) {{
            .hero h1 {{ font-size: 2rem; }}
            .about-content {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    {sections_html}

    <footer>
        <div class="container">
            <p>&copy; {year} {business_name}. Generated by MarketInsightsAI.</p>
        </div>
    </footer>
</body>
</html>"""


def render_hero_section(section: LandingPageSection, config: LandingPageConfig) -> str:
    """Render hero section HTML."""
    cta_html = ""
    if section.cta_text:
        cta_html = f'<a href="{section.cta_url or "#"}" class="btn btn-primary">{section.cta_text}</a>'

    return f"""
    <section class="hero">
        <div class="container">
            <h1>{section.headline}</h1>
            <p>{section.subheadline or ""}</p>
            {cta_html}
        </div>
    </section>
    """


def render_features_section(section: LandingPageSection, config: LandingPageConfig) -> str:
    """Render features section HTML."""
    features_html = ""
    for item in section.items:
        features_html += f"""
        <div class="feature-card">
            <div class="feature-icon">{item.get('icon', '✨')}</div>
            <h3>{item.get('title', '')}</h3>
            <p>{item.get('description', '')}</p>
        </div>
        """

    return f"""
    <section class="features">
        <div class="container">
            <h2>{section.headline}</h2>
            <div class="features-grid">
                {features_html}
            </div>
        </div>
    </section>
    """


def render_about_section(section: LandingPageSection, config: LandingPageConfig) -> str:
    """Render about section HTML."""
    return f"""
    <section class="about">
        <div class="container">
            <div class="about-content">
                <div>
                    <h2>{section.headline}</h2>
                    <p>{section.body or ""}</p>
                </div>
                <div>
                    {f'<img src="{section.image_url}" alt="About" style="width:100%;border-radius:12px;">' if section.image_url else ''}
                </div>
            </div>
        </div>
    </section>
    """


def render_cta_section(section: LandingPageSection, config: LandingPageConfig) -> str:
    """Render CTA section HTML."""
    cta_html = ""
    if section.cta_text:
        cta_html = f'<a href="{section.cta_url or "#"}" class="btn btn-primary">{section.cta_text}</a>'

    return f"""
    <section class="cta">
        <div class="container">
            <h2>{section.headline}</h2>
            <p>{section.subheadline or ""}</p>
            {cta_html}
        </div>
    </section>
    """


def render_section(section: LandingPageSection, config: LandingPageConfig) -> str:
    """Render a section based on its type."""
    renderers = {
        "hero": render_hero_section,
        "features": render_features_section,
        "about": render_about_section,
        "cta": render_cta_section,
    }

    renderer = renderers.get(section.section_type, render_about_section)
    return renderer(section, config)


# =============================================================================
# Generation Functions
# =============================================================================

async def generate_landing_page_content(
    business_name: str,
    business_description: str,
    target_audience: str,
    key_benefits: list[str],
    call_to_action: str,
) -> list[LandingPageSection]:
    """
    Generate landing page content using AI.

    Args:
        business_name: Name of the business
        business_description: What the business does
        target_audience: Who the page is for
        key_benefits: Main value propositions
        call_to_action: What action users should take

    Returns:
        List of LandingPageSection objects
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    prompt = f"""Create compelling landing page content for:

Business: {business_name}
Description: {business_description}
Target Audience: {target_audience}
Key Benefits: {', '.join(key_benefits)}
Call to Action: {call_to_action}

Generate content for these sections in JSON format:
{{
  "hero": {{
    "headline": "compelling headline",
    "subheadline": "supporting text",
    "cta_text": "button text"
  }},
  "features": {{
    "headline": "features section title",
    "items": [
      {{"icon": "emoji", "title": "feature name", "description": "brief description"}},
      // 3-4 features
    ]
  }},
  "about": {{
    "headline": "about section title",
    "body": "2-3 sentences about the business"
  }},
  "cta": {{
    "headline": "final call to action headline",
    "subheadline": "urgency or benefit text",
    "cta_text": "button text"
  }}
}}

Make it engaging, professional, and conversion-focused."""

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )

        content = json.loads(response.choices[0].message.content)

        sections = []

        # Hero
        hero = content.get("hero", {})
        sections.append(LandingPageSection(
            section_type="hero",
            headline=hero.get("headline", business_name),
            subheadline=hero.get("subheadline", business_description),
            cta_text=hero.get("cta_text", call_to_action),
            cta_url="#contact",
        ))

        # Features
        features = content.get("features", {})
        sections.append(LandingPageSection(
            section_type="features",
            headline=features.get("headline", "Why Choose Us"),
            items=features.get("items", [
                {"icon": "🚀", "title": benefit, "description": ""}
                for benefit in key_benefits[:4]
            ]),
        ))

        # About
        about = content.get("about", {})
        sections.append(LandingPageSection(
            section_type="about",
            headline=about.get("headline", f"About {business_name}"),
            body=about.get("body", business_description),
        ))

        # CTA
        cta = content.get("cta", {})
        sections.append(LandingPageSection(
            section_type="cta",
            headline=cta.get("headline", "Ready to Get Started?"),
            subheadline=cta.get("subheadline", "Join thousands of satisfied customers"),
            cta_text=cta.get("cta_text", call_to_action),
            cta_url="#contact",
        ))

        return sections

    except Exception as e:
        logger.error(f"Landing page content generation failed: {e}")
        # Return basic sections
        return [
            LandingPageSection(
                section_type="hero",
                headline=business_name,
                subheadline=business_description,
                cta_text=call_to_action,
            ),
            LandingPageSection(
                section_type="features",
                headline="Our Benefits",
                items=[{"icon": "✨", "title": b, "description": ""} for b in key_benefits[:4]],
            ),
            LandingPageSection(
                section_type="cta",
                headline="Get Started Today",
                cta_text=call_to_action,
            ),
        ]


async def generate_landing_page(
    business_name: str,
    business_description: str,
    target_audience: str,
    key_benefits: list[str],
    call_to_action: str,
    primary_color: str = "#155E81",
    secondary_color: str = "#36B37E",
) -> GeneratedLandingPage:
    """
    Generate a complete landing page.

    Args:
        business_name: Name of the business
        business_description: What the business does
        target_audience: Who the page is for
        key_benefits: Main value propositions
        call_to_action: What action users should take
        primary_color: Primary brand color
        secondary_color: Secondary brand color

    Returns:
        GeneratedLandingPage with HTML content
    """
    # Generate content
    sections = await generate_landing_page_content(
        business_name=business_name,
        business_description=business_description,
        target_audience=target_audience,
        key_benefits=key_benefits,
        call_to_action=call_to_action,
    )

    # Create config
    config = LandingPageConfig(
        title=f"{business_name} - {sections[0].subheadline or business_description}"[:60],
        business_name=business_name,
        tagline=sections[0].subheadline or business_description,
        primary_color=primary_color,
        secondary_color=secondary_color,
    )

    # Render sections
    sections_html = "\n".join(render_section(s, config) for s in sections)

    # Render full page
    html_content = MODERN_TEMPLATE.format(
        title=config.title,
        meta_description=business_description[:160],
        font_family=config.font_family,
        primary_color=config.primary_color,
        secondary_color=config.secondary_color,
        business_name=config.business_name,
        year=datetime.now().year,
        sections_html=sections_html,
    )

    # Save to file
    page_id = str(uuid.uuid4())[:8]
    filename = f"landing_{page_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

    return GeneratedLandingPage(
        page_id=page_id,
        filename=filename,
        filepath=str(filepath),
        html_content=html_content,
        created_at=utc_now(),
        config=config,
        sections=sections,
    )


async def generate_landing_page_from_tapestry(
    store_name: str,
    location: str,
    segments: list[dict],
    business_type: str,
) -> GeneratedLandingPage:
    """
    Generate a landing page based on Tapestry segment data.

    Creates targeted messaging based on the dominant consumer segments.
    """
    # Extract key segment info
    if segments:
        dominant = segments[0]
        segment_name = dominant.get("name", "")
        life_mode = dominant.get("life_mode", "")

        # Build description based on segment
        target_audience = f"{segment_name} consumers - {life_mode}"
    else:
        target_audience = "Local consumers"

    # Generate benefits based on business type
    benefits = [
        f"Serving {location} since day one",
        "Tailored to local preferences",
        "Community-focused approach",
        "Exceptional customer service",
    ]

    return await generate_landing_page(
        business_name=store_name,
        business_description=f"Your trusted {business_type} in {location}",
        target_audience=target_audience,
        key_benefits=benefits,
        call_to_action="Visit Us Today",
    )
