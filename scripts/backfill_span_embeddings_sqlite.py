#!/usr/bin/env python3
"""Заповнити `span_embeddings` для рантайму на SQLite — без PostgreSQL.

`run_embedding_backfill.py` міряє й узгоджує ембединги в PostgreSQL, і через це
здавалось, що семантика в рантаймі неможлива без нього. Це не так: таблиця
`span_embeddings` існує в SQLite, провайдер приймає **loopback**-адресу
(`is_https_or_loopback_url`), а конверт відповіді явно підтримує Ollama. Тобто
семантичний шлях був побудований і ВИМКНЕНИЙ, а не відсутній.

Вектори нормалізуються тим самим `normalize_vector`, що й у рантаймі: зберігати
ненормовані означало б, що косинус рахується не там, де його читають.

Пише інкрементно й ідемпотентно за `text_hash`: перерваний прогін продовжується
запуском наново, а не починається спочатку — 38 863 спани це година роботи, і
втратити її через обрив було б утретє за добу.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.infrastructure.embedding_validation import normalize_vector  # noqa: E402

import httpx  # noqa: E402


def embed_batch(endpoint: str, model: str, texts: list[str], dims: int,
                timeout: float) -> list[list[float]]:
    resp = httpx.post(endpoint, json={"model": model, "input": texts}, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    vectors = payload.get("embeddings") or ([payload["embedding"]] if "embedding" in payload else None)
    if vectors is None or len(vectors) != len(texts):
        raise RuntimeError("провайдер повернув інше число векторів, ніж запитано")
    return [normalize_vector(v, dims) for v in vectors]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--database", required=True)
    ap.add_argument("--endpoint", default="http://127.0.0.1:11434/api/embed")
    ap.add_argument("--model", default="qwen3-embedding:0.6b")
    ap.add_argument("--dimensions", type=int, default=1024)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-chars", type=int, default=3000)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    con = sqlite3.connect(args.database, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    todo = con.execute(
        "SELECT s.id, s.text, s.text_hash FROM evidence_spans s "
        "LEFT JOIN span_embeddings e ON e.span_id = s.id AND e.model_id = ? "
        "WHERE e.span_id IS NULL AND length(trim(s.text)) > 0 ORDER BY s.id",
        (args.model,)).fetchall()
    if args.limit:
        todo = todo[: args.limit]
    total = len(todo)
    print(f"без вектора: {total} спанів · модель {args.model} · {args.dimensions} вимірів",
          flush=True)
    done = failed = 0
    started = time.time()
    for i in range(0, total, args.batch):
        chunk = todo[i : i + args.batch]
        texts = [(t or "")[: args.max_chars] for _, t, _ in chunk]
        try:
            vectors = embed_batch(args.endpoint, args.model, texts, args.dimensions,
                                  args.timeout)
        except Exception as error:
            failed += len(chunk)
            print(f"  партія {i}: {type(error).__name__}: {error}"[:160], file=sys.stderr,
                  flush=True)
            continue
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        con.executemany(
            "INSERT OR REPLACE INTO span_embeddings "
            "(span_id, model_id, dimensions, embedding_json, text_hash, created_at) "
            "VALUES (?,?,?,?,?,?)",
            [(sid, args.model, args.dimensions, json.dumps(vec), th, now)
             for (sid, _, th), vec in zip(chunk, vectors)])
        con.commit()
        done += len(chunk)
        if (i // args.batch) % 20 == 0 or done >= total:
            rate = done / max(time.time() - started, 1e-9)
            left = (total - done) / rate if rate else 0
            print(f"  {done}/{total} · {rate:.1f}/с · лишилось ~{left/60:.0f} хв", flush=True)
    have = con.execute("SELECT count(*) FROM span_embeddings WHERE model_id=?",
                       (args.model,)).fetchone()[0]
    spans = con.execute("SELECT count(*) FROM evidence_spans").fetchone()[0]
    print(f"\nвекторів: {have} із {spans} спанів ({have/spans:.1%}) · невдалих {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
