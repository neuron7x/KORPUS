#!/usr/bin/env python3
"""Чи вміє система відрізнити своє питання від чужого — і чи не розучилась.

Заморожений еталон дерева цього не міряє за побудовою: його запити складені з
речень-доказів ТОГО САМОГО корпусу, тож питання поза доменом там не буває. Виміряно
31.08.2026 на живому розгортанні: при порозі покриття 0.25 система відповідала на
**17 із 20** свідомо чужих питань під зеленим вироком — «як налаштувати гаманець
Ethereum» отримувало обов'язки техніка БпАК.

Дві осі, і вони НЕ взаємозамінні:

    in_corpus_answered      скільки своїх питань отримали відповідь  (більше — краще)
    out_of_corpus_answered  скільки чужих питань отримали відповідь  (менше — краще)

Одну без другої рухати легко й безглуздо: гейт, що відхиляє все, дає ідеальну другу
вісь і нульову першу. Тому ратчет тримає обидві, і послаблення кожної вимагає причини.

Транспортна відмова НЕ є вимірюванням: кейс, до якого не дійшов запит, не потрапляє в
жоден знаменник, а звіт стає UNKNOWN. `0.0` і «не міряли» в теці доказів виглядають
однаково, і саме так народжується хибна підлога.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/datasets/domain_boundary.jsonl"
META = ROOT / "evals/datasets/domain_boundary.meta.json"


def ask(base: str, question: str, token: str, timeout: float) -> dict[str, Any] | None:
    request = urllib.request.Request(
        f"{base.rstrip('/')}/v1/answers",
        data=json.dumps({"text": question}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload: dict[str, Any] = json.load(response)
            return payload
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def evaluate(rows: list[dict[str, Any]], base: str, token: str, timeout: float) -> dict[str, Any]:
    strata: dict[str, dict[str, int]] = {
        "in_corpus": {"answered": 0, "judged": 0},
        "out_of_corpus": {"answered": 0, "judged": 0},
    }
    unreachable: list[str] = []
    for row in rows:
        payload = ask(base, row["query"], token, timeout)
        if payload is None:
            unreachable.append(row["id"])
            continue
        bucket = strata[row["stratum"]]
        bucket["judged"] += 1
        bucket["answered"] += int(payload.get("status") == "answered")

    def rate(bucket: dict[str, int]) -> float | None:
        # None, не 0.0: частка над нулем випадків — це відсутність виміру, а 0.0
        # читається як виміряна підлога.
        return None if not bucket["judged"] else bucket["answered"] / bucket["judged"]

    body = DATASET.read_text(encoding="utf-8")
    return {
        "schema": "korpus.domain-boundary-eval.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "base": base,
        "set_digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "status": "UNKNOWN" if unreachable else "MEASURED",
        "unreachable": unreachable,
        "in_corpus": {**strata["in_corpus"], "rate": rate(strata["in_corpus"])},
        "out_of_corpus": {**strata["out_of_corpus"], "rate": rate(strata["out_of_corpus"])},
        "cannot_judge": json.loads(META.read_text(encoding="utf-8"))["cannot_judge"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8081/api")
    parser.add_argument("--token", default="")
    parser.add_argument("--out", type=Path, default=ROOT / "var/boundary-eval.json")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    report = evaluate(rows, args.base, args.token, args.timeout)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "MEASURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
