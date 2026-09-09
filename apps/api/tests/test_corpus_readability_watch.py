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
import json
import sqlite3
import subprocess
import sys
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


# Прилад, поставлений заради ЧАСУ ПОДІЇ, губив би саме подію: `--out` — ОДИН файл, який
# перезаписується щохвилини, тож відмова о 03:00 зникала б о 03:01. Побачити це можна
# було лише спитавши, що станеться ПІСЛЯ відмови, а не чи ловить він її — перша редакція
# тестів перевіряла друге і була зелена.
def _broken(path: Path) -> Path:
    path.write_bytes("це не база".encode() * 4096)
    return path


def test_a_failure_survives_the_next_successful_observation(tmp_path: Path) -> None:
    """Найдорожчий тест файла: доказ мусить пережити наступний зелений прогін."""
    journal = tmp_path / "failures.jsonl"
    WATCH.append_failure(journal, WATCH.observe(_broken(tmp_path / "broken.db")))
    WATCH.observe(_healthy(tmp_path / "ok.db"))
    lines = [line for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "UNREADABLE"


def test_the_journal_appends_instead_of_replacing(tmp_path: Path) -> None:
    """Чотири пошкодження за три доби мають дати ЧОТИРИ рядки, а не останній."""
    journal = tmp_path / "failures.jsonl"
    broken = _broken(tmp_path / "broken.db")
    for _ in range(3):
        WATCH.append_failure(journal, WATCH.observe(broken))
    assert (
        len([line for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()])
        == 3
    )


def test_every_journal_line_carries_its_moment_and_its_conditions(tmp_path: Path) -> None:
    """Рядок без часу і без умов не входить у розслідування — заради цього прилад і є."""
    journal = tmp_path / "failures.jsonl"
    WATCH.append_failure(journal, WATCH.observe(_broken(tmp_path / "broken.db")))
    record = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
    assert record["observed_at"]
    assert record["machine_at_failure"]["MemAvailable"]


def test_the_runner_actually_writes_the_journal_it_declares(tmp_path: Path) -> None:
    """Проба на ПРОВОДКУ, а не на функцію.

    `append_failure` можна викликати з тесту і бути зеленим, поки `main` її не кличе —
    саме так виглядав би розрив між приладом і його журналом: обидві половини цілі,
    разом не працюють. Тому тут запускається САМ скрипт, як його запускає systemd.
    """
    journal = tmp_path / "failures.jsonl"
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/watch_corpus_readability.py"),
            "--database",
            str(_broken(tmp_path / "broken.db")),
            "--out",
            str(tmp_path / "snapshot.json"),
            "--journal",
            str(journal),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 1, done.stderr[-400:]
    assert journal.is_file(), "виробник оголосив журнал і не написав у нього"
    assert json.loads(journal.read_text(encoding="utf-8").splitlines()[0])["status"] == "UNREADABLE"


def test_a_readable_run_leaves_the_journal_alone(tmp_path: Path) -> None:
    """Негативний контроль проводки: щохвилинний зелений прогін не сміє засмічувати
    журнал, інакше за добу там 1440 рядків і подію в них не знайти."""
    journal = tmp_path / "failures.jsonl"
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/watch_corpus_readability.py"),
            "--database",
            str(_healthy(tmp_path / "ok.db")),
            "--out",
            str(tmp_path / "snapshot.json"),
            "--journal",
            str(journal),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-400:]
    assert not journal.exists()
