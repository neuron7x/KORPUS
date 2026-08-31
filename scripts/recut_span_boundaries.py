#!/usr/bin/env python3
"""Перенести провідний уламок речення до попереднього прольоту, не втративши жодного символу.

Проліт — шматок джерела фіксованого розміру, не речення. Виміряно 31.08.2026 на базі,
яка обслуговується: **32 820 із 38 863 прольотів (84,5 %) починаються посеред речення**,
а межа часто розрізає слово: «Зак|он набирає чинності», «Воєнний об'єкт за|лишається».
Подання вже позначає уривок і віддає перевагу цілому реченню, але сам проліт лишається
розрізаним, і коли цілого речення в ньому немає, читач отримує хвіст.

**Що робить.** Для кожної суміжної пари в межах версії: якщо наступний проліт
починається посеред речення, його провідний уламок (до першого термінатора включно)
переноситься в кінець попереднього. Порядок, кількість і межі версій не змінюються;
змінюються тексти двох прольотів і їхні хеші.

**Інваріант, який тримається побайтово: конкатенація прольотів версії НЕ змінюється.**
Перша редакція робила `tail.lstrip()` — і тим губила пробіли, тобто ламала твердження
«проліт є зрізом сторінки», не змінивши жодного видимого символу. Тому переносяться
рівно ті символи, що були, і перевірка порівнює конкатенацію до і після.

**Чого НЕ робить.**
* Не переносить, якщо в прольоті немає термінатора взагалі (1 033 прольоти) — краще
  лишити розріз видимим, ніж зшити два уламки в одне неречення.
* Не переносить, якщо після перенесення проліт спорожніє (85) — порожній проліт не є
  прольотом, а видалення зсунуло б порядок.
* Не переносить, якщо перенесення зробить проліт БРУДНИМ у сенсі `validate_span_hygiene`
  — виміряно, що без цієї умови ремонт створює один новий брудний проліт: 22 → 23.
  Правка, яка лікує одну вісь і псує іншу, мусить це принаймні бачити.
* Не чіпає ембединги: вони стають застарілими для змінених прольотів і мають бути
  перебудовані окремо (`backfill_span_embeddings_sqlite.py`). Мовчазно перебудовувати
  їх тут означало б сховати ціну ремонту.

    recut_span_boundaries.py --database DB           # показати, нічого не писати
    recut_span_boundaries.py --database DB --apply
    recut_span_boundaries.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.evidence import starts_mid_sentence  # noqa: E402

#: Термінатор речення, за яким іде пробіл або кінець рядка. Крапка всередині «т.зв.»
#: або десяткового числа межею не є — той самий поділ, що в `segment_sentences`.
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")
#: Слід розмітки, що осіла в тексті. Той самий клас, який міряє `validate_span_hygiene`.
_MARKUP = re.compile(r"&(?:lt|gt|amp|quot|#\d+);|<[a-zA-Z/][^>]*>")
#: Стеля довжини прольоту, та сама, що в `extraction.make_spans(max_chars=1400)`.
#: Ремонт не сміє виводити корпус за межі, у яких його зібрано.
MAX_SPAN_CHARS = 1400


def plan_moves(
    spans: list[tuple[str, str, int, str]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Перенесення, які можна зробити, і причини для тих, яких не можна."""
    by_version: dict[str, list[list[Any]]] = {}
    for span_id, version_id, ordinal, text in spans:
        by_version.setdefault(version_id, []).append([span_id, ordinal, text])
    moves: list[dict[str, Any]] = []
    skipped = {
        "no_terminator": 0,
        "would_empty": 0,
        "would_dirty": 0,
        "would_exceed_span_ceiling": 0,
    }
    for items in by_version.values():
        items.sort(key=lambda row: row[1])
        for index in range(1, len(items)):
            previous, current = items[index - 1], items[index]
            if not starts_mid_sentence(current[2]):
                continue
            match = _SENTENCE_END.search(current[2])
            if match is None:
                skipped["no_terminator"] += 1
                continue
            head, tail = current[2][: match.end()], current[2][match.end() :]
            if not tail.strip():
                skipped["would_empty"] += 1
                continue
            joined = previous[2] + head
            if len(joined) > MAX_SPAN_CHARS:
                # Інжест ріже сторінку на шматки не довші за `make_spans(max_chars=1400)`,
                # і на цьому тримається твердження «кожен проліт є зрізом сторінки». Перша
                # редакція цього ремонту інваріант порушила: об'єднаний проліт переріс
                # стелю, його єдине речення вийшло за ліміт цитати 1600 символів, і
                # відповідь упала HTTP 500 на питанні «Як навчити собаку команді сидіти?».
                # Ремонт не сміє виводити корпус за межі, у яких його зібрано.
                skipped["would_exceed_span_ceiling"] += 1
                continue
            if _MARKUP.search(joined) and not _MARKUP.search(previous[2]):
                # Ремонт однієї осі не сміє тихо створювати борг на іншій.
                skipped["would_dirty"] += 1
                continue
            moves.append(
                {
                    "previous_id": previous[0],
                    "previous_text": joined,
                    "current_id": current[0],
                    "current_text": tail,
                }
            )
            previous[2], current[2] = joined, tail
    return moves, skipped


def concatenations(spans: list[tuple[str, str, int, str]]) -> dict[str, str]:
    joined: dict[str, list[tuple[int, str]]] = {}
    for _span_id, version_id, ordinal, text in spans:
        joined.setdefault(version_id, []).append((ordinal, text))
    return {
        version: "".join(text for _, text in sorted(items)) for version, items in joined.items()
    }


def selftest() -> int:
    """Отрути по ДАНИХ: кожна створює пару прольотів, на якій правило зобов'язане спрацювати."""

    def spans(*texts: str) -> list[tuple[str, str, int, str]]:
        return [(f"s{i}", "v", i, text) for i, text in enumerate(texts)]

    cases: list[tuple[str, list[tuple[str, str, int, str]], int, str | None]] = [
        (
            "розріз посеред слова переноситься",
            spans("Зак", "он набирає чинності. Далі текст."),
            1,
            None,
        ),
        (
            "проліт уже на межі речення не чіпається",
            spans("Ціле речення.", "Друге ціле речення."),
            0,
            None,
        ),
        ("без термінатора не переносимо", spans("Початок", "хвіст без крапки"), 0, "no_terminator"),
        (
            "перенесення, що спорожнило б, не робиться",
            spans("Початок", "кінець."),
            0,
            "would_empty",
        ),
        (
            "перенесення, що внесло б розмітку, не робиться",
            spans("Чистий текст.", "хвіст &lt;p> далі. Ще речення."),
            0,
            "would_dirty",
        ),
    ]
    failures: list[str] = []
    for name, rows, want_moves, want_skip in cases:
        moves, skipped = plan_moves(rows)
        if len(moves) != want_moves:
            failures.append(f"{name}: перенесень {len(moves)}, очікувалось {want_moves}")
        elif want_skip and skipped[want_skip] != 1:
            failures.append(f"{name}: {want_skip}={skipped[want_skip]}")
    # Конкатенація не сміє змінитись жодною отрутою.
    rows = spans("Зак", "он набирає чинності. Далі текст.")
    before = concatenations(rows)
    moves, _ = plan_moves(rows)
    applied = {row[0]: row[3] for row in rows}
    for move in moves:
        applied[move["previous_id"]] = move["previous_text"]
        applied[move["current_id"]] = move["current_text"]
    after = "".join(applied[f"s{i}"] for i in range(len(rows)))
    if after != before["v"]:
        failures.append("конкатенація змінилась — проліт перестав бути зрізом сторінки")
    print(
        json.dumps({"selftest": len(cases) + 1, "failed": failures}, ensure_ascii=False, indent=2)
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.database is None or not args.database.is_file():
        print(
            json.dumps({"status": "UNKNOWN", "reason": "потрібна --database"}, ensure_ascii=False)
        )
        return 2
    connection = sqlite3.connect(str(args.database))
    spans = [
        (str(row[0]), str(row[1]), int(row[2]), str(row[3]))
        for row in connection.execute("select id, version_id, ordinal, text from evidence_spans")
    ]
    before = concatenations(spans)
    moves, skipped = plan_moves(spans)
    mid_before = sum(1 for _, _, _, text in spans if starts_mid_sentence(text))
    if args.apply:
        for move in moves:
            for span_id, text in (
                (move["previous_id"], move["previous_text"]),
                (move["current_id"], move["current_text"]),
            ):
                connection.execute(
                    "update evidence_spans set text=?, text_hash=? where id=?",
                    (text, hashlib.sha256(text.encode("utf-8")).hexdigest(), span_id),
                )
        connection.commit()
        after_rows = [
            (str(row[0]), str(row[1]), int(row[2]), str(row[3]))
            for row in connection.execute(
                "select id, version_id, ordinal, text from evidence_spans"
            )
        ]
        after = concatenations(after_rows)
        drift = [version for version in before if before[version] != after.get(version)]
        mid_after = sum(1 for _, _, _, text in after_rows if starts_mid_sentence(text))
    else:
        drift = []
        mid_after = mid_before - len(moves)
    print(
        json.dumps(
            {
                "status": "FAIL" if drift else "PASS",
                "applied": bool(args.apply),
                "spans": len(spans),
                "moves": len(moves),
                "skipped": skipped,
                "mid_sentence_before": mid_before,
                "mid_sentence_after": mid_after,
                "concatenation_drift": drift[:5],
                "embeddings": "застарілі для змінених прольотів; перебудувати окремо",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if drift else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        print(
            json.dumps(
                {"status": "ERROR", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False
            )
        )
        raise SystemExit(2) from error
