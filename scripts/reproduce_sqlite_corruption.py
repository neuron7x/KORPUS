#!/usr/bin/env python3
"""Спроба ВІДТВОРИТИ пошкодження обслуговуваного SQLite — на копії, з бюджетом.

Три пошкодження за добу (07.09, 08.09 07:16, 08.09 18:14), усі під важким паралельним
ЗАПИСОМ, механізм не встановлений. Пасивні виміри вичерпані: ядро не повідомляє помилок
вводу-виводу, EDAC показує нуль (але платформа — споживацька Unbuffered-DDR4, тож нуль
може означати відсутність ЛІЧИЛЬНИКА, а не відсутність помилок), бекапи перевіряються
відновленням, тобто диск не бреше про вже записане.

Тому — активний дослід, і три його правила названі наперед.

ПЕРШЕ: предмет — КОПІЯ. Обслуговуваний корпус не є полем експерименту; репетиція, що
коштує предмета, — не репетиція.

ДРУГЕ: ОДНА змінна. Плечі відрізняються рівно `mmap_size` і нічим більше. Підозра саме
на нього: файл переріс мапу (363 МБ проти 256 МіБ), тобто половина бази читається через
відображення, а решта — звичайним вводом-виводом, і при цьому машина свопить сім
гігабайтів. Це гіпотеза, а не висновок.

ТРЕТЄ: БЮДЖЕТ оголошується ДО прогону. «Не відтворилось» без названого бюджету — не
вимір: 08.09 я вже записав один чистий повтор як послаблення гіпотези, і за одинадцять
годин вона справдилась утретє. Тому вирок при нулі пошкоджень тут — NOT_MEASURED із
числом транзакцій, а не PASS.

Навантаження відтворює ГАРЯЧИЙ ШЛЯХ, а не питання: подія журналу, оновлення голови й
запис у чергу якоря в ОДНІЙ транзакції, нове з'єднання на кожну (форма NullPool),
прагми ті самі, що в продукті.

    reproduce_sqlite_corruption.py --source DB --transactions N [--writers 2]
    reproduce_sqlite_corruption.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from recover_sqlite_corpus import SchemaUnreadable, unreadable_tables  # noqa: E402

#: Прагми продукту, дослівно з `repository._configure_sqlite`. `mmap_size` — єдине, що
#: рухається між плечима, тож воно параметр, а решта константи.
CACHE_MIB = 64
PRODUCTION_MMAP_MIB = 256


def connect(database: Path, mmap_mib: int) -> sqlite3.Connection:
    # `isolation_level=None` — щоб транзакцію відкривати ЯВНО, `BEGIN IMMEDIATE`.
    connection = sqlite3.connect(str(database), timeout=30, isolation_level=None)
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA cache_size=-{CACHE_MIB * 1024}")
    cursor.execute(f"PRAGMA mmap_size={mmap_mib * 1024 * 1024}")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()
    return connection


def _append(connection: sqlite3.Connection, previous: str) -> str:
    """Одна подія ланцюга: та сама трійка таблиць в ОДНІЙ транзакції, що й у продукті."""
    row = connection.execute("select sequence, head_hash from audit_heads").fetchone()
    sequence = int(row[0]) + 1
    payload = json.dumps({"probe": sequence, "filler": "x" * 256}, ensure_ascii=False)
    event_hash = hashlib.sha256(f"{previous}{sequence}{payload}".encode()).hexdigest()
    now = datetime.now(UTC).isoformat()
    connection.execute(
        "insert into audit_events (sequence, event_id, event_schema_version, occurred_at,"
        " actor_subject, action, resource_type, resource_id, payload_json, previous_hash,"
        " event_hash, audit_key_id) values (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            sequence,
            str(uuid.uuid4()),
            1,
            now,
            "probe",
            "probe.write",
            "probe",
            str(sequence),
            payload,
            previous,
            event_hash,
            "probe-key",
        ),
    )
    connection.execute(
        "update audit_heads set sequence=?, head_hash=? where singleton_id=1",
        (sequence, event_hash),
    )
    connection.execute(
        "insert into audit_anchor_outbox (sequence, head_hash, created_at) values (?,?,?)",
        (sequence, event_hash, now),
    )
    return event_hash


def write_batch(database: str, mmap_mib: int, transactions: int) -> tuple[int, int]:
    """Транзакції одного писаря. Нове з'єднання на КОЖНУ — форма NullPool продукту.

    `connect` теж усередині try: `PRAGMA journal_mode=WAL` бере блокування, тож
    «database is locked» прилітає ще ДО транзакції. Перший прогін це й показав —
    виняток вийшов повз обробник і поклав увесь дослід.
    """
    done = 0
    locked = 0
    for _ in range(transactions):
        connection = None
        try:
            connection = connect(Path(database), mmap_mib)
            # BEGIN IMMEDIATE, а не DEFERRED: інакше два писарі ЧИТАЮТЬ ту саму голову і
            # обидва пишуть той самий `sequence` — перший прогін дав саме
            # `UNIQUE constraint failed`. Продукт серіалізує запис своїм замком; тут те
            # саме робить блокування бази, і дослід міряє запис, а не власну гонку.
            connection.execute("BEGIN IMMEDIATE")
            head = connection.execute("select head_hash from audit_heads").fetchone()
            _append(connection, str(head[0]) if head else "0" * 64)
            connection.execute("COMMIT")
            done += 1
        except (sqlite3.OperationalError, sqlite3.IntegrityError):
            # Зайнято іншим писарем — очікувана поведінка SQLite, не подія досліду.
            # Рахується окремо: якщо блокувань майже стільки ж, скільки спроб, бюджет
            # витрачено на чергу, а не на запис, і число транзакцій було б оманливим.
            locked += 1
        finally:
            if connection is not None:
                connection.close()
    return done, locked


def integrity(database: Path) -> dict[str, Any]:
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30)
    except sqlite3.Error as error:
        return {"intact": False, "quick_check": f"{type(error).__name__}: {error}", "damaged": []}
    try:
        rows = [str(row[0]) for row in connection.execute("pragma quick_check(20)")]
        check = rows[0] if rows == ["ok"] else "; ".join(rows)
    except sqlite3.DatabaseError as error:
        check = f"{type(error).__name__}: {error}"
    try:
        damaged = unreadable_tables(connection)
    except SchemaUnreadable as error:
        damaged = [f"<sqlite_master: {error}>"]
    finally:
        connection.close()
    return {"intact": check == "ok" and not damaged, "quick_check": check, "damaged": damaged}


def arm(
    source: Path, workdir: Path, name: str, mmap_mib: int, transactions: int, writers: int
) -> dict[str, Any]:
    """Одне плече. Копія свіжа, щоб плечі не успадковували станів одне одного."""
    database = workdir / f"{name}.db"
    shutil.copyfile(source, database)
    before = integrity(database)
    started = time.monotonic()
    per_writer = max(1, transactions // writers)
    with ProcessPoolExecutor(max_workers=writers) as pool:
        futures = [
            pool.submit(write_batch, str(database), mmap_mib, per_writer) for _ in range(writers)
        ]
        results = [future.result() for future in futures]
    committed = sum(done for done, _ in results)
    locked = sum(blocked for _, blocked in results)
    elapsed = time.monotonic() - started
    after = integrity(database)
    size = database.stat().st_size
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(database) + suffix)
        if target.exists():
            target.unlink()
    return {
        "arm": name,
        "mmap_mib": mmap_mib,
        "writers": writers,
        "transactions_requested": per_writer * writers,
        "transactions_committed": committed,
        "lock_contention_events": locked,
        "seconds": round(elapsed, 1),
        "rate_per_second": round(committed / elapsed, 1) if elapsed else None,
        "bytes_after": size,
        "intact_before": before["intact"],
        "intact_after": after["intact"],
        "damage": None if after["intact"] else after,
    }


def selftest() -> int:
    """Чи вміє дослід ПОБАЧИТИ пошкодження — і чи не кричить на цілій базі."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        database = work / "seed.db"
        connection = sqlite3.connect(str(database))
        connection.executescript(
            "create table audit_events (sequence bigint primary key, event_id varchar(36) unique,"
            " event_schema_version integer, occurred_at datetime, actor_subject varchar(200),"
            " action varchar(200), resource_type varchar(100), resource_id varchar(200),"
            " payload_json text, previous_hash varchar(64), event_hash varchar(64),"
            " audit_key_id varchar(64));"
            "create table audit_heads (singleton_id integer primary key, sequence bigint,"
            " head_hash varchar(64));"
            "create table audit_anchor_outbox (sequence bigint primary key, head_hash varchar(64),"
            " created_at datetime, delivered_at datetime);"
            "insert into audit_heads values (1, 0, 'seed');"
        )
        connection.commit()
        connection.close()

        clean = arm(database, work, "clean", 0, 40, 2)
        if not clean["intact_after"]:
            problems.append(f"ціле плече оголошене пошкодженим: {clean['damage']}")
        if clean["transactions_committed"] < 1:
            problems.append("жодної транзакції не записано — навантаження не працює")

        broken = work / "broken.db"
        shutil.copyfile(database, broken)
        page = int(sqlite3.connect(str(broken)).execute("pragma page_size").fetchone()[0])
        raw = bytearray(broken.read_bytes())
        if len(raw) > page * 4:
            raw[page * 3 : page * 4] = b"\x00" * page
            broken.write_bytes(bytes(raw))
        if integrity(broken)["intact"]:
            problems.append("обнулена сторінка не виявлена — дослід сліпий до пошкодження")
    print(
        json.dumps(
            {"selftest": "korpus.sqlite-corruption-repro", "cases": 3, "failures": problems},
            ensure_ascii=False,
        )
    )
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--transactions", type=int, default=200_000)
    parser.add_argument("--writers", type=int, default=2)
    parser.add_argument("--workdir", type=Path, default=ROOT / "var/corruption-repro")
    parser.add_argument("--out", type=Path, default=ROOT / "var/corruption-repro.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    if arguments.source is None or not arguments.source.is_file():
        parser.error("--source мусить називати наявний файл бази")

    arguments.workdir.mkdir(parents=True, exist_ok=True)
    arms = [
        arm(
            arguments.source,
            arguments.workdir,
            "mmap_production",
            PRODUCTION_MMAP_MIB,
            arguments.transactions,
            arguments.writers,
        ),
        arm(
            arguments.source,
            arguments.workdir,
            "mmap_disabled",
            0,
            arguments.transactions,
            arguments.writers,
        ),
    ]
    reproduced = [entry for entry in arms if not entry["intact_after"]]
    report = {
        "schema": "korpus.sqlite-corruption-repro.v1",
        # Нуль пошкоджень при названому бюджеті — НЕ «не руйнується». Це «не виміряно на
        # цьому бюджеті», і різниця тут коштувала одного пошкодження.
        "status": "REPRODUCED" if reproduced else "NOT_MEASURED",
        "source": str(arguments.source),
        "declared_budget": {
            "transactions_per_arm": arguments.transactions,
            "writers": arguments.writers,
            "why": (
                "продакшен записав ≈11 700 подій за одинадцять годин переривчастого "
                "навантаження і зруйнувався тричі за добу; бюджет плеча стиснює приблизно "
                "той самий обсяг запису в хвилини, щоб частота події стала спостережною"
            ),
        },
        "arms": arms,
        "single_variable": "mmap_size",
        "environment": {
            "sqlite": sqlite3.sqlite_version,
            "page_cache_mib_per_connection": CACHE_MIB,
            "cpu_count": os.cpu_count(),
        },
        "interpretation": (
            "REPRODUCED називає плече, на якому пошкодження сталося, і це вже гіпотеза з "
            "доказом. NOT_MEASURED не є виправданням підозрюваного: він каже лише, що "
            "оголошеного бюджету не вистачило."
        ),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
