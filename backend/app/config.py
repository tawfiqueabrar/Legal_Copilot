from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
MIN_SUPPORT_QUOTE_CHARS = 60


class Settings(BaseSettings):
    # Resolve from this module so CLI tools and the API load the same backend/.env
    # regardless of the process working directory.
    model_config = SettingsConfigDict(env_file=BACKEND_ENV_FILE, env_ignore_empty=True, extra="ignore")
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Keep a tested lightweight backup available in hosted deployments even when
    # GEMINI_FALLBACK_MODEL is omitted; the wrapper uses it only after primary 503/504.
    gemini_fallback_model: str = "gemini-3.1-flash-lite"
    support_check_model: str = ""
    gemini_cache_ttl_seconds: int = 3600
    courtlistener_token: str = ""
    courtlistener_api_token: str = ""
    eurlex_ws_username: str = ""
    eurlex_ws_password: str = ""
    voyage_api_key: str = ""
    cohere_api_key: str = ""
    max_upload_bytes: int = 25_000_000
    session_ttl_seconds: int = 3600
    allowed_origins: str = "http://localhost:3000"

    @model_validator(mode="after")
    def default_support_check_model_to_primary(self):
        if not self.support_check_model.strip():
            self.support_check_model = self.gemini_model
        return self

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
