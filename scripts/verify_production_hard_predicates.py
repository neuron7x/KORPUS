#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from assemble_production_assurance import DEFAULT_GATES  # noqa: E402
from korpus.application.production_hard_predicates import (  # noqa: E402
    evaluate_hard_predicates,
    load_hard_predicate_profile,
)
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

PROFILE = ROOT / "config/assurance/production-hard-predicates-v1.json"

#: Мапа гейт→файл ОДНА на дерево. Тут лежала друга копія, і вона збігалася з першою
#: випадково: обидві треба було правити разом, а перевірки, що вони збігаються, не було.
#: `final_release` існує лише тут — його не оцінює модель продакшену, тому він додається,
#: а не дублюється.
GATE_FILES = {
    **DEFAULT_GATES,
    "final_release": "final_release-gate.json",
}


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def build() -> dict[str, Any]:
    profile = load_hard_predicate_profile(PROFILE)
    gate_dir = ROOT / "var/production"
    gates = {gate: _json(gate_dir / filename) for gate, filename in GATE_FILES.items()}
    source_digest = compute_source_digest(ROOT)
    release = release_tag()
    states = evaluate_hard_predicates(
        ROOT, profile, gates, current_source_sha256=source_digest, current_release=release
    )
    software_ready = sum(state.software_ready for state in states)
    externally_satisfied = sum(state.externally_satisfied for state in states)
    production_satisfied = sum(state.production_satisfied for state in states)
    return {
        "schema": "korpus.production-hard-predicate-report.v1",
        "release": release,
        "source_tree_sha256": source_digest,
        "profile": str(PROFILE.relative_to(ROOT)),
        "predicates_total": len(states),
        "software_ready": software_ready,
        # ЩО САМЕ МІРЯЄ ЦЕ ЧИСЛО. `software_ready = not missing`, а `missing` — оголошені
        # `software_artifacts`, які не проходять `is_file()`. Зміст файла, його версія і
        # здатність виконатись НЕ читаються. Незалежний верифікатор 06.09.2026 назвав це
        # прямо: «14/14 означає буквально файли на місці». Поле нижче стоїть у самому
        # звіті, бо читач бачить ЗВІТ, а не цей рядок коду, і `14/14` без пояснення
        # читається як готовність підсистеми.
        "software_ready_means": (
            "оголошені software_artifacts проходять is_file(); зміст, версія і здатність "
            "виконатись не перевіряються"
        ),
        "externally_satisfied": externally_satisfied,
        "production_satisfied": production_satisfied,
        "software_readiness_percent": round(software_ready / len(states) * 100.0, 6),
        "external_completion_percent": round(externally_satisfied / len(states) * 100.0, 6),
        "production_completion_percent": round(production_satisfied / len(states) * 100.0, 6),
        "states": [state.as_dict() for state in states],
        "interpretation": (
            "Software readiness and external production proof are deliberately separate. "
            "A predicate is production-satisfied only when both are true."
        ),
    }


#: What this tree has already proved. External proof is expensive to obtain and trivial to
#: lose: a gate file is bound to the source digest it was produced against, so any later
#: commit unbinds it silently. Recording the count makes losing it a failure instead of a
#: number nobody reads. Raising it is what closing a predicate looks like in the diff.
FLOOR = ROOT / "config/assurance/production-predicate-floor.json"


def _floor() -> int:
    """The recorded floor, or a refusal. Never a silent zero.

    Returning 0 for a missing or malformed file made the ratchet disappear exactly when it
    was tampered with: `production_satisfied: "14"` and `rm` of the file both produced
    exit 0. A ratchet that vanishes under attack is decoration.
    """
    if not FLOOR.is_file():
        raise SystemExit(
            f"{FLOOR.relative_to(ROOT)} is missing — the external-proof ratchet cannot be "
            "read, and a floor that disappears when deleted is not a floor"
        )
    value = _json(FLOOR).get("production_satisfied")
    if not isinstance(value, int) or isinstance(value, bool):
        raise SystemExit(
            f"{FLOOR.relative_to(ROOT)}: production_satisfied is {value!r}, not an integer — "
            'a string like "14" compares against nothing and lifts the ratchet in silence'
        )
    return value


#: Контексти, у яких цей гейт може виносити вирок. Оголошення контексту НЕ є дозволом:
#: нижче він звіряється з ВИМІРЯНОЮ поверхнею доказу, і обидва напрямки розбіжності —
#: відмова. Клас узятий із `validate_repository.py --context`, де він уже означений.
PRODUCTION_EVIDENCE = "PRODUCTION_EVIDENCE"
SOURCE_CHECKOUT = "SOURCE_CHECKOUT"


def evidence_surface(gate_dir: Path) -> int:
    """Скільки файлів зовнішніх гейтів лежить на цьому дереві.

    Це ВИМІР, а не оголошення. Раннер CI не має `var/` взагалі: там нуль, і підлога
    зовнішнього доказу там невимірювана. Локальне дерево має їх чотирнадцять.
    """
    return sum((gate_dir / name).is_file() for name in GATE_FILES.values())


def context_problem(context: str, surface: int) -> str | None:
    """Розбіжність між ОГОЛОШЕНИМ контекстом і ВИМІРЯНОЮ поверхнею.

    Виміряно 06.09.2026: підлогу 7 було піднято над доказом, що живе лише в
    ігнорованому `var/`, і той самий скрипт у CI бачив нуль закриттів. Джоба
    `repository:validate` стала непрохідною за побудовою — вічний UNKNOWN, а не
    очікування. Лік не в тому, щоб опустити підлогу: він у тому, щоб контекст був
    названий і НЕ МІГ бути названий хибно.
    """
    if context == SOURCE_CHECKOUT and surface:
        return (
            f"контекст оголошено як {SOURCE_CHECKOUT}, але {surface} файлів зовнішніх "
            "гейтів лежать на цьому дереві: підлога тут вимірювана й мусить бути "
            "застосована. Оголошення чекауту над наявним доказом — обхід ратчета"
        )
    if context == PRODUCTION_EVIDENCE and not surface:
        return (
            f"контекст {PRODUCTION_EVIDENCE}, а поверхні зовнішнього доказу немає жодним "
            f"файлом у var/production: вирок про підлогу НЕВИМІРЮВАНИЙ, а невимірюване "
            f"не є проходженням. Для дерева без доказу оголоси --context {SOURCE_CHECKOUT}"
        )
    return None


def floor_failures(payload: dict[str, Any], context: str, surface: int) -> list[str]:
    """Вироки цього гейта. Готовність ПЗ міряється завжди; підлога — лише де вимірювана."""
    failures: list[str] = []
    if payload["software_ready"] != payload["predicates_total"]:
        failures.append(f"software_ready {payload['software_ready']}/{payload['predicates_total']}")
    problem = context_problem(context, surface)
    if problem:
        failures.append(problem)
        return failures
    if context == SOURCE_CHECKOUT:
        return failures
    floor = _floor()
    if payload["production_satisfied"] < floor:
        # Measured 2026-08-29: two predicates were closed against source digest 24ead5ea and
        # the next commit moved the tree to 040321ed. Both gate files stayed on disk, both
        # reported gate_source_bound false, externally_satisfied fell to 0 — and this script
        # still exited 0, because it only ever looked at software readiness.
        failures.append(
            f"production_satisfied {payload['production_satisfied']} is below the recorded "
            f"floor of {floor}: external proof was unbound by a later commit, not withdrawn "
            "on purpose. Re-run the gate that produced it against this tree."
        )
    return failures


def selftest() -> int:
    """Негативний контроль на сам контекст: обидва хибні оголошення мусять відмовляти."""
    cases = [
        (SOURCE_CHECKOUT, 14, True, "чекаут над наявним доказом"),
        (SOURCE_CHECKOUT, 0, False, "чекаут без доказу"),
        (PRODUCTION_EVIDENCE, 0, True, "доказовий контекст над порожнім деревом"),
        (PRODUCTION_EVIDENCE, 14, False, "доказовий контекст над доказом"),
    ]
    bad = [
        name
        for context, surface, refuse, name in cases
        if bool(context_problem(context, surface)) is not refuse
    ]
    ready = {"software_ready": 3, "predicates_total": 3, "production_satisfied": 0}
    if floor_failures(ready, SOURCE_CHECKOUT, 0):
        bad.append("чекаут із готовим ПЗ не мусить падати на підлозі зовнішнього доказу")
    if not floor_failures({**ready, "software_ready": 2}, SOURCE_CHECKOUT, 0):
        bad.append("невистачена готовність ПЗ мусить падати і в чекауті")
    for name in bad:
        print(f"  x {name}", file=sys.stderr)
    print(
        json.dumps(
            {
                "selftest": "korpus.production-hard-predicates.context",
                "cases": len(cases) + 2,
                "failures": bad,
            },
            ensure_ascii=False,
        )
    )
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--context", choices=(PRODUCTION_EVIDENCE, SOURCE_CHECKOUT), default=PRODUCTION_EVIDENCE
    )
    # Звіт мусить лишатись СВІЖИМ навіть коли підлога не тримає: `generate_release_truth.py`
    # читає його, щоб СКАЗАТИ, чого бракує. Виміряно 06.09.2026 — реєстр блокерів не міг
    # бути перезнятий саме тому, що блокери є, і CI падала на доказі, старшому за дерево.
    # Вирок про підлогу від цього не зникає: його виносять `validate` і `release`.
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    payload = build()
    surface = evidence_surface(ROOT / "var/production")
    payload["evidence_surface_files"] = surface
    payload["context"] = args.context
    out = ROOT / "reports/PRODUCTION_HARD_PREDICATES.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    failures = floor_failures(payload, args.context, surface)
    for failure in failures:
        print(f"  x {failure}", file=sys.stderr)
    if args.report_only:
        return 0
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
