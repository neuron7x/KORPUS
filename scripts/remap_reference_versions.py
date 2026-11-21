#!/usr/bin/env python3
"""Remap a frozen reference set to the same source bytes in another database.

Expected holders and the sampled holder must move together. The original frozen
digest retains source-set provenance; an unmapped sampled holder drops its named
case instead of substituting evidence from a different expected holder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reference_eval_set import load_reference_set, validate_case

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

    source_meta, cases = load_reference_set(args.reference)
    by_id = sqlite_map(args.source_sqlite)
    by_hash = target_map(args.target_url)

    def remap_case(case: dict[str, Any]) -> dict[str, Any] | None:
        if case["kind"] != "retrieval":
            return dict(case)
        mapping = {
            vid: by_hash.get(source_hash) if (source_hash := by_id.get(vid)) else None
            for vid in case["must_cite_one_of_if_answered"]
        }
        sampled = mapping[case["sampled_from_version"]]
        if sampled is None:
            return None
        result = {
            **case,
            "sampled_from_version": sampled,
            "must_cite_one_of_if_answered": list(dict.fromkeys(v for v in mapping.values() if v)),
        }
        validate_case(result)
        return result

    print(f"  версій: у джерелі {len(by_id)} · у цілі {len(by_hash)}")

    kept, dropped = [], []
    for case in cases:
        mapped = remap_case(case)
        if mapped is None:
            dropped.append(case["id"])
            continue
        kept.append(mapped)

    args.out.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in kept), encoding="utf-8"
    )

    # Remapped identities require a new digest bound to the admitted source set.
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
