#!/usr/bin/env python3
"""Структурна незалежність замінює організаційну ЛИШЕ поки її замінники виконані.

Owner оголосив 03.09.2026: зовнішнього незалежного оцінювача в проєкті немає й він не є
доступним ресурсом. Тримати його блокуючою умовою означало б мати гейт, якого ніхто не
може пройти, — а такий гейт прибирають, а не задовольняють.

Заміна законна рівно тому, що вона НЕ послаблення. Зникла умова, якої не можна
задовольнити наявними ресурсами; жодна умова, яку МОЖНА задовольнити, не знята. Цей
гейт існує, щоб друге твердження було перевіреним, а не обіцяним: якщо структурний
замінник не виконаний, реліз блокує ВІН, і блокує так само твердо.

## Чого цей гейт НЕ робить

Він не звітує зовнішню незалежність як пройдену. Її стан лишається `NOT_PERFORMED`, і це
видно в кожному звіті. Невиконане не стає виконаним від того, що перестало блокувати —
інакше ми б відтворили рівно ту ваду, проти якої КОРПУС і будується.

    verify_assurance_model.py [--selftest] [--out ФАЙЛ]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "config/governance/assurance-model.json"

#: Стани замінника. `NOT_SATISFIED` блокує; `NOT_MEASURED` теж блокує, бо невимірене не
#: є виконаним. Розрізняються вони тим, що друге називає брак ВИМІРУ, а не брак факту.
SATISFIED, NOT_SATISFIED, NOT_MEASURED = "SATISFIED", "NOT_SATISFIED", "NOT_MEASURED"


def _json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _list(path: Path) -> list[Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, list) else None


def si1_executor_is_not_verifier(root: Path) -> tuple[str, str]:
    """Верифікацію виконав ІНШИЙ агент, ніж той, що робив зміну.

    Предикат, не правило в документі. Засвідчення мусить називати обидві сторони й
    кандидата; збіг сторін — відмова, а не формальність.
    """
    attestation = _json(root / "var/production/verifier-attestation.json")
    if attestation is None:
        return NOT_MEASURED, "засвідчення верифікатора відсутнє"
    executor = str(attestation.get("executor_agent") or "")
    verifier = str(attestation.get("verifier_agent") or "")
    candidate = str(attestation.get("candidate_commit") or "")
    if not executor or not verifier or not candidate:
        return NOT_SATISFIED, "засвідчення не називає обидві сторони й кандидата"
    if executor == verifier:
        return NOT_SATISFIED, f"виконавець і верифікатор — одна сторона: {executor}"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    ).stdout.strip()
    if candidate != head:
        return NOT_SATISFIED, f"засвідчення про {candidate[:8]}, а HEAD {head[:8]}"
    return SATISFIED, f"{verifier} перевірив роботу {executor} на {candidate[:8]}"


def si2_separate_context(root: Path) -> tuple[str, str]:
    attestation = _json(root / "var/production/verifier-attestation.json")
    if attestation is None:
        return NOT_MEASURED, "засвідчення верифікатора відсутнє"
    context = str(attestation.get("verifier_context") or "")
    if not context:
        return NOT_SATISFIED, "засвідчення не називає контексту верифікатора"
    if context == str(attestation.get("executor_context") or ""):
        return NOT_SATISFIED, "верифікатор працював у контексті виконавця"
    return SATISFIED, f"контекст верифікатора {context}"


def si3_adversarial(root: Path) -> tuple[str, str]:
    """Гейти мусять мати ДОВЕДЕНУ здатність відхилити."""
    liveness = _list(root / "var/liveness-all.json")
    if liveness is None:
        return NOT_MEASURED, "звіту про живість гейтів немає"
    if not liveness:
        return NOT_MEASURED, "звіт про живість порожній"
    # Очікуваний вирок береться з конфігу гейтів. Дефолт — ARMED; інше мусить нести
    # написану причину, інакше «очікувано червоний» став би способом зняти вимогу.
    expected: dict[str, str] = {}
    reasons: dict[str, str] = {}
    try:
        import yaml

        config = yaml.safe_load((root / "config/operations/gate-liveness.yaml").read_text("utf-8"))
        for gate in config.get("gates", ()):
            if gate.get("expected"):
                expected[str(gate["name"])] = str(gate["expected"])
                reasons[str(gate["name"])] = str(gate.get("expected_reason") or "")
    except (OSError, ImportError, ValueError):
        return NOT_MEASURED, "конфіг живості не прочитано — очікування невідомі"
    mismatched: list[str] = []
    unreasoned: list[str] = []
    for item in liveness:
        if not isinstance(item, dict):
            continue
        name = str(item.get("gate"))
        want = expected.get(name, "ARMED")
        if want != "ARMED" and len(reasons.get(name, "").strip()) < 40:
            unreasoned.append(name)
        if str(item.get("verdict")) != want:
            mismatched.append(f"{name}: {item.get('verdict')} замість {want}")
    if unreasoned:
        return NOT_SATISFIED, f"очікування без написаної причини: {unreasoned}"
    if mismatched:
        return NOT_SATISFIED, "; ".join(mismatched[:3])
    return SATISFIED, f"{len(liveness)} гейтів мають очікуваний вирок"


def si4_negative_controls(root: Path) -> tuple[str, str]:
    report = _json(root / "var/selftest-coverage.json")
    if report is None:
        return NOT_MEASURED, "звіту про покриття самоперевірками немає"
    if str(report.get("status")) != "PASS":
        return NOT_SATISFIED, f"покриття самоперевірками: {report.get('status')}"
    return SATISFIED, "кожен скрипт із --selftest виконується"


def si5_mutation(root: Path) -> tuple[str, str]:
    report = _json(root / "reports/MUTATION_FULL_CATALOGUE_CURRENT.json")
    if report is None:
        return NOT_MEASURED, "каталогу мутантів немає"
    survived, invalid = report.get("survived") or [], report.get("invalid") or []
    over = report.get("mutation_score_over_catalogue")
    if survived or invalid or over != 1.0:
        return NOT_SATISFIED, f"вижили {len(survived)}, invalid {len(invalid)}, score {over}"
    return SATISFIED, f"{report.get('killed')}/{report.get('mutants')} убито, знаменник цілий"


def si6_clean_room(root: Path) -> tuple[str, str]:
    report = _json(root / "var/clean-clone.json")
    if report is None:
        return NOT_MEASURED, "відтворення з чистого клону не виконувалось"
    if str(report.get("status")) != "PASS":
        return NOT_SATISFIED, f"відтворення: {report.get('status')}"
    return SATISFIED, "кандидат відтворюється з чистого клону"


def si7_ci_hard_gates(root: Path) -> tuple[str, str]:
    report = _json(root / "var/ci-mirror.json")
    if report is None:
        return NOT_MEASURED, "дзеркало локального й CI не виміряне"
    if str(report.get("status")) != "PASS":
        return NOT_SATISFIED, f"дзеркало CI: {report.get('status')}"
    return SATISFIED, "кожна ціль лану має відповідник у конвеєрі"


def si8_runtime_evidence(root: Path) -> tuple[str, str]:
    report = _json(root / "var/serving-freshness.json")
    if report is None:
        return NOT_MEASURED, "свіжість обслуговування не виміряна"
    if report.get("stale"):
        return NOT_SATISFIED, f"процеси, старші за код: {report.get('stale')}"
    return SATISFIED, "процеси, що обслуговують, несуть поточний код"


CHECKS = {
    "SI-1": si1_executor_is_not_verifier,
    "SI-2": si2_separate_context,
    "SI-3": si3_adversarial,
    "SI-4": si4_negative_controls,
    "SI-5": si5_mutation,
    "SI-6": si6_clean_room,
    "SI-7": si7_ci_hard_gates,
    "SI-8": si8_runtime_evidence,
}


def assess(root: Path = ROOT) -> dict[str, Any]:
    model = _json(MODEL)
    if model is None:
        return {
            "schema": "korpus.assurance-model.v1",
            "status": "FAIL",
            "detail": "моделі впевненості немає в дереві",
        }
    names = {item["id"]: item["name"] for item in model["structural_independence_substitutes"]}
    blocking = {
        item["id"] for item in model["structural_independence_substitutes"] if item["blocking"]
    }
    substitutes = {}
    for key, check in CHECKS.items():
        state, detail = check(root)
        substitutes[key] = {
            "name": names.get(key, key),
            "state": state,
            "detail": detail,
            "blocking": key in blocking,
        }
    unmet = sorted(k for k, v in substitutes.items() if v["blocking"] and v["state"] != SATISFIED)
    return {
        "schema": "korpus.assurance-model.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "model": model["model"],
        "release_authority": model["release_authority"]["holder"],
        # Стан зовнішньої незалежності виходить у КОЖЕН звіт і ніколи не є PASS.
        "external_independent_assurance": {
            "status": model["external_independent_assurance"]["status"],
            "blocking": model["external_independent_assurance"]["blocking"],
        },
        "substitutes": substitutes,
        "unmet_blocking_substitutes": unmet,
        "status": "PASS" if not unmet else "FAIL",
        "interpretation": (
            "Структурна незалежність замінює організаційну. Заміна дійсна лише поки кожен "
            "блокуючий замінник виконаний; невиконаний замінник блокує реліз так само твердо, "
            "як блокувала б відсутня зовнішня сторона. Зовнішня незалежність лишається "
            "NOT_PERFORMED і НЕ звітується як пройдена."
        ),
    }


def selftest() -> int:
    """Отрути: заміна не сміє бути тихим послабленням."""
    failures: list[str] = []
    same = {"executor_agent": "a", "verifier_agent": "a", "candidate_commit": "x"}
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "var/production").mkdir(parents=True)
        (root / "var/production/verifier-attestation.json").write_text(
            json.dumps(same), encoding="utf-8"
        )
        state, detail = si1_executor_is_not_verifier(root)
        if state != NOT_SATISFIED or "одна сторона" not in detail:
            failures.append(f"самозасвідчення не відхилено: {state} {detail}")
        state, _ = si2_separate_context(root)
        if state == SATISFIED:
            failures.append("контекст без оголошення визнано окремим")

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "var").mkdir(parents=True)
        for name, check in (
            ("SI-1", si1_executor_is_not_verifier),
            ("SI-5", si5_mutation),
            ("SI-6", si6_clean_room),
            ("SI-8", si8_runtime_evidence),
        ):
            state, _ = check(root)
            if state != NOT_MEASURED:
                failures.append(f"{name}: відсутній артефакт дав {state}, а не NOT_MEASURED")
        (root / "reports").mkdir(parents=True)
        (root / "reports/MUTATION_FULL_CATALOGUE_CURRENT.json").write_text(
            json.dumps(
                {
                    "survived": ["M1"],
                    "invalid": [],
                    "mutation_score_over_catalogue": 1.0,
                    "killed": 1,
                    "mutants": 2,
                }
            ),
            encoding="utf-8",
        )
        if si5_mutation(root)[0] != NOT_SATISFIED:
            failures.append("вижилий мутант не заблокував")

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
