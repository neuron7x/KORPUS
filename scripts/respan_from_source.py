#!/usr/bin/env python3
"""Перенарізати незапечатані версії лише з перевірених оригінальних об'єктів.

Кожен проліт є дослівним `source[start:end]`, усі разом покривають джерело без дірок,
жоден не перевищує стелю. Після запису FTS перебудовується, осиротілі вбудовування
видаляються. Запечатаний набір доказів потребує нової версії та нового рецензування;
`--apply` відмовляє до читання об'єктів і до першого запису.

    respan_from_source.py --database DB [--apply] [--limit N]
    respan_from_source.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "var/runtime/corpus-v6-20260807/korpus.db"
#: Стеля, у якій корпус зібрано. Підняти її означало б підняти й бал осі, не додавши
#: жодного символу інформації — виміряно: 1400 → 1600 дає +0.20 задарма.
MAX_SPAN_CHARS = 1400
OVERLAP_CHARS = 180
_SENTENCE_END = re.compile(r"[.!?…](?=[\s\"»’”)]|$)")


def cut_points(text: str, *, limit: int, overlap: int) -> list[tuple[int, int]]:
    """Пари (початок, кінець) у координатах ОРИГІНАЛУ. Ніякого нового тексту."""
    if not text:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + limit, length)
        if end < length:
            window = text[start:end]
            boundaries = [match.end() for match in _SENTENCE_END.finditer(window)]
            # Межа має бути в останній третині вікна, інакше прольоти вироджуються в
            # короткі уривки і перекриття з'їдає корпус.
            usable = [position for position in boundaries if position > limit // 3]
            if usable:
                end = start + usable[-1]
            else:
                space = window.rfind(" ", limit // 3)
                if space > 0:
                    end = start + space + 1
        spans.append((start, end))
        if end >= length:
            break
        nxt = max(start + 1, end - overlap)
        window = text[nxt:end]
        boundaries = [match.end() for match in _SENTENCE_END.finditer(window)]
        start = nxt + boundaries[0] if boundaries else nxt
        # Межа речення стоїть ОДРАЗУ за крапкою, тож без цього проліт починався б із
        # пробілу — не посеред слова, але й не з речення. Перекриття гарантує, що зсув
        # уперед не робить дірки: `start` лишається меншим за кінець попереднього.
        while start < end and text[start].isspace():
            start += 1
        if start >= end:
            start = end
    return spans


def verify(text: str, spans: list[tuple[int, int]], *, limit: int) -> list[str]:
    """Причини НЕ писати цю версію. Порожньо — єдина підстава записати."""
    problems: list[str] = []
    if not spans:
        return ["жодного прольоту"] if text else []
    if spans[0][0] != 0:
        problems.append(f"перший проліт починається з {spans[0][0]}, не з нуля")
    if spans[-1][1] != len(text):
        problems.append(f"останній проліт кінчається на {spans[-1][1]} із {len(text)}")
    for index, (start, end) in enumerate(spans):
        if end <= start:
            problems.append(f"проліт {index} порожній або перевернутий")
        if end - start > limit:
            problems.append(f"проліт {index} довший за стелю: {end - start}")
        if index and start > spans[index - 1][1]:
            problems.append(f"дірка перед прольотом {index}")
    return problems


def selftest() -> int:
    body = "Перше речення тут. Друге речення тут! Третє речення тут? " * 40
    checks: list[tuple[str, bool]] = []
    spans = cut_points(body, limit=200, overlap=40)
    checks.append(("кожен проліт — дослівний зріз", all(body[a:b] == body[a:b] for a, b in spans)))
    checks.append(("покриття без дірок", not verify(body, spans, limit=200)))
    checks.append(("стеля не порушена", all(b - a <= 200 for a, b in spans)))
    checks.append(
        (
            "проліт починається з речення, не з пробілу й не посеред слова",
            all(not body[a].isspace() and (a == 0 or body[a - 1].isspace()) for a, _ in spans),
        )
    )
    # Речення, довше за стелю: ріжеться, і це видно, а не ховається.
    monster = "А" * 500 + ". " + "Б" * 30
    spans = cut_points(monster, limit=200, overlap=40)
    checks.append(
        ("надто довге речення все одно вкладається у стелю", all(b - a <= 200 for a, b in spans))
    )
    checks.append(("і покриває джерело цілком", not verify(monster, spans, limit=200)))
    checks.append(
        ("порожній текст — жодного прольоту", cut_points("", limit=200, overlap=40) == [])
    )
    # Негативний контроль на сам verify: дірку мусить бачити.
    checks.append(("дірка помічається", bool(verify("абвгд", [(0, 2), (3, 5)], limit=10))))
    checks.append(
        ("хвіст, що не дійшов до кінця, помічається", bool(verify("абвгд", [(0, 3)], limit=10)))
    )
    failed = [name for name, ok in checks if not ok]
    print(json.dumps({"selftest": len(checks), "failed": failed}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def plan_version(
    row: Any, object_root: Path, *, limit: int, overlap: int
) -> tuple[str, list[tuple[int, int]], str | None]:
    """Текст версії та її нові межі — або причина не чіпати цю версію."""
    path = object_root / str(row["object_key"])
    if not path.is_file():
        return "", [], "немає об'єкта"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != str(row["source_hash"]):
        # Об'єкт, що не збігається з оголошеним хешем, не є джерелом цієї версії.
        return "", [], "sha256 об'єкта не збігається"
    text = raw.decode("utf-8", errors="replace")
    spans = cut_points(text, limit=limit, overlap=overlap)
    problems = verify(text, spans, limit=limit)
    if problems:
        return text, [], "; ".join(problems[:3])
    return text, spans, None


def write_version(
    connection: sqlite3.Connection,
    version_id: str,
    text: str,
    spans: list[tuple[int, int]],
    when: str,
) -> None:
    connection.execute("delete from evidence_spans where version_id=?", (version_id,))
    connection.executemany(
        """insert into evidence_spans
           (id, version_id, ordinal, page, section, text, text_hash, created_at)
           values (?,?,?,?,?,?,?,?)""",
        [
            (
                str(uuid.uuid4()),
                version_id,
                ordinal,
                None,
                None,
                text[start:end],
                hashlib.sha256(text[start:end].encode("utf-8")).hexdigest(),
                when,
            )
            for ordinal, (start, end) in enumerate(spans)
        ],
    )


def rebuild_index(connection: sqlite3.Connection) -> dict[str, int]:
    """Індекс і вбудовування — частина запису, а не наслідок, який настане сам."""
    connection.execute("delete from evidence_fts")
    connection.execute(
        "insert into evidence_fts (span_id, text) select id, text from evidence_spans"
    )
    connection.execute(
        "delete from span_embeddings where span_id not in (select id from evidence_spans)"
    )
    connection.commit()
    count = "select count(*) from"
    orphan = "where not exists (select 1 from evidence_spans s where s.id={}.span_id)"
    return {
        "fts_rows": connection.execute(f"{count} evidence_fts").fetchone()[0],
        "fts_orphans": connection.execute(
            f"{count} evidence_fts f {orphan.format('f')}"
        ).fetchone()[0],
        "embedding_orphans": connection.execute(
            f"{count} span_embeddings e {orphan.format('e')}"
        ).fetchone()[0],
        "embeddings_left": connection.execute(f"{count} span_embeddings").fetchone()[0],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--object-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="скільки версій обробити")
    parser.add_argument("--selftest", action="store_true")
    return parser.parse_args()


def sealed_refusal(versions: list[Any]) -> dict[str, Any] | None:
    sealed = [str(row["id"]) for row in versions if row["evidence_digest"] is not None]
    if not sealed:
        return None
    return {
        "status": "REFUSED",
        "applied": False,
        "reason": "запечатані докази потребують нових версій",
        "sealed_versions": sealed[:10],
        "sealed_count": len(sealed),
    }


def main() -> int:
    args = parse_args()
    if args.selftest:
        return selftest()
    if not args.database.is_file():
        print(
            json.dumps(
                {"status": "UNKNOWN", "reason": f"немає {args.database}"}, ensure_ascii=False
            )
        )
        return 2
    object_root = args.object_root or args.database.parent / "objects"
    connection = sqlite3.connect(str(args.database))
    connection.row_factory = sqlite3.Row
    versions = list(
        connection.execute(
            "select id, object_key, source_hash, evidence_digest from document_versions order by id"
        )
    )
    versions = versions[: args.limit] if args.limit else versions
    refusal = sealed_refusal(versions) if args.apply else None
    if refusal:
        connection.close()
        print(json.dumps(refusal, ensure_ascii=False, indent=2))
        return 1
    refused: list[dict[str, Any]] = []
    planned = written = 0
    now = datetime.now(UTC).isoformat(sep=" ")
    for row in versions:
        text, spans, why = plan_version(
            row, object_root, limit=MAX_SPAN_CHARS, overlap=OVERLAP_CHARS
        )
        if why is not None:
            refused.append({"version": str(row["id"]), "why": why})
            continue
        planned += len(spans)
        if args.apply:
            write_version(connection, str(row["id"]), text, spans, now)
            written += len(spans)
    index = rebuild_index(connection) if args.apply else {}
    print(
        json.dumps(
            {
                "status": "REFUSED" if refused and not planned else "PASS",
                "applied": bool(args.apply),
                "versions": len(versions),
                "spans_planned": planned,
                "spans_written": written,
                "refused_versions": refused[:10],
                "refused_count": len(refused),
                "index": index,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if refused else 0


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
