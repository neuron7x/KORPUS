#!/usr/bin/env python3
"""Gate: a web source the operator has expressly reserved against us never becomes ingestible.

HTTP 200 on a government domain is not permission. Two mechanisms say otherwise, and the
catalog checked neither until 2026-08-29:

  * `Content-Signal:` in robots.txt — `ai-train=no`, `ai-input=no`, `use=reference`.
    These bind everyone, and `use=reference` is the subtle one: cite and link, do not
    hold the full text. Some operators (globalsecurity.org, war-sanctions.gur.gov.ua)
    name Article 4 of EU Directive 2019/790 as the express reservation of rights.
  * `User-agent: ClaudeBot` / `anthropic-ai` with `Disallow: /` — a refusal aimed at us.

A `Disallow: /` for Bytespider or PerplexityBot is a refusal aimed at SOMEONE ELSE.
Reading it as a restriction on this system would drop permitted sources for no reason,
so the two are recorded separately and only `reserved_against_us` blocks ingestion.

The probe is a measurement of a live file, so it ages out like `content_probe` does:
a signal read a year ago says nothing about the site's terms today.

Run `--selftest` to prove the gate can fail; a rule nobody has seen go red is not a gate.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
#: How long a reading of a live robots.txt stays a reading.
SIGNAL_MAX_AGE_DAYS = 180
VERDICTS = {"reserved_against_us", "reserved_against_others", "no_restriction", "no_robots"}


def _age_days(stamp: str) -> int | None:
    try:
        return (date.today() - date.fromisoformat(stamp)).days
    except ValueError:
        return None


def problems(entries: list[dict]) -> list[str]:
    found: list[str] = []
    for entry in entries:
        identifier = str(entry.get("id", "<no id>"))
        uri = str(entry.get("source_uri", ""))
        if not uri.startswith("http"):
            continue
        ingestible = bool(entry.get("ingestible"))
        signal = entry.get("content_signal")

        if signal is None:
            if ingestible:
                found.append(
                    f"{identifier}: ingestible web source with no content_signal — "
                    f"nothing read {urlsplit(uri).netloc}/robots.txt, so an express "
                    "reservation of rights would enter the corpus unnoticed"
                )
            continue
        if not isinstance(signal, dict):
            found.append(f"{identifier}: content_signal is not an object")
            continue

        verdict = str(signal.get("verdict", ""))
        if verdict not in VERDICTS:
            found.append(f"{identifier}: unknown content_signal.verdict {verdict!r}")
            continue
        host = str(signal.get("host", ""))
        if host and host != urlsplit(uri).netloc.lower():
            # A signal copied from a neighbouring entry describes the wrong site and
            # would clear a source nobody measured.
            found.append(
                f"{identifier}: content_signal.host {host!r} is not the source's host "
                f"{urlsplit(uri).netloc.lower()!r} — this reading is of another site"
            )
            continue
        age = _age_days(str(signal.get("read_on", "")))
        if age is None:
            found.append(f"{identifier}: content_signal.read_on is not an ISO date")
        elif age > SIGNAL_MAX_AGE_DAYS:
            found.append(
                f"{identifier}: content_signal read {age} days ago, over the "
                f"{SIGNAL_MAX_AGE_DAYS}-day floor — terms change and this reading expired"
            )
        elif age < 0:
            found.append(f"{identifier}: content_signal.read_on is in the future")

        if verdict == "reserved_against_us":
            reasons = signal.get("against_us")
            if not isinstance(reasons, list) or not reasons:
                found.append(
                    f"{identifier}: verdict reserved_against_us with no reason recorded — "
                    "a block without its ground cannot be reviewed or lifted"
                )
            if ingestible:
                found.append(
                    f"{identifier}: the operator expressly reserved this content against "
                    f"us ({'; '.join(map(str, reasons or []))[:160]}) but ingestible=true"
                )
    return found


def _load() -> list[dict[str, Any]]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    sources = data["sources"] if isinstance(data, dict) else data
    if not isinstance(sources, list):
        raise ValueError("catalog sources is not a list")
    return [row for row in sources if isinstance(row, dict)]


def selftest() -> int:
    """Every rule is shown failing on a mutation. A green gate that cannot go red is decor."""
    base: dict[str, Any] = {
        "id": "T",
        "source_uri": "https://example.org/a",
        "ingestible": True,
        "content_signal": {
            "host": "example.org",
            "read_on": date.today().isoformat(),
            "verdict": "no_restriction",
            "against_us": [],
        },
    }

    def mutate(**changes: object) -> list[dict[str, Any]]:
        entry: dict[str, Any] = copy.deepcopy(base)
        signal = entry["content_signal"]
        if not isinstance(signal, dict):  # pragma: no cover - built as a dict above
            raise TypeError("content_signal must be an object")
        for key, value in changes.items():
            (entry if key in entry else signal)[key] = value
        return [entry]

    cases = [
        ("чиста база проходить", [copy.deepcopy(base)], False),
        (
            "немає сигналу на ingestible",
            [{"id": "T", "source_uri": "https://example.org/a", "ingestible": True}],
            True,
        ),
        (
            "немає сигналу, але й не ingestible",
            [{"id": "T", "source_uri": "https://example.org/a", "ingestible": False}],
            False,
        ),
        (
            "застережено проти нас, але ingestible",
            mutate(verdict="reserved_against_us", against_us=["ai-train=no"]),
            True,
        ),
        (
            "застережено проти нас без причини",
            mutate(verdict="reserved_against_us", against_us=[], ingestible=False),
            True,
        ),
        ("проти інших краулерів — не блокує", mutate(verdict="reserved_against_others"), False),
        ("хост сигналу з іншого сайту", mutate(host="other.example"), True),
        ("сигнал протух", mutate(read_on="2019-01-01"), True),
        ("дата не ISO", mutate(read_on="вчора"), True),
        ("невідомий вердикт", mutate(verdict="fine"), True),
        ("сигнал не об'єкт", mutate(content_signal="yes"), True),
        (
            "не-http джерело ігнорується",
            [{"id": "T", "source_uri": "file:///x", "ingestible": True}],
            False,
        ),
    ]
    bad = 0
    for name, entries, want_fail in cases:
        got = bool(problems(entries))
        if got != want_fail:
            bad += 1
            print(
                f"  ✗ {name}: очікували {'падіння' if want_fail else 'PASS'}, отримали "
                f"{'падіння' if got else 'PASS'}"
            )
        else:
            print(f"  ✓ {name}")
    print(f"негативний контроль: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    entries = _load()
    found = problems(entries)
    web = [e for e in entries if str(e.get("source_uri", "")).startswith("http")]
    probed = [e for e in web if isinstance(e.get("content_signal"), dict)]
    reserved = [e for e in probed if e["content_signal"].get("verdict") == "reserved_against_us"]
    others = [e for e in probed if e["content_signal"].get("verdict") == "reserved_against_others"]
    if found:
        print("content signals: FAIL")
        for item in found:
            print(f"  ✗ {item}")
        return 1
    print("content signals: PASS")
    print(f"  {len(web)} web sources · {len(probed)} with a robots.txt reading")
    print(
        f"  {len(reserved)} expressly reserved against us and blocked · "
        f"{len(others)} reserve against other crawlers only (not a restriction here)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
