"""Негативні контролі гейта дельти. Гейт, чиї контролі не бігають, гейтом не є.

Кожен тест тут ставить питання «чи МОЖЕ цей гейт почервоніти», а не «чи він
зелений»: зелений гейт, нездатний на червоне, вимірює власну присутність.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_mutation_delta.py"
SPEC = importlib.util.spec_from_file_location("verify_mutation_delta", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def test_the_curated_catalogue_is_parsed_not_grepped() -> None:
    """Розбір AST, а не пошук підрядком: згадка в коментарі не є мутантом."""
    modules = GATE.catalogued_modules()
    assert len(modules) >= 50, f"каталог розпізнано лише на {len(modules)} — розбір зламався"
    # Каталог ширший за застосунок: виміряно 2026-09-06 — apps 143, scripts 68,
    # deploy 2, Makefile 1. Перша редакція цього тесту вимагала префікса
    # `apps/api/src/` і впала на власному хибному припущенні; воно ж стояло у
    # фільтрі гейта і робило його сліпим до `scripts/`, де живуть самі гейти.
    roots = {name.split("/", 1)[0] for name in modules}
    assert "apps" in roots and "scripts" in roots, roots
    assert any(name.startswith("apps/api/src/") for name in modules)


def test_a_module_that_does_not_exist_is_not_catalogued() -> None:
    assert "apps/api/src/korpus/application/__does_not_exist__.py" not in GATE.catalogued_modules()


def test_an_exception_without_a_closing_condition_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Виняток без `closes_when` вічний, а вічний виняток — це дозвіл, не борг."""
    registry = tmp_path / "exceptions.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "korpus.mutation-delta-exceptions.v1",
                "accepted": [
                    {
                        "module": "apps/api/src/korpus/application/x.py",
                        "class": "requires_live_deployment",
                        "on": "2026-09-05",
                        "reason": "проба потребує піднятого розгортання",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(GATE, "EXCEPTIONS", registry)
    with pytest.raises(SystemExit) as error:
        GATE.load_exceptions()
    assert "closes_when" in str(error.value)


def test_a_complete_exception_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Позитивний контроль: без нього тест вище проходив би на будь-якій поломці читача."""
    registry = tmp_path / "exceptions.json"
    module = "apps/api/src/korpus/application/x.py"
    registry.write_text(
        json.dumps(
            {
                "schema": "korpus.mutation-delta-exceptions.v1",
                "accepted": [
                    {
                        "module": module,
                        "class": "requires_live_deployment",
                        "on": "2026-09-05",
                        "reason": "проба потребує піднятого розгортання",
                        "closes_when": "коли лан отримає підняте розгортання",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(GATE, "EXCEPTIONS", registry)
    assert module in GATE.load_exceptions()


def test_a_missing_registry_is_empty_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Відсутній реєстр означає «винятків нема», тобто СУВОРІШЕ, а не м'якше."""
    monkeypatch.setattr(GATE, "EXCEPTIONS", tmp_path / "absent.json")
    assert GATE.load_exceptions() == {}


def test_the_shipped_registry_is_readable_and_every_entry_names_its_closing_condition() -> None:
    """Реєстр у дереві мусить читатись цим самим кодом, а не лише бути валідним JSON."""
    assert GATE.load_exceptions() is not None


def test_the_selftest_is_wired_and_can_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Самоперевірка, яка не вміє впасти, не є самоперевіркою."""

    def _empty_catalogue() -> set[str]:
        return set()

    monkeypatch.setattr(GATE, "catalogued_modules", _empty_catalogue)
    assert GATE.selftest() == 1
