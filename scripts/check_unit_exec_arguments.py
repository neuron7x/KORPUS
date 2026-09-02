#!/usr/bin/env python3
"""Шлях, підставлений у позицію АРГУМЕНТУ юніта, мусить лишитись одним аргументом.

ВИМІРЯНО 02.09.2026. `korpus-nightly-gates.service` падав із кодом 2 від моменту
встановлення. Причина не в лані: інсталятор підставляє `@KORPUS_ROOT@` у рядок

    ExecStart=/usr/bin/make -C @KORPUS_ROOT@ check-nightly

а канонічний корінь містить пробіли. systemd ділить `ExecStart=` за пробілами так само,
як оболонка, тож виконувалось `make -C /home/neuro7/Desktop/Ядро` з трьома зайвими
«цілями». Журнал казав дослівно: `make: *** /home/neuro7/Desktop/Ядро: Немає такого
файла або каталогу`.

Наслідок не косметичний: `check-nightly` — один із ЧОТИРЬОХ коренів замикання гейтів
(`verify_gate_closure.ROOTS`), і одинадцять перевірочних цілей мають охоплення лише
через нього. Замикання лишалось зеленим за арифметикою, бо воно міряє ОГОЛОШЕНУ
досяжність, а не виконану.

Це КЛАС, не один рядок. Пошук по всіх шаблонах знайшов другий випадок —
`korpus-routine@.service` підставляє корінь двічі, обидва рази без лапок. Два інші
юніти (`korpus-public-api`, `korpus-worker`) роблять правильно: `"@KORPUS_ROOT@/..."`.
Отже правильний зразок у дереві вже був, і саме тому вада не кидалась у вічі.

## Чому перевірка розбирає рядок, а не шукає лапки

«Чи є лапки» — це перевірка НАПИСАННЯ. Вона зелена на `-C "@KORPUS_ROOT@"` і зелена ж
на `-C "@KORPUS_ROOT@` з однією лапкою. Тут питання про ПОВЕДІНКУ: чи доживе шлях до
`execve` одним аргументом. Тому рядок ділиться правилами systemd, і твердження таке:
серед отриманих аргументів мусить бути такий, що містить корінь ЦІЛКОМ.

Корінь для проби береться той, що містить пробіли, навіть якщо дерево лежить за шляхом
без них — інакше перевірка була б зеленою на будь-якому написанні рівно доти, доки
хтось не перенесе дерево, і сама б цього не помітила.

    check_unit_exec_arguments.py [--selftest]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "@KORPUS_ROOT@"

#: Директиви, чиє значення systemd ділить на аргументи. `WorkingDirectory=` і
#: `EnvironmentFile=` сюди НЕ входять: вони беруть значення цілком, і саме тому
#: зламаний юніт мав правильну робочу теку й розбитий рядок запуску.
ARGUMENT_DIRECTIVES = (
    "ExecStart",
    "ExecStartPre",
    "ExecStartPost",
    "ExecStop",
    "ExecStopPost",
    "ExecReload",
    "ExecCondition",
)

#: Корінь із пробілами. Проба мусить бути ворожою незалежно від того, де лежить дерево.
PROBE_ROOT = "/probe root/з пробілами/корпус"


def split_systemd(value: str) -> list[str]:
    """Поділ рядка на аргументи за правилами systemd.

    Подвійні й одинарні лапки знімаються, зворотний скіс екранує наступний символ,
    невзяті в лапки пробіли розділяють. Це та сама механіка, через яку зламався
    нічний лан, тому вона тут відтворена, а не обійдена.
    """
    args: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    started = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            started = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in "\"'":
            quote = char
            started = True
            continue
        if char.isspace():
            if started:
                args.append("".join(current))
                current = []
                started = False
            continue
        current.append(char)
        started = True
    if started:
        args.append("".join(current))
    return args


def unit_problems(name: str, text: str, root: str = PROBE_ROOT) -> list[str]:
    """Аргументні директиви, у яких підставлений корінь розпався на шматки."""
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        directive, _, value = line.partition("=")
        directive = directive.lstrip("-@:+!").strip()
        if directive not in ARGUMENT_DIRECTIVES or PLACEHOLDER not in value:
            continue
        rendered = value.replace(PLACEHOLDER, root)
        arguments = split_systemd(rendered)
        if not any(root in argument for argument in arguments):
            problems.append(
                f"{name}:{number}: {directive} — корінь розпався на аргументи "
                f"{arguments!r}; візьміть {PLACEHOLDER} у лапки"
            )
    return problems


def templates(root: Path = ROOT) -> list[Path]:
    return sorted(
        path for pattern in ("*.service", "*.timer") for path in (root / "deploy").rglob(pattern)
    )


def assess(root: Path = ROOT) -> dict[str, object]:
    problems: list[str] = []
    checked: list[str] = []
    for path in templates(root):
        relative = str(path.relative_to(root))
        checked.append(relative)
        problems.extend(unit_problems(relative, path.read_text(encoding="utf-8")))
    return {
        "schema": "korpus.unit-exec-arguments.v1",
        "probe_root": PROBE_ROOT,
        "units_checked": len(checked),
        "units": checked,
        "problems": problems,
        "status": "PASS" if not problems else "FAIL",
    }


def selftest() -> int:
    """Негативний контроль: гейт мусить ЛОВИТИ, а не лише не падати."""
    failures: list[str] = []

    broken = "[Service]\nExecStart=/usr/bin/make -C @KORPUS_ROOT@ check-nightly\n"
    if not unit_problems("проба", broken):
        failures.append("не спіймано нелапкований корінь у позиції аргументу")

    quoted = '[Service]\nExecStart=/usr/bin/make -C "@KORPUS_ROOT@" check-nightly\n'
    if unit_problems("проба", quoted):
        failures.append("хибне спрацювання на правильно взятому в лапки корені")

    prefixed = '[Service]\nExecStart="@KORPUS_ROOT@/apps/api/.venv/bin/python" -m korpus.cli\n'
    if unit_problems("проба", prefixed):
        failures.append("хибне спрацювання на лапкованому шляху з суфіксом")

    # Директиви, що беруть значення ЦІЛКОМ, не є предметом цієї перевірки: саме тому
    # зламаний юніт мав правильну `WorkingDirectory=` і розбитий `ExecStart=`.
    whole = "[Service]\nWorkingDirectory=@KORPUS_ROOT@\n"
    if unit_problems("проба", whole):
        failures.append("перевірка залізла в директиву, яку systemd не ділить")

    # Одна лапка — це НЕ лапки. Перевірка на написання тут була б зеленою.
    half = '[Service]\nExecStart=/usr/bin/make -C "@KORPUS_ROOT@ check-nightly\n'
    if unit_problems("проба", half):
        failures.append("хибне спрацювання: одна лапка все одно тримає корінь цілим")

    for argument, expected in (
        ('a "b c" d', ["a", "b c", "d"]),
        ("a b\\ c d", ["a", "b c", "d"]),
        ("'x y' z", ["x y", "z"]),
        ("   ", []),
    ):
        if split_systemd(argument) != expected:
            failures.append(f"поділ {argument!r} дав {split_systemd(argument)!r}")

    print(
        json.dumps(
            {"selftest": "PASS" if not failures else "FAIL", "failures": failures},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    report = assess()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.out:
        target = arguments.out if arguments.out.is_absolute() else ROOT / arguments.out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
