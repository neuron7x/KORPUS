#!/usr/bin/env python3
"""The doctrine catalog's own rules, made executable so prose cannot drift from them.

`config/corpus/doctrine_catalog_2026.json` is a curated bibliography, not corpus bytes.
Its value is the provenance discipline it carries per source: primary vs secondary,
open vs restricted vs commercially-sold, verified vs a single-sourced claim. That
discipline was written as flags; a flag nobody checks is a comment. This checks them, and
against the system's *own* taxonomy (`korpus.domain.models`) rather than a copy of it, so
the catalog cannot admit an authority class or classification the ingester would reject.

Fail-closed. Any violation is a non-zero exit and the entry is named. The rules:

  1. classification=restricted            => ingestible=false   (RESTRICTED never enters)
  2. rights_status not open               => ingestible=false   (rights clearance is GOV-006)
  3. source_kind=secondary_analysis       => authority=analytical (lowest, outranked by official)
  4. provenance_status != verified        => requires_second_source=true (enters QUARANTINED)
  5. ingestible=false                     => ingest_block_reason present
  6. ingestible=true                      => source_uri present (nothing enters via a guess)
  7. authority/classification/access_tier are valid domain enum values
  8. ids are unique

Nothing here approves anything. Ingestible means "may be staged"; every source still
passes through the human review workflow, and an unverified one may not be approved until
its index number or issuing order is confirmed against a second copy or the primary issuer.

    validate_doctrine_catalog.py           # human-readable summary
    validate_doctrine_catalog.py --json    # machine-readable report
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.domain.models import AccessTier, AuthorityClass, Classification  # noqa: E402

CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"

REQUIRED_FIELDS = (
    "id",
    "canonical_title",
    "issuer",
    "source_kind",
    "authority",
    "classification",
    "access_tier",
    "provenance_status",
    "rights_status",
    "ingestible",
)


def _entry_problems(entry: dict[str, object]) -> list[str]:
    identifier = entry.get("id", "<no id>")
    problems: list[str] = []

    missing = [
        field for field in REQUIRED_FIELDS if field not in entry or entry[field] in ("", None)
    ]
    if missing:
        problems.append(f"{identifier}: missing {', '.join(missing)}")
        # Without these the rules below cannot be evaluated; report and stop on this entry.
        return problems

    # (7) The taxonomy is the system's, not a copy.
    try:
        AuthorityClass(str(entry["authority"]))
    except ValueError:
        problems.append(f"{identifier}: unknown authority {entry['authority']!r}")
    try:
        classification = Classification(str(entry["classification"]))
    except ValueError:
        problems.append(f"{identifier}: unknown classification {entry['classification']!r}")
        classification = None
    try:
        AccessTier.parse(entry["access_tier"])  # type: ignore[arg-type]
    except (KeyError, ValueError):
        problems.append(f"{identifier}: unparseable access_tier {entry['access_tier']!r}")

    ingestible = bool(entry["ingestible"])

    # (1) RESTRICTED never enters.
    if classification is Classification.RESTRICTED and ingestible:
        problems.append(f"{identifier}: classification=restricted but ingestible=true")

    # (2) Rights clearance is a human decision.
    if str(entry["rights_status"]) != "open" and ingestible:
        problems.append(
            f"{identifier}: rights_status={entry['rights_status']!r} but ingestible=true "
            "(rights clearance is GOV-006, not code)"
        )

    # (3) Analysis is never normative.
    is_secondary = str(entry["source_kind"]) == "secondary_analysis"
    if is_secondary and str(entry["authority"]) != "analytical":
        problems.append(
            f"{identifier}: secondary_analysis must be authority=analytical, not "
            f"{entry['authority']!r} — analysis may not govern an answer"
        )

    # (4) A mirror or a single-sourced claim enters QUARANTINED.
    if str(entry["provenance_status"]) != "verified" and not entry.get("requires_second_source"):
        problems.append(
            f"{identifier}: provenance_status={entry['provenance_status']!r} but "
            "requires_second_source is not true"
        )

    # (5) A blocked entry says why.
    if not ingestible and not str(entry.get("ingest_block_reason", "")).strip():
        problems.append(f"{identifier}: ingestible=false but no ingest_block_reason")

    # (6) Nothing enters described by a guess.
    if ingestible and not str(entry.get("source_uri", "")).strip():
        problems.append(f"{identifier}: ingestible=true but no source_uri to fetch")

    return problems


def evaluate(catalog: dict[str, object]) -> dict[str, object]:
    sources = catalog.get("sources")
    if not isinstance(sources, list) or not sources:
        return {"status": "FAIL", "problems": ["catalog lists no sources"], "summary": {}}

    problems: list[str] = []
    seen: set[str] = set()
    for entry in sources:
        if not isinstance(entry, dict):
            problems.append("a source is not an object")
            continue
        identifier = str(entry.get("id", ""))
        if identifier in seen:
            problems.append(f"{identifier}: id listed twice")
        seen.add(identifier)
        problems.extend(_entry_problems(entry))

    dicts = [e for e in sources if isinstance(e, dict)]
    ingestible = [e for e in dicts if e.get("ingestible")]
    # Governing = an authority prior above analytical: official_ua/allied, manufacturer,
    # approved_training, historical. Analytical is normative too, but confined out of an
    # answer whenever any of these is present — so it governs only in their absence.
    analytical = [e for e in ingestible if str(e.get("authority")) == "analytical"]
    governing = [
        e
        for e in ingestible
        if str(e.get("authority")) != "analytical" and _is_normative(str(e.get("authority", "")))
    ]
    summary = {
        "total": len(dicts),
        "ingestible": len(ingestible),
        "blocked": len(dicts) - len(ingestible),
        "governing_authority": len(governing),
        "analytical_outranked_by_official": len(analytical),
        "quarantine_on_ingest": len([e for e in ingestible if e.get("requires_second_source")]),
        "restricted_quarantined": len(
            [e for e in dicts if str(e.get("classification")) == "restricted"]
        ),
        "rights_blocked": len([e for e in dicts if str(e.get("rights_status", "open")) != "open"]),
    }
    return {
        "status": "PASS" if not problems else "FAIL",
        "problems": problems,
        "summary": summary,
    }


def _is_normative(authority: str) -> bool:
    try:
        return AuthorityClass(authority).is_normative
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    result = evaluate(catalog)

    if arguments.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result["summary"]
        print(f"doctrine catalog: {result['status']}")
        if summary:
            print(
                f"  {summary['total']} sources · {summary['ingestible']} ingestible "
                f"({summary['governing_authority']} governing, "
                f"{summary['analytical_outranked_by_official']} analytical/outranked) · "
                f"{summary['quarantine_on_ingest']} enter quarantine pending a second source"
            )
            print(
                f"  blocked: {summary['blocked']} "
                f"({summary['restricted_quarantined']} RESTRICTED, "
                f"{summary['rights_blocked']} rights-restricted)"
            )
        for problem in result["problems"]:
            print(f"  ✗ {problem}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
