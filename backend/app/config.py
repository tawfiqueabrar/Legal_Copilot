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
    llm_provider: str = "gemini"
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    groq_support_model: str = "openai/gpt-oss-20b"
    gemini_model: str = "gemini-3.8-flash"
    # Keep a tested lightweight backup available in hosted deployments even when
    # GEMINI_FALLBACK_MODEL is omitted; failover is only used for transient failures.
    gemini_fallback_model: str = "gemini-3.1-flash-lite"
    gemini_secondary_fallback_model: str = "gemini-3.5-flash"
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

    @property
    def gemini_fallback_models(self) -> list[str]:
        return list(dict.fromkeys(
            value.strip() for value in (self.gemini_fallback_model, self.gemini_secondary_fallback_model)
            if value and value.strip() and value.strip() != self.gemini_model.strip()
        ))

    @property
    def provider_name(self) -> str:
        return self.llm_provider.strip().casefold()

    @property
    def active_api_key(self) -> str:
        return self.groq_api_key if self.provider_name == "groq" else self.gemini_api_key

    @property
    def analysis_configured(self) -> bool:
        return bool(self.active_api_key)

    @property
    def active_model(self) -> str:
        return self.groq_model if self.provider_name == "groq" else self.gemini_model


settings = Settings()
