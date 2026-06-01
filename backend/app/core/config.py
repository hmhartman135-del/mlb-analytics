from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "MLB Analytics Platform"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics"
    database_url_sync: str = "postgresql://postgres:password@localhost:5432/mlb_analytics"

    # Redis
    redis_url: str = "redis://localhost:6379"
    cache_ttl_seconds: int = 3600

    # Sportradar — NO LONGER REQUIRED.
    # Standings, rosters, and stats now all use the free MLB Stats API.
    # This key is kept only for backward compatibility; it is not called anywhere.
    sportradar_api_key: str = ""
    sportradar_base_url: str = "https://api.sportradar.us/mlb/trial/v7/en"

    # Anthropic — required for all AI features (draft sim, trade finder, etc.)
    anthropic_api_key: str = ""

    # Auth
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
