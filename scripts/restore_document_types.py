#!/usr/bin/env python3
"""Повернути документам тип, який імпорт загубив, — із курованого каталогу.

Рантайм-корпус тримає 256 документів, з них 235 із `document_type = 'other'`. Це не
властивість матеріалу: каталог `config/corpus/doctrine_catalog_2026.json` знає 41 тип і
називає тип КОЖНОГО джерела поіменно. Тип загубився між каталогом і базою.

Ціна втрати не косметична. `build_reference_set.py` стратифікує саме за
`document_type`, тож на чотирьох типах набір оцінювання дає 8 страт при вимозі 20 —
і `test_every_stratum_is_represented_and_none_dominates` червоніє. Тобто система не
може довести якість відповідей, бо не знає, ЯКІ документи вона має.

Зіставлення лише за ТОЧНИМ `source_uri`. Не за назвою, не за хвостом шляху, не за
схожістю: тип документа — нормативна властивість, і вгадана вона гірша за відсутню.
Джерело, якого в каталозі немає, лишається `other` — це чесне «не знаю», а не здогад.

    restore_document_types.py --database DB [--apply]   # без --apply лише показує
    restore_document_types.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
UNKNOWN = "other"


def catalogue_types(catalog: Path) -> dict[str, str]:
    """URI джерела -> оголошений тип. Порожній URI або порожній тип не рахуються."""
    if not catalog.exists():
        raise SystemExit(f"немає каталогу: {catalog}")
    sources = json.loads(catalog.read_text(encoding="utf-8"))["sources"]
    mapping: dict[str, str] = {}
    for source in sources:
        uri = (source.get("source_uri") or "").strip()
        kind = (source.get("document_type") or "").strip()
        if uri and kind:
            mapping[uri] = kind
    if not mapping:
        raise SystemExit("каталог не називає жодного типу — це відмова, не дозвіл")
    return mapping


def plan(connection: sqlite3.Connection, mapping: dict[str, str]) -> list[tuple[str, str, str]]:
    """(document_id, було, стане) для документів, чий тип каталог називає інакше."""
    rows = connection.execute(
        "SELECT d.id, d.document_type, v.source_uri"
        " FROM documents d"
        " JOIN document_versions v ON v.document_id = d.id AND v.is_current = 1"
    ).fetchall()
    changes = []
    for document_id, current, uri in rows:
        declared = mapping.get((uri or "").strip())
        if declared and declared != current:
            changes.append((str(document_id), str(current), declared))
    return changes


def apply(connection: sqlite3.Connection, changes: list[tuple[str, str, str]]) -> None:
    connection.executemany(
        "UPDATE documents SET document_type = ? WHERE id = ?",
        [(new, document_id) for document_id, _old, new in changes],
    )
    connection.commit()


def _strata_count(connection: sqlite3.Connection) -> int:
    return len({r[0] for r in connection.execute("SELECT document_type FROM documents")})


def selftest() -> int:
    """Отрути по ДАНИХ: відновлювач мусить мовчати там, де не має підстави."""
    import tempfile

    results: list[bool] = []

    def check(name: str, got: object, want: object) -> None:
        ok = got == want
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")
        results.append(ok)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.db"
        con = sqlite3.connect(path)
        con.executescript(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, document_type TEXT);"
            "CREATE TABLE document_versions (id TEXT, document_id TEXT,"
            " source_uri TEXT, is_current INTEGER);"
        )
        rows = [
            ("d1", "other", "https://a/1"),
            ("d2", "law", "https://a/2"),
            ("d3", "other", "https://not-in-catalogue/9"),
            ("d4", "other", None),
        ]
        for i, (doc, kind, uri) in enumerate(rows):
            con.execute("INSERT INTO documents VALUES (?,?)", (doc, kind))
            con.execute("INSERT INTO document_versions VALUES (?,?,?,1)", (f"v{i}", doc, uri))
        con.commit()
        mapping = {"https://a/1": "field_manual", "https://a/2": "law"}

        changes = plan(con, mapping)
        check("міняє лише те, що каталог називає інакше", sorted(c[0] for c in changes), ["d1"])
        check("джерело поза каталогом не чіпає", any(c[0] == "d3" for c in changes), False)
        check("порожній URI не чіпає", any(c[0] == "d4" for c in changes), False)
        check("той самий тип не переписує", any(c[0] == "d2" for c in changes), False)

        apply(con, changes)
        got = dict(con.execute("SELECT id, document_type FROM documents"))
        check("після застосування тип став каталожним", got["d1"], "field_manual")
        check("решта незмінна", [got["d2"], got["d3"], got["d4"]], ["law", "other", "other"])
        check("повторний прогін нічого не змінює", plan(con, mapping), [])

        con.close()

    passed = sum(1 for r in results if r)
    print(f"негативний контроль: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database")
    parser.add_argument("--catalog", default=str(CATALOG))
    parser.add_argument("--apply", action="store_true", help="записати; без нього лише показ")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    if not arguments.database:
        parser.error("потрібен --database")

    mapping = catalogue_types(Path(arguments.catalog))
    connection = sqlite3.connect(arguments.database)
    before = _strata_count(connection)
    changes = plan(connection, mapping)
    counts = Counter(new for _id, _old, new in changes)
    if arguments.apply:
        apply(connection, changes)
    after = _strata_count(connection)
    print(
        json.dumps(
            {
                "catalogue_types": len(set(mapping.values())),
                "documents_retyped": len(changes),
                "strata_before": before,
                "strata_after": after if arguments.apply else "не застосовано",
                "applied": arguments.apply,
                "top_types": dict(counts.most_common(8)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
