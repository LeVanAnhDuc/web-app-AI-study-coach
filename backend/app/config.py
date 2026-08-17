from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    jwt_secret: str
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 30

    llm_key_encryption_key: str = ""
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    mistral_api_key: str | None = None

    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    mistral_model: str = "mistral-large-latest"

    llm_fixture_mode: Literal["off", "record", "replay"] = "off"
    llm_fixture_dir: str = "tests/fixtures/llm"


@lru_cache
def get_settings() -> Settings:
    return Settings()
