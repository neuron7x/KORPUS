"""Скільки баз доказів існує — і чи та, яку подають, є тією, яку назвали.

Виміряно 01.09.2026: у розгортанні живуть п'ять сховищ форми «докази» плюс постгрес.
Два з них небезпечні. `var/korpus.db` порожня і лежить рівно там, куди дивиться типове
значення `config.py`, тож процес без `KORPUS_DATABASE_URL` читає корпус із НУЛЯ
документів — і перевірки на порожньому вході зеленіють, бо їм нема на що скаржитись.
Постгрес містить ТІ САМІ 256 документів і на 7399 прольотів більше, тобто нарізка
інша, і `span_id` з нього в обслуговуваній базі означає інший фрагмент або нічого.

Обидва факти знали; жоден не був під перевіркою. Коментар — не гейт.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_evidence_stores.py"
REGISTRY = ROOT / "config/operations/evidence-stores.json"
SPEC = importlib.util.spec_from_file_location("verify_evidence_stores", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

SERVED = "var/runtime/corpus-v6-20260807/korpus.db"


def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _observation() -> dict[str, Any]:
    return {
        "stores": {
            SERVED: {"documents": 256, "spans": 31464},
            "var/korpus.db": {"documents": 0, "spans": 0},
        },
        "unit_database": SERVED,
        "config_default": "var/korpus.db",
    }


def _finding(findings: list[dict[str, str]], check: str) -> dict[str, str]:
    """Конкретна перевірка, не сукупний вирок: інакше мутант ховається за сусідкою."""
    return next(item for item in findings if item["check"] == check)


def test_the_registry_declares_exactly_one_served_store() -> None:
    served = [e for e in _registry()["stores"] if e.get("role") == "served"]
    assert len(served) == 1
    assert served[0]["path"] == SERVED


def test_the_served_store_is_the_one_the_unit_hands_the_service() -> None:
    """Найважливіша пара: реєстр каже одне, юніт віддає інше — і ніхто не звіряв."""
    findings = GATE.assess(_observation(), _registry())
    assert _finding(findings, "served_matches_unit")["verdict"] == "PASS"

    drifted = {**_observation(), "unit_database": "var/korpus.db"}
    assert _finding(GATE.assess(drifted, _registry()), "served_matches_unit")["verdict"] == "FAIL"


def test_a_store_nobody_named_is_refused() -> None:
    observation = _observation()
    observation["stores"]["var/чуже/korpus.db"] = {"documents": 7, "spans": 9}
    assert _finding(GATE.assess(observation, _registry()), "undeclared_store")["verdict"] == "FAIL"


def test_a_record_about_a_store_that_is_gone_is_refused() -> None:
    registry = _registry()
    registry["stores"].append({"path": "var/привид.db", "role": "draft", "reason": "x" * 20})
    assert _finding(GATE.assess(_observation(), registry), "ghost_store")["verdict"] == "FAIL"


def test_an_optional_store_may_be_absent() -> None:
    """Еталон і навчальний прогін існують лише після запуску — і це не діра."""
    assert _finding(GATE.assess(_observation(), _registry()), "ghost_store")["verdict"] == "PASS"


def test_two_served_stores_are_refused() -> None:
    registry = {
        "stores": [
            {"path": SERVED, "role": "served", "reason": "x" * 20},
            {"path": "var/korpus.db", "role": "served", "reason": "x" * 20},
        ]
    }
    assert _finding(GATE.assess(_observation(), registry), "one_served_store")["verdict"] == "FAIL"


def test_the_config_default_must_not_be_the_served_store() -> None:
    """Процес без оточення мусить падати видимо, а не виглядати працездатним."""
    observation = {**_observation(), "config_default": SERVED}
    finding = _finding(GATE.assess(observation, _registry()), "default_is_not_served")
    assert finding["verdict"] == "FAIL"


def test_the_config_default_is_actually_the_empty_database_in_this_tree() -> None:
    """Проти РЕАЛЬНОСТІ, не синтетики: типове значення справді вказує на порожню."""
    config = (ROOT / "apps/api/src/korpus/config.py").read_text(encoding="utf-8")
    matched = GATE._DEFAULT_IN_CONFIG.search(config)
    assert matched is not None and matched.group("path") == GATE.CONFIG_DEFAULT
    entry = next(e for e in _registry()["stores"] if e["path"] == GATE.CONFIG_DEFAULT)
    assert entry["role"] != "served" and entry["documents"] == 0


def test_the_unit_is_parsed_from_the_real_file() -> None:
    observation = GATE.observe(ROOT)
    unit = observation["unit_database"]
    assert unit == SERVED, unit


def test_the_postgres_divergence_is_named_not_discovered() -> None:
    """Друга база доказів мусить бути записана як РІШЕННЯ, а не знахідка.

    Ті самі 256 документів і 38863 прольоти проти 31464 означають іншу нарізку:
    перенесення `span_id` між ними неприпустиме без перерахунку.
    """
    external = _registry()["external"]
    entry = next(e for e in external if "postgres" in e["dsn"])
    assert entry["consistent_with_served"] is False
    assert entry["documents"] == 256 and entry["spans"] > 31464


def test_unknown_is_never_a_pass() -> None:
    assert GATE.verdict(GATE.assess({"stores": {}}, _registry())) == "UNKNOWN"
    blind = {**_observation(), "unit_database": None}
    assert GATE.verdict(GATE.assess(blind, _registry())) == "UNKNOWN"


def test_only_both_tables_together_make_an_evidence_store(tmp_path: Path) -> None:
    """Форма — обидві таблиці РАЗОМ. Інакше перелік захлинувся б кешами mypy.

    Тест будує бази сам, а не шукає їх у дереві: `glob`, що нічого не знайшов, дав би
    цикл із нуля ітерацій і зелений тест, який нічого не перевірив.
    """
    import sqlite3

    def build(name: str, tables: tuple[str, ...]) -> Path:
        path = tmp_path / name
        connection = sqlite3.connect(path)
        for table in tables:
            connection.execute(f"create table {table} (id integer primary key)")
        connection.commit()
        connection.close()
        return path

    assert GATE._shape(build("cache.db", ("meta", "hashes"))) is None
    assert GATE._shape(build("half.db", ("documents",))) is None
    assert GATE._shape(build("other-half.db", ("evidence_spans",))) is None
    assert GATE._shape(build("both.db", GATE.SHAPE)) == {"documents": 0, "spans": 0}


def test_a_store_that_cannot_be_read_is_an_event_not_a_silence(tmp_path: Path) -> None:
    """Мовчазне випадіння зі списку — найгірший вихід: гейт сказав би «усі названі»
    саме тоді, коли одне сховище не відкривається."""
    findings = GATE.assess(
        {
            "stores": {SERVED: {"unreadable": "database disk image is malformed"}},
            "unit_database": SERVED,
            "config_default": "var/korpus.db",
        },
        _registry(),
    )
    assert _finding(findings, "unreadable_store")["verdict"] == "FAIL"


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
