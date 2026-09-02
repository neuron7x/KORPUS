#!/usr/bin/env python3
"""Конфіг, який РОЗДАЄ публічний край, мусить бути тим, що описує дерево.

ВИМІРЯНО 02.09.2026. У `deploy/public/nginx.conf` виправлення межі записових маршрутів
(`location ~` -> `location ~*`) лежало разом із доказом обходу, знятим запитом із
інтернету. Контейнер `korpus-public-edge` при цьому роздавав СТАРИЙ конфіг: рендер у
`var/public/edge/nginx.conf` робить `serve_public.sh`, і після правки шаблона його ніхто
не перезапускав. Межа була виправлена в дереві й обходилась у бою добу.

Це не той самий випадок, що `verify_installed_units`: там розходились ДВІ КОПІЇ опису.
Тут дерево — ШАБЛОН, а розгорнуте — його рендер із підставленим токеном. Питання
інше: чи є розгорнуте рендером ПОТОЧНОГО шаблона.

## Чому порівнюється з маскуванням, а не з підставленим токеном

Щоб не тримати секрет у перевірці. Рендер відрізняється від шаблона рівно в одному
місці — `${KORPUS_PUBLIC_TOKEN}`. Тому в розгорнутому конфігу значення маскується назад
у плейсхолдер, і далі порівнюються два ТЕКСТИ, жоден із яких не містить облікових даних.
Побічний ефект корисний: якщо рендер колись почне відрізнятись ще чимось, це стане
видно як розбіжність, а не розчиниться в «ну там же токен».

## Стани

Контейнера немає — UNKNOWN, не згода: машина, на якій нема що дивитись, не доводить
збігу. Так само `docker` недоступний. Розбіжність — відмова.

    check_edge_config_parity.py [--selftest] [--out ФАЙЛ]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy/public/nginx.conf"
CONTAINER = "korpus-public-edge"
PLACEHOLDER = "${KORPUS_PUBLIC_TOKEN}"

#: Рядок, у якому рендер підставляє токен. Маскується назад у плейсхолдер.
_TOKEN_LINE = re.compile(r'(proxy_set_header Authorization "Bearer )([^"]+)(";)')


def mask(text: str) -> str:
    """Розгорнутий конфіг -> та сама форма, що й шаблон, без облікових даних.

    Заміна функцією, а не рядком-шаблоном: у `${KORPUS_PUBLIC_TOKEN}` є `$`, `{` і `}`,
    і будь-яке екранування під `re.sub` псує зворотні посилання. Перша редакція саме на
    цьому й впала — і впала на власній самоперевірці, а не в бою.
    """
    return _TOKEN_LINE.sub(lambda m: f"{m.group(1)}{PLACEHOLDER}{m.group(3)}", text)


def deployed(container: str = CONTAINER) -> str | None:
    """Що РОЗДАЄ контейнер. None — подивитись неможливо, і це не згода."""
    try:
        result = subprocess.run(
            ["docker", "exec", container, "cat", "/etc/nginx/nginx.conf"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def compare(template: str, live: str | None) -> dict[str, object]:
    if live is None:
        return {
            "verdict": "UNKNOWN",
            "detail": "край не запущений або docker недоступний — не виміряно",
            "divergent_lines": [],
        }
    masked = mask(live)
    if masked == template:
        return {
            "verdict": "PASS",
            "detail": "розгорнуте є рендером цього шаблона",
            "divergent_lines": [],
        }
    expected = template.splitlines()
    observed = masked.splitlines()
    divergent: list[str] = []
    for number, (mine, theirs) in enumerate(zip(expected, observed, strict=False), start=1):
        if mine != theirs:
            divergent.append(
                f"{number}: дерево {mine.strip()[:90]!r} != край {theirs.strip()[:90]!r}"
            )
        if len(divergent) >= 5:
            break
    if len(expected) != len(observed):
        divergent.append(f"довжина: дерево {len(expected)} рядків, край {len(observed)}")
    return {
        "verdict": "FAIL",
        "detail": "розгорнутий конфіг не є рендером поточного шаблона",
        "divergent_lines": divergent,
    }


def assess() -> dict[str, object]:
    template = TEMPLATE.read_text(encoding="utf-8")
    result = compare(template, deployed())
    return {
        "schema": "korpus.edge-config-parity.v1",
        "template": str(TEMPLATE.relative_to(ROOT)),
        "container": CONTAINER,
        "status": result["verdict"],
        **{k: v for k, v in result.items() if k != "verdict"},
    }


def selftest() -> int:
    """Негативний контроль: гейт мусить ЛОВИТИ, а не лише не падати."""
    failures: list[str] = []
    template = (
        'a\nproxy_set_header Authorization "Bearer ${KORPUS_PUBLIC_TOKEN}";\nlocation ~* /x {\n'
    )
    rendered = 'a\nproxy_set_header Authorization "Bearer s3cr3t-value";\nlocation ~* /x {\n'

    if compare(template, rendered)["verdict"] != "PASS":
        failures.append("рендер того самого шаблона не визнано збігом")

    stale = rendered.replace("location ~* /x", "location ~ /x")
    verdict = compare(template, stale)
    if verdict["verdict"] != "FAIL":
        failures.append("СТАРИЙ рендер (регістрозалежна межа) не спіймано")
    elif not verdict["divergent_lines"]:
        failures.append("відмова без названого рядка розбіжності")

    if compare(template, None)["verdict"] != "UNKNOWN":
        failures.append("відсутній край дав щось інше, ніж UNKNOWN")

    # Маскування не сміє лишити секрет у порівнюваному тексті.
    if "s3cr3t-value" in mask(rendered):
        failures.append("маскування лишило облікові дані в тексті")

    # Зайвий рядок у розгорнутому — теж розбіжність, не «майже те саме».
    if compare(template, rendered + "location /extra { }\n")["verdict"] != "FAIL":
        failures.append("зайвий рядок у розгорнутому не спіймано")

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
    # UNKNOWN не є згодою, але й не є відмовою розгортання: край може бути не піднятий
    # на машині, де йде збірка. Відмова — лише доведена розбіжність.
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
