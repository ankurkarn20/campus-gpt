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
    # Login sessions end this long after login, whatever the activity.
    session_hours: int = 12
    # Send the session cookie over HTTPS only. Off for local http://localhost development.
    cookie_secure: bool = False

    # Rate limits (NFR-S5), in the `limits` notation: "10/minute", "100/hour".
    login_rate_per_ip: str = "10/minute"
    chat_rate_per_user: str = "10/minute"
    chat_rate_per_ip: str = "30/minute"
    # An account accepts no logins for a while after this many failed ones in the window.
    login_max_failures: int = 5
    login_failure_window_minutes: int = 15

    # Chat model: any OpenAI-compatible chat-completions endpoint with tool calling.
    # Groq (default) or Gemini: https://generativelanguage.googleapis.com/v1beta/openai
    # with LLM_MODEL=gemini-3.8-flash.
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str | None = None
    llm_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = 60
    # The hosted model the evaluation compares the configured (local) one with.
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"

    # Document search. BGE-small runs on the CPU through ONNX Runtime (fastembed); the model
    # (about 65 MB) is downloaded on first use into the cache directory.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    model_cache_dir: Path = Path.home() / ".cache" / "campusgpt" / "models"
    # Small local models often answer rule questions without searching. The chat therefore
    # searches the documents itself first and hands the passages to the model when the best
    # one is at least this similar to the question (cosine, BGE-small). 1.0 turns it off.
    rag_prefetch_min_similarity: float = 0.62


@lru_cache
def get_settings() -> Settings:
    return Settings()
