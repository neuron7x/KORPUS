#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))
from korpus.application.exact_environment import exact_environment_state  # noqa: E402
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)")
PYTHON = re.compile(r"^ARG PYTHON_IMAGE=python:(\d+\.\d+\.\d+)-", re.M)
RUNTIME_LOCK = ROOT / "apps/api/requirements.runtime.lock"
DEV_LOCK = ROOT / "apps/api/requirements.dev.lock"
PROFILE = ROOT / "config/assurance/exact-environment-v1.json"

#: Який замок застосовний до якого середовища — і це не смак.
#:
#: Перша версія читала ОБИДВА замки завжди й вимагала `production_python_exact`
#: незалежно від того, де біжить. Виміряно 02.09.2026: жодне середовище не могло
#: пройти обидві перевірки. На робочій машині стоїть 3.12.3 при вимозі 3.12.13,
#: тож `production_python_exact` хибне; у продакшенному образі 3.12.13 і воно
#: істинне, але dev-інструментів (pytest, mypy, coverage) там немає й бути не
#: мусить, тож `all_locked_components_installed` хибне. Гейт був нездійсненний
#: ЗА ПОБУДОВОЮ — стан, у якому він зелений, не існував.
#:
#: `production_python_exact` у профілі `development` ВІДСУТНЄ, а не хибне: dev-
#: машина не є продакшеном, і питати її про це — питати не те. Профіль пишеться
#: у доказ, а продакшенний предикат вимагає саме `runtime`: інакше доказ робочої
#: машини задовольнив би твердження про продакшен.
LOCK_PROFILES = {
    "runtime": (RUNTIME_LOCK,),
    "development": (RUNTIME_LOCK, DEV_LOCK),
}
EVIDENCE_CLASSES = {
    "runtime": "EXACT_PRODUCTION_IMAGE",
    "development": "DEVELOPMENT_INTERPRETER",
}


def _pins(locks: tuple[Path, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in locks:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = PIN.match(line.strip())
            if match:
                result[match.group(1).lower().replace("_", "-")] = match.group(2)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    # БЕЗ дефолту. Профіль, обраний мовчки, зробив би доказ одного середовища
    # непомітно придатним для тверджень про інше.
    parser.add_argument("--profile", required=True, choices=sorted(LOCK_PROFILES))
    args = parser.parse_args()
    locks = LOCK_PROFILES[args.profile]
    pins = _pins(locks)
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    installed = {
        d.metadata["Name"].lower().replace("_", "-"): d.version
        for d in importlib.metadata.distributions()
        if d.metadata.get("Name")
    }
    match = PYTHON.search((ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8"))
    required = match.group(1) if match else ""
    hashes_complete = all("--hash=sha256:" in path.read_text(encoding="utf-8") for path in locks)
    checks, missing, mismatched, extras = exact_environment_state(
        pins,
        installed,
        python_version=platform.python_version(),
        required_python=required,
        allowed_unmanaged=profile["allowed_unmanaged_distributions"],
        hashes_complete=hashes_complete,
    )
    if args.profile != "runtime":
        # Не False, а ВІДСУТНЄ: dev-машина не продакшен, і хибний вирок про неї
        # був би твердженням про те, чого ніхто не питав.
        checks.pop("production_python_exact", None)
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        "exact_environment",
        status="PASS" if not failures else "FAIL",
        source_digest=compute_source_digest(ROOT),
        release=release_tag(),
        checks=checks,
        failures=failures,
        evidence_class=EVIDENCE_CLASSES[args.profile],
        profile=args.profile,
        python=platform.python_version(),
        required_python=required,
        implementation=platform.python_implementation(),
        locked_components=len(pins),
        missing=missing,
        mismatched=mismatched,
        unmanaged_distributions=extras,
    )
    # Ім'я файла несе ПРОФІЛЬ. Доти обидва профілі писали один шлях, і слабший
    # клас доказу (`DEVELOPMENT_INTERPRETER`) мовчки затирав сильніший
    # (`EXACT_PRODUCTION_IMAGE`) щоразу, коли біг `validate`. Предикат, який
    # вимагає `runtime`, після лану не міг бути задоволеним ніколи.
    # Продакшенний предикат читає канонічне ім'я; профіль розробки лежить поруч
    # і нічого не перекриває.
    name = (
        "exact_environment-gate.json"
        if args.profile == "runtime"
        else f"exact_environment-{args.profile}-gate.json"
    )
    out = ROOT / "var/production" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
