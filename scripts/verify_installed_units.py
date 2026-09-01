#!/usr/bin/env python3
"""Юніт, ВСТАНОВЛЕНИЙ на машині, мусить бути тим, що описує дерево.

Виміряно 01.09.2026, і це третє оголошення тієї самої властивості. У дереві
`deploy/public/korpus-public-api.service` самооголошений: усі змінні рядками
`Environment=`, `EnvironmentFile=` заборонений тестом, бо властивості безпеки
публічного API мусять читатись у репозиторії. `check_public_env_parity` звіряє цей
шаблон зі `scripts/serve_public.sh`.

А на машині встановлено ІНШЕ: юніт із `EnvironmentFile=%h/.local/state/korpus-public/api.env`.
Тобто гейт паритету звіряв дві копії, жодна з яких не була тим, що виконується. Це не
теорія: сторож відновлює API саме цим юнітом.

Гейт не судить, який варіант кращий. Він відповідає на питання, якого ніхто не ставив:
**чи те, що встановлено, є тим, що ми читаємо.**

Розбіжність — відмова. Відсутність systemd — UNKNOWN, а не згода: машина, на якій
неможливо подивитись, не доводить збігу. Юніт, не встановлений зовсім, — теж окремий
стан: ненаглядовий шлях відновлення тоді просто не існує.

    verify_installed_units.py
    verify_installed_units.py --selftest
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "korpus.installed-units.v1"

_SPEC = importlib.util.spec_from_file_location(
    "install_public_runtime", ROOT / "scripts/install_public_runtime.py"
)
assert _SPEC and _SPEC.loader
INSTALLER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(INSTALLER)


def directives(text: str) -> list[str]:
    """Рядки-директиви без коментарів і порожніх.

    Порівнюємо НАМІР, не форматування: коментар у юніті пояснює рішення, і різниця в
    поясненні не є різницею в поведінці. Порівняння підрядком тут уже одного разу
    покарало за документацію рішення.
    """
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def installed(name: str) -> str | None:
    """Текст встановленого юніта, або None — якщо подивитись неможливо."""
    completed = subprocess.run(
        ["systemctl", "--user", "cat", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    body = completed.stdout.splitlines()
    # Перший рядок `systemctl cat` — коментар зі шляхом файла.
    return "\n".join(body[1:]) if body and body[0].startswith("# ") else completed.stdout


def working_directory(text: str) -> str | None:
    for line in directives(text):
        if line.startswith("WorkingDirectory="):
            return line.split("=", 1)[1]
    return None


def assess(
    observed: dict[str, str | None], rendered: dict[str, str], root: str | None = None
) -> list[dict[str, str]]:
    """Вирок. `root` — корінь ЦЬОГО дерева; потрібен, щоб не червоніти з власної причини.

    Шаблон розгортається відносно дерева, з якого запущено. У worktree це дає інші
    абсолютні шляхи, ніж у каноні, — і гейт доповідав би про розбіжність, якої немає:
    юніт для цього дерева ніхто й не збирався ставити. Це рівно та вада, яку цей гейт
    існує ловити, тільки в ньому самому. Тому «встановлено для іншого кореня» — окремий
    стан UNKNOWN із названою причиною, а не відмова.
    """
    findings: list[dict[str, str]] = []
    for name in sorted(rendered):
        text = observed.get(name)
        installed_root = working_directory(text) if text is not None else None
        if text is not None and root is not None and installed_root not in (None, root):
            findings.append(
                {
                    "check": name,
                    "verdict": "UNKNOWN",
                    "detail": (
                        f"встановлено для іншого кореня ({installed_root}), а це дерево "
                        f"{root} — порівнювати нічого"
                    ),
                }
            )
            continue
        if text is None:
            findings.append(
                {
                    "check": name,
                    "verdict": "UNKNOWN",
                    "detail": "юніт не встановлений або systemd недоступний — не виміряно",
                }
            )
            continue
        mine, theirs = directives(rendered[name]), directives(text)
        if mine == theirs:
            findings.append(
                {"check": name, "verdict": "PASS", "detail": "встановлене дорівнює дереву"}
            )
            continue
        only_installed = [line for line in theirs if line not in mine]
        only_tree = [line for line in mine if line not in theirs]
        findings.append(
            {
                "check": name,
                "verdict": "FAIL",
                "detail": (
                    f"розбіжність: лише встановлене {only_installed[:3]}; "
                    f"лише дерево {only_tree[:3]}"
                ),
            }
        )
    return findings


def verdict(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "UNKNOWN"
    verdicts = {finding["verdict"] for finding in findings}
    if "FAIL" in verdicts:
        return "FAIL"
    return "UNKNOWN" if "UNKNOWN" in verdicts else "PASS"


def selftest() -> int:
    unit = '[Service]\n# пояснення\nExecStart=/x\nEnvironment="A=1"\n'
    cases: list[tuple[str, dict[str, str | None], dict[str, str], str]] = [
        ("однакові — зелено", {"u": unit}, {"u": unit}, "PASS"),
        (
            "інший коментар різницею не є",
            {"u": '[Service]\n# зовсім інше пояснення\nExecStart=/x\nEnvironment="A=1"\n'},
            {"u": unit},
            "PASS",
        ),
        (
            "встановлене має зайву директиву",
            {"u": unit + "EnvironmentFile=%h/x.env\n"},
            {"u": unit},
            "FAIL",
        ),
        (
            "у встановленого інше значення",
            {"u": '[Service]\nExecStart=/x\nEnvironment="A=2"\n'},
            {"u": unit},
            "FAIL",
        ),
        ("юніта немає — UNKNOWN, не PASS", {"u": None}, {"u": unit}, "UNKNOWN"),
        ("нічого не оголошено — UNKNOWN", {}, {}, "UNKNOWN"),
    ]
    bad = 0
    for name, observed, rendered, want in cases:
        got = verdict(assess(observed, rendered))
        ok = got == want
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")

    # Гейт не сміє червоніти з ВЛАСНОЇ причини: у worktree шаблон розгортається на інший
    # корінь, і різниця шляхів не є розбіжністю наміру.
    root_cases: list[tuple[str, str, str, str]] = [
        (
            "інший корінь — UNKNOWN, не FAIL",
            "[Service]\nWorkingDirectory=/canon\nExecStart=/x\n",
            "[Service]\nWorkingDirectory=/worktree\nExecStart=/x\n",
            "UNKNOWN",
        ),
        (
            "той самий корінь — розбіжність видно",
            "[Service]\nWorkingDirectory=/canon\nExecStart=/y\n",
            "[Service]\nWorkingDirectory=/canon\nExecStart=/x\n",
            "FAIL",
        ),
    ]
    for name, inst, tree, want in root_cases:
        got = verdict(assess({"u": inst}, {"u": tree}, working_directory(tree)))
        ok = got == want
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")
    total = len(cases) + len(root_cases)
    print(f"\nнегативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "var/installed-units.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    rendered: dict[str, str] = {name: INSTALLER.render(name) for name in INSTALLER.UNITS}
    observed: dict[str, str | None] = {name: installed(name) for name in rendered}
    findings = assess(observed, rendered, str(ROOT))
    overall = verdict(findings)
    report: dict[str, Any] = {"schema": SCHEMA, "status": overall, "findings": findings}
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for item in findings:
        print(f"  [{item['verdict']}] {item['check']}: {item['detail']}")
    print(f"\ninstalled-units: {overall}  → {arguments.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
