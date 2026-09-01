"""Негативний контроль, який не бігає, негативним контролем не є.

Виміряно 01.09.2026: 31 скрипт у `scripts/` оголошує `--selftest`, і **22 не
виконувались ЖОДНОЮ дорогою**. Серед них саме ті, чиї самоперевірки доводять, що
інструмент здатен ПОЧЕРВОНІТИ: `validate_span_hygiene` (15/15), `verify_public_surface`
(13/13), `recheck_blocked_sources` (24/24), `capture_source_evidence` (41/41),
`threshold_distance` (14/14). Разом вони йдуть 1,8 секунди — ціна мовчання була
нульова, і саме тому ніхто не помітив.

Форма ліків важлива, і тести тримають саме її: переліку немає НАВМИСНО. Перелік був би
ДРУГИМ оголошенням того самого факту й розійшовся б мовчки — як уже розходились юніт
systemd зі скриптом розгортання. Гейт сам знаходить кожен такий скрипт і сам його
запускає, тож «самоперевірку забули підключити» перестає бути станом, у який можна
потрапити.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_selftest_coverage.py"
SPEC = importlib.util.spec_from_file_location("verify_selftest_coverage", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def test_discovery_finds_the_declarations_not_the_mentions() -> None:
    """Згадка `--selftest` у документації не робить скрипт таким, що її має."""
    assert GATE.DECLARES.search('parser.add_argument("--selftest", action="store_true")')
    assert GATE.DECLARES.search("parser.add_argument('--selftest')")
    assert not GATE.DECLARES.search("# запусти з --selftest, щоб побачити контролі")
    assert not GATE.DECLARES.search('print("вжиток: script.py --selftest")')


def test_the_real_tree_declares_the_selftests_this_gate_will_run() -> None:
    """Проти РЕАЛЬНОСТІ: перелік не записаний ніде, він щоразу вимірюється."""
    found = GATE.declaring(ROOT)
    assert len(found) >= 25, found
    for expected in (
        "scripts/validate_span_hygiene.py",
        "scripts/verify_public_surface.py",
        "scripts/verify_gate_closure.py",
        "scripts/verify_evidence_stores.py",
    ):
        assert expected in found, expected


def test_a_declared_selftest_that_did_not_run_is_not_a_silent_pass() -> None:
    """Найдорожча помилка тут — порахувати пропущене за зелене."""
    findings = GATE.assess([{"script": "a.py", "verdict": "PASS"}], ["a.py", "b.py"])
    missed = next(f for f in findings if f["check"] == "every_declared_selftest_ran")
    assert missed["verdict"] == "FAIL" and "b.py" in missed["detail"]


def test_a_failing_selftest_reddens() -> None:
    findings = GATE.assess(
        [{"script": "a.py", "verdict": "PASS"}, {"script": "b.py", "verdict": "FAIL"}],
        ["a.py", "b.py"],
    )
    assert GATE.verdict(findings) == "FAIL"


def test_nothing_declared_is_unknown_not_pass() -> None:
    assert GATE.verdict(GATE.assess([], [])) == "UNKNOWN"


def test_a_selftest_that_hangs_is_a_failure_not_a_wait() -> None:
    """Самоперевірка, що висить, нічого не доводить — а виглядала б як «ще йде»."""
    assert GATE.TIMEOUT > 0
    source = SCRIPT.read_text(encoding="utf-8")
    assert "TimeoutExpired" in source and '"verdict": "FAIL"' in source


def test_the_gate_excludes_itself_from_the_run() -> None:
    """Інакше воно рекурсивно запускало б себе на кожному прогоні."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'if s != "scripts/verify_selftest_coverage.py"' in source


def test_the_gate_runs_green_on_the_real_tree() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False, cwd=ROOT
    )
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
