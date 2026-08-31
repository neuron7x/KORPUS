#!/usr/bin/env python3
"""Якір, який процес, що обслуговує, не може прочитати, — це якір, що не рухається.

Зовнішній якір — незалежна контрольна точка: він каже, на якому місці ланцюг був у момент,
коли його бачив хтось поза базою. Його MAC рахується ключем аудиту. У розгортанні, яке
обслуговується, він був записаний під час відновлення ключем `replace-local-audit-key`, а
процес, що обслуговує, тримає інший — тож кожна його спроба звести якір діставала
`audit anchor MAC mismatch`, і якір замерз на 1024 із 7223. Черга ж спільна, тому
контрольні точки забирали CLI-процеси з тим самим плейсхолдером і клали у ВЛАСНИЙ файл
`var/audit-anchor.json`, який стоїть на 7223. Один розкол ключів дав обидві вади.

Перевипуск — операторська дія над артефактом доказовості, тож він обставлений відмовами:

  · ланцюг мусить перевірятись ЦІЛКОМ наданою каблучкою; на неперевіреному ланцюгу
    перевипуск лише переніс би невідоме під новий підпис;
  · голова в `audit_heads` мусить збігатися з останньою подією;
  · нова послідовність не сміє бути МЕНШОЮ за наявну — якір рухається лише вперед,
    інакше перевипуск ставав би способом відкотити контрольну точку;
  · старий файл не перезаписується наосліп: якщо він читається наявним ключем, його
    вміст показується, щоб було видно, ЩО саме заміщується.

    reissue_audit_anchor.py --database DB --anchor ШЛЯХ --key ід=@config --key ід=ФАЙЛ \
                            --write-with ід [--apply]
    reissue_audit_anchor.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from korpus.infrastructure.audit_anchor import AnchorError, FileAuditAnchorStore  # noqa: E402
from measure_audit_integrity import assess, parse_key  # noqa: E402


def preflight(report: dict[str, Any], anchor_sequence: int, head_sequence: int) -> list[str]:
    """Причини НЕ перевипускати. Порожній список — єдина підстава писати."""
    refusals: list[str] = []
    if report["unverifiable"]:
        refusals.append(f"{report['unverifiable']} подій не перевіряються жодним наданим ключем")
    if report["misattributed"]:
        refusals.append(f"{report['misattributed']} подій названі не тим ключем, що їх підписав")
    if report["linkage_breaks"]:
        refusals.append(f"розриви зчеплення: {report['linkage_breaks']}")
    if report["sequence_gaps"]:
        refusals.append(f"пропуски нумерації: {report['sequence_gaps']}")
    if not report["head_matches_last_event"]:
        refusals.append("голова в audit_heads не збігається з останньою подією")
    if anchor_sequence > head_sequence:
        refusals.append(
            f"якір стоїть на {anchor_sequence}, попереду голови {head_sequence}: "
            "перевипуск був би відкотом"
        )
    return refusals


def selftest() -> int:
    whole = {
        "unverifiable": 0,
        "misattributed": 0,
        "linkage_breaks": [],
        "sequence_gaps": [],
        "head_matches_last_event": True,
    }
    cases = [
        ("цілий ланцюг — перевипуск дозволено", preflight(whole, 1024, 7223), 0),
        ("неперевірювані події — відмова", preflight({**whole, "unverifiable": 1}, 1024, 7223), 1),
        ("хибний ярлик ключа — відмова", preflight({**whole, "misattributed": 3}, 1024, 7223), 1),
        ("розрив зчеплення — відмова", preflight({**whole, "linkage_breaks": [5]}, 1024, 7223), 1),
        ("пропуск нумерації — відмова", preflight({**whole, "sequence_gaps": [9]}, 1024, 7223), 1),
        (
            "голова не збігається — відмова",
            preflight({**whole, "head_matches_last_event": False}, 1024, 7223),
            1,
        ),
        ("якір попереду голови — відмова", preflight(whole, 8000, 7223), 1),
    ]
    failures = [f"{name}: {got}" for name, got, want in cases if len(got) != want]
    print(json.dumps({"selftest": len(cases), "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def resolve_inputs(args: argparse.Namespace) -> tuple[dict[str, bytes] | None, str | None]:
    """Ключі — або причина не починати. Відмова тут дешевша за відмову після читання."""
    if args.database is None or not args.database.is_file():
        return None, f"немає бази {args.database}"
    if not args.key or not args.write_with:
        return None, "потрібні --key і --write-with"
    keys = dict(parse_key(spec) for spec in args.key)
    if args.write_with not in keys:
        return None, f"ключа {args.write_with} не надано"
    return keys, None


def read_anchor(path: Path, keys: dict[str, bytes]) -> dict[str, Any]:
    """Наявний якір очима КОЖНОГО наданого ключа: який його читає, той його й писав."""
    readable: dict[str, Any] = {}
    for key_id, material in keys.items():
        try:
            existing = FileAuditAnchorStore(path, material).read()
        except (AnchorError, OSError):
            continue
        readable[key_id] = {"sequence": existing.sequence, "head_hash": existing.head_hash}
    return readable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--anchor", type=Path)
    parser.add_argument("--key", action="append", default=[], metavar="ІД=ШЛЯХ")
    parser.add_argument("--write-with", metavar="ІД", help="ід ключа, яким писати новий якір")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    keys, refusal = resolve_inputs(args)
    if keys is None:
        print(json.dumps({"status": "UNKNOWN", "reason": refusal}, ensure_ascii=False))
        return 2
    connection = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = [dict(row) for row in connection.execute("select * from audit_events order by sequence")]
    if not rows:
        print(json.dumps({"status": "UNKNOWN", "reason": "у журналі немає подій"}, ensure_ascii=False))
        return 2
    report = assess(rows, keys)
    head_sequence = int(rows[-1]["sequence"])
    head_hash = str(rows[-1]["event_hash"])
    # `assess` міряє події; збіг із `audit_heads` — окреме твердження, і воно потрібне
    # саме тут: якір указує на голову, тож голова, що розійшлася з журналом, робить
    # перевипуск підписом під числом, якого ніхто не звіряв.
    stored_head = connection.execute("select head_hash from audit_heads").fetchone()
    report["head_matches_last_event"] = bool(
        stored_head and str(stored_head["head_hash"]) == head_hash
    )
    readable = read_anchor(args.anchor, keys)
    anchor_sequence = max((entry["sequence"] for entry in readable.values()), default=0)
    refusals = preflight(report, anchor_sequence, head_sequence)
    result: dict[str, Any] = {
        "status": "REFUSED" if refusals else "PASS",
        "applied": False,
        "events": len(rows),
        "head_sequence": head_sequence,
        "anchor_now": readable or "жоден наданий ключ не читає наявний якір",
        "would_write": {"sequence": head_sequence, "with_key": args.write_with},
        "refusals": refusals,
    }
    if refusals:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    if args.apply:
        # Наявний файл прибирається свідомо: його MAC порахований ключем, якого це
        # розгортання більше не вживає, тож `write` не зміг би його навіть прочитати.
        args.anchor.unlink(missing_ok=True)
        store = FileAuditAnchorStore(args.anchor, keys[args.write_with])
        store.write(head_sequence, head_hash)
        written = store.read()
        result["applied"] = True
        result["anchor_after"] = {"sequence": written.sequence, "head_hash": written.head_hash}
        result["reads_back_with_write_key"] = written.head_hash == head_hash
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        print(json.dumps({"status": "ERROR", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False))
        raise SystemExit(2) from error
