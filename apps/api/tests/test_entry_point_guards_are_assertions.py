"""`if __name__ == "__main__":` теж твердження — і його спростування мусить ловити
ТЕСТ, а не аварія збирання.

Обидва вижилі мутанти цього класу (`probe_blank_corpus.py`, `refresh_owner_packet.py`)
формально «вбиті»: інвертований сторож змушує модуль виконати `main()` під час
імпорту, і файл, який імпортує його на рівні модуля, валить збирання pytest кодом 3.
Вирок при цьому виносить ЗБІЙ ПРОЦЕСУ, а не жодне твердження: приберіть завтра
підпроцесні плечі з `test_owner_packet_refresh.py` — мутант лишиться «вбитим», і
метрика не зрушить. Убивця, якого не можна прибрати, не міряє нічого.

Тут модулі НЕ імпортуються на рівні файла. Кожен запускається так, як його запускає
оператор, і предметом твердження є ВИВІД: інвертований сторож дає нуль байтів при
коді виходу 0 — тиша, невідрізненна від успіху.

Виміряно на 6e20c7ce: оригінал `refresh_owner_packet.py --help` — 1651 байт і чотири
входження `--check`; з `if __name__ != "__main__":` — 0 байт, код 0.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

#: Скрипти, які мають ВЛАСНУ точку входу. `current_truth_admission.py` сюди не
#: входить навмисно: це бібліотека без `main`, і вимога сторожа від неї була б
#: вимогою мати те, чого вона не має.
ENTRY_POINTS = ("probe_blank_corpus.py", "refresh_owner_packet.py", "verify_mutation_delta.py")


def _help(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{ROOT}/apps/api/src:{ROOT}/scripts"},
    )


@pytest.mark.parametrize("script", ENTRY_POINTS)
def test_a_script_run_as_a_script_actually_runs(script: str) -> None:
    """Плече, яке відрізняє робочий сторож від інвертованого.

    Твердження про ВИВІД, не про код виходу: інвертований сторож теж виходить нулем,
    тож `returncode == 0` сам по собі мутанта не бачить.
    """
    done = _help(script)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith("usage:"), f"{script} нічого не надрукував: {done.stdout!r}"
    assert script in done.stdout, done.stdout


@pytest.mark.parametrize("script", ENTRY_POINTS)
def test_importing_a_script_does_not_run_it(script: str) -> None:
    """Друга половина того самого твердження, і без неї перша не повна.

    Сторож існує, щоб імпорт НЕ виконував `main()`. Тест, який перевіряє лише запуск,
    зелений і для модуля зовсім без сторожа — а такий модуль виконує роботу від
    самого імпорту будь-ким.
    """
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import importlib.util,sys;"
            f"s=importlib.util.spec_from_file_location('m', r'{ROOT}/scripts/{script}');"
            f"m=importlib.util.module_from_spec(s);sys.modules['m']=m;s.loader.exec_module(m);"
            f"print('IMPORTED_CLEANLY')",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{ROOT}/apps/api/src:{ROOT}/scripts"},
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "IMPORTED_CLEANLY" in done.stdout, done.stdout + done.stderr
