from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_cache_ttl_seconds: int = 3600
    courtlistener_token: str = ""
    courtlistener_api_token: str = ""
    gemini_checker_model: str = "gemini-2.5-pro"
    eurlex_ws_username: str = ""
    eurlex_ws_password: str = ""
    voyage_api_key: str = ""
    cohere_api_key: str = ""
    max_upload_bytes: int = 25_000_000
    session_ttl_seconds: int = 3600
    allowed_origins: str = "http://localhost:3000"

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
