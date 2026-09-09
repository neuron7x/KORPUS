#!/usr/bin/env python3
"""Момент, коли корпус перестав читатися — з умовами машини в ту саму мить.

Чотири пошкодження за три доби, і жодне не має ЧАСУ ПОДІЇ. Є час ВИЯВЛЕННЯ, і він
щоразу випадковий: нічна перевірка, впала служба, я наткнувся запитом. Розслідування
через це стоїть — гіпотезу про тиск памʼяті нічим звірити з подією, бо вікно між
останнім «цілий» і першим «зламаний» щоразу години.

Ця проба не міряє якість корпусу — для цього є `measure_corpus_integrity.py`, і він
дорогий: обхід усіх таблиць по базі на 330 МБ. Ця питає ДЕШЕВЕ і часто:

  · чи обходиться дерево схеми (`sqlite_master`) — саме воно впало 09.09;
  · чи читається один рядок із таблиці, яку обслуговує служба.

Обидва запити — константні за розміром бази, тож проба може бігти щохвилини, не
конкуруючи з тим, що вона стереже.

І головне, заради чого вона є: при ВІДМОВІ вона знімає стан МАШИНИ тієї ж миті —
доступну памʼять, своп, найбільші процеси. Без цього наступна подія знову буде
«сталося колись уночі», а з цим вона матиме умову, яку можна звірити з гіпотезою.

Проба нічого не лікує і нічого не переміщує: файл на 330 МБ, скопійований щохвилини,
сам став би причиною тиску, який вона стереже.

    watch_corpus_readability.py --database DB [--out ФАЙЛ]
    watch_corpus_readability.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "korpus.corpus-readability-watch.v1"

#: Таблиця, яку читає служба на кожному запиті. Порожній результат — теж відповідь:
#: питання в тому, чи ЧИТАЄТЬСЯ, а не скільки там рядків.
PROBE_TABLE = "evidence_spans"


def machine_conditions() -> dict[str, Any]:
    """Стан машини В МИТЬ ВІДМОВИ. Знімається лише тоді — інакше це просто шум."""
    conditions: dict[str, Any] = {}
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
        wanted = ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree", "Dirty", "Writeback")
        for line in meminfo.splitlines():
            name = line.split(":", 1)[0]
            if name in wanted:
                conditions[name] = line.split(":", 1)[1].strip()
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


def readability(database: Path) -> dict[str, Any]:
    """Дешеве питання: чи читається схема і один рядок. Відмова НАЗИВАЄ клас помилки."""
    if not database.is_file():
        return {"readable": False, "stage": "file", "error": "бази немає за шляхом"}
    connection = None
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=10)
        tables = [
            str(row[0])
            for row in connection.execute(
                "select name from sqlite_master where type='table' order by name limit 5"
            )
        ]
        connection.execute(f'select 1 from "{PROBE_TABLE}" limit 1').fetchone()
    except sqlite3.DatabaseError as error:
        return {
            "readable": False,
            # Тотожність типу, не пошук слова: `sqlite3.DatabaseError` рівно цього типу —
            # коди без власного підкласу, серед них SQLITE_CORRUPT і SQLITE_NOTADB.
            "stage": "schema" if not locals().get("tables") else "row",
            "error_class": type(error).__name__,
            "error": str(error),
            "corruption_signal": type(error) is sqlite3.DatabaseError,
        }
    finally:
        if connection is not None:
            connection.close()
    return {"readable": True, "stage": "row", "tables_sampled": len(tables)}


def observe(database: Path) -> dict[str, Any]:
    verdict = readability(database)
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "database": str(database),
        "status": "READABLE" if verdict["readable"] else "UNREADABLE",
        "probe": verdict,
    }
    if not verdict["readable"]:
        # Умови знімаються ЛИШЕ при відмові: щохвилинний знімок машини сам був би
        # шумом, а тут він — єдиний свідок того, в чому саме сталася подія.
        report["machine_at_failure"] = machine_conditions()
    return report


def selftest() -> int:
    """Проба мусить БАЧИТИ пошкодження і МОВЧАТИ на цілій базі. Обидва боки однаково."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        healthy = work / "healthy.db"
        connection = sqlite3.connect(str(healthy))
        connection.executescript(
            f"create table {PROBE_TABLE} (id integer primary key, text text);"
            f"insert into {PROBE_TABLE} (text) values ('проліт');"
        )
        connection.commit()
        connection.close()
        if observe(healthy)["status"] != "READABLE":
            problems.append("ціла база оголошена нечитаною")
        if "machine_at_failure" in observe(healthy):
            problems.append("умови машини знято без відмови — це шум, не свідок")

        broken = work / "broken.db"
        broken.write_bytes("це не база".encode() * 4096)
        seen = observe(broken)
        if seen["status"] != "UNREADABLE":
            problems.append("не база оголошена читаною")
        if not seen["probe"].get("corruption_signal"):
            problems.append("клас помилки не названо як сигнал пошкодження")
        if "MemAvailable" not in seen.get("machine_at_failure", {}):
            problems.append("при відмові не знято умов машини — подія знову без умови")

        missing = work / "absent.db"
        if observe(missing)["status"] != "UNREADABLE":
            problems.append("відсутній файл оголошено читаним")

        # МЕЖА ПРОБИ, названа проби ж самою, а не залишена читачеві на здогад.
        # Обрізана база, у якій уціліли заголовок і кореневі сторінки, обидва дешеві
        # запити віддає — і це не вада, а контракт: проба питає ЧИТАНІСТЬ, а не
        # цілісність. Повноту дає `measure_corpus_integrity.py` з обходом усіх таблиць,
        # і саме тому він лишається нічним, а цей — щохвилинним. Випадок стоїть тут
        # ПОЗИТИВНИМ: якщо колись проба почне звати таке пошкодженням, це зміна
        # контракту, і вона мусить почервоніти.
        truncated = work / "truncated.db"
        truncated.write_bytes(healthy.read_bytes()[: 4096 * 2])
        if observe(truncated)["status"] != "READABLE":
            problems.append(
                "проба оголосила обрізану-але-відкривану базу пошкодженою: це вже не "
                "дешева читаність, і контракт із нічною перевіркою розійшовся"
            )
    print(
        json.dumps(
            {"selftest": "korpus.corpus-readability-watch", "cases": 6, "failures": problems},
            ensure_ascii=False,
        )
    )
    return 1 if problems else 0


def append_failure(journal: Path, report: dict[str, Any]) -> None:
    """Відмова лягає в НЕЗНИЩЕННИЙ журнал, а не лише в поточний знімок.

    Вада, знайдена в цьому ж приладі за годину після встановлення: `--out` — ОДИН файл,
    який перезаписується щохвилини. Відмова о 03:00 зникала б о 03:01, коли наступний
    прогін напише READABLE. Прилад, поставлений заради ЧАСУ ПОДІЇ, губив би саме ту
    подію, заради якої існує — і побачити це можна було лише спитавши, що станеться
    ПІСЛЯ відмови, а не чи ловить він її.

    Дописування, не перезапис: рядок JSON на подію. Файл росте лише на відмовах, тож за
    чотири пошкодження за три доби це чотири рядки, а не сорок тисяч знімків.
    """
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "var/corpus-readability.json")
    parser.add_argument(
        "--journal", type=Path, default=ROOT / "var/corpus-readability-failures.jsonl"
    )
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    if arguments.database is None:
        parser.error("--database обовʼязковий поза --selftest")
    report = observe(arguments.database)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if report["status"] != "READABLE":
        append_failure(arguments.journal, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "READABLE" else 1


if __name__ == "__main__":
    sys.exit(main())
