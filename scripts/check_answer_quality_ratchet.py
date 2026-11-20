#!/usr/bin/env python3
"""Дві межі якості відповідей, і жодну не можна зсунути мовчки.

Ратчет на ОДНІЙ осі безглуздий: систему, що відповідає на все, і систему, що не
відповідає ні на що, розрізняє лише пара чисел. Тому тут дві межі протилежного знаку:

    in_corpus_answered_rate   ПІДЛОГА  — скільки своїх питань система ще тягне
    out_of_corpus_answered_rate СТЕЛЯ  — скільки чужих вона ще впускає

Виміряно 31.08.2026 на живому розгортанні: 0.95 і 0.20. До підняття порогу покриття
друга вісь була 0.85 — сімнадцять чужих питань із двадцяти під зеленим вироком.

UNKNOWN не є PASS: звіт, у якому хоч один кейс не дійшов до сервера, не судиться
взагалі — інакше мережева відмова читалася б як ідеальна стриманість.

Коди виходу: 0 — у межах · 1 — межу порушено · 2 — судити нема чого.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from answer_quality_validation import validation_problems
from evaluation_json import strict_json

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/operations/answer-quality-ratchet.json"
REPORT = ROOT / "var/boundary-eval.json"
MIN_REASON = 20


def problems(report: dict[str, Any], config: dict[str, Any]) -> list[str]:
    found = validation_problems(report, config)
    if found:
        return found
    if report["set_digest"] != config["measured"]["set_digest"]:
        found.append("набір питань не той, на якому записані межі — числа непорівнянні")
    floor = config["floors"]["in_corpus_answered_rate"]
    ceiling = config["ceilings"]["out_of_corpus_answered_rate"]
    inside = report.get("in_corpus", {}).get("rate")
    outside = report.get("out_of_corpus", {}).get("rate")
    if inside < floor:
        found.append(f"своїх питань відповідає {inside:.2f}, підлога {floor:.2f}")
    if outside > ceiling:
        found.append(f"чужих питань впускає {outside:.2f}, стеля {ceiling:.2f}")
    return found


def selftest() -> int:
    config: dict[str, Any] = {
        "schema": "korpus.answer-quality-ratchet.v1",
        "measured": {
            "set_digest": "12cef2e250cba405626017a186b69817f152490f1ccfc73f56a4f38ce614b5ea",
            "in_corpus_answered_rate": 0.95,
            "out_of_corpus_answered_rate": 0.2,
        },
        "floors": {"in_corpus_answered_rate": 0.9},
        "ceilings": {"out_of_corpus_answered_rate": 0.25},
        "case_counts": {"in_corpus": 20, "out_of_corpus": 20},
        "relaxed": [],
    }
    good: dict[str, Any] = {
        "schema": "korpus.domain-boundary-eval.v1",
        "status": "MEASURED",
        "set_digest": config["measured"]["set_digest"],
        "unreachable": [],
        "in_corpus": {"answered": 19, "judged": 20, "rate": 0.95},
        "out_of_corpus": {"answered": 4, "judged": 20, "rate": 0.2},
    }
    cases: list[tuple[str, dict[str, Any], dict[str, Any], bool]] = [
        ("чистий стан приймається", good, config, False),
        (
            "своїх питань стало менше",
            {**good, "in_corpus": {"answered": 17, "judged": 20, "rate": 0.85}},
            config,
            True,
        ),
        (
            "чужих питань стало більше",
            {**good, "out_of_corpus": {"answered": 6, "judged": 20, "rate": 0.3}},
            config,
            True,
        ),
        ("сервер не відповів — не вимір", {**good, "status": "UNKNOWN"}, config, True),
        ("інший набір питань", {**good, "set_digest": "deadbeefdeadbeef"}, config, True),
        ("частки немає", {**good, "in_corpus": {"rate": None}}, config, True),
        (
            "послаблення без причини",
            good,
            {**config, "relaxed": [{"axis": "in_corpus_answered_rate", "reason": "-"}]},
            True,
        ),
        (
            "послаблення з причиною приймається",
            good,
            {
                **config,
                "relaxed": [
                    {
                        "axis": "in_corpus_answered_rate",
                        "reason": "корпус звужено до публічної вибірки, частина питань більше не має джерела",
                    }
                ],
            },
            False,
        ),
    ]
    failures = [
        name
        for name, report, cfg, must_reject in cases
        if bool(problems(report, cfg)) != must_reject
    ]
    print(json.dumps({"selftest": len(cases), "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.report.is_file():
        print(
            json.dumps({"status": "UNKNOWN", "reason": f"немає {args.report}"}, ensure_ascii=False)
        )
        return 2
    report = strict_json(args.report.read_bytes())
    config = strict_json(CONFIG.read_bytes())
    found = problems(report, config)
    print(
        json.dumps(
            {"status": "FAIL" if found else "PASS", "problems": found}, ensure_ascii=False, indent=2
        )
    )
    return 1 if found else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        print(
            json.dumps(
                {"status": "ERROR", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False
            )
        )
        raise SystemExit(2) from error
