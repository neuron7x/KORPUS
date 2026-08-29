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
from datetime import date, timedelta
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
        # Межа названа явно: рівно SIGNAL_MAX_AGE_DAYS днів — ще чинний вимір.
        # `>` проти `>=` тут не стиль: мутант із `>=` вижив, бо проби на межу не було,
        # лише на давно прострочений сигнал.
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
        #: `raw[k]` після фільтра через `.get` — крихко: умова гарантує наявність ключа
        #: лише поки вона саме така. Мутація `== "no"` → `!= "no"` перетворила гейт на
        #: KeyError замість відмови. Падіння теж убиває мутанта, але гейт, який може
        #: впасти від власних даних, — гірший сигнал, ніж гейт, який каже «ні».
        binding = sorted(
            f"{k}={raw.get(k)}"
            for k in ("ai-train", "ai-input")
            if str(raw.get(k, "")).lower() == "no"
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


#: Негативні контролі — ДАНІ, а не код. Кожен рядок: назва, зміни до еталонного запису
#: (або готовий список записів), і чи МУСИТЬ гейт на цьому впасти.
#:
#: Чому таблицею, а не тілом функції: стеля рядків у module-budget рахує проби так само,
#: як логіку, і дев'ять доданих негативних контролів зробили гейт якості червоним —
#: тобто стеля тиснула проти самого покриття. Реєстр даних для цього має виняток
#: (той самий, що в run_mutation_tests.py: «каталог мутантів — це дані»), і таблиця
#: проб належить саме до цього класу. Плюс так її видно в diff як перелік, а не як текст.
PROBE_BASE: dict[str, Any] = {
    "id": "T",
    "source_uri": "https://example.org/a",
    "ingestible": True,
    "content_signal": {
        "host": "example.org",
        "read_on": "",  # проставляється в _probe_entries: «сьогодні»
        "verdict": "no_restriction",
        "against_us": [],
    },
}

#: Дні відносно сьогодні — щоб межа лишалась межею, а не датою, яка колись протухне.
_AT_FLOOR = {"_read_on_days_ago": SIGNAL_MAX_AGE_DAYS}
_OVER_FLOOR = {"_read_on_days_ago": SIGNAL_MAX_AGE_DAYS + 1}

PROBES: tuple[tuple[str, object, bool], ...] = (
    ("чиста база проходить", {}, False),
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
        "не-http джерело ігнорується",
        [{"id": "T", "source_uri": "file:///x", "ingestible": True}],
        False,
    ),
    # Вісь A — блокування: те, заради чого гейт існує.
    (
        "застережено проти нас, але ingestible",
        {"verdict": "reserved_against_us", "against_us": ["ai-train=no"]},
        True,
    ),
    (
        "застережено проти нас без причини",
        {"verdict": "reserved_against_us", "against_us": [], "ingestible": False},
        True,
    ),
    ("проти інших краулерів — не блокує", {"verdict": "reserved_against_others"}, False),
    ("невідомий вердикт", {"verdict": "fine"}, True),
    ("сигнал не об'єкт", {"content_signal": "yes"}, True),
    # Вісь C — предмет виміру: сигнал про ЦЕЙ сайт і не протухлий.
    ("хост сигналу з іншого сайту", {"host": "other.example"}, True),
    ("сигнал протух", {"read_on": "2019-01-01"}, True),
    ("дата не ISO", {"read_on": "вчора"}, True),
    ("рівно на межі віку — ще чинний", _AT_FLOOR, False),  # рядок 105: > проти >=
    ("на день за межею — протух", _OVER_FLOOR, True),
    # Обхід правила вибором написання хоста (знахідка 80352ff0 проти правила 14).
    ("трейлінг-крапка в хості", {"source_uri": "https://example.org./a"}, False),
    ("ВЕЛИКІ літери в хості", {"source_uri": "https://EXAMPLE.ORG/a"}, False),
    ("явний порт :443", {"source_uri": "https://example.org:443/a"}, False),
    ("userinfo перед хостом", {"source_uri": "https://u:p@example.org/a"}, False),
    ("справді інший хост усе ще падає", {"source_uri": "https://evil.org/a"}, True),
    (
        "застережений хост із трейлінг-крапкою не тікає",
        {
            "source_uri": "https://example.org./a",
            "verdict": "reserved_against_us",
            "against_us": ["ai-train=no"],
        },
        True,
    ),
    (
        "IPv6-літерал із портом розбирається в той самий хост",  # рядок 56: [0]→[1]
        {"source_uri": "https://[::1]:443/a", "host": "[::1]"},
        False,
    ),
    (
        "IPv6-літерал проти іншого хоста все одно падає",
        {"source_uri": "https://[::1]:443/a", "host": "example.org"},
        True,
    ),
    # Вісь D — вердикт проти ВЛАСНИХ даних об'єкта: ловить дефект пробника, не даних.
    (
        "ClaudeBot названий, а вердикт «проти інших»",
        {"verdict": "reserved_against_others", "ai_bots_disallowed": ["ClaudeBot"]},
        True,
    ),
    ("ai-train=no, а вердикт «без обмежень»", {"signals": {"ai-train": "no"}}, True),
    ("use=reference, а вердикт «без обмежень»", {"signals": {"use": "reference"}}, True),
    (
        "Bytespider названий — це НЕ про нас, вердикт лишається чинним",
        {"verdict": "reserved_against_others", "ai_bots_disallowed": ["Bytespider"]},
        False,
    ),
    ("search=yes сам по собі нічого не забороняє", {"signals": {"search": "yes"}}, False),
    (
        "ai-train=yes не є підставою вважати вердикт заниженим",  # рядок 125: ==→!=
        {"signals": {"ai-train": "yes"}},
        False,
    ),
    ("ai-input=yes так само не є підставою", {"signals": {"ai-input": "yes"}}, False),
    (
        "ai-train=no ПРИ вердикті reserved_against_us — узгоджено, проходить",
        {
            "verdict": "reserved_against_us",
            "signals": {"ai-train": "no"},
            "against_us": ["ai-train=no"],
            "ingestible": False,
        },
        False,
    ),
    ("against_us непорожній при no_restriction", {"against_us": ["ai-train=no"]}, True),
    (
        "against_us непорожній при reserved_against_others",
        {"verdict": "reserved_against_others", "against_us": ["tdm-reservation"]},
        True,
    ),
    (
        "against_us непорожній при no_robots",
        {"verdict": "no_robots", "against_us": ["ai-input=no"]},
        True,
    ),
    ("against_us із самих пробілів не рахується підставою", {"against_us": ["   ", ""]}, False),
)

#: Фікстура для перевірки самого звіту: 4 web, 3 виміряні, 1 проти нас, 1 проти інших.
REPORT_FIXTURE = (
    {"source_uri": "https://a.example/x", "content_signal": {"verdict": "reserved_against_us"}},
    {"source_uri": "https://b.example/x", "content_signal": {"verdict": "reserved_against_others"}},
    {"source_uri": "https://c.example/x", "content_signal": {"verdict": "no_restriction"}},
    {"source_uri": "https://d.example/x"},
    {"source_uri": "file:///local"},
)
REPORT_EXPECTED = {"web": 4, "probed": 3, "reserved_against_us": 1, "reserved_against_others": 1}


def _probe_entries(changes: object) -> list[dict[str, Any]]:
    """Записи для однієї проби: або готовий список, або еталон із застосованими змінами."""
    if isinstance(changes, list):
        return changes
    if not isinstance(changes, dict):
        raise TypeError(f"проба {changes!r} — ні список записів, ні набір змін")
    entry: dict[str, Any] = copy.deepcopy(PROBE_BASE)
    signal = entry["content_signal"]
    signal["read_on"] = date.today().isoformat()
    for key, value in changes.items():
        if key == "_read_on_days_ago":
            signal["read_on"] = (date.today() - timedelta(days=int(value))).isoformat()
        elif key in entry:
            entry[key] = value
        else:
            signal[key] = value
    return [entry]


def selftest() -> int:
    """Кожне правило показане таким, що падає. Зелений гейт, якого не бачили червоним, — декор."""
    bad = 0
    for name, changes, want_fail in PROBES:
        got = bool(problems(_probe_entries(changes)))
        if got != want_fail:
            bad += 1
            print(f"  ✗ {name}: очікували {'падіння' if want_fail else 'PASS'}")
        else:
            print(f"  ✓ {name}")

    got_counts = summarise(list(REPORT_FIXTURE))
    ok_counts = got_counts == REPORT_EXPECTED
    bad += not ok_counts
    print(
        f"  {'✓' if ok_counts else '✗'} підрахунок звіту"
        + ("" if ok_counts else f": {got_counts} != {REPORT_EXPECTED}")
    )

    ok_floor = SIGNAL_MAX_AGE_DAYS == 180
    bad += not ok_floor
    print(f"  {'✓' if ok_floor else '✗'} межа віку сигналу = 180 днів")

    total = len(PROBES) + 2
    print(f"негативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def summarise(entries: list[dict]) -> dict[str, int]:
    """The numbers the report prints, as a value that can be checked.

    They lived inline in `main()`, where nothing tested them: flipping `==` to `!=` in the
    two verdict counts changed every printed figure and no probe noticed, because the
    selftest only ever called `problems()`. A report nobody can falsify is not a report —
    it is the same defect as a gate nobody has seen go red, one level up.
    """
    web = [e for e in entries if str(e.get("source_uri", "")).startswith("http")]
    probed = [e for e in web if isinstance(e.get("content_signal"), dict)]
    return {
        "web": len(web),
        "probed": len(probed),
        "reserved_against_us": len(
            [e for e in probed if e["content_signal"].get("verdict") == "reserved_against_us"]
        ),
        "reserved_against_others": len(
            [e for e in probed if e["content_signal"].get("verdict") == "reserved_against_others"]
        ),
    }


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    entries = _load()
    found = problems(entries)
    counts = summarise(entries)
    if found:
        print("content signals: FAIL")
        for item in found:
            print(f"  ✗ {item}")
        return 1
    print("content signals: PASS")
    print(f"  {counts['web']} web sources · {counts['probed']} with a robots.txt reading")
    print(
        f"  {counts['reserved_against_us']} expressly reserved against us and blocked · "
        f"{counts['reserved_against_others']} reserve against other crawlers only "
        "(not a restriction here)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
