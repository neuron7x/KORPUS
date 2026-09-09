#!/usr/bin/env python3
"""Момент, коли корпус перестав читатися — тими запитами, які питає САМА служба.

Пʼяте пошкодження, 09.09.2026 о 17:34, оголило ваду в цьому приладі. Постраждали рівно
три таблиці — `audit_events`, `audit_heads`, `audit_anchor_outbox`; зміст лишився цілим
(256 документів, 256 версій, 31464 прольоти). Прилад питав `sqlite_master` і один рядок
з `evidence_spans` — ЄДИНОЇ таблиці, якої пошкодження не торкнулось, — і написав
`READABLE`, коли служба вже віддавала 503. Журнал відмов лишився порожній.

Це не помилка реалізації, а помилка предмета: сторож дивився повз те, що охороняє. Тому
перелік таблиць більше не належить авторові проби. Він ВИВОДИТЬСЯ з коду
`AuditReader.readiness_snapshot` — того самого, чиє падіння і є 503:

  · `self._audit_heads`, `self._audits`, `self._outbox` — обʼєкти таблиць, які туди
    передає `SqlRepository`, а їхні справжні імена лежать у `schema.py`;
  · `self.schema_revision()` — метод репозиторію, з чийого SQL береться `alembic_version`.

Виведення робиться розбором джерела, а не переліком у голові: якщо шлях готовності
почне питати четверту таблицю, зонд почне питати її ТОГО Ж ПРОГОНУ. Якщо виведення
зламається — це `UNKNOWN`, а не `READABLE`; порожній перелік не є дозволом (`all([])`
істинне, і саме так виглядає найтихіша з можливих дірок).

Кожен запит константний за розміром бази — не на слово, а виміряно лічильником кроків
VDBE на двох базах, що різняться в 400 разів (`--selftest`). Запит самої служби по
`audit_anchor_outbox` таким НЕ є: `count(*), min(created_at)` дає 370 кроків на 50
рядках і 300 070 на 50 000. Зонд бере ту саму умову, але обмежену першим рядком.

При ВІДМОВІ знімається стан МАШИНИ тієї ж миті — без цього наступна подія знову буде
«сталося колись уночі». Прилад нічого не лікує і нічого не переміщує; лікує
`scripts/heal_corpus_from_backup.py`, і він питає саме цей зонд.

    watch_corpus_readability.py --database DB [--out ФАЙЛ] [--journal ФАЙЛ] [--immutable]
    watch_corpus_readability.py --selftest
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, TypeGuard

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "korpus.corpus-readability-watch.v2"

READER_CLASS = "AuditReader"
READINESS_METHOD = "readiness_snapshot"
READER_SOURCE = ROOT / "apps/api/src/korpus/infrastructure/audit_reader.py"
REPOSITORY_SOURCE = ROOT / "apps/api/src/korpus/infrastructure/repository.py"
SCHEMA_SOURCE = ROOT / "apps/api/src/korpus/infrastructure/schema.py"

#: Витяг імені таблиці з SQL-рядка. Застосовується ЛИШЕ до констант, які починаються з
#: дієслова SQL: інакше проза в докстрингу («derived from audit_events») стала б
#: «таблицею», і зонд питав би те, чого нема.
SQL_STATEMENT = re.compile(r"^\s*(select|insert|update|delete)\b", re.IGNORECASE)
SQL_TABLE = re.compile(r"\bfrom\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)

#: Запит на таблицю шляху готовності. Умова — ТА САМА, що в `readiness_snapshot`;
#: обмеження — власне, бо проба бігає щохвилини поруч із тим, що стереже.
#:
#: `audit_heads` — рівно рядок singleton_id=1, як у службі.
#: `audit_events` — вибірка за МАКСИМАЛЬНИМ номером, не `count(*)`: служба читає
#:   `event_hash` за номером, тож зонд читає той самий стовпець, і це змушує його
#:   торкнутись дерева таблиці, а не лише покривного індексу.
#: `audit_anchor_outbox` — та сама умова `delivered_at is null` і той самий порядок за
#:   `created_at`, але перший рядок замість перерахунку всіх.
#: `alembic_version` — один рядок; служба читає його через `schema_revision`.
READINESS_QUERIES: dict[str, str] = {
    "audit_heads": 'select sequence, head_hash from "audit_heads" where singleton_id = 1',
    "audit_events": 'select sequence, event_hash from "audit_events" order by sequence desc limit 1',
    "audit_anchor_outbox": (
        'select sequence, created_at from "audit_anchor_outbox" '
        "where delivered_at is null order by created_at limit 1"
    ),
    "alembic_version": 'select version_num from "alembic_version" limit 1',
}


class DerivationError(RuntimeError):
    """Перелік не виведено з коду. Це «не знаю», а НЕ «таблиць нема»."""


class Sources(NamedTuple):
    """Три джерела, з яких виводиться предмет охорони. Приймаються ТЕКСТОМ, щоб
    самоперевірка могла отруїти саме джерело, а не спостерігати за собою."""

    reader: str
    repository: str
    schema: str


class Context(NamedTuple):
    """Чим розвʼязується один аргумент конструктора: імена таблиць і текст репозиторію."""

    literals: dict[str, str]
    repository: str


class Probe(NamedTuple):
    """Один предмет виміру. Зібраний у кортеж, бо стеля аргументів тут — два."""

    database: Path
    immutable: bool
    tables: tuple[str, ...]


# ── виведення предмета з коду ────────────────────────────────────────────────────────


def _class_of(source: str, name: str) -> ast.ClassDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise DerivationError(f"класу {name} немає в джерелі")


def _method_of(node: ast.ClassDef, name: str) -> ast.FunctionDef:
    for child in node.body:
        if isinstance(child, ast.FunctionDef) and child.name == name:
            return child
    raise DerivationError(f"методу {name} немає в {node.name}")


def _parameters(function: ast.FunctionDef) -> list[str]:
    args = function.args
    named = (*args.posonlyargs, *args.args, *args.kwonlyargs)
    return [argument.arg for argument in named if argument.arg != "self"]


def _self_names(node: ast.AST) -> set[str]:
    """Усі `self.X`, згадані у вузлі. Без розрізнення поля й методу — це робить викликач."""
    return {
        child.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute)
        and isinstance(child.value, ast.Name)
        and child.value.id == "self"
    }


def _reachable_attributes(node: ast.ClassDef, entry: str) -> set[str]:
    """Поля, до яких дотягується метод — ЧЕРЕЗ власні методи теж.

    `readiness_snapshot` читає `self._audits` не лише прямо, а й усередині
    `_rollback_state`. Виведення, що дивилось би тільки на тіло входу, загубило б
    `audit_events` — тобто рівно ту таблицю, яка впала 09.09.
    """
    methods = {child.name for child in node.body if isinstance(child, ast.FunctionDef)}
    if entry not in methods:
        raise DerivationError(f"методу {entry} немає в {node.name}")
    fields: set[str] = set()
    seen: set[str] = set()
    queue = [entry]
    while queue:
        name = queue.pop()
        seen.add(name)
        names = _self_names(_method_of(node, name))
        queue.extend(sorted((names & methods) - seen))
        fields |= names - methods
    return fields


def _init_bindings(node: ast.ClassDef) -> dict[str, str]:
    """`self.X = параметр` — єдина форма, яка тут щось значить: саме нею репозиторій
    передає обʼєкти таблиць. Присвоєння з виразу (`x or Y()`) свідомо не рахується."""
    init = _method_of(node, "__init__")
    parameters = set(_parameters(init))
    bound: dict[str, str] = {}
    for child in ast.walk(init):
        if isinstance(child, ast.Assign) and isinstance(child.value, ast.Name):
            bound.update(_targets_of(child, child.value.id) if child.value.id in parameters else {})
    if not bound:
        raise DerivationError(f"у {node.name}.__init__ не знайдено жодного звʼязку поля з входом")
    return bound


def _targets_of(assign: ast.Assign, parameter: str) -> dict[str, str]:
    return {
        target.attr: parameter for target in assign.targets if isinstance(target, ast.Attribute)
    }


def _construction_args(source: str, parameters: list[str]) -> dict[str, ast.expr]:
    """Чим репозиторій наповнює читача. Позиційні — за порядком, іменовані — за іменем."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != READER_CLASS:
            continue
        mapped = dict(zip(parameters, node.args, strict=False))
        mapped.update({word.arg: word.value for word in node.keywords if word.arg})
        return mapped
    raise DerivationError(f"виклику {READER_CLASS}(...) немає в репозиторії")


def _table_literals(source: str) -> dict[str, str]:
    """`имʼя_модуля -> справжнє імʼя таблиці` з `NAME = Table("...", ...)`."""
    literals: dict[str, str] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            literals.update(_table_binding(node))
    if not literals:
        raise DerivationError("у схемі не знайдено жодного оголошення Table(...)")
    return literals


def _is_table_call(node: ast.expr) -> TypeGuard[ast.Call]:
    return (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Table"
    )


def _table_name(call: ast.Call) -> str | None:
    first = call.args[0] if call.args else None
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _table_binding(assign: ast.Assign) -> dict[str, str]:
    if not _is_table_call(assign.value):
        return {}
    name = _table_name(assign.value)
    if name is None:
        return {}
    return {target.id: name for target in assign.targets if isinstance(target, ast.Name)}


def _sql_tables_in(node: ast.AST) -> set[str]:
    """Імена таблиць із SQL-констант вузла. Проза відсіюється до розбору, не після."""
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            found |= set(_tables_in_statement(child.value))
    return found


def _tables_in_statement(text: str) -> list[str]:
    if not SQL_STATEMENT.match(text):
        return []
    return [name.lower() for name in SQL_TABLE.findall(text)]


def _method_sql_tables(source: str, method: str) -> set[str]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == method:
            return _sql_tables_in(node)
    return set()


def _tables_behind(expression: ast.expr | None, context: Context) -> set[str]:
    """Що стоїть за одним аргументом: обʼєкт таблиці зі схеми або метод із власним SQL."""
    if isinstance(expression, ast.Name):
        literal = context.literals.get(expression.id)
        return {literal} if literal else set()
    if isinstance(expression, ast.Attribute):
        return _method_sql_tables(context.repository, expression.attr)
    return set()


def readiness_tables(sources: Sources) -> tuple[str, ...]:
    """Таблиці, які питає шлях готовності служби. Порожньо — це відмова, не дозвіл."""
    reader = _class_of(sources.reader, READER_CLASS)
    bindings = _init_bindings(reader)
    reached = _reachable_attributes(reader, READINESS_METHOD)
    used = sorted({bindings[field] for field in reached if field in bindings})
    arguments = _construction_args(sources.repository, _parameters(_method_of(reader, "__init__")))
    context = Context(_table_literals(sources.schema), sources.repository)
    found: set[str] = set()
    for name in used:
        found |= _tables_behind(arguments.get(name), context)
    if not found:
        raise DerivationError(f"з {READINESS_METHOD} не виведено жодної таблиці")
    return tuple(sorted(found))


def source_texts() -> Sources:
    try:
        return Sources(
            READER_SOURCE.read_text(encoding="utf-8"),
            REPOSITORY_SOURCE.read_text(encoding="utf-8"),
            SCHEMA_SOURCE.read_text(encoding="utf-8"),
        )
    except OSError as error:
        raise DerivationError(f"джерело шляху готовності недоступне: {error}") from error


# ── стан машини в мить відмови ───────────────────────────────────────────────────────


def machine_conditions() -> dict[str, Any]:
    """Стан машини В МИТЬ ВІДМОВИ. Знімається лише тоді — інакше це просто шум."""
    conditions: dict[str, Any] = {}
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
        wanted = ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree", "Dirty", "Writeback")
        for line in meminfo.splitlines():
            if line.split(":", 1)[0] in wanted:
                conditions[line.split(":", 1)[0]] = line.split(":", 1)[1].strip()
    except OSError as error:
        conditions["meminfo_error"] = str(error)
    conditions["largest_processes"] = largest_processes()
    return conditions


def largest_processes(limit: int = 5) -> list[str]:
    """Найбільші процеси — з `/proc`, а НЕ через зовнішній `ps`.

    Перша редакція кликала `ps`, і в контейнері CI його немає: тест упав із
    `KeyError: largest_processes`, бо ключа мовчки не було. Але важливіше за тест інше —
    прилад, який має описати машину В МИТЬ ВІДМОВИ, не сміє залежати від стороннього
    виконуваного файла, якого може не бути саме тоді, коли машині зле.

    Порожній перелік — ЧЕСНА відповідь там, де `/proc` недоступний, і вона відрізняється
    від «процесів немає» лише тим, що ключ присутній ЗАВЖДИ.
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    rows = [
        size
        for entry in proc.iterdir()
        if entry.name.isdigit() and (size := _resident_size(entry)) is not None
    ]
    rows.sort(reverse=True)
    return [f"{rss} {name}" for rss, name in rows[:limit]]


def _resident_size(entry: Path) -> tuple[int, str] | None:
    """Розмір і назва одного процесу, або None, якщо його вже нема.

    Процес, що помер між переліком і читанням, — звичайна гонка, а не подія досліду.
    """
    try:
        status = (entry / "status").read_text(encoding="utf-8")
    except OSError:
        return None
    name = ""
    rss = 0
    for line in status.splitlines():
        if line.startswith("Name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("VmRSS:"):
            rss = int(line.split()[1])
    return (rss, name) if rss else None


# ── сам вимір ────────────────────────────────────────────────────────────────────────


def _connect(probe: Probe) -> sqlite3.Connection:
    """`immutable=1` — для ЗБЕРЕЖЕНИХ доказів, і лише для них.

    Читання бази в режимі WAL створює поруч `-shm` і `-wal`; на файлі, який лежить як
    доказ пошкодження, це запис у доказ. На бойовому корпусі, навпаки, `immutable`
    приховав би WAL, тобто зонд читав би не те, що читає служба.
    """
    suffix = "&immutable=1" if probe.immutable else ""
    return sqlite3.connect(f"file:{probe.database}?mode=ro{suffix}", uri=True, timeout=10)


def _failure(stage: str, error: sqlite3.DatabaseError) -> dict[str, Any]:
    return {
        "readable": False,
        "known": True,
        "stage": stage,
        "error_class": type(error).__name__,
        "error": str(error),
        # Тотожність типу, не пошук слова: `sqlite3.DatabaseError` рівно цього типу —
        # коди без власного підкласу, серед них SQLITE_CORRUPT і SQLITE_NOTADB.
        # `OperationalError` («no such table») — підклас, і це ІНША вада: не пошкодження,
        # а відсутня таблиця.
        "corruption_signal": type(error) is sqlite3.DatabaseError,
    }


def _probe_table(connection: sqlite3.Connection, table: str) -> dict[str, Any]:
    query = READINESS_QUERIES.get(table)
    if query is None:
        return {"table": table, "readable": False, "known": False, "stage": "unqueried"}
    try:
        row = connection.execute(query).fetchone()
    except sqlite3.DatabaseError as error:
        return {"table": table, **_failure("table", error)}
    return {"table": table, "readable": True, "known": True, "row_present": row is not None}


def _unknown_tables(probed: list[dict[str, Any]]) -> list[str]:
    return [row["table"] for row in probed if not row["known"]]


def _broken_tables(probed: list[dict[str, Any]]) -> list[str]:
    return [row["table"] for row in probed if row["known"] and not row["readable"]]


def _stage_of(broken: list[str], unknown: list[str]) -> str:
    if broken:
        return "tables"
    return "unqueried" if unknown else "complete"


def _verdict(probed: list[dict[str, Any]]) -> dict[str, Any]:
    unknown = _unknown_tables(probed)
    broken = _broken_tables(probed)
    return {
        "readable": not broken and not unknown,
        # ВІДМОВА перебиває НЕЗНАННЯ: пошкоджена таблиця лишається пошкодженою, навіть
        # якщо поруч зʼявилась таблиця без оголошеного запиту.
        "known": not unknown or bool(broken),
        "stage": _stage_of(broken, unknown),
        "corruption_signal": any(row.get("corruption_signal") for row in probed),
        "unreadable_tables": broken,
        "unqueried_tables": unknown,
        "tables": probed,
    }


def _interrogate(connection: sqlite3.Connection, tables: tuple[str, ...]) -> dict[str, Any]:
    if not tables:
        # `all([])` істинне, і порожній перелік дав би READABLE, не спитавши нічого.
        return {"readable": False, "known": False, "stage": "empty-plan"}
    try:
        connection.execute("select 1").fetchone()
        schema = connection.execute("select count(*) from sqlite_master where type='table'")
        counted = int(schema.fetchone()[0])
    except sqlite3.DatabaseError as error:
        return _failure("schema", error)
    return {"tables_in_schema": counted, **_verdict([_probe_table(connection, t) for t in tables])}


def readability(probe: Probe) -> dict[str, Any]:
    if not probe.database.is_file():
        return {"readable": False, "known": True, "stage": "file", "error": "бази немає за шляхом"}
    try:
        connection = _connect(probe)
    except sqlite3.DatabaseError as error:
        return _failure("open", error)
    try:
        return _interrogate(connection, probe.tables)
    finally:
        connection.close()


def status_of(verdict: dict[str, Any]) -> str:
    if not verdict["known"]:
        return "UNKNOWN"
    return "READABLE" if verdict["readable"] else "UNREADABLE"


def observe(database: Path, immutable: bool = False) -> dict[str, Any]:
    try:
        tables = readiness_tables(source_texts())
        verdict = readability(Probe(database, immutable, tables))
    except DerivationError as error:
        tables = ()
        verdict = {"readable": False, "known": False, "stage": "derivation", "error": str(error)}
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "database": str(database),
        "status": status_of(verdict),
        "readiness_tables": list(tables),
        "probe": verdict,
    }
    if report["status"] != "READABLE":
        # Умови знімаються ЛИШЕ при відмові: щохвилинний знімок машини сам був би
        # шумом, а тут він — єдиний свідок того, в чому саме сталася подія.
        report["machine_at_failure"] = machine_conditions()
    return report


def append_failure(journal: Path, report: dict[str, Any]) -> None:
    """Відмова лягає в НЕЗНИЩЕННИЙ журнал, а не лише в поточний знімок.

    Вада, знайдена в цьому ж приладі за годину після встановлення: `--out` — ОДИН файл,
    який перезаписується щохвилини. Відмова о 03:00 зникала б о 03:01, коли наступний
    прогін напише READABLE. Прилад, поставлений заради ЧАСУ ПОДІЇ, губив би саме ту
    подію, заради якої існує — і побачити це можна було лише спитавши, що станеться
    ПІСЛЯ відмови, а не чи ловить він її.

    Дописування, не перезапис: рядок JSON на подію. Файл росте лише на відмовах, тож за
    пʼять пошкоджень за три доби це пʼять рядків, а не сорок тисяч знімків.
    """
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False) + "\n")


# ── самоперевірка ────────────────────────────────────────────────────────────────────


PAGE_SIZE = 4096
FIXTURE_SQL = """
create table audit_events (sequence bigint primary key, event_hash text, payload_json text);
create table audit_heads (singleton_id integer primary key, sequence bigint, head_hash text);
create table audit_anchor_outbox (
    sequence bigint primary key, head_hash text, created_at text, delivered_at text);
create index ix_audit_anchor_outbox_pending
    on audit_anchor_outbox (delivered_at, created_at, sequence);
create table alembic_version (version_num text);
create table evidence_spans (id integer primary key, text text);
"""


def fixture(path: Path, rows: int = 40) -> Path:
    """Корпус у мініатюрі: три таблиці шляху готовності, ревізія і зміст."""
    connection = sqlite3.connect(str(path))
    connection.executescript(FIXTURE_SQL)
    connection.execute("insert into alembic_version values ('0024_capability_effect_ledger')")
    connection.execute("insert into audit_heads values (1, ?, ?)", (rows, "a" * 64))
    connection.executemany(
        "insert into audit_events values (?,?,?)",
        ((i, f"{i:064d}", "x" * 120) for i in range(1, rows + 1)),
    )
    connection.executemany(
        "insert into audit_anchor_outbox values (?,?,?,?)",
        ((i, f"{i:064d}", f"2026-09-{i % 28 + 1:02d}", None) for i in range(1, rows + 1)),
    )
    connection.executemany(
        "insert into evidence_spans (text) values (?)", (("проліт" * 20,) for _ in range(rows))
    )
    connection.commit()
    connection.close()
    return path


def poison_table(path: Path, table: str) -> Path:
    """Отрута по ДАНИХ: кореневу сторінку однієї таблиці забито, решта бази ціла.

    Саме ця форма сталася 09.09: `evidence_spans` читався, `audit_heads` — ні. Отрута на
    КОД довела б лише те, що зонд запускається.
    """
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    root = connection.execute(
        "select rootpage from sqlite_master where type='table' and name=?", (table,)
    ).fetchone()[0]
    connection.close()
    data = bytearray(path.read_bytes())
    data[(int(root) - 1) * PAGE_SIZE : int(root) * PAGE_SIZE] = b"\xa5" * PAGE_SIZE
    path.write_bytes(bytes(data))
    return path


def vdbe_steps(database: Path, query: str) -> int:
    """Кроки віртуальної машини SQLite — вимір, а не думка про вартість запиту."""
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    counted = 0

    def tick() -> int:
        nonlocal counted
        counted += 1
        return 0

    connection.set_progress_handler(tick, 1)
    connection.execute(query).fetchone()
    connection.set_progress_handler(None, 1)
    connection.close()
    return counted


def _constancy_problems(work: Path) -> list[str]:
    """Кожен запит зонда — сталий за розміром бази, і прилад це БАЧИТЬ.

    Позитивний контроль обовʼязковий: лічильник, який завжди дає однакове число, довів би
    константність будь-чого. Тут ним стоїть ВЛАСНИЙ запит служби по `audit_anchor_outbox`
    — саме той, замість якого зонд бере обмежений.
    """
    small = fixture(work / "small.db", rows=50)
    large = fixture(work / "large.db", rows=20_000)
    problems = [
        f"{table}: {vdbe_steps(small, query)} кроків на 50 рядках, "
        f"{vdbe_steps(large, query)} на 20000 — запит росте з базою"
        for table, query in READINESS_QUERIES.items()
        if vdbe_steps(small, query) != vdbe_steps(large, query)
    ]
    linear = "select count(*), min(created_at) from audit_anchor_outbox where delivered_at is null"
    if vdbe_steps(small, linear) == vdbe_steps(large, linear):
        problems.append("лічильник кроків не бачить лінійного запиту — вимір без ентропії")
    return problems


def _derivation_problems(sources: Sources) -> list[str]:
    """Виведення мусить читати КОД, а не памʼять автора. Доводиться отрутою по джерелу."""
    problems: list[str] = []
    derived = readiness_tables(sources)
    for table in ("audit_heads", "audit_events", "audit_anchor_outbox"):
        if table not in derived:
            problems.append(f"{table} не виведено зі шляху готовності, а він її питає")
    if "audit_anchor_outbox" in readiness_tables(Sources(_unreached(sources), *sources[1:])):
        problems.append("прибрана зі шляху готовності таблиця лишилась у переліку — це не вимір")
    renamed = sources.reader.replace(f"def {READINESS_METHOD}(", "def _was_readiness_snapshot(")
    if _survives(Sources(renamed, *sources[1:])):
        problems.append("зникнення readiness_snapshot не спинило виведення")
    problems += _transitivity_problems(sources)
    return problems


def _unreached(sources: Sources) -> str:
    """Отрута, що прибирає таблицю САМЕ зі шляху готовності, лишаючи звʼязок у `__init__`.

    Перша редакція перейменовувала поле СКРІЗЬ, разом із присвоєнням у конструкторі —
    тобто була еквівалентним мутантом: виведення чесно йшло за новим імʼям і залишало
    таблицю в переліку. Отрута, яку прилад «пережив», не довела б нічого; ця перевіряє
    саме досяжність із `readiness_snapshot`, а не написання імені.
    """
    reader = _class_of(sources.reader, READER_CLASS)
    parameter = _init_bindings(reader)["_outbox"]
    poisoned = sources.reader.replace("self._outbox", "self._unreached_by_readiness")
    return poisoned.replace(
        f"self._unreached_by_readiness = {parameter}", f"self._outbox = {parameter}"
    )


def _survives(sources: Sources) -> bool:
    try:
        readiness_tables(sources)
    except DerivationError:
        return False
    return True


def _indirect_reader(sources: Sources) -> str:
    """Читач, у якому вхід НЕ торкається поля сам: воно лежить за викликом власного методу.

    Підпис береться з РЕАЛЬНОГО класу, а не переписується сюди: друга копія розійшлася б
    із першою мовчки, і випадок перевіряв би форму, якої в дереві вже немає.
    """
    reader = _class_of(sources.reader, READER_CLASS)
    parameters = ", ".join(_parameters(_method_of(reader, "__init__")))
    parameter = _init_bindings(reader)["_audits"]
    return (
        f"class {READER_CLASS}:\n"
        f"    def __init__(self, {parameters}):\n"
        f"        self._audits = {parameter}\n"
        f"    def _behind_one_call(self):\n"
        f"        return self._audits\n"
        f"    def {READINESS_METHOD}(self):\n"
        f"        return self._behind_one_call()\n"
    )


def _transitivity_problems(sources: Sources) -> list[str]:
    """Поле за викликом власного методу. Невидиме для виведення — і це саме той випадок,
    у якому загубилось би `audit_events`, бо прямо його читає лише `_rollback_state`."""
    derived = readiness_tables(Sources(_indirect_reader(sources), *sources[1:]))
    if derived != ("audit_events",):
        return [f"через власний метод виведено {derived}, а не саму лише audit_events"]
    return []


def _quiet_problems(work: Path) -> list[str]:
    """Один напрямок: на цілій базі зонд мусить МОВЧАТИ."""
    healthy = fixture(work / "healthy.db")
    seen = observe(healthy)
    problems: list[str] = []
    if seen["status"] != "READABLE":
        problems.append(f"ціла база оголошена нечитаною: {seen['probe']}")
    if "machine_at_failure" in seen:
        problems.append("умови машини знято без відмови — це шум, не свідок")
    return problems


def _observation_problems(work: Path) -> list[str]:
    """Другий напрямок: пошкодження форми 09.09 мусить БУТИ побачене й НАЗВАНЕ."""
    poisoned = poison_table(fixture(work / "poisoned.db"), "audit_heads")
    seen = observe(poisoned, immutable=True)
    problems: list[str] = []
    if seen["status"] != "UNREADABLE":
        problems.append("пошкодження 09.09 — цілий зміст, битий журнал — оголошено читаним")
    if seen["probe"].get("unreadable_tables") != ["audit_heads"]:
        problems.append("відмова не називає таблиці, тобто розслідування знову без предмета")
    if _old_question_passes(poisoned) is not True:
        problems.append("отрута не відтворює клас 09.09: стара проба на ній теж червона")
    if observe(work / "absent.db")["status"] != "UNREADABLE":
        problems.append("відсутній файл оголошено читаним")
    return problems


def _old_question_passes(database: Path) -> bool:
    """Питання ПОПЕРЕДНЬОЇ редакції: схема плюс рядок з `evidence_spans`.

    Стоїть тут ПОЗИТИВНИМ: воно мусить лишатися зеленим на отруті. Інакше отрута
    відтворює не той клас, і весь негативний контроль вимірює щось інше.
    """
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        connection.execute("select name from sqlite_master where type='table' limit 5").fetchall()
        connection.execute("select 1 from evidence_spans limit 1").fetchone()
    except sqlite3.DatabaseError:
        return False
    finally:
        connection.close()
    return True


def _plan_problems(work: Path) -> list[str]:
    """Неоголошений запит і порожній план — це UNKNOWN, і жодне з них не є дозволом."""
    problems: list[str] = []
    healthy = fixture(work / "planned.db")
    if status_of(readability(Probe(healthy, False, ()))) != "UNKNOWN":
        problems.append("порожній перелік таблиць дав вирок — `all([])` пройшло як згода")
    unqueried = readability(Probe(healthy, False, ("audit_heads", "documents")))
    if status_of(unqueried) != "UNKNOWN":
        problems.append("таблиця шляху готовності без оголошеного запиту не дала UNKNOWN")
    both = readability(
        Probe(
            poison_table(fixture(work / "both.db"), "audit_heads"),
            True,
            ("audit_heads", "documents"),
        )
    )
    if status_of(both) != "UNREADABLE":
        problems.append("відмова не перебила незнання: пошкодження сховалось за UNKNOWN")
    dropped = fixture(work / "dropped.db")
    connection = sqlite3.connect(str(dropped))
    connection.executescript("drop table audit_events;")
    connection.close()
    seen = observe(dropped)
    if seen["status"] != "UNREADABLE" or seen["probe"]["corruption_signal"]:
        problems.append("відсутня таблиця або пропущена, або названа пошкодженням")
    return problems


def _survived(block: Any, work: Path) -> list[str]:
    """Виняток в одному блоці не сміє знімати з прогону решту.

    Без цього перший же зламаний блок валив увесь `--selftest` трасуванням, тобто решта
    випадків НЕ ЗАПУСКАЛАСЬ — а звіт про це мовчав. Виміряно на власному мутанті: зняття
    транзитивності виведення вбивало перший блок, і наступні три не бігли жодною дорогою.
    """
    try:
        return list(block(work))
    except Exception as error:  # noqa: BLE001 — саме широка, бо ловить будь-який обрив блоку
        return [f"{block.__name__} обірвався: {type(error).__name__}: {error}"]


def selftest() -> int:
    problems: list[str] = []
    blocks = (
        _derivation_block,
        _quiet_problems,
        _observation_problems,
        _plan_problems,
        _constancy_problems,
    )
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        for block in blocks:
            problems += _survived(block, work)
    print(
        json.dumps(
            {
                "selftest": "korpus.corpus-readability-watch",
                "cases": 17,
                "blocks": len(blocks),
                "failures": problems,
            },
            ensure_ascii=False,
        )
    )
    return 1 if problems else 0


def _derivation_block(work: Path) -> list[str]:
    """Виведення джерел не потребує тимчасової теки; підпис спільний, щоб блоки були
    однакові й перелік нижче не мусив розрізняти їх особливими випадками."""
    del work
    return _derivation_problems(source_texts())


# ── запуск ───────────────────────────────────────────────────────────────────────────


EXIT_CODES = {"READABLE": 0, "UNREADABLE": 1, "UNKNOWN": 2}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "var/corpus-readability.json")
    parser.add_argument(
        "--journal", type=Path, default=ROOT / "var/corpus-readability-failures.jsonl"
    )
    parser.add_argument(
        "--immutable",
        action="store_true",
        help="для збережених доказів: не створювати поруч -wal/-shm",
    )
    parser.add_argument("--selftest", action="store_true")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.selftest:
        return selftest()
    if arguments.database is None:
        build_parser().error("--database обовʼязковий поза --selftest")
    report = observe(arguments.database, arguments.immutable)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if report["status"] != "READABLE":
        append_failure(arguments.journal, report)
    print(json.dumps(report, ensure_ascii=False))
    return EXIT_CODES[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
