from __future__ import annotations

from fastapi.testclient import TestClient
from korpus.config import Settings
from korpus.main import create_app


def test_model_executors_are_built_once_per_process_lifespan(monkeypatch) -> None:
    planner = object()
    composer = object()
    calls = {"planner": 0, "composer": 0}

    def build_planner(settings: Settings) -> object:
        del settings
        calls["planner"] += 1
        return planner

    def build_composer(settings: Settings) -> object:
        del settings
        calls["composer"] += 1
        return composer

    monkeypatch.setattr("korpus.model_composition.build_query_planner", build_planner)
    monkeypatch.setattr("korpus.model_composition.build_answer_composer", build_composer)
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        assert app.state.query_planner is planner
        assert app.state.answer_composer is composer

    assert calls == {"planner": 1, "composer": 1}
