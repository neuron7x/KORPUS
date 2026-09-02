#!/usr/bin/env python3
"""Ізольований відтворюваний вимір `diversify_evidence`: розподіл, не одне число.

ЧОМУ ЦЕЙ ХАРНЕС ІСНУЄ. Порівняння двох редакцій послідовними прогонами не відрізняє
зміну коду від дрейфу машини. Виміряно 02.09.2026: винос згортання в окрему одиницю
«показав» +3..6 % у трьох випадках, і саме такий порядок має дрейф між прогонами,
рознесеними на хвилини. Висновок «стало гірше» був би зроблений із шуму.

Тому тут:
  * дві редакції живуть В ОДНОМУ ПРОЦЕСІ й міряються ЧЕРГУВАННЯМ A,B,A,B — дрейф лягає
    на обидві однаково;
  * вхід детермінований (фіксоване зерно), тож два прогони харнеса порівнянні між собою;
  * зберігаються СИРІ відліки, а не лише зведення: p50 без n і без розкиду не є виміром;
  * прогрів окремо від виміру: перший прогін платить за холодний кеш і не належить
    розподілу.

ЩО ЦЕ НЕ Є. Це не вимір продукту: він міряє одну функцію на синтетично зібраних
кандидатах, а не наскрізну відповідь. Перенесення числа звідси на латентність системи
було б підміною предмета.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.retrieval import (  # noqa: E402
    AUTHORITY_PRIOR,
    authority_tier,
    authority_tier_floor,
    diversify_evidence,
    subject_rank,
)
from korpus.application.retrieval_math import character_ngrams, jaccard  # noqa: E402
from korpus.domain.models import (  # noqa: E402
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    RetrievedEvidence,
)

_WORDS = ("варта", "наказ", "командир", "підрозділ", "зброя", "статут", "служба", "пост")


def build_case(count: int, versions: int, seed: int) -> list[RetrievedEvidence]:
    """Детермінований вхід: те саме зерно дає той самий набір на будь-якій машині."""
    rng = random.Random(seed)
    items: list[RetrievedEvidence] = []
    for index in range(count):
        version_index = index % versions
        document_id = UUID(int=version_index)
        version_id = UUID(int=10_000 + version_index)
        text = " ".join(rng.choice(_WORDS) for _ in range(rng.randint(40, 160)))
        items.append(
            RetrievedEvidence(
                document=DocumentRecord(
                    id=document_id,
                    canonical_title=f"д{version_index}",
                    corpus_id="c",
                    issuer="i",
                    jurisdiction="UA",
                    document_type="doctrine",
                    access_tier=AccessTier.PUBLIC,
                    classification=Classification.PUBLIC,
                ),
                version=DocumentVersionRecord(
                    id=version_id,
                    document_id=document_id,
                    revision="1",
                    source_hash=f"{version_index:064x}",
                    object_key=f"o{version_index}",
                    mime_type="text/plain",
                    authority=AuthorityClass.OFFICIAL_UA,
                ),
                span=EvidenceSpanRecord(
                    id=UUID(int=20_000 + index), version_id=version_id, ordinal=index, text=text
                ),
                score=max(0.0, 1.0 - index / (count + 1)),
                query_coverage=0.5,
                rank=index + 1,
            )
        )
    return items


def reference_diversify(
    ranked: list[RetrievedEvidence], *, limit: int, diversity_lambda: float, per_version_cap: int
) -> list[RetrievedEvidence]:
    """Редакція З ПЕРЕРАХУНКОМ З НУЛЯ — те, що було до лінивого згортання."""
    tier_floor = authority_tier_floor(ranked, 0.0)
    selected: list[RetrievedEvidence] = []
    remaining = list(ranked)
    version_counts: defaultdict[str, int] = defaultdict(int)
    grams = {str(item.span.id): character_ngrams(item.span.text) for item in ranked}
    while remaining and len(selected) < limit:
        admissible = [
            item for item in remaining if version_counts[str(item.version.id)] < per_version_cap
        ]
        if not admissible:
            break

        def utility(item: RetrievedEvidence) -> tuple[float, float, float, float, str, int]:
            redundancy = max(
                (
                    jaccard(grams[str(item.span.id)], grams[str(other.span.id)])
                    for other in selected
                ),
                default=0.0,
            )
            return (
                subject_rank(item, frozenset()),
                authority_tier(item, AUTHORITY_PRIOR, tier_floor),
                diversity_lambda * item.score - (1 - diversity_lambda) * redundancy,
                item.score,
                item.version.source_hash,
                -item.span.ordinal,
            )

        winner = max(admissible, key=utility)
        selected.append(winner)
        version_counts[str(winner.version.id)] += 1
        remaining.remove(winner)
    return [item.model_copy(update={"rank": rank}) for rank, item in enumerate(selected, start=1)]


def _distribution(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)

    def at(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]

    return {
        "n": len(ordered),
        "p50_ms": round(at(0.50) * 1000, 3),
        "p95_ms": round(at(0.95) * 1000, 3),
        "p99_ms": round(at(0.99) * 1000, 3),
        "min_ms": round(ordered[0] * 1000, 3),
        "mean_ms": round(statistics.fmean(ordered) * 1000, 3),
        "stdev_ms": round(statistics.pstdev(ordered) * 1000, 3) if len(ordered) > 1 else 0.0,
    }


def measure(case: list[RetrievedEvidence], rounds: int, warmup: int) -> dict[str, Any]:
    """Чергування A,B,A,B в одному процесі. Прогрів не входить у розподіл."""
    variants = {
        "current": lambda: diversify_evidence(case, limit=8, per_version_cap=1),
        "reference": lambda: reference_diversify(
            case, limit=8, diversity_lambda=0.82, per_version_cap=1
        ),
    }
    for _ in range(warmup):
        for run in variants.values():
            run()
    samples: dict[str, list[float]] = {name: [] for name in variants}
    outputs: dict[str, list[str]] = {}
    for _ in range(rounds):
        for name, run in variants.items():
            started = time.perf_counter()
            result = run()
            samples[name].append(time.perf_counter() - started)
            outputs[name] = [f"{i.rank}:{i.span.id}" for i in result]
    identical = outputs["current"] == outputs["reference"]
    report: dict[str, Any] = {name: _distribution(values) for name, values in samples.items()}
    report["identical_output"] = identical
    report["raw_ms"] = {
        name: [round(v * 1000, 4) for v in values] for name, values in samples.items()
    }
    base = report["reference"]["p50_ms"]
    report["p50_change_percent"] = (
        round((report["current"]["p50_ms"] - base) / base * 100, 1) if base else None
    )
    return report


def selftest() -> int:
    """Негативні контролі на сам харнес."""
    case = build_case(count=24, versions=6, seed=1)
    twin = build_case(count=24, versions=6, seed=1)
    if [i.span.text for i in case] != [i.span.text for i in twin]:
        print(
            json.dumps({"selftest": "FAIL", "case": "вхід не детермінований"}, ensure_ascii=False)
        )
        return 1
    if [i.span.text for i in case] == [i.span.text for i in build_case(24, 6, seed=2)]:
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "зерно ні на що не впливає"}, ensure_ascii=False
            )
        )
        return 1
    produced = [str(i.span.id) for i in diversify_evidence(case, limit=8, per_version_cap=1)]
    expected = [
        str(i.span.id)
        for i in reference_diversify(case, limit=8, diversity_lambda=0.82, per_version_cap=1)
    ]
    if produced != expected:
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "еталон розійшовся з чинним"}, ensure_ascii=False
            )
        )
        return 1
    if len(_distribution([0.001, 0.002, 0.003])["n"] * [0]) != 3:
        print(
            json.dumps({"selftest": "FAIL", "case": "розподіл губить відліки"}, ensure_ascii=False)
        )
        return 1
    print(json.dumps({"selftest": "PASS", "negative_controls": 4}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=15)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--candidates", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    report: dict[str, Any] = {
        "schema": "korpus.diversify-benchmark.v1",
        "seed": arguments.seed,
        "candidates": arguments.candidates,
        "rounds": arguments.rounds,
        "warmup": arguments.warmup,
        "cases": {},
    }
    for label, versions in (("вузька", 1), ("середня", 10), ("широка", 20)):
        case = build_case(arguments.candidates, versions, arguments.seed + versions)
        report["cases"][label] = {
            "versions": versions,
            **measure(case, arguments.rounds, arguments.warmup),
        }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.out:
        arguments.out.write_text(text + "\n", encoding="utf-8")
    summary = {
        label: {
            "versions": data["versions"],
            "identical_output": data["identical_output"],
            "reference_p50_ms": data["reference"]["p50_ms"],
            "current_p50_ms": data["current"]["p50_ms"],
            "p50_change_percent": data["p50_change_percent"],
        }
        for label, data in report["cases"].items()
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
