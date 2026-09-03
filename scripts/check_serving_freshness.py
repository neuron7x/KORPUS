#!/usr/bin/env python3
"""Чи процес, який відповідає читачеві, виконує ТЕ САМЕ дерево, що лежить у git.

Чотири осі профілю відповідей — `subject`, `reference`, `boundary_own`,
`boundary_foreign`, `paraphrase` — міряються ЗАПИТОМ ДО ЖИВОГО СЕРВЕРА. Отже вони
описують ПРОЦЕС, а не дерево. Різниця не теоретична: 01.09.2026 усі чотири серверні
процеси були старші за найновіший файл коду, включно з тим, що обслуговує читача.

## Чому це не видно й чому воно небезпечніше, ніж «звіт застарів»

Звіт із застарілим корпусом ловиться ідентичністю входів. Звіт із застарілим ПРОЦЕСОМ
не ловиться нічим: корпус той самий, вимірювач той самий, вік малий. Змінилось те, ЧИМ
відповідали, і жодне з полів звіту про це не каже.

Гірше: Python вантажить ліниво імпортований модуль у мить ПЕРШОГО виклику. Тому
довгоживучий сервер тримає СУМІШ двох ревізій — старий модуль зі старту й новий,
підтягнутий пізніше, — і падає лише в ліниво імпортованій гілці. Виміряно того ж дня:
семантичний контрольний сервер віддавав HTTP 500 на кожне питання, бо старий
`retrieval.py` кликав нову сигнатуру `execute_hybrid_search`. Дерево при цьому було
УЗГОДЖЕНЕ — перевірено розбором виклику проти сигнатури.

## Що саме тут вирішується

Порівнюється час старту процесу з mtime найновішого файла під `apps/api/src`. Процес,
старший за код, не виконує дерево — і жоден звіт, отриманий від нього, не кредитує
дерево. Це переводить фразу «звіт описує розгортання, а не код» із прози у вимір.

**Чого це НЕ доводить.** mtime рухається від `git checkout` і `touch`, тож «процес
старший» іноді означає лише перемикання гілки. Помилка в цей бік дешева: вона вимагає
перезапуску там, де він не потрібен. Протилежна — кредитувати вісь числом, порахованим
іншим кодом, — коштує рівно того, заради чого профіль існує.

    check_serving_freshness.py [--out ФАЙЛ]
    check_serving_freshness.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("apps/api/src",)
_PORT = re.compile(r"--port[= ](\d+)")


def newest_source(root: Path = ROOT) -> tuple[float, str]:
    """Найновіший файл коду, який сервер міг би виконувати."""
    newest = (0.0, "")
    for name in SOURCE_ROOTS:
        for path in (root / name).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            stamp = path.stat().st_mtime
            if stamp > newest[0]:
                newest = (stamp, str(path.relative_to(root)))
    return newest


def serving_processes(proc: Path = Path("/proc")) -> list[dict[str, Any]]:
    """Процеси, які обслуговують корпус, — знайдені з оточення, не з реєстру.

    Ознака — `KORPUS_DATABASE_URL` в оточенні: процес, що відкрив базу доказів, є тим,
    хто відповідає. Перелік у конфізі був би другим оголошенням того самого факту й
    розійшовся б мовчки саме тоді, коли хтось підняв ще один.
    """
    found: list[dict[str, Any]] = []
    for entry in sorted(proc.glob("[0-9]*")):
        try:
            raw = (entry / "environ").read_bytes()
            started = entry.stat().st_ctime
            cmdline = (entry / "cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if b"KORPUS_DATABASE_URL=" not in raw:
            continue
        command = cmdline.replace("\0", " ").strip()
        port = _PORT.search(command)
        found.append(
            {
                "pid": entry.name,
                "port": int(port.group(1)) if port else None,
                "started_at": datetime.fromtimestamp(started, tz=UTC).isoformat(),
                "started_epoch": started,
                "command": command[:120],
            }
        )
    return found


def adjudicate(processes: list[dict[str, Any]], newest: tuple[float, str]) -> dict[str, Any]:
    stamp, path = newest
    judged = [{**item, "serves_current_code": item["started_epoch"] >= stamp} for item in processes]
    fresh = sum(1 for item in judged if item["serves_current_code"])
    return {
        "schema": "korpus.serving-freshness.v1",
        "newest_source": path,
        "newest_source_at": datetime.fromtimestamp(stamp, tz=UTC).isoformat() if stamp else None,
        "processes": len(judged),
        "serving_current_code": fresh,
        "stale": [item["pid"] for item in judged if not item["serves_current_code"]],
        "rate": (fresh / len(judged)) if judged else None,
        # Нуль процесів — не згода. Це відсутність предмета, і кредитувати нею вісь
        # означало б, що вимкнений сервер робить профіль зеленим.
        "status": "MEASURED" if judged else "UNKNOWN",
        "detail": judged,
        "cannot_judge": [
            "mtime рухається від `git checkout` і `touch`: «процес старший» іноді означає "
            "лише перемикання гілки, а не іншу поведінку.",
            "Процес НЕ старший за код усе одно міг завантажити модуль до правки, якщо "
            "правка сталася між стартом і першим лінивим імпортом.",
        ],
    }


def selftest() -> int:
    now = datetime.now(UTC).timestamp()

    def process(pid: str, offset: float) -> dict[str, Any]:
        return {
            "pid": pid,
            "port": 8000,
            "started_at": "",
            "started_epoch": now + offset,
            "command": "uvicorn",
        }

    checks: list[tuple[str, Any, Any]] = [
        (
            "процес, старший за код, не свіжий",
            adjudicate([process("1", -10)], (now, "x.py"))["rate"],
            0.0,
        ),
        (
            "процес, новіший за код, свіжий",
            adjudicate([process("1", +10)], (now, "x.py"))["rate"],
            1.0,
        ),
        (
            "один із двох",
            adjudicate([process("1", -10), process("2", +10)], (now, "x.py"))["rate"],
            0.5,
        ),
        ("нуль процесів — UNKNOWN, не згода", adjudicate([], (now, "x.py"))["status"], "UNKNOWN"),
        ("нуль процесів не дає ставки", adjudicate([], (now, "x.py"))["rate"], None),
        (
            "старий названий поіменно",
            adjudicate([process("77", -10)], (now, "x.py"))["stale"],
            ["77"],
        ),
    ]
    passed = 0
    for name, got, want in checks:
        ok = got == want
        passed += ok
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")
    print(f"негативний контроль: {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "var/serving-freshness.json")
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    report = adjudicate(serving_processes(arguments.proc_root), newest_source())
    report["ran_at"] = datetime.now(UTC).isoformat()
    # Прив'язка до дерева: споживач (модель впевненості) відкидає звіт про інший коміт.
    # Без поля звіт описував «якийсь» стан, і вчорашній вимір читався як сьогоднішній.
    report["commit"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    arguments.out.write_text(rendered, encoding="utf-8")
    print(rendered)
    if report["status"] != "MEASURED":
        return 2
    return 0 if report["rate"] == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
