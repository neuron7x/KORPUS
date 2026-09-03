#!/usr/bin/env python3
"""Зібрати машинно-перевірну частину TEVV з ВИМІРІВ, які вже робить це дерево.

Профіль TEVV вимагає золотої розмітки двома анотаторами з узгодженістю — це робота
людей, і підробляти її заборонено. Але не весь TEVV такий: там, де очікуваний
результат ВИВОДИТЬСЯ з фактів корпусу й системи, судження людини не потрібне зовсім.
Цей звіт розділяє ці дві частини й ніколи не видає першу за другу.

Нового вимірювача тут немає ЖОДНОГО. Кожен клас показує на існуючий артефакт, його
число й підлогу, оголошену конфігом. Якщо артефакт не прив'язаний до цього дерева —
клас виходить NOT_MEASURED, а не зникає.

    build_machine_tevv.py [--selftest] [--out ФАЙЛ]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import compute_source_digest  # noqa: E402

NOT_MEASURED = "NOT_MEASURED"

#: (клас, звіт, шлях до числа, підлога, звідки підлога). Підлоги НЕ вигадані тут:
#: усі, крім двох, читаються з `config/operations/answer-axes.json`, і два останні —
#: з профілю TEVV. Жодне число тут не пом'якшене.
CLASSES: tuple[dict[str, Any], ...] = (
    {
        "class": "supported_retrieval",
        "question": "чи система відповідає там, де відповідь у корпусі є",
        "report": "var/pilot/reference-eval-pg.json",
        "path": ["retrieval_effectiveness", "supported_answer_rate"],
        "floor": 0.92,
        "floor_from": "config/operations/answer-axes.json:reference.floor",
    },
    {
        "class": "abstention_out_of_domain",
        "question": "чи система мовчить там, де відповіді в корпусі немає",
        "report": "var/pilot/boundary-eval-pg.json",
        "path": ["out_of_corpus", "rate"],
        "ceiling": 0.25,
        "floor_from": "config/operations/answer-quality-ratchet: стеля чужих питань",
    },
    {
        "class": "in_domain_answer_rate",
        "question": "чи система не мовчить там, де мусить відповісти",
        "report": "var/pilot/boundary-eval-pg.json",
        "path": ["in_corpus", "rate"],
        "floor": 0.90,
        "floor_from": "config/operations/answer-quality-ratchet: підлога своїх питань",
    },
    {
        "class": "subject_disambiguation",
        "question": "чи відповідь про того, кого спитали",
        "report": "var/pilot/subject-precision-pg.json",
        "field": "top1_subject_precision",
        "floor": 0.956,
        "floor_from": "config/operations/answer-axes.json:subject.floor",
    },
    {
        "class": "citation_identity",
        "question": "чи цитата належить джерелу, яке названо",
        "report": "var/pilot/subject-precision-pg.json",
        "field": "any_citation_subject_recall",
        "floor": 1.0,
        "floor_from": "вимір 01.09.2026: 1.0000, нижче не приймалось",
    },
)


def _json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _dig(payload: dict[str, Any], keys: list[str]) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def measure(root: Path = ROOT) -> dict[str, Any]:
    results = []
    for spec in CLASSES:
        report = _json(root / str(spec["report"]))
        if report is None:
            results.append(
                {
                    **{k: spec[k] for k in ("class", "question", "report")},
                    "state": NOT_MEASURED,
                    "why": "звіту немає",
                }
            )
            continue
        raw = (
            _dig(report, list(spec["path"]))
            if "path" in spec
            else report.get(str(spec.get("field")))
        )
        if raw is None:
            results.append(
                {
                    **{k: spec[k] for k in ("class", "question", "report")},
                    "state": NOT_MEASURED,
                    "why": "поля немає у звіті",
                }
            )
            continue
        value = float(raw)
        if "ceiling" in spec:
            meets = value <= float(spec["ceiling"])
            bound = {"ceiling": spec["ceiling"]}
        else:
            meets = value >= float(spec["floor"])
            bound = {"floor": spec["floor"]}
        results.append(
            {
                "class": spec["class"],
                "question": spec["question"],
                "report": spec["report"],
                "value": value,
                **bound,
                "bound_from": spec["floor_from"],
                "state": "PASS" if meets else "FAIL",
            }
        )
    unmeasured = [r for r in results if r["state"] == NOT_MEASURED]
    failed = [r for r in results if r["state"] == "FAIL"]
    return {
        "schema": "korpus.machine-tevv.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "source_digest": compute_source_digest(root),
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "scope": (
            "МАШИННО-ПЕРЕВІРНА частина TEVV: очікуване виводиться з фактів корпусу й "
            "системи. Судження предметної людини сюди НЕ входить і не імітується."
        ),
        "human_domain_part": {
            "status": "HUMAN_DOMAIN_REVIEW_REQUIRED",
            "why": (
                "Профіль вимагає ≥200 запитів із розміткою ДВОМА анотаторами, ≥40 сліпих "
                "холдаут-запитів, узгодженість Cohen's kappa ≥0.6 і суддю, який не є "
                "жодним з анотаторів. Два контексти LLM не є двома незалежними "
                "предметними анотаторами."
            ),
            "policy": "apps/api/src/korpus/application/gold_annotation.py",
        },
        "classes": results,
        "status": "PASS" if not failed and not unmeasured else "FAIL",
        "unmeasured": [r["class"] for r in unmeasured],
        "failed": [r["class"] for r in failed],
    }


def selftest() -> int:
    """Негативні контролі: жодна відсутність не сміє читатись як згода."""
    import tempfile

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as raw:
        sub = Path(raw)
        empty = measure(sub)
        if empty["status"] != "FAIL":
            failures.append(f"порожнє дерево дало {empty['status']}, а не FAIL")
        if len(empty["unmeasured"]) != len(CLASSES):
            failures.append("не всі класи стали NOT_MEASURED на порожньому дереві")
        # значення нижче підлоги мусить давати FAIL
        (sub / "var/pilot").mkdir(parents=True, exist_ok=True)
        (sub / "var/pilot/subject-precision-pg.json").write_text(
            json.dumps({"top1_subject_precision": 0.5, "any_citation_subject_recall": 1.0}),
            encoding="utf-8",
        )
        low = measure(sub)
        if "subject_disambiguation" not in low["failed"]:
            failures.append("значення нижче підлоги не дало FAIL")
        if "citation_identity" in low["failed"]:
            failures.append("значення НА підлозі помилково дало FAIL")
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
    parser.add_argument("--out", type=Path, default=ROOT / "reports/MACHINE_TEVV.json")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    report = measure()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
