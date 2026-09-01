"""Юніт, ВСТАНОВЛЕНИЙ на машині, мусить бути тим, що описує дерево.

Виміряно 01.09.2026 — третє оголошення тієї самої властивості. У дереві
`korpus-public-api.service` самооголошений (усі змінні рядками `Environment=`, а
`EnvironmentFile=` заборонений тестом, бо властивості безпеки публічного API мусять
читатись у репозиторії). `check_public_env_parity` звіряє цей шаблон зі скриптом
розгортання. А на машині встановлено ІНШЕ: юніт з
`EnvironmentFile=%h/.local/state/korpus-public/api.env`.

Тобто гейт паритету сумлінно звіряв дві копії, **жодна з яких не виконується**. І це не
теорія: сторож відновлює API саме цим юнітом.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_installed_units.py"
SPEC = importlib.util.spec_from_file_location("verify_installed_units", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

UNIT = '[Service]\n# пояснення\nWorkingDirectory=/canon\nExecStart=/x\nEnvironment="A=1"\n'


def test_a_comment_is_not_a_difference() -> None:
    """Порівняння підрядком уже одного разу покарало за документацію рішення."""
    other = UNIT.replace("# пояснення", "# зовсім інше пояснення, і довше")
    assert GATE.verdict(GATE.assess({"u": other}, {"u": UNIT}, "/canon")) == "PASS"


def test_an_extra_directive_in_the_installed_unit_is_refused() -> None:
    """Саме так виглядає жива розбіжність: `EnvironmentFile=` є там і немає тут."""
    installed = UNIT + "EnvironmentFile=%h/.local/state/korpus-public/api.env\n"
    finding = GATE.assess({"u": installed}, {"u": UNIT}, "/canon")[0]
    assert finding["verdict"] == "FAIL" and "EnvironmentFile" in finding["detail"]


def test_a_changed_value_is_refused() -> None:
    assert (
        GATE.verdict(GATE.assess({"u": UNIT.replace("A=1", "A=2")}, {"u": UNIT}, "/canon"))
        == "FAIL"
    )


def test_a_unit_installed_for_another_root_is_unknown_not_a_failure() -> None:
    """Гейт не сміє червоніти з ВЛАСНОЇ причини.

    Шаблон розгортається відносно дерева, з якого запущено; у worktree це дає інші
    абсолютні шляхи, і юніт для нього ніхто ставити не збирався. Оголосити це
    розбіжністю означало б повторити в самому гейті ту ваду, яку він ловить.
    """
    finding = GATE.assess({"u": UNIT}, {"u": UNIT.replace("/canon", "/worktree")}, "/worktree")[0]
    assert finding["verdict"] == "UNKNOWN" and "іншого кореня" in finding["detail"]


def test_the_same_root_still_shows_a_real_difference() -> None:
    """Дуал: знижка за корінь не сміє ковтати справжню розбіжність."""
    finding = GATE.assess({"u": UNIT.replace("/x", "/y")}, {"u": UNIT}, "/canon")[0]
    assert finding["verdict"] == "FAIL"


def test_a_missing_unit_is_unknown_not_a_pass() -> None:
    assert GATE.verdict(GATE.assess({"u": None}, {"u": UNIT}, "/canon")) == "UNKNOWN"
    assert GATE.verdict(GATE.assess({}, {}, "/canon")) == "UNKNOWN"


def test_the_tree_template_is_still_self_declaring() -> None:
    """Рішення дерева не змінилось: оточення читається в репозиторії.

    Гейт не судить, який варіант кращий; він відповідає на питання, якого ніхто не
    ставив — чи встановлене є тим, що ми читаємо.
    """
    unit = GATE.INSTALLER.render("korpus-public-api.service")
    assert not any(line.startswith("EnvironmentFile=") for line in GATE.directives(unit))
    assert any(line.startswith("Environment=") for line in GATE.directives(unit))


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
