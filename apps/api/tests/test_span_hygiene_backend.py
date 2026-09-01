"""Яку базу міряє гейт чистоти прольотів — і чому це не деталь реалізації.

Правило було «є файл — SQLite, немає — psql». Воно тихо міняло ПРЕДМЕТ виміру.
Виміряно 01.09.2026: у чистому worktree `var/runtime/` немає взагалі, тож шлях до
обслуговуваного корпусу не існував і гейт ішов у psql. Того дня psql на сокеті не
було, і вийшла зрозуміла відмова. Але `korpus-postgres-1` піднятий і здоровий; якби
сокет був відкритий, гейт ПОМІРЯВ БИ ІНШИЙ КОРПУС і доповів число так, наче воно про
той, що подається солдату.

Це вже коштувало дня в `audit-verify`, де «anchor is ahead of the database head»
описувало не журнал, а дві різні бази під одним якорем. Тому форма рядка вирішує, а
існування перевіряється ПІСЛЯ вибору: названий файл, якого немає, — відмова, а не
привід спитати когось іншого.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/validate_span_hygiene.py"
SPEC = importlib.util.spec_from_file_location("validate_span_hygiene", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("var/runtime/corpus-v6-20260807/korpus.db", "sqlite"),
        ("/absolute/korpus.db", "sqlite"),
        ("korpus.sqlite3", "sqlite"),
        ("sqlite:////tmp/korpus.db", "sqlite"),
        ("sqlite:///relative.db", "sqlite"),
        ("postgresql://user@host/korpus", "psql"),
        ("postgres://user@host/korpus", "psql"),
        ("dbname=korpus host=localhost", "psql"),
        ("korpus", "psql"),
    ],
)
def test_the_backend_follows_the_form_of_the_string(value: str, expected: str) -> None:
    assert GATE.backend(value)[0] == expected


def test_a_path_that_does_not_exist_is_still_sqlite() -> None:
    """Ядро вади: відсутність файла НЕ сміє перетворювати шлях на іншу базу."""
    assert GATE.backend("var/runtime/цього-немає/korpus.db") == (
        "sqlite",
        "var/runtime/цього-немає/korpus.db",
    )


def test_a_named_file_that_is_missing_is_a_refusal_not_another_database() -> None:
    with pytest.raises(SystemExit) as raised:
        GATE._rows_from("var/runtime/цього-немає/korpus.db")
    assert "якого немає" in str(raised.value)


def test_the_sqlite_scheme_keeps_the_absolute_path() -> None:
    assert GATE.backend("sqlite:////home/x/korpus.db")[1] == "/home/x/korpus.db"


def test_the_selftest_covers_both_the_rule_and_the_subject() -> None:
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
