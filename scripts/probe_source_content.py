#!/usr/bin/env python3
"""Measure what a catalogued source actually returns, because reachable is not complete.

Every source in `doctrine_catalog_2026.json` was verified as HTTP 200. That check is
weaker than it looks. On zakon.rada.gov.ua the URL a human bookmarks is a *card*: title,
registration number, revision date, and nothing else. The act's text — and the links to
its DOCX annexes — live only at the `/print` variant. Measured 2026-08-29:

    548-14    card    725 words → /print  66069 words   (×91, 27 tables)
    z0927-20  card    736 words → /print   4790 words   (the 927-position roster is a
                                                         DOCX linked *only* from /print)

An ingester pointed at the card fetches 200 OK, parses clean HTML, extracts a title and
almost no body, and reports success. Nothing fails. That is the failure: a source that
looks ingested and carries none of its content.

The inverse also occurs — for z0372-26 the card carries *more* than /print — so "append
/print" is not a rule. The variant must be measured, not assumed.

This probe needs the network, so it cannot be a CI gate. It writes its measurement into
the catalog as `content_probe`; `validate_doctrine_catalog.py` rule 10 then enforces
offline that `source_uri` is the variant the probe found richest. The measurement is
evidence with a date on it; the gate is the part that cannot drift.

It also captures the attachments it finds. For order №317 the /print page is 4790 words
and the roster it publishes — 1068 rows, 1773 distinct MOS codes — is a DOCX that page only
links to; naming an attachment is not fetching one. Captures land in
config/corpus/attachments/ and rule 11 holds their digests, along with an honest mark of
whether this system's extractor can read each format (six of the seven are OLE2 .doc and it
cannot).

    probe_source_content.py            # report only
    probe_source_content.py --write    # record, repoint source_uri, capture attachments
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api/src"))

from korpus.infrastructure.extraction import SUPPORTED_SUFFIXES

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
ATTACHMENTS = ROOT / "config/corpus/attachments"

PROBED_HOSTS = ("zakon.rada.gov.ua",)
ATTACHMENT = re.compile(r'href="([^"]+\.(?:docx|doc|rtf|xlsx|xls|pdf))"', re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")


class Measurement(TypedDict):
    """What one URL variant actually returned, in the terms rule 10 checks."""

    uri: str
    words: int
    tables: int
    attachments: list[str]


class Anchor(TypedDict):
    uri: str
    path: str
    sha256: str
    bytes: int
    captured_on: str
    extractor_supports_format: bool


class Probe(TypedDict):
    probed_on: str
    variants: dict[str, Measurement]
    chosen_variant: str
    chosen_uri: str
    chosen_words: int
    required_attachments: list[str]


def _capture_attachments(identifier: str, probe: Probe, timeout: int) -> list[Anchor]:
    """Fetch what the page only points to, so rule 11 has something to hold."""
    ATTACHMENTS.mkdir(parents=True, exist_ok=True)
    anchors: list[Anchor] = []
    for uri in probe["required_attachments"]:
        name = f"{identifier}__{uri.rsplit('/', 1)[-1]}"
        target = ATTACHMENTS / name
        payload = _fetch_bytes(uri, probe["chosen_uri"], timeout)
        target.write_bytes(payload)
        target.chmod(0o644)
        anchors.append(
            {
                "uri": uri,
                "path": str(target.relative_to(ROOT)),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "captured_on": probe["probed_on"],
                "extractor_supports_format": target.suffix.lower() in SUPPORTED_SUFFIXES,
            }
        )
    return anchors


def _fetch_bytes(uri: str, referer: str, timeout: int) -> bytes:
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "-L",
            "--max-time",
            str(timeout),
            "-A",
            "Mozilla/5.0 (KORPUS provenance probe)",
            "-e",
            referer,
            uri,
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl exit {result.returncode} on {uri}")
    return result.stdout


def _fetch(uri: str, timeout: int) -> str:
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "-L",
            "--compressed",
            "--max-time",
            str(timeout),
            "-A",
            "Mozilla/5.0 (KORPUS provenance probe)",
            "-e",
            "https://zakon.rada.gov.ua/",
            uri,
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl exit {result.returncode} on {uri}")
    return result.stdout.decode("utf-8", "replace")


def _measure(html: str, uri: str) -> Measurement:
    return {
        "uri": uri,
        "words": len(TAG.sub(" ", html).split()),
        "tables": html.count("<table"),
        "attachments": sorted({_absolute(href, uri) for href in ATTACHMENT.findall(html)}),
    }


def _absolute(href: str, base: str) -> str:
    if href.startswith("http"):
        return href
    origin = "/".join(base.split("/")[:3])
    return origin + href if href.startswith("/") else f"{origin}/{href}"


def _variants(uri: str) -> dict[str, str]:
    """Variants of the *act*, not of whatever the catalog currently points at.

    A second run reads back a source_uri the first run already repointed to /print. Without
    stripping it the probe would compare /print against /print/print, label the first "card",
    and report a card richer than its print variant — the measurement inverted by its own
    previous success. Normalise to the act's base URI so the run is idempotent.
    """
    base = uri.rstrip("/")
    if base.endswith("/print"):
        base = base[: -len("/print")]
    return {"card": base, "print": base + "/print"}


def probe(entry: dict[str, object], timeout: int) -> Probe | None:
    uri = str(entry.get("source_uri", ""))
    if not any(host in uri for host in PROBED_HOSTS):
        return None

    variants = _variants(uri)
    measured = {
        name: _measure(_fetch(variant, timeout), variant) for name, variant in variants.items()
    }
    richest = max(measured, key=lambda name: measured[name]["words"])
    return {
        "probed_on": date.today().isoformat(),
        "variants": measured,
        "chosen_variant": richest,
        "chosen_uri": measured[richest]["uri"],
        "chosen_words": measured[richest]["words"],
        "required_attachments": measured[richest]["attachments"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="record results in the catalog")
    parser.add_argument("--timeout", type=int, default=60)
    arguments = parser.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    repointed: list[str] = []
    probed = 0

    for entry in catalog["sources"]:
        result = probe(entry, arguments.timeout)
        if result is None:
            continue
        probed += 1
        card = result["variants"]["card"]["words"]
        best = result["chosen_words"]
        moved = result["chosen_uri"] != entry.get("source_uri")
        print(
            f"{entry['id']:26} card={card:7} best={best:7} "
            f"variant={result['chosen_variant']:5} "
            f"attachments={len(result['required_attachments'])} "
            f"{'REPOINT' if moved else ''}"
        )
        if moved:
            repointed.append(str(entry["id"]))
        if arguments.write:
            entry["content_probe"] = result
            entry["source_uri"] = result["chosen_uri"]
            if result["required_attachments"]:
                entry["attachment_anchors"] = _capture_attachments(
                    str(entry["id"]), result, arguments.timeout
                )

    if arguments.write:
        CATALOG.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nwritten: {probed} probed, {len(repointed)} repointed")
    else:
        print(f"\n{probed} probed, {len(repointed)} would be repointed (run with --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
