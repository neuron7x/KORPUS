"""Composition root for optional, non-authoritative model executors."""

from __future__ import annotations

from typing import Any

from korpus.application.composition import AnswerComposer
from korpus.application.query_plan import QueryPlanner
from korpus.config import Settings
from korpus.infrastructure.anthropic_planner import (
    AnthropicAnswerComposer,
    AnthropicQueryPlanner,
)
from korpus.infrastructure.openai_planner import OpenAIAnswerComposer, OpenAIQueryPlanner
from korpus.model_settings import resolved_model_api_key, resolved_model_base_url
from korpus.tenancy_composition import build_egress_policy


def _model_adapter(settings: Settings, *, composer: bool) -> AnswerComposer | QueryPlanner:
    api_key = resolved_model_api_key(settings)
    model = settings.query_planner_model
    base_url = resolved_model_base_url(settings)
    timeout_seconds = (
        max(settings.query_planner_timeout_seconds, 8.0)
        if composer
        else settings.query_planner_timeout_seconds
    )
    egress = build_egress_policy(settings)
    arguments: dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "timeout_seconds": timeout_seconds,
        "egress": egress,
    }
    if settings.query_planner_provider == "openai":
        return (
            OpenAIAnswerComposer(api_key, **arguments)
            if composer
            else OpenAIQueryPlanner(api_key, **arguments)
        )
    return (
        AnthropicAnswerComposer(api_key, **arguments)
        if composer
        else AnthropicQueryPlanner(api_key, **arguments)
    )


def build_answer_composer(settings: Settings) -> AnswerComposer | None:
    """Build the bounded arranger only when explicitly enabled and credentialled."""
    if not settings.answer_composer_enabled or not resolved_model_api_key(settings):
        return None
    return _model_adapter(settings, composer=True)  # type: ignore[return-value]


def build_query_planner(settings: Settings) -> QueryPlanner | None:
    """Build the bounded reformulator only when explicitly enabled and credentialled."""
    if not settings.query_planner_enabled or not resolved_model_api_key(settings):
        return None
    return _model_adapter(settings, composer=False)  # type: ignore[return-value]


def install_model_executors(state: Any, settings: Settings) -> None:
    """Install process-scoped executors so circuit state survives requests."""
    state.query_planner = build_query_planner(settings)
    state.answer_composer = build_answer_composer(settings)
