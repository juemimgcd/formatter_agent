from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = Field(
        default="Structured Search Agent", validation_alias="APP_NAME"
    )
    app_env: str = Field(default="dev", validation_alias="APP_ENV")
    debug: bool = Field(default=True, validation_alias="APP_DEBUG")
    host: str = Field(default="127.0.0.1", validation_alias="APP_HOST")
    port: int = Field(default=8000, validation_alias="APP_PORT")
    api_prefix: str = Field(default="/api/v1", validation_alias="APP_API_PREFIX")

    database_url: str = Field(
        default="",
        validation_alias="DATABASE_URL",
    )

    dashscope_api_key: str = Field(default="", validation_alias="DASHSCOPE_API_KEY")
    llm_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias="LLM_BASE_URL",
    )
    llm_model_name: str = Field(default="qwen-plus", validation_alias="LLM_MODEL_NAME")
    llm_temperature: float = Field(default=0.2, validation_alias="LLM_TEMPERATURE")
    llm_timeout_seconds: float = Field(
        default=60.0, validation_alias="LLM_TIMEOUT_SECONDS"
    )
    llm_max_retries: int = Field(default=0, validation_alias="LLM_MAX_RETRIES")
    candidate_chunk_timeout_seconds: float = Field(
        default=0.0,
        validation_alias="CANDIDATE_CHUNK_TIMEOUT_SECONDS",
    )
    structured_stage_timeout_seconds: float = Field(
        default=0.0,
        validation_alias="STRUCTURED_STAGE_TIMEOUT_SECONDS",
    )
    search_provider: str = Field(
        default="duckduckgo_html", validation_alias="SEARCH_PROVIDER"
    )
    search_timeout_seconds: float = Field(
        default=12.0, validation_alias="SEARCH_TIMEOUT_SECONDS"
    )
    search_result_limit: int = Field(default=5, validation_alias="SEARCH_RESULT_LIMIT")
    search_region: str = Field(default="cn-zh", validation_alias="SEARCH_REGION")

    output_dir: Path = BASE_DIR / "outputs"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
