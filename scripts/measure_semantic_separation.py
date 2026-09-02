#!/usr/bin/env python3
"""Does meaning-based retrieval separate what word-matching could not — measured, not assumed.

On 2026-08-29 this system answered "what is the corporate tax rate in 2019" with four
verbatim citations from Ukrainian defence law. `Ставка` in `Ставка Верховного
Головнокомандувача` (the Supreme Commander's headquarters) is the same word as `ставка`
(a tax rate), and a word index cannot see the difference. The negative control on answers
was then attempted with a threshold on lexical coverage and refuted on its own terms:
across eleven questions `min(in-domain) = 0.25` sat below `max(out-of-domain) = 0.50`,
an empty interval. The defect was never the threshold. It was retrieval that reads
letters rather than meaning.

This measures whether the missing axis exists. It is an EXPERIMENT, not the production
index: `run_embedding_backfill.py` writes pgvector under a governance profile and a lock,
and nothing here promotes anything. What it can do is decide whether that work is worth
doing, by answering one question with a number:

    does the worst in-domain question outrank the best out-of-domain question?

An empty interval here means dense retrieval buys nothing on this corpus and the honest
answer is to say so. A non-empty interval is the first evidence that the corpus can be
asked questions rather than only searched.

    measure_semantic_separation.py --limit 400   # a sample first
    measure_semantic_separation.py
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.infrastructure.semantic import HttpEmbeddingProvider  # noqa: E402

#: Питання, на які корпус МУСИТЬ відповідати: вони про те, що в ньому є.
IN_DOMAIN = (
    "Хто здійснює загальне керівництво Збройними Силами України?",
    "Що таке Ставка Верховного Головнокомандувача?",
    "Які обов'язки командира підрозділу щодо застосування БпАК?",
    "Що робити при виявленні ознак мінування місцевості?",
    "Хто затверджує Статут внутрішньої служби Збройних Сил України?",
    "Які завдання виконує сержантський склад?",
    "Що входить до обов'язків чергового по роті?",
)
#: Питання, на які він мусить НЕ відповідати: у корпусі про це нема нічого.
#: Перше — той самий омонім, який зламав лексичний пошук: «ставка» податку.
OUT_OF_DOMAIN = (
    "Яка ставка податку на прибуток підприємств у 2019 році?",
    "Скільки коштує оренда квартири в Празі?",
    "Як приготувати борщ із пампушками?",
    "Яка максимальна швидкість автомобіля Toyota Corolla?",
    "Коли відкривається сезон полювання на качок?",
)


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def captured(root: Path, limit: int | None) -> list[tuple[str, str]]:
    """Корпус із `config/corpus/captures/` — тіла extract record, які лежать У GIT.

    Це не заміна робочому індексу, а сильніша база для ЕКСПЕРИМЕНТУ: вимір, який
    залежить від `var/`, відтворити не можна після першого ж прибирання — 2026-08-30 о
    07:58 `make clean` забрав звідти корпусну базу на 7608 спанів разом із 530 МБ
    вихідних байтів. Те, що лежить у git, переживає і прибирання, і відкіт, і клон.
    Тіло кожного запису обмежене (перші 400 і останні 200 слів), і саме тому тут воно
    названо своїм ім'ям: вибірка з документа, а не документ.
    """
    rows: list[tuple[str, str]] = []
    for path in sorted(root.glob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        body = text.split("\n---\n", 1)[-1].strip()
        if len(body) > 40:
            rows.append((path.stem, body))
    return rows[:limit] if limit else rows


def spans(database: Path, limit: int | None) -> list[tuple[str, str]]:
    with sqlite3.connect(database) as connection:
        query = "SELECT id, text FROM evidence_spans WHERE length(text) > 40 ORDER BY id"
        rows = connection.execute(query + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    return [(str(identifier), str(text)) for identifier, text in rows]


def embed_all(provider: HttpEmbeddingProvider, texts: list[str]) -> list[list[float]]:
    size = provider.max_batch_size
    return [
        vector
        for start in range(0, len(texts), size)
        for vector in provider.embed_many(texts[start : start + size])
    ]


def stream_best(
    provider: HttpEmbeddingProvider, texts: list[str], asked: list[list[float]]
) -> tuple[list[float], list[str]]:
    """Найкращий бал кожного питання й текст його найкращого спана — потоково.

    Перша версія тримала всі 7608 векторів по 1024 float у пам'яті й була вбита OOM на
    машині з 13 із 15 ГБ, уже зайнятими трьома сесіями. Пам'ять тут не оптимізація:
    вимір, який не можна довести до кінця, не є виміром. Тримається рівно стільки, скільки
    треба для відповіді — по одному числу й одному рядку на питання.
    """
    best = [0.0] * len(asked)
    where = [""] * len(asked)
    size = provider.max_batch_size
    for start in range(0, len(texts), size):
        chunk = texts[start : start + size]
        for text, vector in zip(chunk, provider.embed_many(chunk), strict=True):
            for index, question in enumerate(asked):
                score = cosine(question, vector)
                if score > best[index]:
                    best[index] = score
                    where[index] = text[:160]
    return best, where


def measure(
    database: Path,
    endpoint: str,
    model: str,
    dimensions: int,
    limit: int | None,
    from_captures: bool = False,
) -> Any:
    corpus = (
        captured(ROOT / "config/corpus/captures", limit)
        if from_captures
        else spans(database, limit)
    )
    provider = HttpEmbeddingProvider(
        endpoint, model, dimensions, timeout_seconds=60, max_attempts=2
    )
    started = time.perf_counter()
    try:
        asked = embed_all(provider, list(IN_DOMAIN) + list(OUT_OF_DOMAIN))
        best, where = stream_best(provider, [text for _identifier, text in corpus], asked)
    finally:
        provider.close()
    duration = time.perf_counter() - started

    inside = best[: len(IN_DOMAIN)]
    outside = best[len(IN_DOMAIN) :]
    matched = where[len(IN_DOMAIN) :]
    worst_inside = min(inside)
    best_outside = max(outside)
    # Той самий вимір, що на лексичному покритті дав порожній інтервал: 0.25 проти 0.50.
    return {
        "schema": "korpus.semantic-separation.v1",
        "measured_at": datetime.now(UTC).isoformat(),
        "corpus": "config/corpus/captures (у git)" if from_captures else database.name,
        "model": model,
        "dimensions": dimensions,
        "spans_embedded": len(corpus),
        "duration_seconds": round(duration, 1),
        "embeddings_per_second": round((len(corpus) + len(asked)) / duration, 1),
        "in_domain": [
            {"question": q, "best": round(s, 4)}
            for q, s in sorted(zip(IN_DOMAIN, inside, strict=True), key=lambda pair: pair[1])
        ],
        # Для позаменних показується ще й ЩО саме знайшлось: число без тексту не дає
        # побачити, чи це випадковий збіг, чи система впевнено відповідає не про те.
        "out_of_domain": [
            {"question": q, "best": round(s, 4), "matched": m}
            for q, s, m in sorted(
                zip(OUT_OF_DOMAIN, outside, matched, strict=True), key=lambda row: -row[1]
            )
        ],
        "worst_in_domain": round(worst_inside, 4),
        "best_out_of_domain": round(best_outside, 4),
        "interval": round(worst_inside - best_outside, 4),
        "separates": worst_inside > best_outside,
        "promotion_authorized": False,
        "limitation": (
            "Експеримент, не робочий індекс: нічого не вмикає, продакшн-шлях — "
            "run_embedding_backfill.py під pgvector, профілем governance і блокуванням. "
            "Межі виміру: тіла extract record обмежені (перші 400 і останні 200 слів), "
            "тобто це вибірка з документа, а не документ; питань 7 у домені і 5 поза ним, "
            "і на такій кількості інтервал є спостереженням, а не оцінкою з довірою. "
            "Прогін на 7608 спанах корпусної бази зробити не вдалося: базу знесло "
            "`make clean` 2026-08-30 о 07:58 разом із 530 МБ вихідних байтів."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database", type=Path, default=ROOT / "var/runtime/corpus-v6-20260807/korpus.db"
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/api/embed")
    parser.add_argument("--model", default="qwen3-embedding:0.6b")
    parser.add_argument("--dimensions", type=int, default=1024)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--from-captures",
        action="store_true",
        help="корпус із config/corpus/captures — відтворюваний із чистого клону",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "var/semantic-separation.json")
    arguments = parser.parse_args()

    report = measure(
        arguments.database,
        arguments.endpoint,
        arguments.model,
        arguments.dimensions,
        arguments.limit,
        arguments.from_captures,
    )
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Порожній інтервал — це результат, а не помилка прогону: він каже, що ця вісь на
    # цьому корпусі нічого не купує, і саме це треба знати перед бекфілом.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
