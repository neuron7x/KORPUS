#!/usr/bin/env python3
"""Два оголошення оточення публічного API не сміють розійтися.

`scripts/serve_public.sh` і `deploy/public/korpus-public-api.service` описують ОДНЕ й
те саме — як налаштований публічний API. Копії дві, і це рішення, а не недбалість:
юніт мусить бути самооголошеним, бо його властивості безпеки читаються в репозиторії,
а не у файлі, якого в репозиторії немає (`EnvironmentFile=` тут заборонений тестом
`test_units_use_secret_file_and_do_not_allow_resource_control_overrides`).

Ціна двох копій — розходження, і воно сталося. Виміряно 31.08.2026: сторож відновлює
API через `systemctl --user restart`, тобто **ненаглядовий шлях іде юнітом**. Після
відновлення о 21:34 у живому процесі не було ні `KORPUS_MODEL_EGRESS_POSTURE`, ні ключа
аудиту — виправлення, зроблене у скрипті, туди просто не доходило. Наслідок: посада
лишалась `external_allowed`, а журнал доказів підписувався плейсхолдером
`replace-local-audit-key` із `config.py`. Обидві вади були б непомітні саме тому, що
шлях ненаглядовий.

Гейт вимагає не тотожності, а щоб КОЖНА різниця була названою:

  ЕКВІВАЛЕНТНА ПАРА  `KORPUS_JWT_SECRET` у скрипті проти `KORPUS_JWT_SECRET_FILE` у
                     юніті. Скрипт читає файл і експортує значення; юніт не сміє нести
                     секрет значенням. Це та сама властивість у двох формах.
  ЛИШЕ ЮНІТ          змінні, що описують роль процесу під наглядом systemd і не мають
                     сенсу для запуску з оболонки.
  БЕЗПЕКОВІ ЗНАЧЕННЯ мусять збігатися ДОСЛІВНО в обох, бо саме вони визначають, що
                     робить процес, а не як його запустили.

Будь-яка інша різниця — відмова.

    check_public_env_parity.py
    check_public_env_parity.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIT = ROOT / "deploy/public/korpus-public-api.service"
SCRIPT = ROOT / "scripts/serve_public.sh"
SCHEMA = "korpus.public-env-parity.v1"

#: Та сама властивість у двох формах: значення проти файла.
EQUIVALENT = {"KORPUS_JWT_SECRET": "KORPUS_JWT_SECRET_FILE"}

#: Змінні, що описують роль процесу під наглядом systemd. Оболонка їх не потребує.
UNIT_ONLY = {"KORPUS_RUNTIME_ROLE"}

#: Значення, які визначають ПОВЕДІНКУ, а не спосіб запуску. Розходження тут і було
#: тим, що ніхто не побачив: посада єгресу та ід ключа, яким підписується доказ.
SAFETY_VALUES = {
    "KORPUS_MODEL_EGRESS_POSTURE": "local_only",
    "KORPUS_BIND_HOST": "127.0.0.1",
    "KORPUS_AUTH_MODE": "jwt",
    "KORPUS_AUDIT_KEY_ID": "korpus-public-2026-08-31",
}

_UNIT_ENV = re.compile(r'^Environment="?(?P<name>KORPUS_[A-Z0-9_]+)=(?P<value>[^"\n]*)', re.M)
#: Відступ дозволений: `export` усередині `if` чи `{}` — звичайний shell, і парсер,
#: прибитий до початку рядка, мовчки не побачив би такої змінної. Сьогодні їх нуль, і
#: саме тому діра була б латентною.
_SHELL_EXPORT = re.compile(r"^[ \t]*export (?P<name>KORPUS_[A-Z0-9_]+)=(?P<value>.*)$", re.M)


def unit_environment(text: str) -> dict[str, str]:
    return {m.group("name"): m.group("value").strip() for m in _UNIT_ENV.finditer(text)}


def shell_environment(text: str) -> dict[str, str]:
    """Змінні, які скрипт СПРАВДІ експортує.

    Тут стояло ще й зняття коментарів — і воно не боронило нічого: якір `export` на
    початку рядка й так не збігається з `# export ...`, бо перед словом стоїть `#`.
    Мутант, що знімав це зняття, вижив, і правильно: захист, який неможливо змусити
    впасти, не є захистом. Прибрано разом із його тестом.
    """
    found: dict[str, str] = {}
    for match in _SHELL_EXPORT.finditer(text):
        raw = match.group("value").strip().strip('"')
        # `${VAR:-default}` — значенням є типове, бо саме воно чинне без оточення.
        default = re.fullmatch(r"\$\{[A-Z0-9_]+:-(?P<default>[^}]*)\}", raw)
        found[match.group("name")] = default.group("default") if default else raw
    return found


def _finding(check: str, verdict: str, detail: str) -> dict[str, str]:
    return {"check": check, "verdict": verdict, "detail": detail}


def assess(unit: dict[str, str], shell: dict[str, str]) -> list[dict[str, str]]:
    """UNKNOWN — окремо і НЕ PASS: нерозібране оголошення нічого не доводить."""
    if not unit or not shell:
        return [_finding("public_env_parity", "UNKNOWN", "одне з оголошень не розібрано")]

    findings: list[dict[str, str]] = []
    normalised_shell = {EQUIVALENT.get(name, name) for name in shell}
    unit_names = set(unit)

    missing_in_unit = sorted(normalised_shell - unit_names)
    findings.append(
        _finding(
            "unit_missing",
            "FAIL",
            "скрипт оголошує, а юніт ні — ненаглядовий шлях їх не матиме: "
            + ", ".join(missing_in_unit),
        )
        if missing_in_unit
        else _finding("unit_missing", "PASS", f"{len(normalised_shell)} змінних скрипта є в юніті")
    )

    extra_in_unit = sorted(unit_names - normalised_shell - UNIT_ONLY)
    findings.append(
        _finding(
            "unit_extra",
            "FAIL",
            "юніт оголошує те, чого скрипт не знає, і різниця не названа: "
            + ", ".join(extra_in_unit),
        )
        if extra_in_unit
        else _finding("unit_extra", "PASS", "кожна різниця названа")
    )

    drifted = sorted(
        f"{name}: юніт={unit.get(name)!r} скрипт={shell.get(name)!r} очікувано={expected!r}"
        for name, expected in SAFETY_VALUES.items()
        if unit.get(name) != expected or shell.get(name) != expected
    )
    findings.append(
        _finding("safety_values", "FAIL", "; ".join(drifted))
        if drifted
        else _finding(
            "safety_values", "PASS", f"{len(SAFETY_VALUES)} безпекових значень збігаються"
        )
    )

    leaked = sorted(name for name in unit if name.endswith("_SECRET"))
    findings.append(
        _finding("no_secret_by_value", "FAIL", "юніт несе секрет значенням: " + ", ".join(leaked))
        if leaked
        else _finding("no_secret_by_value", "PASS", "юніт посилається на секрет файлом")
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
    clean_unit = {
        "KORPUS_MODEL_EGRESS_POSTURE": "local_only",
        "KORPUS_BIND_HOST": "127.0.0.1",
        "KORPUS_AUTH_MODE": "jwt",
        "KORPUS_AUDIT_KEY_ID": "korpus-public-2026-08-31",
        "KORPUS_JWT_SECRET_FILE": "%h/x",
        "KORPUS_RUNTIME_ROLE": "api",
    }
    clean_shell = {
        "KORPUS_MODEL_EGRESS_POSTURE": "local_only",
        "KORPUS_BIND_HOST": "127.0.0.1",
        "KORPUS_AUTH_MODE": "jwt",
        "KORPUS_AUDIT_KEY_ID": "korpus-public-2026-08-31",
        "KORPUS_JWT_SECRET": "s3cret",
    }

    def drop(source: dict[str, str], name: str) -> dict[str, str]:
        return {k: v for k, v in source.items() if k != name}

    cases: list[tuple[str, dict[str, str], dict[str, str], str]] = [
        ("рівні оголошення", clean_unit, clean_shell, "PASS"),
        (
            "юніт без посади єгресу — саме та вада, що сталася",
            drop(clean_unit, "KORPUS_MODEL_EGRESS_POSTURE"),
            clean_shell,
            "FAIL",
        ),
        (
            "юніт із ІНШОЮ посадою єгресу",
            {**clean_unit, "KORPUS_MODEL_EGRESS_POSTURE": "external_allowed"},
            clean_shell,
            "FAIL",
        ),
        (
            "інший ід ключа в юніті — журнал ляже під чужий ярлик",
            {**clean_unit, "KORPUS_AUDIT_KEY_ID": "legacy-unversioned"},
            clean_shell,
            "FAIL",
        ),
        (
            "юніт із секретом ЗНАЧЕННЯМ",
            {**drop(clean_unit, "KORPUS_JWT_SECRET_FILE"), "KORPUS_JWT_SECRET": "s3cret"},
            clean_shell,
            "FAIL",
        ),
        (
            "юніт має зайву неназвану змінну",
            {**clean_unit, "KORPUS_SOMETHING_NEW": "x"},
            clean_shell,
            "FAIL",
        ),
        ("порожнє оголошення — UNKNOWN, не PASS", {}, clean_shell, "UNKNOWN"),
        ("порожній скрипт — UNKNOWN, не PASS", clean_unit, {}, "UNKNOWN"),
    ]

    bad = 0
    for name, unit, shell, expected in cases:
        got = verdict(assess(unit, shell))
        ok = got == expected
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")
    print(f"\nнегативний контроль: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def export_lines(unit_text: str, home: str) -> list[str]:
    """Оголошення юніта у формі, придатній до споживання оболонкою.

    Причина існування: гейт, що перевіряє ЖУРНАЛ, мусить дивитись на ту саму базу,
    той самий якір і ту саму каблучку ключів, що й сервіс. `make audit-verify` цього
    не робив — він брав типові значення `Settings` і читав базу РОЗРОБНИКА, а вирок
    «external audit anchor is ahead of the database head» описував не журнал, а
    розбіжність двох різних баз під одним якорем.

    Оголошення вже є, воно вже під гейтом паритету — лишалось зробити його
    придатним до споживання, а не переписувати вчетверте.
    """
    return [
        f"{name}={value.replace('%h', home)}" for name, value in unit_environment(unit_text).items()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "var/public-env-parity.json")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument(
        "--export",
        action="store_true",
        help="вивести оточення юніта як KEY=value для `env $(...)`, і нічого не судити",
    )
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    if arguments.export:
        for line in export_lines(UNIT.read_text(encoding="utf-8"), str(Path.home())):
            print(line)
        return 0

    unit = unit_environment(UNIT.read_text(encoding="utf-8"))
    shell = shell_environment(SCRIPT.read_text(encoding="utf-8"))
    findings = assess(unit, shell)
    overall = verdict(findings)
    report = {
        "schema": SCHEMA,
        "status": overall,
        "unit_variables": len(unit),
        "shell_variables": len(shell),
        "findings": findings,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for finding in findings:
        print(f"  [{finding['verdict']}] {finding['check']}: {finding['detail']}")
    print(f"\npublic-env-parity: {overall}  → {arguments.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
