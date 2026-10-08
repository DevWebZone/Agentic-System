from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="Agentic URL Shortener", validation_alias="APP_NAME")
    app_env: str = Field(default="development", validation_alias="APP_ENV")
    debug: bool = Field(default=False, validation_alias="DEBUG")
    api_v1_prefix: str = Field(default="/api/v1", validation_alias="API_V1_PREFIX")
    database_url: str = Field(
        default="sqlite:///./agentic_url_shortener.db", validation_alias="DATABASE_URL"
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    llm_requirements_enabled: bool = Field(
        default=False, validation_alias="LLM_REQUIREMENTS_ENABLED"
    )
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    requirements_model: str = Field(default="gpt-4.1-mini", validation_alias="REQUIREMENTS_MODEL")
    llm_max_output_tokens: int = Field(default=1200, validation_alias="LLM_MAX_OUTPUT_TOKENS")
    planning_model: str = Field(default="Sol", validation_alias="PLANNING_MODEL")
    code_model: str = Field(default="Terra", validation_alias="CODE_MODEL")
    gate_model: str = Field(default="Luna", validation_alias="GATE_MODEL")


@lru_cache
def get_settings() -> Settings:
    """Return the immutable, cached application configuration."""

    return Settings()
