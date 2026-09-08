#!/usr/bin/env python3
"""Відновлення обслуговуваного SQLite-корпусу, коли пошкоджено ОКРЕМІ дерева.

Двічі за дванадцять годин (07.09 і 08.09.2026) файл `korpus.db` ставав
`database disk image is malformed`, і обидва рази пошкодження сиділо у гарячих
сторінках журналу аудиту, а корпус лишався цілим. Перший раз відновлення робилося
рукою: `.dump` через SELECT, ROLLBACK замінено на COMMIT, завантаження в чисту базу.
Рука — не виробник: другого разу її довелось би згадувати, а не запускати.

Що робить:

  · читає джерело ТІЛЬКИ на читання і не торкається його ЖОДНОГО разу;
  · знаходить дерева, які не читаються, ЗАПУСКОМ `select count(*)` по кожній таблиці —
    а не переліком, бо перелік був би другим оголошенням того, що вже сказала база;
  · переносить схему і дані в чистий файл у порядку, який не бореться зі схемою:
    таблиці → дані → індекси → тригери. Тригери незмінності (`trg_evidence_spans_*`)
    відхилили б власні рядки, якби стояли раніше;
  · голову журналу НЕ вигадує. `audit_heads` — похідна від ланцюга: голова дорівнює
    останній ВЦІЛІЛІЙ події. Якщо подій нема, таблиця лишається порожньою і система
    скаже про це сама.

Чого НЕ робить: не приховує втрати. Розрив у послідовності подій і якір, що стоїть
попереду голови, лишаються видимими — тамперостійкий журнал існує рівно для цього.

    recover_sqlite_corpus.py --source DB --target DB [--apply]
    recover_sqlite_corpus.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

#: Голова журналу — єдина таблиця, яку цей скрипт має право відбудувати з іншої.
DERIVED_FROM_CHAIN = "audit_heads"


class SchemaUnreadable(RuntimeError):
    """Дерево СХЕМИ не обходиться, тож переліку таблиць не існує.

    Виміряно 08.09.2026 на ТРЕТЬОМУ пошкодженні за добу: `select name from sqlite_master`
    кинув `database disk image is malformed`, і обидва споживачі цієї функції — вимірювач
    цілісності й це відновлення — падали трейсбеком там, де мали винести вирок. Названий
    клас робить межу видимою: це відновлення переносить ДЕРЕВА за схемою, тож без схеми
    воно не має предмета, і дорога тут одна — відновлення з бекапа.
    """


def unreadable_tables(connection: sqlite3.Connection) -> list[str]:
    """Таблиці, чиє дерево не обходиться. Вимір, а не перелік."""
    try:
        names = [
            str(row[0])
            for row in connection.execute(
                "select name from sqlite_master where type='table' order by name"
            )
        ]
    except sqlite3.DatabaseError as error:
        raise SchemaUnreadable(f"{type(error).__name__}: {error}") from error
    damaged: list[str] = []
    for name in names:
        try:
            connection.execute(f'select count(*) from "{name}"').fetchone()
        except sqlite3.DatabaseError:
            damaged.append(name)
    return damaged


def schema_objects(connection: sqlite3.Connection, kind: str) -> list[tuple[str, str]]:
    return [
        (str(row[0]), str(row[1]))
        for row in connection.execute(
            "select name, sql from sqlite_master where type=? and sql is not null order by rowid",
            (kind,),
        )
    ]


def virtual_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        name for name, sql in schema_objects(connection, "table") if "virtual table" in sql.lower()
    ]


def creation_order(connection: sqlite3.Connection) -> list[str]:
    """CREATE-и таблиць у порядку, який не бореться з FTS5.

    Тіньові таблиці (`evidence_fts_data` і сестри) стоять у `sqlite_master` власними
    CREATE-ами, але створює їх САМА віртуальна таблиця. Виконати їх окремо означає
    дістати «table already exists» — виміряно 08.09.2026 на першому ж прогоні.
    """
    virtual = virtual_tables(connection)
    statements = dict(schema_objects(connection, "table"))
    shadows = {
        name for name in statements if any(name.startswith(f"{owner}_") for owner in virtual)
    }
    ordered = [statements[name] for name in virtual]
    ordered += [
        sql for name, sql in statements.items() if name not in shadows and name not in virtual
    ]
    return ordered


def copyable_tables(connection: sqlite3.Connection, damaged: list[str]) -> list[str]:
    """Таблиці, чиї рядки переносяться як є, у порядку створення.

    Тіньові таблиці FTS5 сюди входять, а сама віртуальна — ні: індекс переноситься
    ВМІСТОМ. Вставка в `evidence_fts` спершу стерла б щойно перенесені тіні, а потім
    перетокенізувала все наново — інший індекс і відновлення, невідтворюване щодо
    оригіналу. Виміряно 08.09.2026: перший прогін робив саме це й лишався зеленим,
    тобто вада була б невидима за вироком.
    """
    skip = set(damaged) | {DERIVED_FROM_CHAIN} | set(virtual_tables(connection))
    return [name for name, _ in schema_objects(connection, "table") if name not in skip]


def head_from_chain(connection: sqlite3.Connection) -> tuple[int, str] | None:
    """Голова = остання вціліла подія. Немає подій — немає голови."""
    try:
        row = connection.execute(
            "select sequence, event_hash from audit_events order by sequence desc limit 1"
        ).fetchone()
    except sqlite3.DatabaseError:
        return None
    return (int(row[0]), str(row[1])) if row else None


def refusals(source: Path, target: Path, damaged: list[str]) -> list[str]:
    """Причини не запускати відновлення. Порожній список — єдиний дозвіл."""
    problems: list[str] = []
    if not source.is_file():
        problems.append(f"джерело не є файлом: {source}")
    if target.exists():
        problems.append(f"ціль уже існує: {target}")
    if not damaged:
        problems.append(
            "жодне дерево не пошкоджене: відновлення цілої бази — не відновлення, "
            "а непотрібне переписування з власними ризиками"
        )
    unexpected = [name for name in damaged if name != DERIVED_FROM_CHAIN]
    if unexpected:
        problems.append(
            "пошкоджено дерева, які нема з чого відбудувати: "
            f"{unexpected}. Цей скрипт відбудовує лише {DERIVED_FROM_CHAIN}, бо лише "
            "вона є похідною від іншої таблиці"
        )
    return problems


def rebuild(source_path: Path, target_path: Path) -> dict[str, Any]:
    """Перенос у порядку таблиці → дані → індекси → тригери."""
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)
    damaged = unreadable_tables(source)
    target = sqlite3.connect(str(target_path), timeout=30)
    copied: dict[str, int] = {}
    try:
        target.execute("pragma journal_mode=WAL")
        target.execute("pragma foreign_keys=OFF")
        for sql in creation_order(source):
            target.execute(sql)
        for name in copyable_tables(source, damaged):
            rows = source.execute(f'select * from "{name}"').fetchall()
            if not rows:
                copied[name] = 0
                continue
            placeholders = ",".join("?" * len(rows[0]))
            # FTS5 сама кладе рядок у `_config` при створенні віртуальної таблиці;
            # перенесений вміст мусить замістити його, а не лягти поруч.
            target.execute(f'delete from "{name}"')
            target.executemany(f'insert into "{name}" values ({placeholders})', rows)
            copied[name] = len(rows)
        head = head_from_chain(source)
        if head is not None:
            target.execute(
                f'insert into "{DERIVED_FROM_CHAIN}" (singleton_id, sequence, head_hash) '
                "values (1, ?, ?)",
                head,
            )
        for _, sql in schema_objects(source, "index"):
            target.execute(sql)
        for _, sql in schema_objects(source, "trigger"):
            target.execute(sql)
        target.commit()
        integrity = [str(row[0]) for row in target.execute("pragma integrity_check(50)")]
    finally:
        source.close()
        target.close()
    return {
        "damaged": damaged,
        "copied": copied,
        "head_rebuilt_from_chain": list(head) if head else None,
        "integrity_check": integrity,
    }


def selftest() -> int:
    """Негативний контроль: ціла база мусить бути ВІДХИЛЕНА, а не «відновлена»."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        healthy = root / "healthy.db"
        connection = sqlite3.connect(str(healthy))
        connection.execute("create table audit_events (sequence integer, event_hash text)")
        connection.execute(
            "create table audit_heads (singleton_id integer primary key, "
            "sequence bigint not null, head_hash varchar(64) not null)"
        )
        connection.execute("insert into audit_events values (1, 'aa'), (2, 'bb')")
        connection.execute("insert into audit_heads values (1, 2, 'bb')")
        connection.commit()

        readable = sqlite3.connect(f"file:{healthy}?mode=ro", uri=True)
        damaged = unreadable_tables(readable)
        if damaged:
            problems.append(f"ціла база оголошена пошкодженою: {damaged}")
        if not refusals(healthy, root / "new.db", damaged):
            problems.append("відновлення цілої бази не відхилене")
        if refusals(root / "absent.db", root / "new.db", ["audit_heads"])[:1] == []:
            problems.append("відсутнє джерело не відхилене")
        if not refusals(healthy, healthy, ["audit_heads"]):
            problems.append("наявна ціль не відхилена")
        if not refusals(healthy, root / "new.db", ["documents"]):
            problems.append("непохідне пошкоджене дерево не відхилене")
        if head_from_chain(readable) != (2, "bb"):
            problems.append("голова не виведена з останньої події")
        readable.close()
        connection.close()

    print(
        json.dumps(
            {"selftest": "korpus.sqlite-corpus-recovery", "cases": 5, "failures": problems},
            ensure_ascii=False,
        )
    )
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    if arguments.source is None or arguments.target is None:
        parser.error("--source і --target обов'язкові поза --selftest")

    source = sqlite3.connect(f"file:{arguments.source}?mode=ro", uri=True, timeout=30)
    try:
        damaged = unreadable_tables(source)
    except SchemaUnreadable as error:
        source.close()
        print(
            json.dumps(
                {
                    "source": str(arguments.source),
                    "status": "REFUSED",
                    "refusals": [
                        f"дерево схеми не обходиться ({error}): переліку таблиць не існує, "
                        "а це відновлення переносить дерева ЗА СХЕМОЮ — предмета немає"
                    ],
                    "road": (
                        "відновлення з бекапа: scripts/restore_sqlite.sh <backup.tar.enc> "
                        "<каталог>. Втрата — усе, що записано після знімка, і вона мусить "
                        "лишитись видимою в послідовності журналу"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    head = head_from_chain(source)
    source.close()
    problems = refusals(arguments.source, arguments.target, damaged)
    plan = {
        "source": str(arguments.source),
        "target": str(arguments.target),
        "damaged": damaged,
        "head_from_chain": list(head) if head else None,
        "refusals": problems,
    }
    if problems or not arguments.apply:
        plan["status"] = "REFUSED" if problems else "PLANNED"
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 1 if problems else 0
    report = rebuild(arguments.source, arguments.target)
    report["status"] = "PASS" if report["integrity_check"] == ["ok"] else "FAIL"
    print(json.dumps({**plan, **report}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
