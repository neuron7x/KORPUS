from __future__ import annotations

from fastapi.testclient import TestClient
from korpus.config import Settings
from korpus.main import create_app


def test_model_executors_are_built_once_per_process_lifespan(monkeypatch, tmp_path) -> None:
    """Виконавці моделей будуються РАЗ на процес — твердження про життєвий цикл.

    База тут не предмет, і саме тому її не можна брати з оточення. `Settings` без
    явного `database_url` підхоплює `KORPUS_DATABASE_URL` конвеєра, а разом із ним і
    типовий `schema_mode="auto"`: старт пробує створити пошуковий індекс, і роль
    застосунку — не власник таблиці — дістає відмову. Виміряно 03.09.2026 у джобі
    `api:postgres-and-restore`: єдиний упалий тест із усього набору, і впав він не
    через життєвий цикл, а через успадковану умову.

    Конфтест цю позицію знає й ставить `schema_mode="migrations"` своїм фікстурам, але
    цей тест їх не бере — тобто оточення було оголошене ДВІЧІ, і копії розійшлися.
    """
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
    app = create_app(
        Settings(
            environment="test",
            database_url=f"sqlite:///{tmp_path}/lifecycle.db",
            object_root=tmp_path / "objects",
        )
    )

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        assert app.state.query_planner is planner
        assert app.state.answer_composer is composer

    assert calls == {"planner": 1, "composer": 1}
