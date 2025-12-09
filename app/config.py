from pydantic_settings import BaseSettings
from functools import lru_cache


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
    gemini_image_model: str = "imagen-3.0-generate-002"  # Imagen 3 for high-quality images

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

    # JWT Authentication
    jwt_secret: str = "your-super-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
