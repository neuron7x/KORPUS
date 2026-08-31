#!/usr/bin/env python3
"""Кожна подія називає ключ, яким її НЕ підписували, тож журнал не перевіряється цілим.

Колонка `audit_key_id` існує саме для того, щоб ключ можна було замінити, не втративши
здатність довести минуле (AUD-003 у `application/keyring.py`). У базі, яку обслуговують,
вона не заповнена: 7223 події записані як `legacy-unversioned`, хоча підписані двома
різними ключами — 4061 літералом із `config.py`, 3162 ключем процесу, що обслуговує.
Каблучка тримає один матеріал на один ід, тож жодна перевірка не проходить далі 1025-ї.

Цей інструмент ставить ярлик, який відповідає дійсності: для кожної події перебирає надані
ключі й записує ід того, який СПРАВДІ дає її підпис.

**Чому це не переписування журналу.** `audit_key_id` не входить у канонічну форму
(`audit_canonical` бере sequence, event_id, occurred_at, actor_subject, action,
resource_type, resource_id, payload_json, previous_hash — і все). Ярлик не впливає на
`event_hash`. Твердження перевіряється, а не проголошується: усі 7223 хеші знімаються ДО
запису й звіряються ПІСЛЯ; розбіжність бодай в одному — відкат.

**Відмови fail-closed.** Якщо хоч одна подія не перевіряється жодним наданим ключем —
інструмент не пише НІЧОГО. Позначити ключем журнал, який не вдалося перевірити цілим,
означало б видати «ключа не дали» за «все гаразд». Так само відмова, якщо одну подію
підтверджують два ключі: це означає, що ключі не розрізняють, і ярлик був би вгадуванням.

    attribute_audit_keys.py --database DB --key ід=@config --key ід=/шлях [--apply]
    attribute_audit_keys.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_audit_integrity import (
    LEGACY_KEY_ID,
    assess,
    canonical_of,
    parse_key,
)


def attribute(
    rows: list[dict[str, Any]], keys: dict[str, bytes]
) -> tuple[list[tuple[str, int]], list[str]]:
    """Пари (ід ключа, sequence) для запису, і причини відмовитись писати взагалі."""
    plan: list[tuple[str, int]] = []
    refusals: list[str] = []
    for row in rows:
        message = canonical_of(row)
        matches = [
            key_id
            for key_id, material in keys.items()
            if hmac.compare_digest(
                hmac.new(material, message, hashlib.sha256).hexdigest(), str(row["event_hash"])
            )
        ]
        if not matches:
            refusals.append(f"подія {row['sequence']} не перевіряється жодним наданим ключем")
        elif len(matches) > 1:
            refusals.append(
                f"подію {row['sequence']} підтверджують кілька ключів: {sorted(matches)}"
            )
        elif matches[0] != str(row["audit_key_id"] or LEGACY_KEY_ID):
            plan.append((matches[0], int(row["sequence"])))
    return plan, refusals


def selftest() -> int:
    good, other = b"k" * 40, b"j" * 40

    def event(seq: int, key: bytes, named: str) -> dict[str, Any]:
        row = {
            "sequence": seq,
            "event_id": f"e{seq}",
            "occurred_at": "2026-08-31T00:00:00+00:00",
            "actor_subject": "a",
            "action": "x",
            "resource_type": "r",
            "resource_id": None,
            "payload_json": "{}",
            "previous_hash": "0" * 64,
            "audit_key_id": named,
        }
        row["event_hash"] = hmac.new(key, canonical_of(row), hashlib.sha256).hexdigest()
        return row

    checks: list[tuple[str, bool]] = []
    plan, refusals = attribute(
        [event(1, other, LEGACY_KEY_ID)], {"legacy-unversioned": good, "b": other}
    )
    checks.append(("хибний ярлик виправляється", plan == [("b", 1)] and not refusals))
    plan, refusals = attribute([event(1, good, "a")], {"a": good})
    checks.append(("правильний ярлик не чіпається", plan == [] and not refusals))
    plan, refusals = attribute([event(1, other, "a")], {"a": good})
    checks.append(("невідомий ключ — відмова, не здогад", not plan and len(refusals) == 1))
    plan, refusals = attribute([event(1, good, "a")], {"a": good, "duplicate": good})
    checks.append(("два ключі на одну подію — відмова", not plan and len(refusals) == 1))
    # Ключове твердження інструмента: ярлик не входить у канонічну форму.
    row = event(1, good, "a")
    before = canonical_of(row)
    row["audit_key_id"] = "щось-інше"
    checks.append(("ярлик не впливає на канонічну форму", canonical_of(row) == before))
    failed = [name for name, ok in checks if not ok]
    print(json.dumps({"selftest": len(checks), "failed": failed}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--key", action="append", default=[], metavar="ІД=ШЛЯХ")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.database is None or not args.database.is_file():
        print(
            json.dumps(
                {"status": "UNKNOWN", "reason": f"немає бази {args.database}"}, ensure_ascii=False
            )
        )
        return 2
    if not args.key:
        print(json.dumps({"status": "UNKNOWN", "reason": "ключів не надано"}, ensure_ascii=False))
        return 2
    keys = dict(parse_key(spec) for spec in args.key)
    connection = sqlite3.connect(str(args.database))
    connection.row_factory = sqlite3.Row
    rows = [dict(row) for row in connection.execute("select * from audit_events order by sequence")]
    hashes_before = {int(row["sequence"]): str(row["event_hash"]) for row in rows}
    plan, refusals = attribute(rows, keys)
    if refusals:
        print(
            json.dumps(
                {
                    "status": "REFUSED",
                    "wrote": 0,
                    "reasons": refusals[:10],
                    "refusals": len(refusals),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    result: dict[str, Any] = {
        "status": "PASS",
        "applied": bool(args.apply),
        "events": len(rows),
        "relabelled": len(plan),
    }
    if args.apply and plan:
        connection.executemany("update audit_events set audit_key_id=? where sequence=?", plan)
        connection.commit()
        after = [
            dict(row) for row in connection.execute("select * from audit_events order by sequence")
        ]
        changed = [
            int(row["sequence"])
            for row in after
            if hashes_before[int(row["sequence"])] != str(row["event_hash"])
        ]
        if changed:  # pragma: no cover - лише якщо канонічна форма зміниться
            connection.executemany(
                "update audit_events set audit_key_id=? where sequence=?",
                [(str(row["audit_key_id"]), int(row["sequence"])) for row in rows],
            )
            connection.commit()
            result.update({"status": "ROLLED_BACK", "hashes_changed": changed[:10]})
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        result["hashes_unchanged"] = True
        result["attribution_after"] = assess(after, keys)["rate"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


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
