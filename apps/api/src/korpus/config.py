from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    llm_provider: Literal["stub", "openai", "local"] = "stub"
    openai_quality_model: str = "gpt-5.6-sol"
    openai_balanced_model: str = "gpt-5.6-terra"
    openai_router_model: str = "gpt-5.6-luna"
    min_retrieval_score: float = Field(0.72, ge=0, le=1)
    min_citation_coverage: float = Field(0.95, ge=0, le=1)


@lru_cache
def get_settings() -> Settings:
    # pydantic-settings populates declared defaults and environment values at runtime.
    return Settings()  # type: ignore[call-arg]
