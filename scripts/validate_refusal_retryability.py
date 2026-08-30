#!/usr/bin/env python3
"""`retryable: false` на відмові «недосяжно З ЦІЄЇ ТОЧКИ» — це неправда про документ.

Клас `host_unreachable_from_here` уже містить у назві те, що заперечує `retryable:
false`: недосяжність прив'язана до НАШОЇ мережевої позиції, а не до документа. Читач,
який бачить «не піддається повтору», припиняє шукати — і саме так виникає прогалина,
якої немає. Доведено сьогодні на двох джерелах:

    T1B-DELTA-NATO-ACT   HTTP 403 з цієї машини · ПРОЧИТАНИЙ паралельною сесією
    T3A-FM-3-09          тайм-аут дзеркала     · публікація вже в корпусі з armypubs

Правило розділяє те, що відмова каже про СВІТ, і те, що вона каже про НАС:

    OURS      наш екстрактор, наше кодування — повтор без змін марний → retryable false
    THEIRS    сервер відмовив або віддав не те — повтор може допомогти пізніше → true
    VANTAGE   недосяжно З ЦІЄЇ ТОЧКИ — повтор ЗВІДСИ марний, з іншої ні
              → `retryable` саме по собі відповіді не має; потрібне поле
                `retryable_from`, яке називає, що мусить змінитися

Гейт не вимагає лізти в мережу. Він вимагає, щоб запис не обіцяв більше, ніж знає.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"

VANTAGE = {"host_unreachable_from_here"}
OURS = {"extractor_refused", "too_few_words", "extractor_misclassified"}
THEIRS = {"http_forbidden", "http_error", "transport_error", "dns_unresolved",
          "tls_refused", "content_type_mismatch", "rights_reserved", "no_uri"}
KNOWN = VANTAGE | OURS | THEIRS
#: Що саме мусить змінитися, щоб повтор мав сенс. Закритий словник: слово поза ним
#: перетворює поле на вільний текст, який ніхто не звірить.
FROM_VALUES = {"another_network", "another_machine", "another_country", "unknown"}


def check(sources: list[dict]) -> list[str]:
    bad: list[str] = []
    for s in sources:
        r = s.get("evidence_refusal")
        if not isinstance(r, dict):
            continue
        cls, sid = r.get("class"), s.get("id", "?")
        if cls not in KNOWN:
            bad.append(f"{sid}: клас відмови {cls!r} поза словником — слово поза "
                       f"словником стає тишею, а не вироком")
            continue
        if cls in VANTAGE:
            if "retryable_from" not in r:
                bad.append(f"{sid}: клас {cls} без поля `retryable_from` — «недосяжно "
                           f"з цієї точки» нічого не каже про повтор з іншої, а "
                           f"`retryable: {r.get('retryable')}` каже, і це не його справа")
            elif r["retryable_from"] not in FROM_VALUES:
                bad.append(f"{sid}: `retryable_from`={r['retryable_from']!r} поза "
                           f"словником ({', '.join(sorted(FROM_VALUES))})")
        elif cls in OURS and r.get("retryable") is True:
            bad.append(f"{sid}: клас {cls} — вада НАША, повтор без змін марний, "
                       f"а `retryable: true` обіцяє протилежне")
        if "retryable" in r and not isinstance(r["retryable"], bool):
            #: `bool("False")` істинне — рядок замість булевого значення робить
            #: КОЖНУ відмову придатною до повтору й нічого про це не каже
            bad.append(f"{sid}: `retryable` має тип {type(r['retryable']).__name__}, "
                       f"а не bool — рядок «False» істинний")
    return bad


def selftest() -> int:
    def rec(i, cls, **extra):
        return {"id": i, "evidence_refusal": {"class": cls, **extra}}

    cases = [
        ("джерело без відмови — зелений", [{"id": "A"}], False),
        ("VANTAGE із retryable_from — зелений",
         [rec("A", "host_unreachable_from_here", retryable=True,
              retryable_from="another_network")], False),
        ("VANTAGE без retryable_from — червоний",
         [rec("A", "host_unreachable_from_here", retryable=False)], True),
        ("VANTAGE із retryable_from поза словником — червоний",
         [rec("A", "host_unreachable_from_here", retryable=True, retryable_from="колись")],
         True),
        ("THEIRS із retryable false — зелений (сервер може передумати або ні)",
         [rec("A", "http_forbidden", retryable=False)], False),
        ("OURS із retryable true — червоний",
         [rec("A", "extractor_refused", retryable=True)], True),
        ("OURS із retryable false — зелений",
         [rec("A", "extractor_refused", retryable=False)], False),
        ("клас поза словником — червоний", [rec("A", "щось_нове", retryable=False)], True),
        ("retryable рядком замість bool — червоний",
         [rec("A", "http_error", retryable="False")], True),
        ("VANTAGE із retryable_from unknown — зелений, бо невідомість НАЗВАНА",
         [rec("A", "host_unreachable_from_here", retryable=True, retryable_from="unknown")],
         False),
    ]
    bad = 0
    for name, sources, want_red in cases:
        red = bool(check(sources))
        ok = red == want_red
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}")
    print(f"\nсамоперевірка: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    problems = check(data["sources"] if isinstance(data, dict) else data)
    if problems:
        print(f"refusal-retryability: ВІДМОВЛЕНО — {len(problems)}", file=sys.stderr)
        for p in problems:
            print("  ·", p, file=sys.stderr)
        return 1
    print("refusal-retryability: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
