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

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/operations/answer-quality-ratchet.json"
REPORT = ROOT / "var/boundary-eval.json"
MIN_REASON = 20


def problems(report: dict[str, Any], config: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for entry in config.get("relaxed", []):
        reason = str(entry.get("reason", "")).strip()
        if len(reason) < MIN_REASON:
            found.append(
                f"послаблення {entry.get('axis')!r} без записаної причини — межа, "
                "зсунута мовчки, не відрізняється від межі, якої ніколи не було"
            )
    if report.get("status") != "MEASURED":
        return [*found, f"звіт не є виміром: status={report.get('status')!r}"]
    if report.get("set_digest", "")[:16] != config["measured"]["set_digest"][:16]:
        found.append("набір питань не той, на якому записані межі — числа непорівнянні")
    floor = config["floors"]["in_corpus_answered_rate"]
    ceiling = config["ceilings"]["out_of_corpus_answered_rate"]
    inside = report.get("in_corpus", {}).get("rate")
    outside = report.get("out_of_corpus", {}).get("rate")
    if inside is None or outside is None:
        return [*found, "у звіті немає частки для однієї зі страт — судити нема чого"]
    if inside < floor:
        found.append(f"своїх питань відповідає {inside:.2f}, підлога {floor:.2f}")
    if outside > ceiling:
        found.append(f"чужих питань впускає {outside:.2f}, стеля {ceiling:.2f}")
    return found


def selftest() -> int:
    config: dict[str, Any] = {
        "measured": {"set_digest": "12cef2e250cba405"},
        "floors": {"in_corpus_answered_rate": 0.9},
        "ceilings": {"out_of_corpus_answered_rate": 0.25},
        "relaxed": [],
    }
    good: dict[str, Any] = {
        "status": "MEASURED",
        "set_digest": "12cef2e250cba405ff",
        "in_corpus": {"rate": 0.95},
        "out_of_corpus": {"rate": 0.2},
    }
    cases: list[tuple[str, dict[str, Any], dict[str, Any], bool]] = [
        ("чистий стан приймається", good, config, False),
        ("своїх питань стало менше", {**good, "in_corpus": {"rate": 0.85}}, config, True),
        ("чужих питань стало більше", {**good, "out_of_corpus": {"rate": 0.3}}, config, True),
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
    report = json.loads(args.report.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
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
