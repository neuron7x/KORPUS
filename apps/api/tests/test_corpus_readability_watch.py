"""Подія без ЧАСУ і без УМОВИ не входить у розслідування.

Чотири пошкодження корпусу за три доби, і в жодного немає часу події — лише час
випадкового виявлення, щоразу за години: нічна перевірка, впала служба, наткнувся
запитом. Через це гіпотезу про тиск памʼяті нічим звірити з подією.

Проба дешева НАВМИСНО: два константні за розміром бази запити, тож вона може бігти
щохвилини, не конкуруючи з тим, що стереже. Її контракт — ЧИТАНІСТЬ, не цілісність, і
межа названа тестом нижче, а не лишена читачеві на здогад.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "watch_corpus_readability", ROOT / "scripts/watch_corpus_readability.py"
)
assert SPEC and SPEC.loader
WATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WATCH)


def _healthy(path: Path) -> Path:
    connection = sqlite3.connect(str(path))
    connection.executescript(
        f"create table {WATCH.PROBE_TABLE} (id integer primary key, text text);"
        f"insert into {WATCH.PROBE_TABLE} (text) values ('проліт');"
    )
    connection.commit()
    connection.close()
    return path


def test_a_healthy_corpus_is_readable(tmp_path: Path) -> None:
    assert WATCH.observe(_healthy(tmp_path / "ok.db"))["status"] == "READABLE"


def test_a_healthy_corpus_does_not_drag_the_machine_state_along(tmp_path: Path) -> None:
    """Знімок машини щохвилини був би шумом. Він має сенс РІВНО при відмові."""
    assert "machine_at_failure" not in WATCH.observe(_healthy(tmp_path / "ok.db"))


def test_a_file_that_is_not_a_database_is_unreadable(tmp_path: Path) -> None:
    """Саме цим впав корпус 09.09: `file is not a database`, схема не обходиться."""
    target = tmp_path / "broken.db"
    target.write_bytes("це не база".encode() * 4096)
    seen = WATCH.observe(target)
    assert seen["status"] == "UNREADABLE"
    assert seen["probe"]["stage"] == "schema"


def test_a_corruption_is_named_by_type_identity_not_by_words(tmp_path: Path) -> None:
    """`sqlite3.DatabaseError` рівно цього типу — коди без власного підкласу, серед них
    SQLITE_CORRUPT і SQLITE_NOTADB. Шукати «malformed» у тексті означало б матчити
    ВІДКРИТУ множину повідомлень."""
    target = tmp_path / "broken.db"
    target.write_bytes("це не база".encode() * 4096)
    assert WATCH.observe(target)["probe"]["corruption_signal"] is True


def test_a_failure_carries_the_machine_conditions_of_its_moment(tmp_path: Path) -> None:
    """Єдиний свідок того, В ЧОМУ сталася подія. Без нього наступне пошкодження знову
    буде «сталося колись уночі»."""
    target = tmp_path / "broken.db"
    target.write_bytes("це не база".encode() * 4096)
    conditions = WATCH.observe(target)["machine_at_failure"]
    assert "MemAvailable" in conditions
    assert "SwapFree" in conditions
    assert conditions["largest_processes"]


def test_a_missing_database_is_unreadable_rather_than_silent(tmp_path: Path) -> None:
    assert WATCH.observe(tmp_path / "absent.db")["status"] == "UNREADABLE"


def test_the_cheap_probe_names_its_limit_instead_of_pretending(tmp_path: Path) -> None:
    """Обрізана база з уцілілим заголовком віддає обидва запити — і це КОНТРАКТ, не вада.

    Повноту дає нічна `measure_corpus_integrity.py` з обходом усіх таблиць. Якщо колись
    дешева проба почне звати таке пошкодженням, розподіл праці між ними розійдеться, і
    цей тест мусить почервоніти.
    """
    healthy = _healthy(tmp_path / "ok.db")
    truncated = tmp_path / "cut.db"
    truncated.write_bytes(healthy.read_bytes()[: 4096 * 2])
    assert WATCH.observe(truncated)["status"] == "READABLE"
