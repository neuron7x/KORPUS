#!/usr/bin/env python3
"""Запуск підпроцесів гейта PostgreSQL — і збереження ПРИЧИНИ їхньої відмови.

postgres_gate_process.py --selftest
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

#: Скільки символів кожної труби лишається у доказі. Бюджет НА ТРУБУ, не на суму:
#: саме сума й губила причину.
TAIL_BUDGET = 4000


def run(
    root: Path,
    command: list[str],
    timeout: int,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    selected = {**os.environ, "PYTHONPATH": str(root / "apps/api/src")}
    if environment:
        selected.update(environment)
    return subprocess.run(
        command,
        cwd=root,
        env=selected,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def labelled_tail(stdout: str, stderr: str, budget: int = TAIL_BUDGET) -> str:
    """Дві труби — два хвости, кожен підписаний.

    Було `(stdout + stderr)[-8000:]`. Це не «останні 8000 символів виводу», це останні
    8000 символів ТОЇ ТРУБИ, що прийшла другою. Виміряно 04.09.2026 на звіті гейта
    `postgres_security`: pytest назвав відмову у stdout, alembic залив stderr журналом
    міграцій — і в доказі лишився самий журнал міграцій. Гейт сказав `FAIL`, назвав
    перевірку, і не міг назвати причину, бо сам її і викинув.
    """
    return (
        f"--- stdout (останні {budget}) ---\n{stdout[-budget:]}\n"
        f"--- stderr (останні {budget}) ---\n{stderr[-budget:]}"
    )


def postgres_available(database_url: str | None, docker: str | None) -> bool:
    """Чи є ЧИМ ганяти набір: або зовнішня база, або docker. Досить одного.

    Винесено 04.09.2026, бо рішення ПРОПУСТИТИ гейт не мало жодного негативного
    контролю: самоперевірка звіряла лише підписані хвости виводу. Переворот `or` на
    `and` тут пропускав би гейт усюди, де є тільки docker, — і це `NOT_EXECUTED`, яке
    ніхто не відрізнить від `PASS`, бо пропуск повертає код `None`, не відмову.
    """
    return bool(database_url) or docker is not None


def skips(targets_present: bool, available: bool) -> bool:
    """Гейт не бігає, коли нема чого міряти АБО нема чим. Обидві причини — не PASS."""
    return not targets_present or not available


def runtime(root: Path, targets: list[str], targets_present: bool) -> tuple[bool, int | None, str]:
    available = postgres_available(os.getenv("KORPUS_TEST_DATABASE_URL"), shutil.which("docker"))
    if skips(targets_present, available):
        return available, None, ""
    completed = run(
        root,
        ["bash", "scripts/run_postgres_suite.sh", *targets],
        600,
        environment={"PYTHON": sys.executable},
    )
    return available, completed.returncode, labelled_tail(completed.stdout, completed.stderr)


def selftest() -> int:
    """Негативний контроль: причина живе у КОРОТШІЙ трубі, шум — у довшій."""
    cause = "FAILED apps/api/tests/test_postgres_rls_policy_state.py::test_policies"
    noise = "\n".join(f"INFO [alembic] running upgrade {index:04d}" for index in range(600))
    cases = [
        ("старий вигляд гейта губив причину", cause in (cause + noise)[-8000:], False),
        ("підписані хвости зберігають причину", cause in labelled_tail(cause, noise), True),
        ("підписані хвости зберігають і шум", "upgrade 0599" in labelled_tail(cause, noise), True),
        ("порожні труби не падають", labelled_tail("", "").count("---"), 4),
        # Рішення ПРОПУСТИТИ гейт — теж вирок, і доти його не звіряв ніхто.
        ("сама зовнішня база — досить", postgres_available("postgresql://x", None), True),
        ("сам docker — досить", postgres_available(None, "/usr/bin/docker"), True),
        ("обидва — теж досить", postgres_available("postgresql://x", "/usr/bin/docker"), True),
        ("немає нічого — гейт не має чим бігти", postgres_available(None, None), False),
        ("порожній рядок бази не є базою", postgres_available("", None), False),
        ("без цілей — пропуск", skips(False, True), True),
        ("нема чим бігти — пропуск", skips(True, False), True),
        ("є цілі й є чим — БІЖИТЬ", skips(True, True), False),
        ("нема ні того, ні того — пропуск", skips(False, False), True),
    ]
    bad = 0
    for name, actual, expected in cases:
        ok = actual == expected
        bad += not ok
        print(f"  {'ok' if ok else 'FAIL'} {name}: {actual!r}")
    print(f"негативний контроль: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    if not parser.parse_args().selftest:
        parser.print_usage()
        return 2
    return selftest()


if __name__ == "__main__":
    raise SystemExit(main())
