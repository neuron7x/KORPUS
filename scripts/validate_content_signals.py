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

from iso_dates import iso_date

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
#: How long a reading of a live robots.txt stays a reading.
SIGNAL_MAX_AGE_DAYS = 180
VERDICTS = {"reserved_against_us", "reserved_against_others", "no_restriction", "no_robots"}


def host_of(uri: str) -> str:
    """The host, in one spelling.

    `https://ZAKON.RADA.GOV.UA/x`, `https://zakon.rada.gov.ua./x` and
    `https://zakon.rada.gov.ua:443/x` are one host to DNS and three strings to a
    comparison. A rule keyed on the raw netloc is bypassed by choosing a spelling —
    reported by session 80352ff0 against rule 14 of the catalog validator, and this
    gate had the same hole: a signal recorded for `example.org` and a source_uri of
    `https://example.org./a` compared unequal and failed a source that was measured.
    Port is dropped too: a userinfo@ or :443 spelling is the same site.
    """
    netloc = urlsplit(uri).netloc.lower().rstrip(".")
    netloc = netloc.rsplit("@", 1)[-1]
    if netloc.startswith("["):  # IPv6 literal keeps its brackets
        return netloc.split("]", 1)[0] + "]"
    return netloc.split(":", 1)[0]


def _age_days(stamp: str) -> int | None:
    try:
        return int((date.today() - iso_date(stamp)).days)
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
                    f"nothing read {host_of(uri)}/robots.txt, so an express "
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
        if host and host.lower().rstrip(".") != host_of(uri):
            # A signal copied from a neighbouring entry describes the wrong site and
            # would clear a source nobody measured.
            found.append(
                f"{identifier}: content_signal.host {host!r} is not the source's host "
                f"{host_of(uri)!r} — this reading is of another site"
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

        # The verdict has to agree with the data it was drawn from. Everything above
        # checks the verdict against the source; nothing checked it against its own
        # fields, so a defect in the *prober* — not the gate — passed straight through:
        # `ai_bots_disallowed: ["ClaudeBot"]` under `verdict: reserved_against_others`
        # reads as "someone else's refusal" while naming us in the same object.
        OURS = {"claudebot", "anthropic-ai", "claude-web", "claude-searchbot"}
        raw = signal.get("signals")
        raw = raw if isinstance(raw, dict) else {}
        bots = signal.get("ai_bots_disallowed")
        bots = [str(b) for b in bots] if isinstance(bots, list) else []
        named_us = sorted(b for b in bots if b.lower() in OURS)
        binding = sorted(
            f"{k}={raw[k]}" for k in ("ai-train", "ai-input") if str(raw.get(k, "")).lower() == "no"
        )
        if str(raw.get("use", "")).lower() in {"reference", "immediate"}:
            binding.append(f"use={raw['use']}")
        # `against_us` is the most direct record of a restriction aimed at us, and the
        # first version of this check read everything EXCEPT it: raw signals and bot
        # names, but not the field whose name says what it holds. Reported by session
        # 80352ff0 as MUTATION 1 — `against_us: ["ai-train=no"]` with
        # `verdict: no_restriction` stayed ingestible. Symmetry laid in one place and
        # omitted in the one that mattered.
        declared = sorted(str(x) for x in (signal.get("against_us") or []) if str(x).strip())
        if (named_us or binding or declared) and verdict != "reserved_against_us":
            found.append(
                f"{identifier}: verdict is {verdict!r} but the reading itself carries "
                f"{', '.join(named_us + binding + declared)} — a restriction aimed at us "
                f"cannot be "
                "recorded as someone else's; this is a defect in the prober, not the data"
            )
            continue

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
        # Обхід правила вибором написання хоста — знахідка сесії 80352ff0 проти правила 14
        # каталогу. Написання, які DNS вважає одним хостом, мусять і тут бути одним;
        # інакше застережене джерело проходить під іншим рядком того самого сайту.
        ("трейлінг-крапка в хості", mutate(source_uri="https://example.org./a"), False),
        ("ВЕЛИКІ літери в хості", mutate(source_uri="https://EXAMPLE.ORG/a"), False),
        ("явний порт :443", mutate(source_uri="https://example.org:443/a"), False),
        ("userinfo перед хостом", mutate(source_uri="https://u:p@example.org/a"), False),
        ("справді інший хост усе ще падає", mutate(source_uri="https://evil.org/a"), True),
        (
            "застережений хост із трейлінг-крапкою не тікає",
            mutate(
                source_uri="https://example.org./a",
                verdict="reserved_against_us",
                against_us=["ai-train=no"],
            ),
            True,
        ),
        # Вісь D: вердикт проти ВЛАСНИХ даних об'єкта. Ловить дефект пробника, не даних.
        (
            "ClaudeBot названий, а вердикт «проти інших»",
            mutate(verdict="reserved_against_others", ai_bots_disallowed=["ClaudeBot"]),
            True,
        ),
        (
            "ai-train=no, а вердикт «без обмежень»",
            mutate(signals={"ai-train": "no"}),
            True,
        ),
        (
            "use=reference, а вердикт «без обмежень»",
            mutate(signals={"use": "reference"}),
            True,
        ),
        (
            "Bytespider названий — це НЕ про нас, вердикт лишається чинним",
            mutate(verdict="reserved_against_others", ai_bots_disallowed=["Bytespider"]),
            False,
        ),
        (
            "search=yes сам по собі нічого не забороняє",
            mutate(signals={"search": "yes"}),
            False,
        ),
        # Мутація 1 сесії 80352ff0: непорожній `against_us` при будь-якому іншому
        # вердикті. Три випадки, а не один — `no_robots` пропускав так само.
        (
            "against_us непорожній при no_restriction",
            mutate(against_us=["ai-train=no"]),
            True,
        ),
        (
            "against_us непорожній при reserved_against_others",
            mutate(verdict="reserved_against_others", against_us=["tdm-reservation"]),
            True,
        ),
        (
            "against_us непорожній при no_robots",
            mutate(verdict="no_robots", against_us=["ai-input=no"]),
            True,
        ),
        (
            "against_us із самих пробілів не рахується підставою",
            mutate(against_us=["   ", ""]),
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
