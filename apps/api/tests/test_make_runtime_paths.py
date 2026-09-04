"""Шляхи рантайму в Makefile укорінені в КАНОНІЧНОМУ оголошенні.

Два плечі, і це не дублювання. Властивість тут — ТЕКСТ Makefile: `SERVED_CORPUS`
виводиться з `CANONICAL_ROOT`, а той — із `config/operations/canonical-state.json`.
Для цього `make` не потрібен. Друге плече перевіряє РОЗГОРТАННЯ й потребує `make`;
там, де двійника немає, предмета цього плеча немає теж.

Виміряно 04.09.2026: перша редакція мала лише друге плече й падала в CI із
`FileNotFoundError: 'make'` — у `python:3.12-slim` його немає й не було. Один
відсутній двійник скасував п'ятнадцять джобів, серед них `source:package`, тобто саме
той, що мав закрити останній машинний блокер. Сьома поява форми, у якій проба
успадковує ІНСТРУМЕНТ від середовища замість створити свою умову.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _make_value(name: str) -> str:
    recipe = f"__print_runtime_path:\n\t@printf '%s\\n' \"$({name})\""
    completed = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-s",
            "--eval",
            recipe,
            "__print_runtime_path",
            f"PY={sys.executable}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


SUFFIXES = {
    "SERVED_CORPUS": "var/runtime/corpus-v6-20260807/korpus.db",
    "SERVED_OBJECTS": "var/runtime/corpus-v6-20260807/objects",
}


def _definition(name: str) -> str:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    found = re.search(rf"^{name}\s*\??=\s*(.+)$", text, re.MULTILINE)
    assert found, f"Makefile не оголошує {name}"
    return found.group(1).strip()


def test_the_runtime_paths_are_written_against_the_canonical_declaration() -> None:
    """Плече без інструмента: властивість ТЕКСТУ, тож правдиве скрізь однаково."""
    assert "canonical-state.json" in _definition("CANONICAL_ROOT"), (
        "корінь мусить походити з оголошення, а не з поточного каталогу"
    )
    for name, suffix in SUFFIXES.items():
        assert _definition(name) == f"$(CANONICAL_ROOT)/{suffix}", name


def test_make_expands_those_paths_to_the_declared_root() -> None:
    """Плече з інструментом: чи РОЗГОРТАННЯ дає те, що написано."""
    if shutil.which("make") is None:
        pytest.skip("`make` відсутній: предмета цього плеча в цьому середовищі немає")
    registry = json.loads(
        (ROOT / "config/operations/canonical-state.json").read_text(encoding="utf-8")
    )
    canonical = Path(registry["canonical_root"])
    for name, suffix in SUFFIXES.items():
        assert _make_value(name) == str(canonical / suffix), name
