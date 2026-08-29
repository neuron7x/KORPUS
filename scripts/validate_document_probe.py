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
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
SHA = re.compile(r"^[0-9a-f]{64}$")
PROBE_MAX_AGE_DAYS = 365
#: Below this a "text layer" is page furniture — headers, page numbers, a stamp — not text.
MIN_WORDS_PER_PAGE = 20


def _named_system_problems(identifier: str, probe: dict) -> list[str]:
    """The index of named systems has to be an index, not a list of hopes.

    A name recorded with a count of zero says the reading found it when it did not, and a
    `named_systems_total` under the number of entries listed means the two were written by
    different passes. Both are cheap to state and cheap to contradict — which is the only
    reason the index is worth carrying at all.
    """
    systems = probe.get("named_systems")
    if systems is None:
        return []
    if not isinstance(systems, dict):
        return [f"{identifier}: document_probe.named_systems is not an object"]
    found: list[str] = []
    bad = [k for k, v in systems.items() if not isinstance(v, int) or isinstance(v, bool) or v <= 0]
    if bad:
        found.append(
            f"{identifier}: named_systems has non-positive counts for "
            f"{', '.join(sorted(bad)[:4])} — a name listed with zero hits is a "
            "claim the reading does not support"
        )
    total = probe.get("named_systems_total")
    if isinstance(total, int) and not isinstance(total, bool) and total < len(systems):
        found.append(
            f"{identifier}: named_systems_total {total} is under the {len(systems)} entries listed"
        )
    return found


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
        # НЕ `words <= 0`: нуль слів — це саме скан, тобто випадок, заради якого
        # цей гейт існує, і виходити тут означало б пропускати його без перевірки
        # `machine_readable`. Мутант `<` → `<=` вижив рівно на цьому.

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

        # A readable document blocked for rights or currency is somebody else's rule —
        # rules 2 and 12 own that. Written as the absence of a branch rather than a bare
        # `pass`, which reads as an unfinished thought and is refused by the pseudo-runtime
        # check for exactly that reason.
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

        found.extend(_named_system_problems(identifier, probe))

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


#: Негативні контролі — ДАНІ: назва, зміни до еталонного запису (або готовий список),
#: і чи МУСИТЬ гейт на цьому впасти. Таблицею, а не тілом функції, з тієї ж причини,
#: що і в validate_content_signals: стеля рядків рахує проби як логіку, тобто тисне
#: проти покриття. Реєстр даних для цього має виняток; перелік у diff читається як
#: перелік, а не як суцільний текст.
PROBE_BASE: dict[str, Any] = {
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
        "probed_on": "",  # проставляється в _probe_entries: «сьогодні»
    },
}
_FLOOR_WORDS = 10 * MIN_WORDS_PER_PAGE

PROBES: tuple[tuple[str, object, bool], ...] = (
    ("чиста база проходить", {}, False),
    ("джерело без document_probe ігнорується", [{"id": "T"}], False),
    ("probe не об'єкт", {"document_probe": "yes"}, True),
    ("вимір ІНШОГО документа", {"uri": "https://example.org/b.pdf"}, True),
    ("сторінок нуль", {"pages": 0}, True),
    ("слів від'ємно", {"words": -1}, True),
    ("скан без тексту названо машинночитаним", {"words": 200, "machine_readable": True}, True),
    ("текст є, а машинночитаним не названо", {"machine_readable": False}, True),
    ("нечитане, але ingestible", {"words": 200, "machine_readable": False}, True),
    ("machine_readable не булеве", {"machine_readable": "так"}, True),
    ("немає text_sha256", {"text_sha256": ""}, True),
    ("text_sha256 не хеш", {"text_sha256": "deadbeef"}, True),
    ("система з нульовою частотою", {"named_systems": {"T-72": 0}}, True),
    (
        "систем більше, ніж заявлено в total",
        {"named_systems": {"A": 1, "B": 2}, "named_systems_total": 1},
        True,
    ),
    ("дата не ISO", {"probed_on": "вчора"}, True),
    ("вимір протух", {"probed_on": "2019-01-01"}, True),
    ("дата в майбутньому", {"probed_on": "2099-01-01"}, True),
    ("скан на 0 слів, названий машинночитаним", {"words": 0, "machine_readable": True}, True),
    (
        "скан на 0 слів, чесно позначений і не інжеститься",
        {"words": 0, "machine_readable": False, "ingestible": False},
        False,
    ),
    ("документ на одну сторінку", {"pages": 1, "words": 300, "machine_readable": True}, False),
    (
        "рівно на порозі слів/сторінку — ще НЕ читаний",
        {"pages": 10, "words": _FLOOR_WORDS, "machine_readable": False, "ingestible": False},
        False,
    ),
    (
        "рівно на порозі, але названий читаним",
        {"pages": 10, "words": _FLOOR_WORDS, "machine_readable": True},
        True,
    ),
    (
        "на одне слово вище порога — читаний",
        {"pages": 10, "words": _FLOOR_WORDS + 1, "machine_readable": True},
        False,
    ),
    ("вимір рівно на межі віку — ще чинний", {"_probed_days_ago": PROBE_MAX_AGE_DAYS}, False),
    ("вимір на день за межею", {"_probed_days_ago": PROBE_MAX_AGE_DAYS + 1}, True),
    (
        "система з частотою рівно 1",
        {"named_systems": {"Lancet": 1}, "named_systems_total": 1},
        False,
    ),
    ("вимір зроблено сьогодні", {"_probed_days_ago": 0}, False),
)


def _probe_entries(changes: object) -> list[dict[str, Any]]:
    """Записи для однієї проби: готовий список або еталон із застосованими змінами."""
    if isinstance(changes, list):
        return changes
    if not isinstance(changes, dict):
        raise TypeError(f"проба {changes!r} — ні список записів, ні набір змін")
    entry: dict[str, Any] = copy.deepcopy(PROBE_BASE)
    probe = entry["document_probe"]
    probe["probed_on"] = date.today().isoformat()
    for key, value in changes.items():
        if key == "_probed_days_ago":
            probe["probed_on"] = (date.today() - timedelta(days=int(value))).isoformat()
        elif key in entry:
            entry[key] = value
        else:
            probe[key] = value
    return [entry]


def selftest() -> int:
    """Кожне правило показане таким, що падає."""
    bad = 0
    for name, changes, want_fail in PROBES:
        got = bool(problems(_probe_entries(changes)))
        if got != want_fail:
            bad += 1
            print(f"  ✗ {name}: очікували {'падіння' if want_fail else 'PASS'}")
        else:
            print(f"  ✓ {name}")
    ok_floors = (MIN_WORDS_PER_PAGE, PROBE_MAX_AGE_DAYS) == (20, 365)
    bad += not ok_floors
    print(
        f"  {'✓' if ok_floors else '✗'} пороги: {MIN_WORDS_PER_PAGE} слів/стор., "
        f"{PROBE_MAX_AGE_DAYS} днів"
    )
    total = len(PROBES) + 1
    print(f"негативний контроль: {total - bad}/{total}")
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
