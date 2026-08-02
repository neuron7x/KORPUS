from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Anchored to the repository, not to the process working directory. A relative
    # ".env" means the production guard silently does not fire when the service is
    # started from anywhere but the repo root.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[4] / ".env",
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    llm_provider: Literal["stub", "openai", "local"] = "stub"
    openai_quality_model: str = "gpt-5.6-sol"
    openai_balanced_model: str = "gpt-5.6-terra"
    openai_router_model: str = "gpt-5.6-luna"
    min_retrieval_score: float = Field(0.72, ge=0, le=1)


@lru_cache
def get_settings() -> Settings:
    # pydantic-settings populates declared defaults and environment values at runtime.
    return Settings()  # type: ignore[call-arg]
