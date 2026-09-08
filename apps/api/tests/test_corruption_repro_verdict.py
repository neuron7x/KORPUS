"""Вирок інструмента дослідження мусить мати сторожа — інакше він тихо зміліє.

08.09.2026 у самому відтворювачі знайдено глушіння: читач ковтав
`sqlite3.DatabaseError`, тобто клас, яким приходить «database disk image is malformed».
Лікування додало ДРУГУ дорогу до вироку: пошкодження, побачене читачем ПОСЕРЕД прогону,
рахується навіть тоді, коли підсумковий `quick_check` чистий — файл міг полагодитись
відкатом WAL, і тоді підсумок мовчить про подію, яка сталася.

Ця друга дорога — саме те, що легко зникає без сліду: вона нічого не ламає, коли її
прибрати, і звіт лишається зеленим. Тому вона має тести і мутантів.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "reproduce_sqlite_corruption", ROOT / "scripts/reproduce_sqlite_corruption.py"
)
assert SPEC and SPEC.loader
REPRO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPRO)

QUIET: dict[str, object] = {"observed": 0, "corruption": 0, "other": 0, "first": []}
SAW: dict[str, object] = {
    "observed": 3,
    "corruption": 2,
    "other": 1,
    "first": [{"class": "DatabaseError", "error": "database disk image is malformed"}],
}


def test_a_clean_run_reports_no_damage() -> None:
    """Позитивний контроль: без нього дві проби нижче були б зелені й порожні."""
    assert REPRO.damage_of({"intact": True}, QUIET) is None


def test_a_broken_file_reports_the_final_check() -> None:
    after = {"intact": False, "quick_check": "malformed", "damaged": ["evidence_spans"]}
    assert REPRO.damage_of(after, QUIET) == after


def test_what_the_reader_saw_is_damage_even_when_the_file_ends_clean() -> None:
    """Подія сталася. «Файл полагодився» не робить її такою, що не сталася."""
    damage = REPRO.damage_of({"intact": True}, SAW)
    assert damage is not None
    assert damage["seen_by_readers"] == SAW["first"]


def _emit_status(tmp_path: Path, arms: list[dict[str, object]]) -> str:
    out = tmp_path / "repro.json"
    arguments = SimpleNamespace(
        writers=2, transactions=10, readers=4, source=Path("probe.db"), out=out
    )
    REPRO._emit(arguments, arms)
    return str(json.loads(out.read_text(encoding="utf-8"))["status"])


def test_the_verdict_is_not_measured_when_nothing_was_seen(tmp_path: Path) -> None:
    arms = [{"arm": "mmap_production", "intact_after": True, "readers_observed": QUIET}]
    assert _emit_status(tmp_path, arms) == "NOT_MEASURED"


def test_the_verdict_is_reproduced_when_only_the_reader_saw_it(tmp_path: Path) -> None:
    """Єдина ознака — журнал читача. Підсумкова перевірка тут чиста."""
    arms = [{"arm": "mmap_production", "intact_after": True, "readers_observed": SAW}]
    assert _emit_status(tmp_path, arms) == "REPRODUCED"


def test_the_verdict_is_reproduced_when_the_final_check_is_dirty(tmp_path: Path) -> None:
    arms = [{"arm": "mmap_production", "intact_after": False, "readers_observed": QUIET}]
    assert _emit_status(tmp_path, arms) == "REPRODUCED"
