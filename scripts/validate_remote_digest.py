#!/usr/bin/env python3
"""Gate: evidence for an artifact too large to hold in the tree — and it stays its own axis.

Rule 11 requires a captured file because otherwise there is no subject to compare against.
That is right, and it leaves 74 sources whose artifact is a 1.5–145 MB PDF unprovable: an
`integrity_anchor` with no file is the claim "I saw these bytes", which nobody can confirm
or refute. What separates evidence from decoration is whether a CHEAP procedure lets a
third party get the same result or contradict it — and hashing 145 MB is not cheap, so
nobody ever would.

`remote_digest` records what two Range requests see: sha256 of the first 65536 bytes, of
the last 65536, and the Content-Length. Rechecking costs 128 KB. Replacing the document at
the same URL moves the length, the tail, or the head — a PDF keeps its xref table at the
end, so almost any edit shifts the tail. A server without Range support fails honestly:
the field is not filled and the class is not assigned.

THE LINE THIS GATE EXISTS TO HOLD: a remote_digest proves the artifact EXISTED and was
THIS one. It measures nothing about the content. It is not a content_probe, it does not
enter attachments_captured, and a source carrying one is still uninspected. Folding the
two together would hand 67 sources "evidence" without measuring a single one of them.

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

from iso_dates import iso_date

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
REQUIRED = ("uri", "content_length", "head_sha256", "tail_sha256", "probed_on", "window_bytes")
SHA = re.compile(r"^[0-9a-f]{64}$")
#: A digest is a reading of a live URL and ages out like any other reading.
DIGEST_MAX_AGE_DAYS = 365
#: Below this the two windows overlap and the "head" and "tail" stop being independent.
MIN_WINDOW = 4096


def problems(entries: list[dict]) -> list[str]:
    found: list[str] = []
    for entry in entries:
        identifier = str(entry.get("id", "<no id>"))
        digest = entry.get("remote_digest")
        if digest is None:
            continue
        if not isinstance(digest, dict):
            found.append(f"{identifier}: remote_digest is not an object")
            continue

        missing = [f for f in REQUIRED if not str(digest.get(f, "")).strip()]
        if missing:
            found.append(
                f"{identifier}: remote_digest is missing {', '.join(missing)} — "
                "a partial reading cannot be repeated, so it proves nothing"
            )
            continue

        for field in ("head_sha256", "tail_sha256"):
            if not SHA.match(str(digest[field])):
                found.append(f"{identifier}: remote_digest.{field} is not a sha256 digest")

        uri = str(digest["uri"])
        if uri != str(entry.get("source_uri", "")):
            # A digest copied from a neighbouring entry describes another file and would
            # clear a source nobody read. Same defect class as a shared integrity_anchor.
            found.append(
                f"{identifier}: remote_digest.uri {uri!r} is not the source_uri — "
                "a reading of a different artifact is not evidence for this one"
            )

        if str(digest["head_sha256"]) == str(digest["tail_sha256"]):
            # Equal windows mean the file is smaller than one window, or the same range
            # was fetched twice and the tail request silently returned the head.
            found.append(
                f"{identifier}: head_sha256 equals tail_sha256 — either the artifact is "
                "smaller than one window, or the tail request returned the head"
            )

        try:
            window = int(str(digest["window_bytes"]))
            length = int(str(digest["content_length"]))
        except ValueError:
            found.append(
                f"{identifier}: remote_digest window_bytes/content_length are not integers"
            )
            continue
        if window < MIN_WINDOW:
            found.append(
                f"{identifier}: window_bytes is {window}, below {MIN_WINDOW} — "
                "a window this small does not identify a document"
            )
        if length <= 0:
            found.append(f"{identifier}: content_length is {length}")
        elif length < 2 * window:
            found.append(
                f"{identifier}: content_length {length} is under two windows ({2 * window}) — "
                "head and tail overlap, so they are not two independent readings"
            )

        try:
            age = (date.today() - iso_date(str(digest["probed_on"]))).days
        except ValueError:
            found.append(f"{identifier}: remote_digest.probed_on is not an ISO date")
            continue
        if age > DIGEST_MAX_AGE_DAYS:
            found.append(
                f"{identifier}: remote_digest read {age} days ago, over the "
                f"{DIGEST_MAX_AGE_DAYS}-day floor"
            )
        if age < 0:
            found.append(f"{identifier}: remote_digest.probed_on is in the future")

        # The class must not present itself as a measurement of content.
        for forbidden in ("content_probe", "attachment_anchors"):
            if forbidden in digest:
                found.append(
                    f"{identifier}: remote_digest carries {forbidden} — this class proves the "
                    "artifact existed and was this one, and says nothing about its content"
                )
    return found


def selftest() -> int:
    base: dict[str, Any] = {
        "id": "T",
        "source_uri": "https://example.org/a.pdf",
        "remote_digest": {
            "uri": "https://example.org/a.pdf",
            "content_length": "5000000",
            "head_sha256": "a" * 64,
            "tail_sha256": "b" * 64,
            "window_bytes": "65536",
            "probed_on": date.today().isoformat(),
        },
    }

    def mutate(**changes: object) -> list[dict[str, Any]]:
        entry: dict[str, Any] = copy.deepcopy(base)
        digest = entry["remote_digest"]
        if not isinstance(digest, dict):  # pragma: no cover - built as a dict above
            raise TypeError("remote_digest must be an object")
        for key, value in changes.items():
            (entry if key in entry else digest)[key] = value
        return [entry]

    cases = [
        ("чиста база проходить", [copy.deepcopy(base)], False),
        ("джерело без remote_digest ігнорується", [{"id": "T"}], False),
        ("digest не об'єкт", mutate(remote_digest="yes"), True),
        ("немає head_sha256", mutate(head_sha256=""), True),
        ("немає probed_on", mutate(probed_on=""), True),
        ("head не sha256", mutate(head_sha256="deadbeef"), True),
        ("digest від ІНШОГО файла", mutate(uri="https://example.org/b.pdf"), True),
        ("голова = хвіст", mutate(tail_sha256="a" * 64), True),
        ("вікно замале", mutate(window_bytes="512"), True),
        ("файл менший за два вікна", mutate(content_length="100000"), True),
        ("довжина нуль", mutate(content_length="0"), True),
        ("довжина не число", mutate(content_length="багато"), True),
        ("дата не ISO", mutate(probed_on="вчора"), True),
        ("вимір протух", mutate(probed_on="2019-01-01"), True),
        ("дата в майбутньому", mutate(probed_on="2099-01-01"), True),
        ("видає себе за вимір вмісту", mutate(content_probe={"variants": {}}), True),
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
        print("remote digests: FAIL")
        for item in found:
            print(f"  ✗ {item}")
        return 1
    withd = [e for e in entries if isinstance(e.get("remote_digest"), dict)]
    files = [
        e
        for e in entries
        if str(e.get("source_uri", "")).lower().split("?")[0].endswith((".pdf", ".doc", ".docx"))
    ]
    print("remote digests: PASS")
    print(f"  {len(withd)} of {len(files)} file-backed sources carry a 128 KB-recheckable digest")
    print(
        "  counted as its OWN axis: existence and identity, never content — a source here "
        "is still uninspected"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
