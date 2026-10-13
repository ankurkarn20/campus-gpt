"""Application settings, read from environment variables or the repository's .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str
    test_database_url: str | None = None
    # Password given to the demo accounts created by the seed command.
    demo_password: str = "campusgpt-demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
