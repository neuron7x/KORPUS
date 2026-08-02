import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
CALIBRATION_FILE = REPO_ROOT / "config" / "calibration.json"


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
    # Operational limits. They live here rather than in the code because an operator
    # under load must be able to change them without a release, and because a number
    # nobody can find is a number nobody can defend.
    max_answer_spans: int = Field(8, ge=1, le=50)
    candidate_multiplier: int = Field(8, ge=1, le=64)
    generator_timeout_seconds: float = Field(30.0, gt=0, le=300)
    rate_limit_burst: int = Field(30, ge=1, le=10_000)
    rate_limit_per_second: float = Field(1.0, ge=0, le=1000)
    circuit_failure_threshold: int = Field(5, ge=1, le=100)
    circuit_cooldown_seconds: float = Field(30.0, gt=0, le=3600)
    max_search_results: int = Field(20, ge=1, le=100)
    # Where the corpus and audit trail live. Anchored like the env file: a relative
    # path would put the database wherever the service happened to be started.
    corpus_path: Path = Path(__file__).resolve().parents[4] / "data" / "korpus.sqlite3"


def calibrated_threshold(path: Path | None = None) -> float | None:
    """Read the frozen retrieval threshold, if one has been calibrated.

    A malformed or missing file is not a startup failure: the code default stands and
    the reason is logged. Refusing to boot because a tuning file is unreadable would
    trade a slightly worse threshold for no service at all.
    """
    source = path or CALIBRATION_FILE
    if not source.exists():
        return None
    try:
        value = float(json.loads(source.read_text(encoding="utf-8"))["min_retrieval_score"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        log.error("ignoring unreadable calibration at %s: %s", source, error)
        return None
    if not 0.0 <= value <= 1.0:
        log.error("ignoring out-of-range calibrated threshold %s", value)
        return None
    return value


@lru_cache
def get_settings() -> Settings:
    # pydantic-settings populates declared defaults and environment values at runtime.
    settings = Settings()  # type: ignore[call-arg]
    calibrated = calibrated_threshold()
    if calibrated is not None and calibrated != settings.min_retrieval_score:
        log.info("using calibrated retrieval threshold %.2f", calibrated)
        settings = settings.model_copy(update={"min_retrieval_score": calibrated})
    return settings
