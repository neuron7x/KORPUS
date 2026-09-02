#!/usr/bin/env python3
"""nDCG@10, MRR@10 і Recall@20 на замороженому еталонному наборі проти живого корпусу.

`CalibrationProfile` вимагає цих трьох чисел для `ranking_valid`, і поля під них існують
з першої версії схеми. Математика теж існує — `application/ranking_evaluation` рахує їх
повністю, з експоненційним виграшем і збереженням НАЙГІРШОГО запиту. Не існувало
водія: `JudgedQuery` не будував ніхто поза тестами, тобто ранжувальне плече профілю
жодного разу не бачило корпусу. Цей скрипт — рівно той водій і нічого більше; жодної
метрики він не рахує сам, щоб не з'явилась друга тотожність одного предмета.

ЩО САМЕ МІРЯЄТЬСЯ, І ЧОМУ САМЕ ТАК

Пул кандидатів — 256 прольотів за BM25 з FTS5, бо рівно стільки бачить бойовий добір
(`retrieval_candidate_budget`). Пул, зібраний інакше, міряв би іншу систему.

Релевантність двійкова й береться з мітки самого набору (`must_cite_one_of_if_answered`,
тотожність версії), а не з думки цього скрипта. Двійкові оцінки в nDCG — стандарт, і
вони НЕ завищують: ідеальний DCG рахується з тих самих оцінок.

Запит, чий пул не містить жодного релевантного прольоту, — це провал добору, а не
незручність. Він рахується НУЛЕМ і лишається в знаменнику. Викинути такі запити
означало б міряти якість ранжування там, де ранжувати вже нічого, і кожен провал
добору піднімав би оцінку. Обидва числа звітуються окремо, щоб різницю було видно.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.calibration import CalibrationProfile  # noqa: E402
from korpus.application.ranking_evaluation import (  # noqa: E402
    JudgedCandidate,
    JudgedQuery,
    evaluate_ranking,
)

DEFAULT_DATABASE = ROOT / "var/runtime/corpus-v6-20260807/korpus.db"
DEFAULT_REFERENCE = ROOT / "evals/datasets/reference.jsonl"
DEFAULT_OUT = ROOT / "var/ranking-eval.json"
#: Стільки кандидатів бачить бойовий добір. Число взяте звідти, не підібране тут.
DEFAULT_POOL = 256
_WORD = re.compile(r"[\w'’-]+", re.UNICODE)


def fts_expression(query: str) -> str:
    """Слова запиту як диз'юнкція фраз: лапки знімають синтаксис FTS з даних."""
    words = [word for word in _WORD.findall(query.lower()) if len(word) > 1]
    return " OR ".join('"' + word.replace('"', "") + '"' for word in words)


def _authority_prior(profile: CalibrationProfile) -> dict[str, float]:
    return {key.value: value for key, value in profile.authority_priors.items()}


def candidate_pool(
    connection: sqlite3.Connection, query: str, limit: int, priors: dict[str, float]
) -> list[tuple[str, str, float]]:
    expression = fts_expression(query)
    if not expression:
        return []
    rows = connection.execute(
        "SELECT s.text, s.version_id, v.authority "
        "FROM evidence_fts f "
        "JOIN evidence_spans s ON s.id = f.span_id "
        "JOIN document_versions v ON v.id = s.version_id "
        "WHERE evidence_fts MATCH ? ORDER BY bm25(evidence_fts) LIMIT ?",
        (expression, limit),
    ).fetchall()
    return [(text, version, priors.get(str(authority), 0.0)) for text, version, authority in rows]


def recall_ceiling(relevant_in_pool: int, cutoff: int = 20) -> float:
    """Найбільший Recall@20, ДОСЯЖНИЙ для запиту з такою кількістю релевантних.

    Метрика ділить влучання в топ-20 на кількість релевантних У ПУЛІ, а мітка набору
    двійкова на рівні ВЕРСІЇ — тож релевантними стають усі прольоти потрібного документа,
    інколи сотня. Тоді Recall@20 не може перевищити 20/N хоч би яким ідеальним було
    ранжування. Число їде разом із виміром саме тому, що без нього 0.52 проти порога 0.85
    читається як зламаний ранжувальник, а не як поріг, написаний для іншої зернистості.
    """
    return 1.0 if relevant_in_pool <= cutoff else cutoff / relevant_in_pool


def judged_queries(
    connection: sqlite3.Connection,
    cases: list[dict[str, Any]],
    limit: int,
    priors: dict[str, float],
) -> tuple[list[JudgedQuery], list[str], list[int]]:
    """Судимі запити, недосяжні (рахуються нулями) і кількість релевантних у кожному пулі."""
    built: list[JudgedQuery] = []
    unreachable: list[str] = []
    relevant_counts: list[int] = []
    for case in cases:
        wanted = set(case["must_cite_one_of_if_answered"])
        pool = candidate_pool(connection, case["query"], limit, priors)
        candidates = tuple(
            JudgedCandidate(
                text=text, relevance=1 if version in wanted else 0, authority_score=prior
            )
            for text, version, prior in pool
            if text.strip()
        )
        relevant = sum(1 for candidate in candidates if candidate.relevance > 0)
        if not relevant:
            unreachable.append(str(case["id"]))
            continue
        relevant_counts.append(relevant)
        built.append(
            JudgedQuery(query_id=str(case["id"]), query=case["query"], candidates=candidates)
        )
    return built, unreachable, relevant_counts


def measure(database: Path, reference: Path, limit: int) -> dict[str, Any]:
    cases = [
        row
        for row in (
            json.loads(line)
            for line in reference.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if row.get("kind") == "retrieval" and row.get("must_cite_one_of_if_answered")
    ]
    profile = CalibrationProfile(
        profile_id="ranking-measurement-defaults",
        dataset_sha256="0" * 64,
        accepted_samples=0,
        observed_errors=0,
        confidence_delta=0.05,
        risk_limit=0.05,
        minimum_score=0.18,
        minimum_query_coverage=0.5,
        minimum_support_score=0.18,
    )
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        built, unreachable, relevant_counts = judged_queries(
            connection, cases, limit, _authority_prior(profile)
        )
    finally:
        connection.close()
    total = len(cases)
    if not built:
        return {
            "status": "UNKNOWN",
            "reason": "жоден запит не має релевантного кандидата в пулі",
            "queries_in_set": total,
            "queries_without_relevant_candidate": len(unreachable),
        }
    metrics = evaluate_ranking(built, profile.retrieval_weights, profile.bm25_parameters)
    # Середнє по ВСЬОМУ наборі: недосяжні запити входять нулями. Це зважене середнє по
    # розбиттю, а не друга реалізація метрики — саме тому воно записане одним множником.
    reachable_share = metrics.evaluated_queries / total
    return {
        "status": "MEASURED",
        "queries_in_set": total,
        "queries_ranked": metrics.evaluated_queries,
        "queries_without_relevant_candidate": len(unreachable),
        "unreachable_ids": sorted(unreachable),
        "candidate_pool": limit,
        "on_ranked_queries": {
            "ndcg_at_10": round(metrics.ndcg_at_10, 6),
            "mrr_at_10": round(metrics.mrr_at_10, 6),
            "recall_at_20": round(metrics.recall_at_20, 6),
            "worst_ndcg_at_10": round(metrics.worst_ndcg_at_10, 6),
            "worst_reciprocal_rank_at_10": round(metrics.worst_reciprocal_rank_at_10, 6),
            "worst_recall_at_20": round(metrics.worst_recall_at_20, 6),
        },
        "on_the_whole_set": {
            "ndcg_at_10": round(metrics.ndcg_at_10 * reachable_share, 6),
            "mrr_at_10": round(metrics.mrr_at_10 * reachable_share, 6),
            "recall_at_20": round(metrics.recall_at_20 * reachable_share, 6),
        },
        "recall_at_20_is_bounded_by_the_labelling": {
            "relevant_per_pool_median": sorted(relevant_counts)[len(relevant_counts) // 2],
            "relevant_per_pool_max": max(relevant_counts),
            "queries_above_the_cutoff": sum(1 for count in relevant_counts if count > 20),
            "mean_achievable_recall_at_20": round(
                sum(recall_ceiling(count) for count in relevant_counts) / len(relevant_counts), 6
            ),
            "profile_floor": profile.minimum_recall_at_20,
            "queries_where_that_floor_is_reachable": sum(
                1
                for count in relevant_counts
                if recall_ceiling(count) >= profile.minimum_recall_at_20
            ),
        },
        "interpretation": (
            "`on_the_whole_set` — те, що належить у профіль: запит без релевантного "
            "кандидата в пулі рахується нулем, бо провал добору не сміє піднімати оцінку "
            "ранжування. `on_ranked_queries` показано поруч, щоб різницю було видно. "
            "Recall@20 звіряти ЛИШЕ з `mean_achievable_recall_at_20`: мітка двійкова на "
            "рівні версії, тож релевантними стають усі прольоти документа, і 20/N — стеля "
            "за побудовою, а не якість ранжування."
        ),
    }


def selftest() -> int:
    """Негативний контроль: недосяжний запит мусить ТИСНУТИ оцінку, а не зникати."""
    perfect = JudgedQuery(
        query_id="q1",
        query="alpha beta",
        candidates=(
            JudgedCandidate(text="alpha beta gamma", relevance=1),
            JudgedCandidate(text="zulu yankee", relevance=0),
        ),
    )
    profile_weights = CalibrationProfile(
        profile_id="selftest-defaults",
        dataset_sha256="0" * 64,
        accepted_samples=0,
        observed_errors=0,
        confidence_delta=0.05,
        risk_limit=0.05,
        minimum_score=0.18,
        minimum_query_coverage=0.5,
        minimum_support_score=0.18,
    )
    metrics = evaluate_ranking(
        [perfect], profile_weights.retrieval_weights, profile_weights.bm25_parameters
    )
    if metrics.ndcg_at_10 != 1.0:
        print(f"selftest FAIL: ідеальне ранжування дало {metrics.ndcg_at_10}", file=sys.stderr)
        return 1
    # Один досяжний із двох у наборі мусить дати рівно половину.
    share = metrics.evaluated_queries / 2
    if metrics.ndcg_at_10 * share != 0.5:
        print("selftest FAIL: недосяжний запит не тисне оцінку", file=sys.stderr)
        return 1
    if fts_expression('погано "лапки"') != '"погано" OR "лапки"':
        print("selftest FAIL: лапки з даних не знято", file=sys.stderr)
        return 1
    if fts_expression("  ") != "":
        print("selftest FAIL: порожній запит не дав порожнього виразу", file=sys.stderr)
        return 1
    print(json.dumps({"selftest": "PASS"}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--pool", type=int, default=DEFAULT_POOL)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.database.is_file():
        raise SystemExit(f"немає бази корпусу: {args.database}")
    report = measure(args.database, args.reference, args.pool)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "MEASURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
