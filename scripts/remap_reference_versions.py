#!/usr/bin/env python3
"""Перенести еталонний набір на іншу базу з ТИМИ САМИМИ документами.

Порівняння двох конфігурацій вимагає ОДНАКОВИХ питань і ОДНАКОВИХ цілей. Але
`import_corpus.py` видає новий UUID кожній версії, тож той самий документ у SQLite
і в PostgreSQL має різні `version_id`, а еталон називає саме їх у
`must_cite_one_of_if_answered`. Прогін замороженого набору проти другої бази провалив
би всі випадки пошуку — і не через семантику, а через ідентифікатори.

Це та сама вада, що весь день: вимір, який показує різницю там, де її немає.
Тому версії зіставляються за `source_hash` — вмістом файла, з якого версію зроблено.
Він однаковий в обох базах за побудовою: імпорт ішов з одного маніфесту й тих самих
файлів. Зіставлення за назвою було б слабшим: назви повторюються, хеш ні.

Випадок, чию ціль не вдалося зіставити, НЕ переноситься мовчки — він вибувае з набору
з іменем, бо тихо зменшений знаменник це те, чим вимір бреше найчастіше.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))


def sqlite_map(path: Path) -> dict[str, str]:
    con = sqlite3.connect(path)
    return {
        vid: sh
        for vid, sh in con.execute(
            "SELECT id, source_hash FROM document_versions WHERE source_hash IS NOT NULL"
        )
    }


def target_map(url: str) -> dict[str, str]:
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    with engine.connect() as con:
        return {
            sh: vid
            for vid, sh in con.execute(
                text("SELECT id, source_hash FROM document_versions WHERE source_hash IS NOT NULL")
            )
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-sqlite", type=Path, required=True)
    ap.add_argument("--target-url", required=True)
    ap.add_argument("--reference", type=Path, default=ROOT / "evals/datasets/reference.jsonl")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    by_id = sqlite_map(args.source_sqlite)
    by_hash = target_map(args.target_url)
    print(f"  версій: у джерелі {len(by_id)} · у цілі {len(by_hash)}")

    kept, dropped = [], []
    for line in args.reference.open(encoding="utf-8"):
        case = json.loads(line)
        want = case.get("must_cite_one_of_if_answered")
        if not want:
            kept.append(case)
            continue
        if isinstance(want, str):
            want = json.loads(want.replace("'", '"'))
        mapped = []
        for vid in want:
            sh = by_id.get(vid)
            tid = by_hash.get(sh) if sh else None
            if tid:
                mapped.append(tid)
        if not mapped:
            dropped.append(case["id"])
            continue
        case["must_cite_one_of_if_answered"] = mapped
        kept.append(case)

    args.out.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in kept), encoding="utf-8"
    )

    # Набір без свого meta не набір: `run_reference_eval.py` вимагає його і без нього
    # мовчки виходить, тож перенесений еталон був непридатний до вжитку, а помилка
    # виглядала як «немає замороженого набору». Свій відбиток тут ОБОВʼЯЗКОВО новий —
    # ідентифікатори цілей інші, отже це інший набір, — але він носить відбиток
    # джерела, бо порівнювати число проти перенесеного набору можна лише з числом
    # проти набору, з якого його перенесли.
    source_meta_path = args.reference.with_suffix(".meta.json")
    source_meta = (
        json.loads(source_meta_path.read_text(encoding="utf-8"))
        if source_meta_path.is_file()
        else {}
    )
    digest = hashlib.sha256()
    for case in kept:
        digest.update(json.dumps(case, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        digest.update(b"\n")
    args.out.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "frozen_at": datetime.now(UTC).isoformat(),
                "database": args.target_url.split("@")[-1],
                "cases": len(kept),
                "content_digest": digest.hexdigest(),
                "remapped_from_digest": source_meta.get("content_digest"),
                "remapped_from": str(args.reference),
                "dropped_case_ids": dropped,
                "cannot_judge": source_meta.get("cannot_judge", []),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  перенесено {len(kept)} випадків · вибуло {len(dropped)}")
    if dropped:
        print("  вибули поіменно:", ", ".join(dropped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
