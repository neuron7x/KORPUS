"""Вирок гейта дельти — те, чого не читав жоден із семи наявних контролів.

Сім контролів у `test_mutation_delta_gate.py` тримають читача каталогу і реєстр
винятків. `classify` — функція, яка ВИНОСИТЬ вирок, — і `main`, яка перетворює його
на код виходу, не виконувались жодним тестом: мутаційний прогін по d41b12f1 показав,
що обидві належності (`in catalogued`, `in exceptions`), відбір `needs_probe` і сам
код виходу можна інвертувати, і повна батарея лишається зеленою.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_mutation_delta.py"
SPEC = importlib.util.spec_from_file_location("verify_mutation_delta_verdict", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

CATALOGUED = "apps/api/src/korpus/application/provenance.py"
EXCEPTED = "scripts/__excepted__.py"
UNCOVERED = "scripts/__brand_new__.py"


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "exceptions.json"
    path.write_text(
        json.dumps(
            {
                "schema": "korpus.mutation-delta-exceptions.v1",
                "accepted": [
                    {
                        "module": EXCEPTED,
                        "class": "requires_live_deployment",
                        "on": "2026-09-06",
                        "reason": "проба потребує піднятого розгортання",
                        "closes_when": "коли лан отримає підняте розгортання",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(GATE, "EXCEPTIONS", path)
    return path


def test_each_changed_module_gets_the_state_its_evidence_earns(
    registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Три стани, три різні підстави — і жодна з них не є станом за замовчуванням."""
    assert CATALOGUED in GATE.catalogued_modules(), "предмет тесту зник із каталогу"
    monkeypatch.setattr(GATE, "changed_modules", lambda _base: [CATALOGUED, EXCEPTED, UNCOVERED])
    report = GATE.classify("origin/main")
    assert {item["module"]: item["state"] for item in report["modules"]} == {
        CATALOGUED: "CATALOGUED",
        EXCEPTED: "EXCEPTED",
        UNCOVERED: "NEEDS_PROBE",
    }
    assert report["needs_probe"] == [UNCOVERED]


def test_a_delta_that_is_fully_covered_needs_no_probe(
    registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Позитивне плече: без нього тест вище проходив би на гейті, що завжди вимагає проби."""
    monkeypatch.setattr(GATE, "changed_modules", lambda _base: [CATALOGUED, EXCEPTED])
    assert GATE.classify("origin/main")["needs_probe"] == []


def test_the_exit_code_says_needs_probe_and_pass_apart(
    registry: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Код виходу — єдине, що читає лан. Вирок, який не доходить до нього, гейтом не є."""
    monkeypatch.setattr(GATE, "changed_modules", lambda _base: [CATALOGUED, EXCEPTED])
    monkeypatch.setattr(
        sys, "argv", ["gate", "--base", "origin/main", "--out", str(tmp_path / "a.json")]
    )
    assert GATE.main() == 0

    monkeypatch.setattr(GATE, "changed_modules", lambda _base: [UNCOVERED])
    monkeypatch.setattr(
        sys, "argv", ["gate", "--base", "origin/main", "--out", str(tmp_path / "b.json")]
    )
    assert GATE.main() == 2
    written = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert written["status"] == "NEEDS_PROBE"
    assert written["needs_probe"] == [UNCOVERED]


def test_the_selftest_passes_on_the_tree_as_shipped() -> None:
    """Додатне плече до `test_the_selftest_is_wired_and_can_fail`.

    Той тест доводить, що самоперевірка вміє червоніти. Він проходить і на
    самоперевірці, яка червоніє ЗАВЖДИ — зокрема на інвертованому контролі
    «неіснуючий модуль не каталогізований», який без цього плеча вижив.
    """
    assert GATE.selftest() == 0


def test_running_the_script_actually_runs_it(tmp_path: Path) -> None:
    """`if __name__ == "__main__"` — теж твердження, і воно не перевірялось.

    Інвертоване, воно робить скрипт мовчазним: жодного виводу, код виходу нуль.
    Це найгірша форма зеленого — гейт, якого не було.
    """
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{ROOT}/apps/api/src:{ROOT}/scripts"},
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout)["selftest"] == "PASS"
