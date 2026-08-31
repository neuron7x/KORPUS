"""Прийняте червоне мусить мати стелю, інакше воно просто червоне.

`span-hygiene` був FAIL ще до 31.08.2026 і не червонив нічого: ціль не була досяжна з
жодного входу, бо міряє РОЗГОРТАННЯ, а `make check` мусить проходити там, де корпусу
немає. Підключити як є — зробити щоденний гейт червоним; лишити мовчки — вдавати, що
діри немає. Третій стан: борг названий, має стелю, і гейт відмовляє на погіршенні.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/check_deployment_debt.py"
REGISTRY = ROOT / "config/operations/deployment-debt.json"
SPEC = importlib.util.spec_from_file_location("check_deployment_debt", SCRIPT)
assert SPEC and SPEC.loader
DEBT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEBT)

ENTRY = {"target": "t", "metric": "spans_dirty", "ceiling": 89}


def test_worsening_by_one_is_refused() -> None:
    """Ратчет існує рівно заради цього випадку."""
    result = DEBT.judge(ENTRY, {"spans_dirty": 90})
    assert result["verdict"] == "FAIL" and "+1" in result["detail"]


def test_sitting_on_the_ceiling_passes() -> None:
    assert DEBT.judge(ENTRY, {"spans_dirty": 89})["verdict"] == "PASS"


def test_improvement_demands_a_lower_ceiling() -> None:
    """Ратчет, який не помічає покращення, з часом стає дозволом."""
    result = DEBT.judge(ENTRY, {"spans_dirty": 40})
    assert result["verdict"] == "PASS" and result["lower_ceiling_to"] == 40


def test_a_missing_metric_is_unknown_not_pass() -> None:
    """Звіт без метрики нічого не доводить; нуль тут оголосив би борг закритим тим,
    що його не міряли."""
    assert DEBT.judge(ENTRY, {"other": 1})["verdict"] == "UNKNOWN"
    assert DEBT.judge(ENTRY, None)["verdict"] == "UNKNOWN"


def test_a_boolean_is_not_a_measurement() -> None:
    """`True` є `int` у Python — саме так проходить те, що не мало права."""
    assert DEBT.judge(ENTRY, {"spans_dirty": True})["verdict"] == "UNKNOWN"


def test_an_entry_without_a_ceiling_is_refused_not_allowed() -> None:
    assert DEBT.judge({"target": "t", "metric": "x"}, {"x": 1})["verdict"] == "FAIL"


def test_every_registered_debt_names_a_reason_a_ceiling_and_a_way_out() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert registry["accepted"], "порожній реєстр боргу читався б як відсутність боргу"
    for entry in registry["accepted"]:
        assert isinstance(entry["ceiling"], int) and not isinstance(entry["ceiling"], bool)
        assert len(entry["reason"].strip()) >= 40, entry["target"]
        assert entry["closes_when"].strip(), entry["target"]
        assert isinstance(entry["command"], list) and entry["command"]


def test_the_span_hygiene_ceiling_is_the_measured_number() -> None:
    """Стеля — виміряне значення дня, не кругле й не із запасом."""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entry = next(e for e in registry["accepted"] if e["target"] == "span-hygiene")
    assert entry["ceiling"] == 89 and entry["metric"] == "spans_dirty"


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
