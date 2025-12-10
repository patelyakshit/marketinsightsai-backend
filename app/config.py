import logging
import warnings
from pydantic_settings import BaseSettings
from pydantic import field_validator, model_validator
from functools import lru_cache
from typing import Self

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # App settings
    app_name: str = "MarketInsightsAI"
    debug: bool = False

    # CORS - comma-separated list of allowed origins
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/marketinsights"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    # Google Gemini (for image generation)
    google_api_key: str = ""
    gemini_image_model: str = "imagen-3.0-generate-002"  # Imagen 3 for generate_images() API

    # Google OAuth
    google_client_id: str = ""

    # Esri/ArcGIS GeoEnrichment
    arcgis_api_key: str = ""  # Uses ARCGIS_API_KEY or fallback to location key
    arcgis_location_api_key: str = ""  # For geocoding/location services
    arcgis_data_api_key: str = ""  # For GeoEnrichment/demographics
    esri_geoenrich_base_url: str = "https://geoenrich.arcgis.com/arcgis/rest/services/World/geoenrichmentserver/Geoenrichment"
    esri_cache_ttl_hours: int = 24

    @property
    def effective_arcgis_api_key(self) -> str:
        """Get the best available API key for geocoding."""
        return self.arcgis_api_key or self.arcgis_location_api_key or self.arcgis_data_api_key

    # Report settings
    reports_output_path: str = "./reports"

    # Supabase Storage (for cloud file storage)
    supabase_url: str = ""
    supabase_service_key: str = ""  # Service role key for server-side operations
    supabase_storage_bucket: str = "reports"  # Default bucket name

    # Backend URL (for generating full URLs when Supabase not configured)
    backend_url: str = ""  # e.g., https://marketinsightsai-backend-production.up.railway.app

    # JWT Authentication
    jwt_secret: str = "your-super-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Sentry Error Monitoring
    sentry_dsn: str = ""
    sentry_environment: str = "development"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Validate database URL format."""
        if not v:
            raise ValueError("DATABASE_URL is required")
        if not v.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Warn if using default JWT secret in production."""
        if v == "your-super-secret-key-change-in-production":
            warnings.warn(
                "Using default JWT secret! Set JWT_SECRET environment variable in production.",
                UserWarning,
                stacklevel=2,
            )
        elif len(v) < 32:
            warnings.warn(
                f"JWT_SECRET is only {len(v)} characters. Recommend at least 32 characters.",
                UserWarning,
                stacklevel=2,
            )
        return v

    @model_validator(mode="after")
    def validate_config(self) -> Self:
        """Validate configuration at startup and warn about missing optional configs."""
        missing_warnings = []

        # Check critical API keys
        if not self.openai_api_key:
            missing_warnings.append("OPENAI_API_KEY not set - AI chat features will not work")

        if not self.google_client_id:
            missing_warnings.append("GOOGLE_CLIENT_ID not set - Google OAuth disabled")

        if not self.google_api_key:
            missing_warnings.append("GOOGLE_API_KEY not set - image generation disabled")

        if not self.effective_arcgis_api_key:
            missing_warnings.append("No ArcGIS API key set - geocoding/demographics disabled")

        # Log warnings for missing configs
        for warning in missing_warnings:
            logger.warning(f"Config: {warning}")

        # Log info about configured features
        configured = []
        if self.openai_api_key:
            configured.append("OpenAI")
        if self.google_client_id:
            configured.append("Google OAuth")
        if self.google_api_key:
            configured.append("Imagen 3")
        if self.effective_arcgis_api_key:
            configured.append("ArcGIS")
        if self.sentry_dsn:
            configured.append("Sentry")

        if configured:
            logger.info(f"Config: Enabled features - {', '.join(configured)}")

        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
