"""Resolution and validation of optional model-provider configuration."""
from __future__ import annotations

from typing import Any

_PROVIDER_BASE_URL = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
}


def validate_model_provider(settings: Any) -> None:
    if settings.query_planner_provider not in _PROVIDER_BASE_URL:
        raise ValueError(f"query_planner_provider must be one of {sorted(_PROVIDER_BASE_URL)}")
    if settings.query_planner_provider == "openai" and settings.query_planner_model == "claude-sonnet-5":
        raise ValueError("OpenAI provider requires an explicit OpenAI model name")


def resolved_model_api_key(settings: Any) -> str:
    path = settings.query_planner_api_key_file
    if path is None:
        return settings.query_planner_api_key
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"empty secret file: {path}")
    return value


def resolved_model_base_url(settings: Any) -> str:
    if settings.query_planner_base_url:
        return settings.query_planner_base_url.rstrip("/")
    return _PROVIDER_BASE_URL[settings.query_planner_provider]
