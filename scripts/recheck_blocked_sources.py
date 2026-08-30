#!/usr/bin/env python3
"""Re-measure the sources this catalogue calls unreachable, because a refusal is a claim.

A poison asks what gets through that should not. Nothing asks the quieter question: what
is turned away that should not be. That failure is harder to see, because a refusal
arrives already looking like a fact — `dead`, `STALE`, `документа за ним немає` — and
nobody re-measures a fact.

Measured 2026-08-29. Eight sources carried the block reason "URI не резолвиться (порожня
або замала відповідь): посилання перевірено запитом, документа за ним немає". Re-probed:

    ARM-ATP-3-90-5-2021       200  17.8 MB  %PDF-      the document is there
    ARM-TC-3-20-31-120-2025   200 145.8 MB  %PDF-      the document is there
    SIG-ATP-6-02.45-2019      200   1.9 MB  %PDF-      the document is there
    ARM-TC-3-20-31-1-2015     200  42.2 KB  <!DOCTYPE  a catalogue card, not the document
    CAM-FM-90-2-1988          200  42.9 KB  <!DOCTYPE  a catalogue card, not the document
    MED-STP-21-1-SMCT-2025    200  42.2 KB  <!DOCTYPE  a catalogue card, not the document
    SIG-AJP-3.6-EDC           —              no source_uri at all
    SIG-ATP-2-22.6-2024       —              TLS certificate verification failed

Three of the eight are simply wrong: the document is served, right now, as a PDF. Three
more are wrong in a subtler way — the document exists and the URI points at its catalogue
card, which is the same defect `probe_source_content.py` was built for on zakon.rada, and
"there is no document" points the reader away from it.

This does not unblock anything. `ingestible` is somebody's decision and stays theirs. What
it does is refuse to let a measurement from one bad minute keep standing as a fact: the
re-reading is written next to the reason, with its own date, and a reason contradicted by
the tree is reported as a contradiction.

    recheck_blocked_sources.py               # measure and report
    recheck_blocked_sources.py --write       # record the re-reading in the catalog
    recheck_blocked_sources.py --selftest    # prove each verdict can be reached
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
#: Substrings that mark a block whose ground is reachability. A block on rights, on
#: classification or on legal status is a decision about the document, not a reading of
#: the network, and re-probing says nothing about it.
REACHABILITY_REASONS = ("не резолвиться", "does not resolve", "Публічний PDF відсутній")
#: …але не тоді, коли та сама причина називає ГРИФ. «Публічний PDF відсутній» стоїть у
#: реченні «Розповсюдження обмежене: C U.S. GOVERNMENT AGENCIES ONLY» — там відсутність
#: файлу є НАСЛІДКОМ обмеження, а не показанням мережі, і картка замість документа є рівно
#: тим, чого й слід чекати. Без цього інструмент оголошував суперечністю правильний запис.
RIGHTS_MARKERS = (
    "розповсюдження обмежене",
    "dist restriction",
    "restricted",
    "cui",
    "гриф",
    "not open",
)
#: НЕ розділювач карток і документів: така вісь не існує. Виміряно 2026-08-30 на власних
#: даних — 92 захоплені документи 41 609 … 145 793 253 байт, 6 карток каталогу
#: 41 553 … 42 459. `max(картки) < min(документи)` = False: XC-COTCCC-JTS (41 609 Б) лежить
#: усередині діапазону карток, і жодне значення порога цього не змінить.
#:
#: Що це насправді: стеля «завелике, щоб бути карткою» — 4.7× над найбільшою відомою
#: карткою. Вона працює лише тому, що розмір тут НЕ єдиний сигнал: `%PDF-` перевіряється
#: раніше й вирішує сам, а `card_not_document` лишається наслідком «200, не PDF, і
#: невелике». Спрощення умови до самого розміру мовчки перетворило б справжні документи
#: на картки — і саме тому назва каже про роль, а не про поділ.
NOT_A_CARD_ABOVE_BYTES = 200_000
PDF_SIGNATURE = b"%PDF-"
#: Розповсюдження читається З ПРЕФІКСА ШЛЯХУ, бо на сторінці запису його немає взагалі.
#: `armypubs Details.aspx` коду не показує; він видний у `Details_Printer.aspx` і в шляху
#: файла. Без цього вирок «документ віддається» читався б як «можна брати» — і назвав би
#: так документ під `DR_d`. Байти віддаються і тому, що ми не маємо права брати.
OPEN_DISTRIBUTION = "/dr_a/"
RESTRICTED_DISTRIBUTION = ("/dr_b/", "/dr_c/", "/dr_d/")


def distribution(uri: str) -> str:
    """`public_release` · `restricted` · `unknown`. Ніколи не «припустимо, що відкрите»."""
    lowered = uri.lower()
    if any(marker in lowered for marker in RESTRICTED_DISTRIBUTION):
        return "restricted"
    return "public_release" if OPEN_DISTRIBUTION in lowered else "unknown"


def verdict(status: int | None, head: bytes, size: int, dist: str = "unknown") -> str:
    """What the re-reading says about the recorded reason. Four states, no fifth.

    `document_served` contradicts "there is no document" outright. `card_not_document`
    contradicts it differently and more usefully: the document exists and the URI names
    its catalogue page. Both are contradictions; conflating them would hide the second,
    which is the one with an actionable fix.
    """
    if status is None:
        return "still_unreachable"
    if head.startswith(PDF_SIGNATURE):
        # Віддається ≠ можна брати. Гриф обмеженого кола робить це не спростуванням
        # причини блокування, а її підтвердженням з іншого боку.
        return "served_but_restricted" if dist == "restricted" else "document_served"
    if status == 200 and size > NOT_A_CARD_ABOVE_BYTES:
        return "large_response_unknown_format"
    return "card_not_document" if status == 200 else "still_unreachable"


#: Які вироки СУПЕРЕЧАТЬ записаній причині. `served_but_restricted` свідомо поза списком:
#: він каже, що файл існує, і водночас що брати його не можна — причина блокування
#: лишається дійсною, змінюється лише її формулювання.
CONTRADICTS = frozenset({"document_served", "card_not_document", "large_response_unknown_format"})


def record_reading(identifier: str, ruling: str, **extra: Any) -> dict[str, Any]:
    """The single place a re-reading is built. Carried into `reachability_recheck` with its
    own date, so the reading that contradicts a recorded reason is itself recorded."""
    return {"id": identifier, "verdict": ruling, "read_on": date.today().isoformat(), **extra}


def probe(source: dict[str, Any], timeout: int) -> dict[str, Any]:
    uri = str(source.get("source_uri", "")).strip()
    identifier = str(source["id"])
    if not uri:
        return record_reading(identifier, "no_uri", detail="джерело без source_uri")
    request = urllib.request.Request(uri, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            head = response.read(4096)
            declared = response.headers.get("Content-Length")
            size = int(declared) if declared and declared.isdigit() else len(head)
            dist = distribution(response.url or uri)
            return record_reading(
                identifier,
                verdict(response.status, head, size, dist),
                http=response.status,
                bytes=size,
                distribution=dist,
                media_type=str(response.headers.get("Content-Type", "")).split(";")[0],
            )
    except urllib.error.HTTPError as error:
        return record_reading(identifier, verdict(error.code, b"", 0), http=error.code)
    except Exception as error:  # noqa: BLE001 — one fact: still not read
        return record_reading(
            identifier, "still_unreachable", detail=f"{type(error).__name__}: {str(error)[:120]}"
        )


def targets(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Blocked on reachability, or refused as retryable by the capture run."""
    out = []
    for source in catalog["sources"]:
        if not isinstance(source, dict):
            continue
        reason = str(source.get("ingest_block_reason", ""))
        if any(marker in reason.lower() for marker in RIGHTS_MARKERS):
            continue
        refusal = source.get("evidence_refusal")
        retryable = isinstance(refusal, dict) and bool(refusal.get("retryable"))
        if (not source.get("ingestible") and any(m in reason for m in REACHABILITY_REASONS)) or (
            retryable
        ):
            out.append(source)
    return out


SELFTEST_CASES: tuple[tuple[str, int | None, bytes, int, str], ...] = (
    ("PDF віддано — «документа немає» спростовано", 200, b"%PDF-1.7", 900_000, "document_served"),
    ("картка замість документа", 200, b"\r\n<!DOCTYPE html>", 42_000, "card_not_document"),
    (
        "великий не-PDF — формат невідомий",
        200,
        b"PK\x03\x04",
        900_000,
        "large_response_unknown_format",
    ),
    ("справді недосяжне", None, b"", 0, "still_unreachable"),
    ("404 — не суперечить", 404, b"", 0, "still_unreachable"),
    (
        "рівно на порозі картки — ще картка",
        200,
        b"<html>",
        NOT_A_CARD_ABOVE_BYTES,
        "card_not_document",
    ),
    (
        "на байт вище порога",
        200,
        b"<html>",
        NOT_A_CARD_ABOVE_BYTES + 1,
        "large_response_unknown_format",
    ),
)


DISTRIBUTION_CASES: tuple[tuple[str, str, str], ...] = (
    (
        "DR_a — public release",
        "https://armypubs.army.mil/epubs/DR_pubs/DR_a/x.pdf",
        "public_release",
    ),
    ("DR_b — обмежене коло", "https://armypubs.army.mil/epubs/DR_pubs/DR_b/x.pdf", "restricted"),
    ("DR_c — обмежене коло", "https://armypubs.army.mil/epubs/DR_pubs/DR_c/x.pdf", "restricted"),
    ("DR_d — обмежене коло", "https://armypubs.army.mil/epubs/DR_pubs/DR_d/x.pdf", "restricted"),
    ("великі літери в шляху", "https://armypubs.army.mil/epubs/DR_pubs/DR_D/x.pdf", "restricted"),
    (
        "Details.aspx — гриф там не показують",
        "https://armypubs.army.mil/ProductMaps/PubForm/Details.aspx?PUB_ID=1",
        "unknown",
    ),
    ("сторонній хост", "https://example.org/doc.pdf", "unknown"),
    ("«dr_a» як частина слова, не сегмент", "https://example.org/adr_across/x.pdf", "unknown"),
)


def selftest() -> int:
    """Кожен вирок показаний досяжним, і поріг картки — таким, що ріже рівно на межі."""
    bad = 0
    for name, uri, expected_dist in DISTRIBUTION_CASES:
        got_dist = distribution(uri)
        if got_dist != expected_dist:
            bad += 1
            print(f"  ✗ {name}: очікували {expected_dist!r}, отримали {got_dist!r}")
    # Розмір НЕ вирішує сам. Найменший захоплений документ (41 609 Б, XC-COTCCC-JTS)
    # лежить усередині діапазону карток каталогу (41 553 … 42 459) — вісь розміру класи
    # не розділяє. Тримається все на тому, що `%PDF-` перевіряється РАНІШЕ: PDF розміром
    # із картку мусить лишитись документом.
    if verdict(200, b"%PDF-1.7", 41_609) != "document_served":
        bad += 1
        print("  ✗ PDF розміром із картку названо карткою — розмір вирішив сам")
    # І нижче ВСІХ карток: 34 559 Б — найменший документ у ширшій вибірці паралельної
    # сесії, менший за найменшу картку (41 553). Обидві проби ловлять одне майбутнє
    # спрощення — «розмір і є ознакою картки», — але з різних боків діапазону.
    if verdict(200, b"%PDF-1.7", 34_559) != "document_served":
        bad += 1
        print("  ✗ документ, менший за будь-яку картку, названо карткою")
    if verdict(200, b"<html>", 41_609) != "card_not_document":
        bad += 1
        print("  ✗ HTML розміром із картку перестав бути карткою")
    # Той самий PDF під грифом НЕ сміє дати той самий вирок, що відкритий.
    if verdict(200, b"%PDF-1.7", 900_000, "restricted") != "served_but_restricted":
        bad += 1
        print("  ✗ PDF під грифом названо document_served")
    if "served_but_restricted" in CONTRADICTS:
        bad += 1
        print("  ✗ «віддається, але під грифом» зараховано спростуванням причини")
    for name, status, head, size, expected in SELFTEST_CASES:
        got = verdict(status, head, size)
        if got != expected:
            bad += 1
            print(f"  ✗ {name}: очікували {expected!r}, отримали {got!r}")
    # Суперечність — це підмножина вироків, а не всі: «still_unreachable» НЕ сміє
    # рахуватись запереченням причини, інакше кожна мережева невдача «спростовувала» б її.
    if "still_unreachable" in CONTRADICTS or "no_uri" in CONTRADICTS:
        bad += 1
        print("  ✗ недосяжність зарахована як спростування причини")
    # Блок на правах або на грифі не є показанням мережі й не переміряється.
    rights = {"id": "X", "ingestible": False, "ingest_block_reason": "NATO RESTRICTED — not open"}
    if targets({"sources": [rights]}):
        bad += 1
        print("  ✗ блок на грифі взято на перемір — мережа про нього нічого не каже")
    total = len(SELFTEST_CASES) + len(DISTRIBUTION_CASES) + 9
    print(f"негативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    chosen = targets(catalog)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        readings = list(pool.map(lambda s: probe(s, arguments.timeout), chosen))
    by_id = {str(s["id"]): s for s in chosen}
    contradicted = []
    for reading in readings:
        source = by_id[reading["id"]]
        mark = "⚠" if reading["verdict"] in CONTRADICTS else "·"
        print(f"  {mark} {reading['id']:28} {reading['verdict']:30} {reading.get('bytes', 0)}")
        if reading["verdict"] in CONTRADICTS:
            contradicted.append(
                {
                    "id": reading["id"],
                    "recorded_reason": str(source.get("ingest_block_reason", ""))[:120],
                    "measured": reading["verdict"],
                }
            )
        if arguments.write:
            source["reachability_recheck"] = reading

    if arguments.write:
        CATALOG.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "rechecked": len(readings),
                "reason_contradicted_by_the_tree": len(contradicted),
                "contradictions": contradicted,
                "written": arguments.write,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
