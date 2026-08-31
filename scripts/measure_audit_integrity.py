#!/usr/bin/env python3
"""Журнал доказів, який ніхто не перевіряв, бо перевірка дивилась на іншу базу.

КОРПУС продає одне: знайти затверджене джерело й показати, ДЕ САМЕ це написано. Журнал
подій — те, що робить цю обіцянку перевірюваною заднім числом: кожна подія несе HMAC, кожна
посилається на хеш попередньої. `make audit-verify` існує з самого початку й читає
`./var/korpus.db` — порожню базу розробника. База, яку обслуговують, лежить в іншому місці,
і її ланцюг не перевіряв ніхто й ніколи. Виміряно 31.08.2026.

Що знайшлось у ній (7223 події):
  · 4061 подія підписана рядком `replace-local-audit-key` — літералом із `config.py`.
    Для JWT-секрета проєкт таке забороняє (`startswith("replace-")`), для ключа аудиту —
    ні, хоча JWT боронить сесію, а цей ключ боронить сам доказ.
  · 3162 події підписані ключем процесу, що обслуговує.
  · Обидва сегменти записані як `legacy-unversioned`, тож жодна каблучка не перевірить
    журнал цілим: колонка `audit_key_id` існує саме для цього і не заповнена.
  · Підробки НЕМАЄ: кожна подія перевіряється рівно одним із двох ключів, зчеплення
    `previous_hash` ціле, голова збігається з останньою подією.

Тому вимір рахує не «чи цілий ланцюг», а три РІЗНІ речі, які раніше зливались в одне
«audit hash mismatch»:

  attributed   — подія перевіряється ключем, який САМА називає. Це і є справжня частка.
  misattributed— перевіряється якимось наданим ключем, але не тим, що названий у рядку.
                 Лікується атрибуцією (`attribute_audit_keys.py`), бо `audit_key_id` не
                 входить у канонічну форму й переписування ярлика не чіпає хешів.
  unverifiable — не перевіряється ЖОДНИМ наданим ключем. Ось це — або підробка, або ключа
                 просто не дали. Розрізнити зсередини неможливо, тому вимір НЕ називає це
                 підробкою: він каже, скільки ключів йому дали.

Ключів у репозиторії немає й бути не може. Без `--key` вимір повертає UNKNOWN (rc=2), а не
PASS: сліпа перевірка, що звітує успіх, гірша за відсутню.

    measure_audit_integrity.py --database DB --key legacy-unversioned=@config \
                               --key korpus-serving-2026-08=/шлях/до/ключа
    measure_audit_integrity.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus_identity import inputs_digest, report_inputs  # noqa: E402
from korpus.infrastructure.audit_canonical import audit_canonical  # noqa: E402

LEGACY_KEY_ID = "legacy-unversioned"
#: Те, що конфіг ставить, коли оператор нічого не поставив. Ключ, надрукований у
#: вихідному коді, не є секретом; подія, підписана ним, не є засвідченою.
PLACEHOLDER = "replace-local-audit-key"
#: Мінімум, який проєкт уже вимагає від JWT-секрета. Ключ аудиту боронить більше.
MIN_KEY_CHARS = 32


def as_iso(value: Any) -> str:
    """SQLite повертає наївний час; підпис рахувався над часом з поясом."""
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


def canonical_of(row: dict[str, Any]) -> bytes:
    canonical: bytes = audit_canonical(
        sequence=row["sequence"],
        event_id=row["event_id"],
        occurred_at=as_iso(row["occurred_at"]),
        actor_subject=row["actor_subject"],
        action=row["action"],
        resource_type=row["resource_type"],
        resource_id=row["resource_id"],
        payload_json=row["payload_json"],
        previous_hash=row["previous_hash"],
    )
    return canonical


def signed_by(row: dict[str, Any], keys: dict[str, bytes]) -> str | None:
    """Ід ключа, який справді дає цей підпис, або None. Перебір, не довіра ярлику."""
    message = canonical_of(row)
    for key_id, material in keys.items():
        candidate = hmac.new(material, message, hashlib.sha256).hexdigest()
        if hmac.compare_digest(candidate, str(row["event_hash"])):
            return key_id
    return None


def assess(rows: list[dict[str, Any]], keys: dict[str, bytes]) -> dict[str, Any]:
    attributed = misattributed = unverifiable = 0
    linkage_breaks: list[int] = []
    placeholder_signed = 0
    misattributed_examples: list[dict[str, Any]] = []
    previous = "0" * 64
    expected = 1
    gaps: list[int] = []
    for row in rows:
        if row["sequence"] != expected:
            gaps.append(int(row["sequence"]))
            expected = int(row["sequence"])
        expected += 1
        if str(row["previous_hash"]) != previous:
            linkage_breaks.append(int(row["sequence"]))
        previous = str(row["event_hash"])
        actual = signed_by(row, keys)
        named = str(row["audit_key_id"] or LEGACY_KEY_ID)
        if actual is None:
            unverifiable += 1
        elif actual == named:
            attributed += 1
        else:
            misattributed += 1
            if len(misattributed_examples) < 3:
                misattributed_examples.append(
                    {"sequence": int(row["sequence"]), "names": named, "signed_by": actual}
                )
        if actual is not None and keys[actual] == PLACEHOLDER.encode():
            placeholder_signed += 1
    total = len(rows)
    return {
        "events": total,
        "attributed": attributed,
        "misattributed": misattributed,
        "unverifiable": unverifiable,
        "placeholder_signed": placeholder_signed,
        "linkage_breaks": linkage_breaks[:10],
        "sequence_gaps": gaps[:10],
        # Частка над порожнім — відсутність виміру, не нуль.
        "rate": (attributed / total) if total else None,
        "misattributed_examples": misattributed_examples,
    }


def rule(report: dict[str, Any], *, floor: float | None, ceiling: int | None) -> None:
    """Вирок окремо від виміру: інструмент, що лише міряє, лишає судити нікому.

    На еталоні це й виявилось: подія, що називає не той ключ, який її підписав, знижувала
    частку — і жоден код виходу про це не казав, бо вирок за головною метрикою виносив
    хтось інший, а насправді не виносив ніхто.
    """
    rate = report["rate"]
    if floor is not None and (rate is None or rate < floor):
        report["status"] = "REGRESSED"
        report["regression"] = (
            f"атрибутовано {rate}, підлога {floor}: подія, що називає не той ключ, який її "
            "підписав, робить журнал неперевірюваним цілим."
        )
    elif ceiling is not None and report["placeholder_signed"] > ceiling:
        report["status"] = "REGRESSED"
        report["regression"] = (
            f"подій, підписаних ключем із вихідного коду: {report['placeholder_signed']}, "
            f"стеля {ceiling}. Нова така подія означає, що якийсь процес знову пише в цей "
            "журнал із конфігом за замовчуванням."
        )


def parse_key(spec: str) -> tuple[str, bytes]:
    """`ід=@config` бере плейсхолдер із коду; `ід=шлях` читає файл."""
    if "=" not in spec:
        raise ValueError(f"ключ подається як ід=шлях, отримано {spec!r}")
    key_id, _, source = spec.partition("=")
    if source == "@config":
        return key_id, PLACEHOLDER.encode()
    return key_id, Path(source).read_bytes().strip()


def selftest() -> int:
    """Отрути по ДАНИХ: підмінюємо те, що вимір читає, і дивимось, чи він червоніє."""
    good = b"k" * 40
    other = b"j" * 40

    def event(seq: int, previous: str, key: bytes, named: str) -> dict[str, Any]:
        row = {
            "sequence": seq,
            "event_id": f"e{seq}",
            "occurred_at": "2026-08-31T00:00:00+00:00",
            "actor_subject": "a",
            "action": "x",
            "resource_type": "r",
            "resource_id": None,
            "payload_json": "{}",
            "previous_hash": previous,
            "audit_key_id": named,
        }
        row["event_hash"] = hmac.new(key, canonical_of(row), hashlib.sha256).hexdigest()
        return row

    zero = "0" * 64
    cases: list[tuple[str, dict[str, Any], str, Any]] = []
    ok = event(1, zero, good, "a")
    cases.append(
        ("названий ключ підписав — зараховано", assess([ok], {"a": good}), "attributed", 1)
    )
    wrong = event(1, zero, other, "a")
    cases.append(
        (
            "підписав ІНШИЙ ключ — не зараховано",
            assess([wrong], {"a": good, "b": other}),
            "misattributed",
            1,
        )
    )
    cases.append(
        ("жоден наданий ключ не підходить", assess([wrong], {"a": good}), "unverifiable", 1)
    )
    tampered = dict(ok)
    tampered["payload_json"] = '{"changed":1}'
    cases.append(("зміна вмісту ламає підпис", assess([tampered], {"a": good}), "unverifiable", 1))
    first = event(1, zero, good, "a")
    broken = event(2, "f" * 64, good, "a")
    cases.append(
        ("розрив зчеплення помічено", assess([first, broken], {"a": good}), "linkage_breaks", [2])
    )
    cases.append(("порожній набір не має частки", assess([], {"a": good}), "rate", None))
    ph = event(1, zero, PLACEHOLDER.encode(), "a")
    cases.append(
        (
            "підпис плейсхолдером порахований окремо",
            assess([ph], {"a": PLACEHOLDER.encode()}),
            "placeholder_signed",
            1,
        )
    )
    failures = [
        f"{name}: {field}={report[field]!r}, очікувалось {want!r}"
        for name, report, field, want in cases
        if report[field] != want
    ]
    print(json.dumps({"selftest": len(cases), "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--key", action="append", default=[], metavar="ІД=ШЛЯХ")
    parser.add_argument(
        "--max-placeholder-signed",
        type=int,
        default=None,
        help=(
            "стеля на число подій, підписаних ключем із вихідного коду. Їх не можна "
            "перепідписати — це змінило б event_hash і зруйнувало ланцюг, — тому борг "
            "не зменшується, а лише не росте."
        ),
    )
    parser.add_argument(
        "--min-attribution",
        type=float,
        default=None,
        help=(
            "підлога на частку подій, які перевіряються ключем, що САМІ називають. Без "
            "неї інструмент лише міряє: вирок за головною метрикою виносив хтось інший, "
            "і на еталоні виявилось, що не виносив ніхто."
        ),
    )
    parser.add_argument("--out", type=Path, default=ROOT / "var/audit-integrity.json")
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
        # Сліпий прогін не має права звітувати PASS.
        print(
            json.dumps(
                {
                    "status": "UNKNOWN",
                    "reason": "жодного ключа не надано; без ключа перевірити підпис неможливо",
                },
                ensure_ascii=False,
            )
        )
        return 2
    keys = dict(parse_key(spec) for spec in args.key)
    weak = sorted(
        key_id
        for key_id, material in keys.items()
        if material == PLACEHOLDER.encode() or len(material) < MIN_KEY_CHARS
    )
    connection = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = [dict(row) for row in connection.execute("select * from audit_events order by sequence")]
    head = connection.execute("select sequence, head_hash from audit_heads").fetchone()
    report = assess(rows, keys)
    report.update(
        {
            "schema": "korpus.audit-integrity.v1",
            "ran_at": datetime.now(UTC).isoformat(),
            "database": str(args.database),
            # Ключі входять у входи звіту ІМЕНАМИ, не матеріалом: змінився набір ключів —
            # змінилась і атрибуція, тож старе число більше не про цей стан. Матеріал у
            # звіт не потрапляє ніколи.
            "inputs": report_inputs(
                args.database, Path(__file__).resolve(), keys="|".join(sorted(keys))
            ),
            "inputs_digest": inputs_digest(
                report_inputs(args.database, Path(__file__).resolve(), keys="|".join(sorted(keys)))
            ),
            "keys_offered": sorted(keys),
            "weak_keys": weak,
            "head_matches_last_event": bool(
                head and rows and str(head["head_hash"]) == str(rows[-1]["event_hash"])
            ),
            "status": "MEASURED" if rows else "UNKNOWN",
            "cannot_judge": [
                "Подія, що не перевіряється жодним НАДАНИМ ключем, може бути підробленою або "
                "підписаною ключем, якого не дали. Зсередини це не розрізняється.",
                "Ключ, який пройшов перевірку довжини, не є через це збереженим таємно.",
            ],
        }
    )
    rule(report, floor=args.min_attribution, ceiling=args.max_placeholder_signed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "REGRESSED":
        return 1
    return 0 if report["status"] == "MEASURED" else 2


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
