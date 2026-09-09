"""Зонд читаності мусить питати те, що питає ШЛЯХ ГОТОВНОСТІ, а не те, що обрав автор.

Пʼяте пошкодження корпусу за три доби, 09.09.2026 о 17:34, поламало рівно три таблиці —
`audit_events`, `audit_heads`, `audit_anchor_outbox`. Зміст лишився цілим: 256 документів,
256 версій, 31464 прольоти. Попередня редакція зонда питала `sqlite_master` і один рядок
з `evidence_spans` — єдиної таблиці, якої пошкодження не торкнулось, — і написала
`READABLE`, коли служба вже віддавала 503. Журнал відмов лишився порожній.

Тут два роди перевірок, і кожен закриває свою половину.

ПРЕДМЕТ. Перелік таблиць виводиться з коду `AuditReader.readiness_snapshot`. Це
твердження перевіряється ДРУГИМ, незалежним способом: справжній `readiness_snapshot`
запускається на справжньому репозиторії, а SQL, який він шле, перехоплюється — і
множина таблиць у ньому мусить лежати всередині виведеної. Розбір джерела бачить УСІ
гілки, прогін бачить лише пройдені; жоден з них поодинці не достатній.

ЗДАТНІСТЬ ПОЧЕРВОНІТИ. Отрута вноситься в ДАНІ: кореневу сторінку однієї таблиці забито,
решта бази ціла. Форма 09.09 відтворена буквально, і поруч стоїть контроль, що ПОПЕРЕДНЄ
питання на тій самій отруті лишається зеленим — інакше отрута відтворює інший клас, і
весь негативний контроль вимірює не те.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from korpus.application.policy import PolicyEngine
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.repository import SqlRepository
from sqlalchemy import event
from sqlalchemy import text as sql_text

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "watch_corpus_readability", ROOT / "scripts/watch_corpus_readability.py"
)
assert SPEC and SPEC.loader
WATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WATCH)

WHO = Identity(
    subject="curator",
    roles=frozenset({"admin", "user", "auditor"}),
    clearance=AccessTier.RESTRICTED,
    corpora=frozenset({"public"}),
)
SQL_TABLE = re.compile(r"\bfrom\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)
#: `sqlite_master` не таблиця корпусу, а дерево схеми; зонд обходить його окремою
#: сходинкою `schema`, до всякого запиту по таблиці, і саме воно впало 09.09.
CONTAINER = {"sqlite_master"}


# ── ПРЕДМЕТ: що саме питає шлях готовності ───────────────────────────────────────────


def _tables_touched_by_readiness(tmp_path: Path) -> set[str]:
    """Таблиці, які `readiness_snapshot` питає НАСПРАВДІ — з перехопленого SQL.

    Умова створюється, а не успадковується: якір ставиться на голову ланцюга, інакше
    гілка `anchor.sequence >= 1` не виконується і `audit_events` не буде спитано взагалі.
    Проба, що успадкувала умову від середовища, вироджується мовчки — і тут це виглядало
    б як «шлях готовності не питає audit_events», тобто як дозвіл не питати її й зонду.
    """
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'seam.db'}", "seam-audit-key", PolicyEngine(), tmp_path / "a.json"
    )
    repository.initialize()
    for index in range(3):
        repository.append_audit(WHO, "document.ingested", "document_version", f"d{index}", {})
    with repository.engine.begin() as connection:
        connection.execute(sql_text("create table alembic_version (version_num varchar(32))"))
        connection.execute(sql_text("insert into alembic_version values ('0024_probe')"))
    first = repository.readiness_snapshot(max_pending_events=64, max_pending_age_seconds=60.0)
    repository.anchor_store.write(int(first["audit_head_sequence"]), str(first["audit_head_hash"]))

    statements: list[str] = []
    event.listen(
        repository.engine,
        "before_cursor_execute",
        lambda conn, cur, statement, *rest: statements.append(statement),
    )
    repository.readiness_snapshot(max_pending_events=64, max_pending_age_seconds=60.0)
    return {name.lower() for text in statements for name in SQL_TABLE.findall(text)}


def test_the_probe_asks_every_table_the_readiness_path_asks(tmp_path: Path) -> None:
    """Друге, незалежне свідчення про предмет: не розбір джерела, а перехоплений SQL.

    Розбір джерела бачить усі гілки й не знає, які з них виконуються; прогін бачить лише
    виконані. Дірку в зонді видно рівно там, де ці двоє розходяться.
    """
    touched = _tables_touched_by_readiness(tmp_path) - CONTAINER
    derived = set(WATCH.readiness_tables(WATCH.source_texts()))

    assert touched, "перехоплення не побачило жодної таблиці — вимір без предмета"
    assert touched <= derived, f"шлях готовності питає {sorted(touched - derived)}, зонд — ні"


def test_every_derived_table_has_a_declared_query() -> None:
    """Виведена таблиця без запиту — не помилка виведення, а дірка в зонді, і вона мусить
    бути видима як UNKNOWN, а не мовчки випасти з переліку."""
    derived = set(WATCH.readiness_tables(WATCH.source_texts()))

    assert derived <= set(WATCH.READINESS_QUERIES), sorted(derived - set(WATCH.READINESS_QUERIES))


def test_the_three_damaged_tables_are_all_in_the_plan() -> None:
    """Саме ці три постраждали 09.09; зонд, який не питає котроїсь, знову напише READABLE."""
    derived = set(WATCH.readiness_tables(WATCH.source_texts()))

    assert {"audit_events", "audit_heads", "audit_anchor_outbox"} <= derived


def test_the_plan_is_read_from_the_code_rather_than_remembered() -> None:
    """Отрута по ДЖЕРЕЛУ: таблиця, до якої `readiness_snapshot` більше не дотягується,
    мусить зникнути з переліку ТОГО Ж прогону. Звʼязок у `__init__` лишається — інакше
    це перейменування, тобто еквівалентний мутант, який виведення чесно переживе."""
    sources = WATCH.source_texts()

    poisoned = WATCH.readiness_tables(WATCH.Sources(WATCH._unreached(sources), *sources[1:]))

    assert "audit_anchor_outbox" not in poisoned
    assert "audit_heads" in poisoned, "отрута знесла більше, ніж один шлях"


def test_a_field_reached_through_another_method_is_still_found() -> None:
    """`audit_events` шлях готовності читає і через `_rollback_state`. Виведення, що не
    йде за власними викликами класу, загубило б саме її."""
    sources = WATCH.source_texts()
    indirect = WATCH.Sources(WATCH._indirect_reader(sources), *sources[1:])

    assert WATCH.readiness_tables(indirect) == ("audit_events",)


def test_a_readiness_path_that_cannot_be_read_is_not_an_empty_plan() -> None:
    """Зламане виведення — це «не знаю». Порожній перелік дав би READABLE, не спитавши
    нічого: `all([])` істинне, і це найтихіша з можливих дірок."""
    sources = WATCH.source_texts()
    renamed = sources.reader.replace("def readiness_snapshot(", "def gone(")

    try:
        WATCH.readiness_tables(WATCH.Sources(renamed, *sources[1:]))
    except WATCH.DerivationError:
        return
    raise AssertionError("зникнення readiness_snapshot не спинило виведення")


# ── ЗДАТНІСТЬ ПОЧЕРВОНІТИ: отрута по даних ───────────────────────────────────────────


def test_the_shape_of_the_ninth_is_unreadable(tmp_path: Path) -> None:
    """Кореневу сторінку `audit_heads` забито, зміст цілий — форма 09.09 буквально."""
    poisoned = WATCH.poison_table(WATCH.fixture(tmp_path / "corpus.db"), "audit_heads")

    seen = WATCH.observe(poisoned, True)

    assert seen["status"] == "UNREADABLE"
    assert seen["probe"]["unreadable_tables"] == ["audit_heads"]
    assert seen["probe"]["corruption_signal"] is True


def test_the_previous_question_stays_green_on_that_same_file(tmp_path: Path) -> None:
    """Контроль над самою отрутою: питання ПОПЕРЕДНЬОЇ редакції — схема плюс рядок із
    `evidence_spans` — мусить лишитись зеленим. Інакше отрута відтворює інший клас, і
    червоний тест вище доводив би не те, що сталося 09.09."""
    poisoned = WATCH.poison_table(WATCH.fixture(tmp_path / "corpus.db"), "audit_heads")

    assert WATCH._old_question_passes(poisoned) is True


def test_a_corpus_broken_only_in_the_audit_events_tree_is_unreadable(tmp_path: Path) -> None:
    """Друга з трьох таблиць, окремо: запит за максимальним номером читає `event_hash`,
    тобто мусить торкнутись дерева таблиці, а не лише покривного індексу."""
    poisoned = WATCH.poison_table(WATCH.fixture(tmp_path / "corpus.db"), "audit_events")

    seen = WATCH.observe(poisoned, True)

    assert seen["status"] == "UNREADABLE"
    assert seen["probe"]["unreadable_tables"] == ["audit_events"]


def test_an_intact_corpus_is_readable(tmp_path: Path) -> None:
    assert WATCH.observe(WATCH.fixture(tmp_path / "corpus.db"))["status"] == "READABLE"


def test_an_intact_corpus_does_not_drag_the_machine_state_along(tmp_path: Path) -> None:
    """Знімок машини щохвилини був би шумом. Він має сенс РІВНО при відмові."""
    assert "machine_at_failure" not in WATCH.observe(WATCH.fixture(tmp_path / "corpus.db"))


def test_a_missing_table_is_not_reported_as_corruption(tmp_path: Path) -> None:
    """`OperationalError` — підклас, і це ІНША вада: не пошкодження, а відсутня таблиця.
    Обидві дають UNREADABLE, і розслідування має бачити, котра саме."""
    corpus = WATCH.fixture(tmp_path / "corpus.db")
    connection = sqlite3.connect(str(corpus))
    connection.executescript("drop table audit_events;")
    connection.close()

    seen = WATCH.observe(corpus)

    assert seen["status"] == "UNREADABLE"
    assert seen["probe"]["corruption_signal"] is False


def test_a_file_that_is_not_a_database_is_unreadable(tmp_path: Path) -> None:
    target = tmp_path / "broken.db"
    target.write_bytes("це не база".encode() * 4096)

    seen = WATCH.observe(target)

    assert seen["status"] == "UNREADABLE"
    assert seen["probe"]["stage"] == "schema"


def test_a_missing_database_is_unreadable_rather_than_silent(tmp_path: Path) -> None:
    assert WATCH.observe(tmp_path / "absent.db")["status"] == "UNREADABLE"


def test_a_failure_carries_the_machine_conditions_of_its_moment(tmp_path: Path) -> None:
    """Єдиний свідок того, В ЧОМУ сталася подія. Без нього наступне пошкодження знову
    буде «сталося колись уночі»."""
    poisoned = WATCH.poison_table(WATCH.fixture(tmp_path / "corpus.db"), "audit_heads")

    conditions = WATCH.observe(poisoned, True)["machine_at_failure"]

    assert "MemAvailable" in conditions
    assert "SwapFree" in conditions
    assert conditions["largest_processes"]


# ── UNKNOWN не є PASS ────────────────────────────────────────────────────────────────


def test_an_empty_plan_is_unknown_rather_than_readable(tmp_path: Path) -> None:
    corpus = WATCH.fixture(tmp_path / "corpus.db")

    verdict = WATCH.readability(WATCH.Probe(corpus, False, ()))

    assert WATCH.status_of(verdict) == "UNKNOWN"


def test_a_table_without_a_declared_query_is_unknown(tmp_path: Path) -> None:
    corpus = WATCH.fixture(tmp_path / "corpus.db")

    verdict = WATCH.readability(WATCH.Probe(corpus, False, ("audit_heads", "documents")))

    assert WATCH.status_of(verdict) == "UNKNOWN"


def test_a_failure_outranks_the_unknown_beside_it(tmp_path: Path) -> None:
    """FAIL перебиває UNKNOWN: пошкодження не сміє сховатись за неоглянутою таблицею."""
    poisoned = WATCH.poison_table(WATCH.fixture(tmp_path / "corpus.db"), "audit_heads")

    verdict = WATCH.readability(WATCH.Probe(poisoned, True, ("audit_heads", "documents")))

    assert WATCH.status_of(verdict) == "UNREADABLE"


# ── ціна виміру ──────────────────────────────────────────────────────────────────────


def test_each_probe_is_constant_in_the_size_of_the_corpus(tmp_path: Path) -> None:
    """Не заявлено, а виміряно: кроки віртуальної машини SQLite на базах у 400 разів
    різного розміру. Зонд бігає щохвилини поруч із тим, що стереже."""
    small = WATCH.fixture(tmp_path / "small.db", rows=50)
    large = WATCH.fixture(tmp_path / "large.db", rows=20_000)

    for table, query in WATCH.READINESS_QUERIES.items():
        assert WATCH.vdbe_steps(small, query) == WATCH.vdbe_steps(large, query), table


def test_the_step_counter_can_see_a_query_that_grows(tmp_path: Path) -> None:
    """Позитивний контроль лічильника, і водночас — вимір про саму службу: ВЛАСНИЙ запит
    `readiness_snapshot` по `audit_anchor_outbox` лінійний, тож зонд бере обмежений."""
    small = WATCH.fixture(tmp_path / "small.db", rows=50)
    large = WATCH.fixture(tmp_path / "large.db", rows=20_000)
    linear = "select count(*), min(created_at) from audit_anchor_outbox where delivered_at is null"

    assert WATCH.vdbe_steps(small, linear) < WATCH.vdbe_steps(large, linear)


def test_reading_an_exhibit_does_not_write_beside_it(tmp_path: Path) -> None:
    """Збережений пошкоджений файл — доказ. Читання бази в режимі WAL створює поруч
    `-wal` і `-shm`; на доказі це запис у доказ, і в цьому дереві такі сліди вже лежать
    поруч із двома попередніми пошкодженнями."""
    corpus = WATCH.fixture(tmp_path / "corpus.db")
    connection = sqlite3.connect(str(corpus))
    connection.execute("pragma journal_mode=wal").fetchone()
    connection.close()
    before = {path.name for path in tmp_path.iterdir()}

    WATCH.observe(corpus, True)

    assert {path.name for path in tmp_path.iterdir()} == before


# ── проводка: те, що запускає systemd ────────────────────────────────────────────────


def _run(database: Path, journal: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/watch_corpus_readability.py"),
            "--database",
            str(database),
            "--out",
            str(journal.parent / "snapshot.json"),
            "--journal",
            str(journal),
            "--immutable",
        ],
        capture_output=True,
        timeout=180,
        check=False,
    )


def test_the_runner_actually_writes_the_journal_it_declares(tmp_path: Path) -> None:
    """Проба на ПРОВОДКУ, а не на функцію.

    `append_failure` можна викликати з тесту і бути зеленим, поки `main` її не кличе —
    саме так виглядав би розрив між приладом і його журналом: обидві половини цілі,
    разом не працюють. Тому тут запускається САМ скрипт, як його запускає systemd.
    """
    journal = tmp_path / "failures.jsonl"
    poisoned = WATCH.poison_table(WATCH.fixture(tmp_path / "corpus.db"), "audit_heads")

    done = _run(poisoned, journal)

    assert done.returncode == 1, done.stderr[-600:]
    assert journal.is_file(), "виробник оголосив журнал і не написав у нього"
    record = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
    assert record["status"] == "UNREADABLE"
    assert record["probe"]["unreadable_tables"] == ["audit_heads"]
    assert record["machine_at_failure"]["MemAvailable"]


def test_a_readable_run_leaves_the_journal_alone(tmp_path: Path) -> None:
    """Негативний контроль проводки: щохвилинний зелений прогін не сміє засмічувати
    журнал, інакше за добу там 1440 рядків і подію в них не знайти."""
    journal = tmp_path / "failures.jsonl"

    done = _run(WATCH.fixture(tmp_path / "corpus.db"), journal)

    assert done.returncode == 0, done.stderr[-600:]
    assert not journal.exists()


def test_a_failure_survives_the_next_successful_observation(tmp_path: Path) -> None:
    """Найдорожчий тест файла: доказ мусить пережити наступний зелений прогін."""
    journal = tmp_path / "failures.jsonl"
    poisoned = WATCH.poison_table(WATCH.fixture(tmp_path / "corpus.db"), "audit_heads")
    _run(poisoned, journal)

    _run(WATCH.fixture(tmp_path / "healthy.db"), journal)

    lines = [line for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "UNREADABLE"


def test_the_selftest_runs_and_is_the_one_the_makefile_calls() -> None:
    """Самоперевірка, яка не бігає, нею не є. `make corpus-readability` кличе саме її."""
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts/watch_corpus_readability.py"), "--selftest"],
        capture_output=True,
        timeout=300,
        check=False,
    )

    assert done.returncode == 0, done.stdout[-800:]
    assert json.loads(done.stdout)["failures"] == []
