#!/usr/bin/env python3
"""Union the coverage of the two database dialects this system runs on.

The suite executes against SQLite by default and against PostgreSQL under
`make postgres-suite`. The deployment runs PostgreSQL; SQLite is the local and offline
profile. Both are real, and the code says so — `repository.py` alone carries eight
`dialect.name` branches, and `_initialize_search_index` writes an FTS5 virtual table on
one and a GIN index on the other.

Measuring only the SQLite run therefore reports every PostgreSQL arm as untaken. Those
branches are not untested; they are tested by a run whose coverage nobody reads. Measured
2026-08-28: the PostgreSQL run is a strict superset of the SQLite one — it covers eleven
branches SQLite cannot reach and none the other way — so the union is what the two runs
together actually established.

The union is per branch arc, not per file: an arc counts as covered when either run took
it. Anything neither run took stays missing, which is the number the ratchet reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, Any]:
    """json.loads returns Any; a coverage report that is not an object is not a report."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def same_subject(primary: dict[str, Any], secondary: dict[str, Any]) -> str | None:
    """Причина, чому два прогони описують РІЗНІ дерева, або None.

    Злиття зіставляє гілки за (файл, дуга), а дуга — це пара НОМЕРІВ РЯДКІВ. Якщо два
    прогони зняті на різних деревах, зсув коду робить старі дуги випадково збіжними з
    новим кодом, і вони зараховуються як покриті. Помилка йде в НЕБЕЗПЕЧНИЙ бік:
    покриття завищується, а ратчет читає саме це число.

    Виміряно 08.09.2026. `var/coverage-postgres.json` був знятий 06.09, до злиття
    керованого шару спроможностей (16 407 рядків). Обʼєднання з ним давало 233
    непокриті гілки; після перезняття ПостгреSQL на цьому ж дереві — 247. Чотирнадцять
    «покритих» гілок існували лише як збіг номерів.

    Перевірка не потребує стороннього провенансу: якщо дерева ті самі, перелік файлів і
    кількість тверджень у кожному збігаються. Розбіжність тут — не «трохи інший
    прогін», а інший предмет.
    """
    left, right = primary.get("files", {}), secondary.get("files", {})
    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    if only_left or only_right:
        return (
            "прогони описують різні дерева: файлів лише в первинному "
            f"{len(only_left)}, лише у вторинному {len(only_right)}; "
            f"напр. {(only_left or only_right)[:2]}"
        )
    shifted = [
        path
        for path, entry in left.items()
        if entry.get("summary", {}).get("num_statements")
        != right[path].get("summary", {}).get("num_statements")
    ]
    if shifted:
        return (
            f"прогони описують різні дерева: у {len(shifted)} файлах різна кількість "
            f"тверджень; напр. {sorted(shifted)[:2]}"
        )
    return None


def merge(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = json.loads(json.dumps(primary))
    files: dict[str, Any] = merged["files"]
    other: dict[str, Any] = secondary.get("files", {})
    for path, entry in files.items():
        counterpart = other.get(path)
        if counterpart is None:
            continue
        missing_here = {tuple(arc) for arc in entry.get("missing_branches", [])}
        missing_there = {tuple(arc) for arc in counterpart.get("missing_branches", [])}
        still_missing = sorted(missing_here & missing_there)
        entry["missing_branches"] = [list(arc) for arc in still_missing]
        missing_lines = sorted(
            set(entry.get("missing_lines", [])) & set(counterpart.get("missing_lines", []))
        )
        entry["missing_lines"] = missing_lines

        summary = entry["summary"]
        summary["missing_branches"] = len(still_missing)
        summary["covered_branches"] = summary["num_branches"] - len(still_missing)
        summary["missing_lines"] = len(missing_lines)
        summary["covered_lines"] = summary["num_statements"] - len(missing_lines)
        if summary["num_branches"]:
            summary["percent_branches_covered"] = (
                100.0 * summary["covered_branches"] / summary["num_branches"]
            )
        if summary["num_statements"]:
            summary["percent_statements_covered"] = (
                100.0 * summary["covered_lines"] / summary["num_statements"]
            )

    totals = merged["totals"]
    totals["missing_branches"] = sum(
        entry["summary"]["missing_branches"] for entry in files.values()
    )
    totals["covered_branches"] = totals["num_branches"] - totals["missing_branches"]
    totals["missing_lines"] = sum(entry["summary"]["missing_lines"] for entry in files.values())
    totals["covered_lines"] = totals["num_statements"] - totals["missing_lines"]
    totals["percent_statements_covered"] = (
        100.0 * totals["covered_lines"] / totals["num_statements"]
    )
    totals["percent_branches_covered"] = 100.0 * totals["covered_branches"] / totals["num_branches"]
    merged["dialect_union"] = {
        "schema": "korpus.dialect-coverage-union.v1",
        "runs": ["sqlite", "postgresql"],
        "interpretation": (
            "A branch counts as covered when either dialect's run took it. Both dialects "
            "are executed by the suite; only one of them was previously measured."
        ),
    }
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", type=Path, default=ROOT / "var/coverage.json")
    parser.add_argument("--secondary", type=Path, default=ROOT / "var/coverage-postgres.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/coverage-union.json")
    args = parser.parse_args()

    for path in (args.primary, args.secondary):
        if not path.is_file():
            print(json.dumps({"status": "FAIL", "reason": f"missing coverage report: {path}"}))
            return 1

    primary, secondary = _load(args.primary), _load(args.secondary)
    divergence = same_subject(primary, secondary)
    if divergence is not None:
        print(json.dumps({"status": "FAIL", "reason": divergence}, ensure_ascii=False))
        return 1
    merged = merge(primary, secondary)
    args.out.write_text(json.dumps(merged) + "\n", encoding="utf-8")
    totals = merged["totals"]
    print(
        json.dumps(
            {
                "schema": "korpus.dialect-coverage-union.v1",
                "status": "PASS",
                "out": str(args.out.relative_to(ROOT)),
                "missing_branches": totals["missing_branches"],
                "branch_rate": round(totals["covered_branches"] / totals["num_branches"], 6),
                "statement_rate": round(totals["covered_lines"] / totals["num_statements"], 6),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
