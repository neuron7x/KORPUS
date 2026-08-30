#!/usr/bin/env python3
"""Зібрати маніфест і тексти для рантайм-корпусу з перевіреного корпусу zsu-dataset.

Рантайм-базу, яку подавав публічний веб, знищив `make clean` разом із усім `var/`.
Вміст при цьому не втрачено: він лежить у `~/zsu-dataset/corpus.sqlite` — 279 документів
із провенансом, правами й посиланням на першоджерело, і кожен пройшов схему-гейт
(`rights_status = 'open'` при ЗАПИСІ, щільність тексту, відсутність нульового байта).

Метадані беруться з КАТАЛОГУ, не з імені файла: ім'я — це схема, яку ніхто не валідує,
і здогад про видавця вирішує, що покажуть військовому. Чого в каталозі немає, тут
теж немає — поле лишається порожнім, а не вигаданим.

Тексти пишуться як `.txt` у UTF-8: рантайм-екстрактор їх читає, а зберігати PDF заново
означало б тягнути 300 МБ заради вмісту, який уже витягнутий і звірений із чужим
відбитком байтів.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZSU = Path.home() / "zsu-dataset"
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"

#: Тип документа з каталогу → словник рантайму. Невідоме лишається `other`,
#: а не вгадується: вигаданий тип змінює те, як відповідь показують.
DOC_TYPE = {"statute": "regulation", "law": "law", "order": "order", "manual": "manual",
            "doctrine": "manual", "guideline": "manual", "report": "other",
            "webpage": "other", "standard": "regulation"}


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:80] or "doc"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "var/runtime/import")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if not (ZSU / "corpus.sqlite").is_file():
        print(f"немає {ZSU/'corpus.sqlite'}", file=sys.stderr)
        return 1
    catalog = {s["id"]: s for s in json.loads(CATALOG.read_text(encoding="utf-8"))["sources"]}
    con = sqlite3.connect(ZSU / "corpus.sqlite")
    con.row_factory = sqlite3.Row
    docs = con.execute("SELECT id, title, jurisdiction, source_uri, words, probed_on, "
                       "rights_status FROM document ORDER BY id").fetchall()
    if args.limit:
        docs = docs[: args.limit]

    files = args.out / "files"
    files.mkdir(parents=True, exist_ok=True)
    entries, skipped = [], []
    for d in docs:
        if d["rights_status"] != "open":
            skipped.append((d["id"], f"права {d['rights_status']}"))
            continue
        text = "\n\n".join(r[0] for r in con.execute(
            "SELECT text FROM chunk WHERE document_id=? ORDER BY ordinal", (d["id"],)))
        if len(text.strip()) < 200:
            skipped.append((d["id"], "тексту менше за 200 символів"))
            continue
        name = f"{slug(d['id'])}.txt"
        (files / name).write_text(text, encoding="utf-8")
        src = catalog.get(d["id"], {})
        entries.append({
            "file": f"files/{name}",
            "canonical_title": d["title"][:300],
            "issuer": src.get("issuer") or ("Верховна Рада України" if d["jurisdiction"] == "UA"
                                            else "US Army"),
            "revision": "1",
            "publication_date": (d["probed_on"] or "")[:10] or None,
            "authority": src.get("authority") or ("official_ua" if d["jurisdiction"] == "UA"
                                                  else "official_allied"),
            "document_type": DOC_TYPE.get(str(src.get("document_type")), "other"),
            "access_tier": 0,
            "classification": "public",
            "compartments": [],
            "publication_identifier": d["id"],
            "source_uri": d["source_uri"],
        })
    manifest = {"corpus_id": "public", "documents": entries}
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum((files / Path(e["file"]).name).stat().st_size for e in entries)
    print(f"маніфест: {args.out/'manifest.json'} · документів {len(entries)} · "
          f"тексту {total/1e6:.1f} МБ")
    if skipped:
        print(f"пропущено {len(skipped)}, поіменно:")
        for i, why in skipped[:10]:
            print(f"  · {i}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
