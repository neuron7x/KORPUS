#!/usr/bin/env python3
"""Gate: a measurement of what a document FILE contains — and it stays honest about pages.

`content_probe` demands a `card` and a `print` variant, because it was built for
zakon.rada pages where those two really differ in length. A PDF has no such variants, and
inventing them to satisfy the shape would be form without measurement. So a file-backed
source gets its own reading: pages, words, structure, and an index of the named systems
it actually mentions.

Why an index of names and not a summary: "this manual covers Russian equipment" is a
promise. "T-72B3 appears 4 times, TOS-1A 5, Orlan-10 4, across appendices A–K" is a claim
somebody can contradict with the same two tools. The catalogue should carry the second kind.

The rule that matters most here is `machine_readable`. A 280-page scan with no text layer
reports pages=280 and words=0, and a catalogue that records only the page count says the
document is available when nothing can read it. Words per page decides, not the file size.

`--selftest` mutates each rule and requires it to fire.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
SHA = re.compile(r"^[0-9a-f]{64}$")
PROBE_MAX_AGE_DAYS = 365
#: Below this a "text layer" is page furniture — headers, page numbers, a stamp — not text.
MIN_WORDS_PER_PAGE = 20


def problems(entries: list[dict]) -> list[str]:
    found: list[str] = []
    for entry in entries:
        identifier = str(entry.get("id", "<no id>"))
        probe = entry.get("document_probe")
        if probe is None:
            continue
        if not isinstance(probe, dict):
            found.append(f"{identifier}: document_probe is not an object")
            continue

        uri = str(probe.get("uri", ""))
        if uri != str(entry.get("source_uri", "")):
            found.append(
                f"{identifier}: document_probe.uri {uri!r} is not the source_uri — "
                "a reading of another document is not a measurement of this one"
            )

        try:
            pages = int(str(probe.get("pages")))
            words = int(str(probe.get("words")))
        except ValueError:
            found.append(f"{identifier}: document_probe pages/words are not integers")
            continue
        if pages <= 0:
            found.append(f"{identifier}: document_probe.pages is {pages}")
            continue
        if words < 0:
            found.append(f"{identifier}: document_probe.words is {words}")
            continue

        per_page = words / pages
        claimed = probe.get("machine_readable")
        if not isinstance(claimed, bool):
            found.append(f"{identifier}: document_probe.machine_readable is not a boolean")
        elif claimed is not (per_page > MIN_WORDS_PER_PAGE):
            # The defect this catches: a scan reports pages and zero words, and something
            # downstream reads "we have the document". Availability is not readability.
            found.append(
                f"{identifier}: machine_readable={claimed} but the reading is "
                f"{per_page:.1f} words/page over {pages} pages "
                f"(floor {MIN_WORDS_PER_PAGE}) — a page count is not a text layer"
            )

        if claimed is True and entry.get("ingestible") is False:
            pass  # readable but blocked for rights or currency: not this gate's business
        if claimed is False and entry.get("ingestible"):
            found.append(
                f"{identifier}: the probe found no readable text layer, yet ingestible=true — "
                "the extractor would take in a scan and produce nothing"
            )

        for field in ("text_sha256", "file_sha256"):
            value = str(probe.get(field, ""))
            if value and not SHA.match(value):
                found.append(f"{identifier}: document_probe.{field} is not a sha256 digest")
        if not str(probe.get("text_sha256", "")).strip():
            found.append(
                f"{identifier}: document_probe has no text_sha256 — without it a later "
                "reading cannot tell a changed document from a changed extractor"
            )

        systems = probe.get("named_systems")
        if systems is not None:
            if not isinstance(systems, dict):
                found.append(f"{identifier}: document_probe.named_systems is not an object")
            else:
                bad = [
                    k
                    for k, v in systems.items()
                    if not isinstance(v, int) or isinstance(v, bool) or v <= 0
                ]
                if bad:
                    found.append(
                        f"{identifier}: named_systems has non-positive counts for "
                        f"{', '.join(sorted(bad)[:4])} — a name listed with zero hits is a "
                        "claim the reading does not support"
                    )
                total = probe.get("named_systems_total")
                if isinstance(total, int) and not isinstance(total, bool) and total < len(systems):
                    found.append(
                        f"{identifier}: named_systems_total {total} is under the "
                        f"{len(systems)} entries listed"
                    )

        try:
            age = (date.today() - date.fromisoformat(str(probe.get("probed_on")))).days
        except ValueError:
            found.append(f"{identifier}: document_probe.probed_on is not an ISO date")
            continue
        if age > PROBE_MAX_AGE_DAYS:
            found.append(f"{identifier}: document_probe read {age} days ago, over the floor")
        if age < 0:
            found.append(f"{identifier}: document_probe.probed_on is in the future")
    return found


def selftest() -> int:
    base: dict[str, Any] = {
        "id": "T",
        "source_uri": "https://example.org/a.pdf",
        "ingestible": True,
        "document_probe": {
            "uri": "https://example.org/a.pdf",
            "pages": 280,
            "words": 100992,
            "machine_readable": True,
            "text_sha256": "a" * 64,
            "file_sha256": "b" * 64,
            "named_systems": {"T-72": 19},
            "named_systems_total": 78,
            "probed_on": date.today().isoformat(),
        },
    }

    def mutate(**changes: object) -> list[dict[str, Any]]:
        entry: dict[str, Any] = copy.deepcopy(base)
        probe = entry["document_probe"]
        if not isinstance(probe, dict):  # pragma: no cover - built as a dict above
            raise TypeError("document_probe must be an object")
        for key, value in changes.items():
            (entry if key in entry else probe)[key] = value
        return [entry]

    cases = [
        ("чиста база проходить", [copy.deepcopy(base)], False),
        ("джерело без document_probe ігнорується", [{"id": "T"}], False),
        ("probe не об'єкт", mutate(document_probe="yes"), True),
        ("вимір ІНШОГО документа", mutate(uri="https://example.org/b.pdf"), True),
        ("сторінок нуль", mutate(pages=0), True),
        ("слів від'ємно", mutate(words=-1), True),
        ("скан без тексту названо машинночитаним", mutate(words=200, machine_readable=True), True),
        ("текст є, а машинночитаним не названо", mutate(machine_readable=False), True),
        ("нечитане, але ingestible", mutate(words=200, machine_readable=False), True),
        ("machine_readable не булеве", mutate(machine_readable="так"), True),
        ("немає text_sha256", mutate(text_sha256=""), True),
        ("text_sha256 не хеш", mutate(text_sha256="deadbeef"), True),
        ("система з нульовою частотою", mutate(named_systems={"T-72": 0}), True),
        (
            "систем більше, ніж заявлено в total",
            mutate(named_systems={"A": 1, "B": 2}, named_systems_total=1),
            True,
        ),
        ("дата не ISO", mutate(probed_on="вчора"), True),
        ("вимір протух", mutate(probed_on="2019-01-01"), True),
        ("дата в майбутньому", mutate(probed_on="2099-01-01"), True),
    ]
    bad = 0
    for name, entries, want_fail in cases:
        got = bool(problems(entries))
        if got != want_fail:
            bad += 1
            print(f"  ✗ {name}: очікували {'падіння' if want_fail else 'PASS'}")
        else:
            print(f"  ✓ {name}")
    print(f"негативний контроль: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    entries = data["sources"] if isinstance(data, dict) else data
    found = problems(entries)
    if found:
        print("document probes: FAIL")
        for item in found:
            print(f"  ✗ {item}")
        return 1
    probed = [e for e in entries if isinstance(e.get("document_probe"), dict)]
    pages = sum(int(e["document_probe"]["pages"]) for e in probed)
    words = sum(int(e["document_probe"]["words"]) for e in probed)
    print("document probes: PASS")
    print(f"  {len(probed)} documents read: {pages} pages, {words} words")
    print("  its own axis: volume and structure, never an assessment of what the text claims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
