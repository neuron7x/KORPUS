#!/usr/bin/env python3
"""Перелік тверджень БЕЗ вироку — вхід для приймальника.

Бюджет на актора тисне тоді, коли є що приймати. Цей перелік і є те, що приймальник
має розсудити: id, автор, вік, текст і докази. Порядок — від найстарших, бо непроста
властивість боргу в тому, що старі твердження вже встигли на щось вплинути.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / ".verdict-ledger.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--actor", help="лише твердження цього актора")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    recs = [json.loads(l) for l in LEDGER.open(encoding="utf-8") if l.strip()]
    reg = json.loads((LEDGER.parent / "config/agents/axes.json").read_text(encoding="utf-8"))
    settles = set(reg["verdict_vocabulary"]["settles"])
    settled = {r["id"] for r in recs if r.get("kind") == "verdict" and r.get("verdict") in settles}
    claims = [r for r in recs if r.get("kind") == "claim" and r["id"] not in settled]
    if args.actor:
        claims = [c for c in claims if c.get("actor") == args.actor]
    claims.sort(key=lambda c: c.get("at", ""))
    if args.limit:
        claims = claims[:args.limit]
    if args.json:
        print(json.dumps(claims, ensure_ascii=False, indent=2))
        return 0
    for c in claims:
        print(f"{c['id']}  {c.get('at','')[:16]}  {c.get('actor','')}")
        print(f"   {c.get('claim','')}")
        for e in (c.get("evidence") or []):
            print(f"     · {e[:150]}")
        print()
    print(f"без вироку: {len(claims)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
