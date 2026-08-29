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
  9. integrity_anchor, where present, resolves inside the repository and its sha256 matches
 10. content_probe, where present, is self-consistent and source_uri is its richest variant

Rule 9 exists because a source with no publication date and no revision trail (a ministry
web page) can be silently rewritten. The anchor is a captured snapshot whose digest is
recorded here; a changed page becomes a failed check rather than a quiet substitution.
An anchor that points outside the repository is not an anchor — nothing in CI can read it.

Rule 10 exists because HTTP 200 is not evidence of content. On zakon.rada.gov.ua the URL a
human bookmarks is a card carrying the act's title and nothing else; the text and its DOCX
annexes are reachable only at the /print variant (measured: 548-14 card 725 words vs /print
66069). An ingester pointed at the card succeeds, extracts almost nothing, and reports no
error. probe_source_content.py measures both variants over the network and records the
result as content_probe; this rule holds offline that source_uri is the variant that
measurement found richest, so a later edit cannot quietly point the catalog back at a card.

Nothing here approves anything. Ingestible means "may be staged"; every source still
passes through the human review workflow, and an unverified one may not be approved until
its index number or issuing order is confirmed against a second copy or the primary issuer.

    validate_doctrine_catalog.py           # human-readable summary
    validate_doctrine_catalog.py --json    # machine-readable report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.domain.models import AccessTier, AuthorityClass, Classification  # noqa: E402

CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"


class Summary(TypedDict):
    total: int
    ingestible: int
    blocked: int
    governing_authority: int
    analytical_outranked_by_official: int
    quarantine_on_ingest: int
    restricted_quarantined: int
    rights_blocked: int
    integrity_anchored: int
    content_probed: int


class Result(TypedDict):
    status: str
    problems: list[str]
    summary: Summary | None


EMPTY_SUMMARY: Summary = {
    "total": 0,
    "ingestible": 0,
    "blocked": 0,
    "governing_authority": 0,
    "analytical_outranked_by_official": 0,
    "quarantine_on_ingest": 0,
    "restricted_quarantined": 0,
    "rights_blocked": 0,
    "integrity_anchored": 0,
    "content_probed": 0,
}

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
    identifier = str(entry.get("id", "<no id>"))
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
        AccessTier.parse(entry["access_tier"])
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

    # (9) An undated source is pinned by a snapshot this repository can re-check.
    problems.extend(_anchor_problems(identifier, entry.get("integrity_anchor")))

    # (10) A measured source points at the variant that actually carries its text.
    problems.extend(
        _probe_problems(identifier, entry.get("content_probe"), str(entry.get("source_uri", "")))
    )

    return problems


def _probe_problems(identifier: str, probe: object, source_uri: str) -> list[str]:
    if probe is None:
        return []
    if not isinstance(probe, dict):
        return [f"{identifier}: content_probe is not an object"]

    variants = probe.get("variants")
    if not isinstance(variants, dict) or not variants:
        return [f"{identifier}: content_probe records no variants"]

    problems: list[str] = []
    measured: dict[str, int] = {}
    for name, data in variants.items():
        if not isinstance(data, dict) or not isinstance(data.get("words"), int):
            problems.append(f"{identifier}: content_probe variant {name!r} has no word count")
            continue
        measured[str(name)] = int(data["words"])
    if problems:
        return problems

    richest = max(measured, key=lambda name: measured[name])
    chosen = str(probe.get("chosen_variant", ""))
    if chosen not in measured:
        return [f"{identifier}: content_probe.chosen_variant {chosen!r} was never measured"]
    if measured[chosen] < measured[richest]:
        problems.append(
            f"{identifier}: content_probe chose {chosen!r} at {measured[chosen]} words over "
            f"{richest!r} at {measured[richest]} — the catalog points at the thinner variant"
        )
    if probe.get("chosen_words") != measured[chosen]:
        problems.append(
            f"{identifier}: content_probe.chosen_words {probe.get('chosen_words')!r} "
            f"contradicts the {chosen!r} measurement of {measured[chosen]}"
        )

    chosen_uri = str(variants[chosen].get("uri", "")) if isinstance(variants[chosen], dict) else ""
    if str(probe.get("chosen_uri", "")) != chosen_uri:
        problems.append(f"{identifier}: content_probe.chosen_uri is not the {chosen!r} variant uri")
    elif source_uri and source_uri != chosen_uri:
        problems.append(
            f"{identifier}: source_uri points at {source_uri} but the probe found the content "
            f"at {chosen_uri} — an ingester would fetch 200 OK and almost no text"
        )
    return problems


def _anchor_problems(identifier: str, anchor: object) -> list[str]:
    if anchor is None:
        return []
    if not isinstance(anchor, dict):
        return [f"{identifier}: integrity_anchor is not an object"]

    declared = str(anchor.get("sha256", ""))
    relative = str(anchor.get("path", ""))
    if len(declared) != 64 or any(c not in "0123456789abcdef" for c in declared):
        return [f"{identifier}: integrity_anchor.sha256 is not a sha256 digest"]
    if not relative:
        return [f"{identifier}: integrity_anchor has no path"]

    target = (ROOT / relative).resolve()
    try:
        target.relative_to(ROOT)
    except ValueError:
        return [
            f"{identifier}: integrity_anchor.path {relative!r} escapes the repository — "
            "an anchor CI cannot read is not an anchor"
        ]
    if not target.is_file():
        return [f"{identifier}: integrity_anchor.path {relative!r} is not a file in the tree"]

    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != declared:
        return [
            f"{identifier}: integrity_anchor mismatch on {relative} — "
            f"recorded {declared[:16]}…, tree holds {actual[:16]}… "
            "(the source changed, or the snapshot was edited)"
        ]
    return []


def evaluate(catalog: dict[str, object]) -> Result:
    sources = catalog.get("sources")
    if not isinstance(sources, list) or not sources:
        return {"status": "FAIL", "problems": ["catalog lists no sources"], "summary": None}

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
    summary: Summary = {
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
        "integrity_anchored": len([e for e in dicts if e.get("integrity_anchor")]),
        "content_probed": len([e for e in dicts if e.get("content_probe")]),
    }
    return {
        "status": "PASS" if not problems else "FAIL",
        "problems": problems,
        "summary": summary,
    }


def _is_normative(authority: str) -> bool:
    try:
        return bool(AuthorityClass(authority).is_normative)
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
                f"  {summary['integrity_anchored']} pinned by an in-tree snapshot digest, "
                f"{summary['content_probed']} content-probed"
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
