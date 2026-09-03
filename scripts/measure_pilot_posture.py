#!/usr/bin/env python3
"""Скільки умов КЕРОВАНОГО середовища виконує розгортання приватного пілоту.

Реєстр `korpus.controlled_requirements` — це те, що САМА система вважає умовами
керованого середовища. Пілот оголошує себе `local`, тобто ЖОДНА з цих умов рантаймом
не вимагається: перевірка вмикається рядком `environment in {production, controlled,
isolated}`. Оголошення класу нижче вимоги не є ані обманом, ані пропуском — воно є
СТАНОМ, і власник мусить бачити цей стан числом, перш ніж запросити людей.

Три стани, не два. Умова, яка не стосується цієї ролі рантайму, — НЕ виконана: вона
не має предмета. Порахувати її як виконану означало б повторити помилку, через яку
`all([])` роками віддавав істину про порожній перелік.

    measure_pilot_posture.py
    measure_pilot_posture.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "apps/api/src")]

from korpus.config import Settings  # noqa: E402
from korpus.controlled_requirements import CONTROLLED_REQUIREMENTS  # noqa: E402

SCHEMA = "korpus.pilot-deployment-posture.v1"
UNIT = "deploy/pilot/korpus-pilot-api.service"
MET = "MET"
UNMET = "UNMET"
NOT_APPLICABLE = "NOT_APPLICABLE_TO_ROLE"
NOT_MEASURED = "NOT_MEASURED"
#: Предикат кинув виняток. Це НЕ «не виконано»: невідоме не є ані пройденим, ані
#: провалом, і мовчазне зведення його до UNMET сховало б поламаний вимірювач.
EVALUATION_ERROR = "EVALUATION_ERROR"
#: Ключі, значення яких у звіт не потрапляють НІКОЛИ.
SECRET = re.compile(r"(SECRET|PASSWORD|TOKEN|KEY|URL)$")


def environment_file(root: Path = ROOT) -> Path | None:
    """Шлях до оточення бере САМ юніт — друга копія розійшлася б мовчки."""
    unit = root / UNIT
    if not unit.is_file():
        return None
    for line in unit.read_text(encoding="utf-8").splitlines():
        if line.startswith("EnvironmentFile="):
            raw = line.split("=", 1)[1].lstrip("-")
            return Path(raw.replace("%h", str(Path.home())))
    return None


def parse_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def posture(settings: Any) -> list[dict[str, str]]:
    """Стан кожної умови керованого середовища для ЦЬОГО розгортання."""
    rows: list[dict[str, str]] = []
    for requirement in CONTROLLED_REQUIREMENTS:
        if not requirement.applies_to(settings):
            rows.append({"name": requirement.name, "state": NOT_APPLICABLE})
            continue
        try:
            holds = bool(requirement.holds(settings))
        except Exception as error:  # noqa: BLE001
            detail = f"{type(error).__name__}: {error}"
            print(f"предикат {requirement.name} не обчислився: {detail}", file=sys.stderr)
            rows.append({"name": requirement.name, "state": EVALUATION_ERROR, "detail": detail})
            continue
        rows.append({"name": requirement.name, "state": MET if holds else UNMET})
    return rows


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(root: Path = ROOT) -> dict[str, Any]:
    path = environment_file(root)
    if path is None or not path.is_file():
        return {
            "schema": SCHEMA,
            "status": NOT_MEASURED,
            "reason": f"оточення юніта не знайдено: {path}",
            "unit": UNIT,
        }
    values = parse_environment(path)
    previous = dict(os.environ)
    try:
        os.environ.update(values)
        settings = Settings()
        rows = posture(settings)
        declared = str(settings.environment)
        auth = str(settings.auth_mode)
    finally:
        os.environ.clear()
        os.environ.update(previous)
    counts = {
        state: sum(1 for row in rows if row["state"] == state)
        for state in (MET, UNMET, NOT_APPLICABLE, EVALUATION_ERROR)
    }
    return {
        "schema": SCHEMA,
        "status": "MEASURED",
        "unit": UNIT,
        "unit_sha256": _digest(root / UNIT),
        "environment_file": str(path),
        "environment_keys": sorted(key for key in values if not SECRET.search(key)),
        "declared_environment": declared,
        "auth_mode": auth,
        "controlled_requirements_enforced": declared in {"production", "controlled", "isolated"},
        "requirements_total": len(rows),
        "counts": counts,
        "requirements": rows,
        "interpretation": (
            "Пілот оголошує клас `local`, тож рантайм НЕ вимагає жодної з цих умов. Число "
            "виконаних — це те, що розгортання виконує САМЕ ПО СОБІ, без примусу. Умова поза "
            "роллю рантайму не виконана й не порушена: у неї немає предмета."
        ),
    }


def _state_of_a_broken_predicate() -> str:
    """Проба СТВОРЮЄ свою умову: предмет, що кидає на будь-якому доступі до поля."""

    class _Explodes:
        runtime_role = "api"

        def __getattr__(self, name: str) -> Any:
            raise RuntimeError(f"поле {name} недоступне")

    return posture(_Explodes())[0]["state"]


def selftest() -> int:
    api = Settings()
    worker = Settings(runtime_role="worker")
    oidc = Settings(auth_mode="oidc")
    named = {row["name"]: row["state"] for row in posture(api)}
    worker_named = {row["name"]: row["state"] for row in posture(worker)}
    oidc_named = {row["name"]: row["state"] for row in posture(oidc)}
    cases = [
        ("умова поза роллю не рахується виконаною", worker_named["oidc"], NOT_APPLICABLE),
        ("умова ролі worker для api не має предмета", named["malware_scanning"], NOT_APPLICABLE),
        ("умова worker'а для worker'а міряється", worker_named["malware_scanning"], UNMET),
        ("дефолтне оточення не виконує oidc", named["oidc"], UNMET),
        ("oidc вмикається зміною предмета, не прапорцем звіту", oidc_named["oidc"], MET),
        ("станів рівно стільки, скільки умов", len(posture(api)), len(CONTROLLED_REQUIREMENTS)),
        ("порожнього оточення юніта не існує — це NOT_MEASURED", measure(Path("/nonexistent"))["status"], NOT_MEASURED),
        ("предикат, що кинув виняток, не стає UNMET", _state_of_a_broken_predicate(), EVALUATION_ERROR),
    ]
    bad = 0
    for name, actual, expected in cases:
        ok = actual == expected
        bad += not ok
        print(f"  {'ok' if ok else 'FAIL'} {name}: {actual!r}")
    print(f"негативний контроль: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Постава розгортання приватного пілоту")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--out", default="reports/PILOT_DEPLOYMENT_POSTURE.json")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    result = measure()
    (ROOT / arguments.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
