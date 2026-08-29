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

And it reads the portal's own legal-status marker. Substring-matching "втратив чинність"
against the page text does not work: order 402 says it of its own clause 2, and resolution
704 says it of the eleven resolutions it repeals — both are in force, and a naive check
calls both dead. The portal states the act's own status structurally as
`<span class="valid">чинний</span>` or `<span class="invalid">втратив чинність</span>`;
confirmed against law 565-XII (repealed 2015), which is the only one of the sources probed
so far that returns `invalid`. Rule 12 refuses to let a repealed act stay ingestible: a
soldier asking what he is entitled to must not be answered out of a law that no longer
applies.

Each variant is fetched more than once and scored by its largest reading. The portal is not
deterministic: on 2026-08-29 the card for z0927-20 returned 736 words in one run and 5583 in
another, minutes apart, both HTTP 200. A single sample let one thin response repoint a
source onto the weaker variant and rewrite the recorded measurement to match — the probe
undoing its own earlier, better reading. Taking the maximum over samples means a short
response can only fail to raise the score, never lower it.

    probe_source_content.py            # report only
    probe_source_content.py --write    # record, repoint source_uri, capture attachments
    probe_source_content.py --samples 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
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
# The act's own status, as the portal marks it — not a phrase found anywhere in the text.
LEGAL_STATUS = re.compile(r'<span class="(valid|invalid)">\s*([^<]{1,60}?)\s*</span>')


class Measurement(TypedDict):
    """What one URL variant actually returned, in the terms rule 10 checks."""

    uri: str
    words: int
    tables: int
    attachments: list[str]


class Survey(TypedDict):
    words: int
    opening: str
    surveyed_with: str
    surveyed_on: str
    note: str


class Anchor(TypedDict, total=False):
    uri: str
    path: str
    sha256: str
    bytes: int
    captured_on: str
    extractor_supports_format: bool
    unreadable_content_survey: Survey


class Probe(TypedDict):
    probed_on: str
    variants: dict[str, Measurement]
    chosen_variant: str
    chosen_uri: str
    chosen_words: int
    samples_per_variant: int
    word_readings: dict[str, list[int]]
    required_attachments: list[str]
    legal_status: str
    legal_status_text: str


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
        readable = target.suffix.lower() in SUPPORTED_SUFFIXES
        anchor: Anchor = {
            "uri": uri,
            "path": str(target.relative_to(ROOT)),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "captured_on": probe["probed_on"],
            "extractor_supports_format": readable,
        }
        if not readable:
            survey = _survey(target, probe["probed_on"])
            if survey is not None:
                anchor["unreadable_content_survey"] = survey
        anchors.append(anchor)
    return anchors


def _survey(target: Path, probed_on: str) -> Survey | None:
    """Say what an unreadable capture holds, without pretending it was ingested.

    Fourteen of the captures are OLE2 .doc — forms and specimen registers annexed to the
    statutes. The extractor does not accept the format and should not grow a parser for it:
    that is a new supply-chain dependency for 2716 words of blank forms. Rule 13 asks for a
    survey instead, so the material sits outside the corpus rather than outside anyone's
    knowledge. LibreOffice does the reading; if it is absent the anchor carries no survey
    and rule 13 fails, which is the correct outcome — a missing survey is a missing fact.
    """
    if shutil.which("soffice") is None:
        return None
    with tempfile.TemporaryDirectory() as workdir:
        converted = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "txt:Text (encoded):UTF8",
                "--outdir",
                workdir,
                str(target),
            ],
            capture_output=True,
            check=False,
            timeout=180,
        )
        if converted.returncode != 0:
            return None
        produced = Path(workdir) / f"{target.stem}.txt"
        if not produced.is_file():
            return None
        text = re.sub(r"\s+", " ", produced.read_text(encoding="utf-8").lstrip("\ufeff")).strip()
    version = subprocess.run(
        ["soffice", "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    return {
        "words": len(text.split()),
        "opening": text[:120],
        "surveyed_with": version or "LibreOffice",
        "surveyed_on": probed_on,
        "note": (
            "Формат, який korpus.infrastructure.extraction не приймає. Опис зроблений "
            "одноразово стороннім конвертером і не є інжестом: вміст залишається поза "
            "корпусом, а не поза відомістю."
        ),
    }


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


def probe(entry: dict[str, object], timeout: int, sample_count: int = 3) -> Probe | None:
    uri = str(entry.get("source_uri", ""))
    if not any(host in uri for host in PROBED_HOSTS):
        return None

    variants = _variants(uri)
    samples = {
        name: [_measure(_fetch(variant, timeout), variant) for _ in range(sample_count)]
        for name, variant in variants.items()
    }
    measured = {
        name: max(readings, key=lambda reading: reading["words"])
        for name, readings in samples.items()
    }
    richest = max(measured, key=lambda name: measured[name]["words"])
    status, status_text = _legal_status(_fetch(variants["card"], timeout))
    return {
        "probed_on": date.today().isoformat(),
        "variants": measured,
        "chosen_variant": richest,
        "chosen_uri": measured[richest]["uri"],
        "chosen_words": measured[richest]["words"],
        "samples_per_variant": sample_count,
        "word_readings": {
            name: sorted(reading["words"] for reading in readings)
            for name, readings in samples.items()
        },
        "required_attachments": measured[richest]["attachments"],
        "legal_status": status,
        "legal_status_text": status_text,
    }


def _legal_status(card_html: str) -> tuple[str, str]:
    """Read the act's status from the portal's marker, never from its prose."""
    for marker, text in LEGAL_STATUS.findall(card_html):
        if "чинн" in text.lower():
            return marker, text
    return "unknown", ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="record results in the catalog")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        help="fetches per variant; the largest reading scores it (the portal varies)",
    )
    arguments = parser.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    repointed: list[str] = []
    probed = 0

    for entry in catalog["sources"]:
        result = probe(entry, arguments.timeout, arguments.samples)
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
            f"status={result['legal_status']:7} "
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
