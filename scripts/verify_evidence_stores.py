#!/usr/bin/env python3
"""Скільки баз доказів існує — і чи та, яку подають, є тією, яку назвали.

Виміряно 01.09.2026. Крім корпусу, що подається солдату, у дереві живуть ще чотири
бази форми «докази», а поруч у докері — п'ята:

    var/runtime/corpus-v6-20260807/korpus.db   256 док. · 31464 прольоти  ← подається
    var/korpus.db                                0 док. ·     0 прольотів
    var/liveness-fixture/korpus.db               2 док. ·     3 прольоти
    var/sqlite-recovery-drill/source.db          9 док. ·     1 проліт
    var/sqlite-recovery-drill/restored/korpus.db 4 док. ·     1 проліт
    postgres://korpus                          256 док. · 38863 прольоти

Два факти з цього переліку — небезпечні, і жоден не був під гейтом.

ПЕРШИЙ. `var/korpus.db` порожня і лежить рівно там, куди дивиться типове значення
`config.py` (`sqlite:///./var/korpus.db`). Процес, запущений без
`KORPUS_DATABASE_URL`, читає корпус із НУЛЯ документів — і більшість перевірок на
порожньому вході зеленіють, бо їм нема на що скаржитись. Це знали: два файли несуть
про це коментар. Але коментар — не перевірка.

ДРУГИЙ. Постгрес містить ТІ САМІ 256 документів і на 7399 прольотів БІЛЬШЕ. Тобто
нарізка інша, і `span_id` з однієї бази в іншій означає інший фрагмент — або нічого.
Дві бази доказів під одним ім'ям корпусу вже коштували нам дня в `audit-verify`.

Гейт не вимагає, щоб баз була одна: чернетки, еталони й навчальні прогони — законні.
Він вимагає, щоб КОЖНА була НАЗВАНА, щоб роль `served` була рівно одна, і щоб вона
збігалася з тим, що юніт справді віддає сервісу.

    verify_evidence_stores.py
    verify_evidence_stores.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config/operations/evidence-stores.json"
UNIT = ROOT / "deploy/public/korpus-public-api.service"
SCHEMA = "korpus.evidence-stores.v1"

#: Форма «сховище доказів»: обидві таблиці разом. Одна з них трапляється і в чужих
#: базах, тому вимагаються обидві — інакше кеш mypy потрапив би в перелік.
SHAPE = ("documents", "evidence_spans")

#: Куди дивиться типове значення налаштувань, коли оточення не назвало базу.
CONFIG_DEFAULT = "var/korpus.db"
_DEFAULT_IN_CONFIG = re.compile(r'database_url:\s*str\s*=\s*"sqlite:///\./(?P<path>[^"]+)"')
_UNIT_DATABASE = re.compile(r'Environment="KORPUS_DATABASE_URL=sqlite:/*(?P<path>[^"]+)"')


# ----------------------------------------------------------------- спостереження (I/O)


def _shape(path: Path) -> dict[str, Any] | None:
    """(документи, прольоти), або None — якщо це взагалі не сховище доказів.

    Розрізнення тут не стилістичне. «Не сховище» вирішує ФОРМА — обидві таблиці разом;
    «сховище, яке не читається» — це подія, і вона мусить лишитись у переліку з
    позначкою, а не зникнути. Раніше обидва випадки давали None, і сховище з
    пошкодженим файлом просто випадало зі списку: гейт казав «п'ять сховищ, усі
    названі» саме тоді, коли шосте не відкривалось. Вимір, який мовчить про власну
    сліпоту, гірший за відсутній.

    Побічний наслідок цього ж розрізнення: перевірка форми стала ЄДИНИМ, що вирішує.
    Доти її мовчки дублював `except`, тож мутант, який міняв `<=` на `&`, виживав —
    не тому, що правило слабке, а тому, що воно нічого не вирішувало.
    """
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        names = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
    except sqlite3.Error:
        return None
    try:
        if not set(SHAPE) <= names:
            return None
        documents = connection.execute("select count(*) from documents").fetchone()[0]
        spans = connection.execute("select count(*) from evidence_spans").fetchone()[0]
    except sqlite3.Error as error:
        return {"unreadable": str(error)[:120]}
    finally:
        connection.close()
    return {"documents": int(documents), "spans": int(spans)}


def observe(root: Path = ROOT) -> dict[str, Any]:
    """Що є НАСПРАВДІ. Тут дозволено I/O і заборонено судити."""
    stores: dict[str, dict[str, Any]] = {}
    var = root / "var"
    if var.is_dir():
        for path in sorted(var.rglob("*.db")):
            shape = _shape(path)
            if shape is not None:
                stores[str(path.relative_to(root))] = shape

    unit_path: str | None = None
    if UNIT.is_file():
        matched = _UNIT_DATABASE.search(UNIT.read_text(encoding="utf-8"))
        if matched:
            unit_path = matched.group("path").replace("@KORPUS_ROOT@/", "")

    config_default: str | None = None
    config = root / "apps/api/src/korpus/config.py"
    if config.is_file():
        matched = _DEFAULT_IN_CONFIG.search(config.read_text(encoding="utf-8"))
        if matched:
            config_default = matched.group("path")

    return {"stores": stores, "unit_database": unit_path, "config_default": config_default}


def observe_external() -> dict[str, Any]:
    """Бази поза деревом. Недосяжність — це UNKNOWN, а не «їх немає»."""
    listed = subprocess.run(
        [
            "docker",
            "exec",
            "korpus-postgres-1",
            "psql",
            "-U",
            "postgres",
            "-tAc",
            "select datname from pg_database where datistemplate=false",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        return {"reachable": False, "databases": []}
    return {
        "reachable": True,
        "databases": sorted(name.strip() for name in listed.stdout.split() if name.strip()),
    }


# --------------------------------------------------------------------- судження (чисте)


def _finding(check: str, verdict: str, detail: str) -> dict[str, str]:
    return {"check": check, "verdict": verdict, "detail": detail}


def _declared(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = registry.get("stores") if isinstance(registry, dict) else None
    if not isinstance(entries, list):
        return {}
    return {
        entry["path"]: entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }


def _check_undeclared(
    observation: dict[str, Any], declared: dict[str, dict[str, Any]]
) -> dict[str, str]:
    extra = sorted(set(observation["stores"]) - set(declared))
    if extra:
        return _finding(
            "undeclared_store",
            "FAIL",
            "сховище доказів, якого ніхто не назвав: " + ", ".join(extra),
        )
    return _finding("undeclared_store", "PASS", f"{len(observation['stores'])} сховищ, усі названі")


def _check_ghost(
    observation: dict[str, Any], declared: dict[str, dict[str, Any]]
) -> dict[str, str]:
    ghosts = sorted(
        path
        for path, entry in declared.items()
        if path not in observation["stores"] and not entry.get("optional")
    )
    if ghosts:
        return _finding(
            "ghost_store", "FAIL", "запис про сховище, якого немає: " + ", ".join(ghosts)
        )
    return _finding("ghost_store", "PASS", "жодного запису про неіснуюче сховище")


def _check_one_served(
    _observation: dict[str, Any], declared: dict[str, dict[str, Any]]
) -> dict[str, str]:
    served = sorted(path for path, entry in declared.items() if entry.get("role") == "served")
    if len(served) == 1:
        return _finding("one_served_store", "PASS", f"подається рівно одне: {served[0]}")
    return _finding(
        "one_served_store",
        "FAIL",
        f"роль served мають {len(served)} сховищ: " + (", ".join(served) or "жодного"),
    )


def _check_served_matches_unit(
    observation: dict[str, Any], declared: dict[str, dict[str, Any]]
) -> dict[str, str]:
    served = [path for path, entry in declared.items() if entry.get("role") == "served"]
    unit = observation.get("unit_database")
    if unit is None:
        return _finding("served_matches_unit", "UNKNOWN", "юніт не прочитано — не виміряно")
    if len(served) != 1:
        return _finding(
            "served_matches_unit", "UNKNOWN", "роль served не одна — нема з чим звіряти"
        )
    if served[0] != unit:
        return _finding(
            "served_matches_unit",
            "FAIL",
            f"названо {served[0]}, а сервісу віддають {unit}",
        )
    return _finding("served_matches_unit", "PASS", f"названо й віддається одне: {unit}")


def _check_default_is_not_served(
    observation: dict[str, Any], declared: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Типове значення налаштувань не сміє вказувати на те, що подають.

    Не тому, що воно шкідливе саме по собі, а тому, що процес БЕЗ оточення тоді
    виглядав би працездатним. Порожня база на типовому шляху — чесніша: вона падає
    видимо. Але й вона мусить бути названа, інакше перший, хто її знайде, вирішить,
    що знайшов корпус.
    """
    default = observation.get("config_default")
    if default is None:
        return _finding("default_is_not_served", "UNKNOWN", "типове значення не прочитано")
    entry = declared.get(default)
    if entry is None:
        return _finding(
            "default_is_not_served",
            "UNKNOWN" if default not in observation["stores"] else "FAIL",
            f"типовий шлях {default} не названий у реєстрі",
        )
    if entry.get("role") == "served":
        return _finding(
            "default_is_not_served",
            "FAIL",
            f"типовий шлях {default} оголошено тим, що подається: процес без оточення "
            "виглядав би працездатним",
        )
    return _finding(
        "default_is_not_served", "PASS", f"типовий шлях {default} названий як {entry.get('role')}"
    )


def _check_readable(
    observation: dict[str, Any], _declared: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Сховище, яке не читається, — відмова. Мовчазне випадіння зі списку — ні."""
    broken = sorted(path for path, shape in observation["stores"].items() if "unreadable" in shape)
    if broken:
        return _finding(
            "unreadable_store", "FAIL", "сховище доказів не читається: " + ", ".join(broken)
        )
    return _finding("unreadable_store", "PASS", "кожне знайдене сховище прочитано")


CHECKS = (
    _check_readable,
    _check_undeclared,
    _check_ghost,
    _check_one_served,
    _check_served_matches_unit,
    _check_default_is_not_served,
)


def assess(observation: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, str]]:
    if not observation.get("stores"):
        return [_finding("evidence_stores", "UNKNOWN", "жодного сховища не знайдено — не виміряно")]
    declared = _declared(registry)
    return [check(observation, declared) for check in CHECKS]


def verdict(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "UNKNOWN"
    verdicts = {finding["verdict"] for finding in findings}
    if "FAIL" in verdicts:
        return "FAIL"
    return "UNKNOWN" if "UNKNOWN" in verdicts else "PASS"


# ------------------------------------------------------------------ негативні контролі


def selftest() -> int:
    served = "var/runtime/corpus-v6-20260807/korpus.db"
    stores: dict[str, Any] = {
        served: {"documents": 256, "spans": 31464},
        "var/korpus.db": {"documents": 0, "spans": 0},
    }
    base: dict[str, Any] = {
        "stores": stores,
        "unit_database": served,
        "config_default": "var/korpus.db",
    }
    registry = {
        "stores": [
            {"path": served, "role": "served", "reason": "корпус, який подається солдату"},
            {"path": "var/korpus.db", "role": "empty_developer_default", "reason": "порожня"},
        ]
    }
    cases: list[tuple[str, dict[str, Any], dict[str, Any], str]] = [
        ("названо все — зелено", base, registry, "PASS"),
        (
            "з'явилось сховище, якого ніхто не назвав",
            {
                **base,
                "stores": {**base["stores"], "var/чуже/korpus.db": {"documents": 7, "spans": 9}},
            },
            registry,
            "FAIL",
        ),
        (
            "запис про сховище, якого немає",
            base,
            {
                "stores": registry["stores"]
                + [{"path": "var/привид.db", "role": "draft", "reason": "x"}]
            },
            "FAIL",
        ),
        (
            "два сховища з роллю served",
            base,
            {
                "stores": [
                    {"path": served, "role": "served", "reason": "x"},
                    {"path": "var/korpus.db", "role": "served", "reason": "x"},
                ]
            },
            "FAIL",
        ),
        (
            "жодного served",
            base,
            {"stores": [{"path": p, "role": "draft", "reason": "x"} for p in stores]},
            "FAIL",
        ),
        (
            "юніт віддає НЕ те, що названо",
            {**base, "unit_database": "var/korpus.db"},
            registry,
            "FAIL",
        ),
        (
            "юніт не прочитано — UNKNOWN, не PASS",
            {**base, "unit_database": None},
            registry,
            "UNKNOWN",
        ),
        (
            "типовий шлях оголошено тим, що подається",
            {**base, "config_default": served},
            registry,
            "FAIL",
        ),
        (
            "типовий шлях існує й не названий",
            base,
            {"stores": [{"path": served, "role": "served", "reason": "x"}]},
            "FAIL",
        ),
        ("порожнє спостереження — UNKNOWN, не PASS", {"stores": {}}, registry, "UNKNOWN"),
        (
            "сховище не читається — подія, не тиша",
            {**base, "stores": {**stores, served: {"unreadable": "database is locked"}}},
            registry,
            "FAIL",
        ),
    ]
    bad = 0
    for name, observation, reg, expected in cases:
        got = verdict(assess(observation, reg))
        ok = got == expected
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")
    print(f"\nнегативний контроль: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/evidence-stores.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    try:
        registry = json.loads(arguments.registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"schema": SCHEMA, "status": "UNKNOWN", "reason": "реєстр не прочитано"}))
        return 2

    observation = observe(arguments.root)
    findings = assess(observation, registry)
    external = observe_external()
    overall = verdict(findings)
    report = {
        "schema": SCHEMA,
        "status": overall,
        "observed": observation,
        "external": external,
        "findings": findings,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for item in findings:
        print(f"  [{item['verdict']}] {item['check']}: {item['detail']}")
    print(f"\nevidence-stores: {overall}  → {arguments.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
