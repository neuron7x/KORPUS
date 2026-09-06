#!/usr/bin/env python3
"""Чи корпус ПЕРЕНОСИТЬСЯ на інше дерево тотожним. Умова закритої бети.

256 документів живуть лише в ігнорованому `var/`, тож свіжий клон дає систему з одним
фікстурним документом — і саме її побачить запрошена людина. Незалежний аудит
06.09.2026 виніс «дороги дістати корпус НЕМАЄ»: пробували `offline-pack` (503, вимкнено)
і `import-corpus` (маніфесту в дереві нема). Дорога існувала й працювала —
`backup_sqlite.sh` / `restore_sqlite.sh`. Невидимим був не механізм, а його ІМʼЯ:
ціль описувала захист від втрати, а не встановлення.

Цей гейт звіряє живий корпус із відновленим по осях, які не збігаються за побудовою.

    verify_corpus_transport.py --live var/runtime/... --restored /шлях/до/відновленого
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "var/runtime/corpus-v6-20260807"
OUT = ROOT / "reports/closure/CORPUS_TRANSPORT_REHEARSAL.json"


def survey(root: Path) -> dict[str, Any]:
    """Що корпус містить. Множина імен обʼєктів сюди НЕ входить навмисно.

    Сховище адресує вміст хешем, тож множина імен і множина `source_hash` тотожні за
    побудовою: рахувати обидві означало б рахувати одне двічі й видавати за дві осі.
    Незалежне питання — чи дійшли БАЙТИ, і воно живе в `content_holds` нижче.
    """
    connection = sqlite3.connect(f"file:{root / 'korpus.db'}?mode=ro", uri=True)
    hashes = sorted(
        str(row[0]) for row in connection.execute("select source_hash from document_versions")
    )
    return {
        "documents": connection.execute("select count(*) from documents").fetchone()[0],
        "approved_versions": connection.execute(
            "select count(*) from document_versions where review_state='approved'"
        ).fetchone()[0],
        "spans": connection.execute("select count(*) from evidence_spans").fetchone()[0],
        "objects": sum(1 for path in (root / "objects").rglob("*") if path.is_file()),
        "source_hash_set_sha256": hashlib.sha256("\n".join(hashes).encode()).hexdigest(),
    }


def content_holds(root: Path) -> dict[str, Any]:
    """Чи кожен обʼєкт у ВІДНОВЛЕНІЙ копії відповідає власному імені-хешу."""
    mismatches: list[dict[str, str]] = []
    checked = hashed = 0
    for path in sorted((root / "objects").rglob("*")):
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checked += 1
        hashed += path.stat().st_size
        if digest != path.name:
            mismatches.append({"name": path.name, "actual": digest})
    return {
        "objects_checked": checked,
        "bytes_hashed": hashed,
        "content_addressing_holds": checked > 0 and not mismatches,
        "mismatches": mismatches[:5],
    }


def verdict(
    live: dict[str, Any], restored: dict[str, Any], content: dict[str, Any]
) -> dict[str, Any]:
    """Порожній корпус, перенесений тотожно, не є доказом переносу корпусу."""
    checks = {
        "restored_is_identical": live == restored,
        "corpus_is_not_empty": bool(live.get("documents")) and bool(live.get("spans")),
        # Вирок НЕ довіряє прапорцю, якого сам не перевіряв: нуль перехешованих обʼєктів
        # і чиста перевірка виглядають однаково, якщо читати лише `content_addressing_holds`.
        # Спіймано власною самоперевіркою 06.09.2026 — знаменник мусить бути в вироку.
        "object_bytes_survived": bool(content["content_addressing_holds"])
        and int(content.get("objects_checked", 0)) > 0
        and not content.get("mismatches"),
    }
    failures = [name for name, ok in checks.items() if not ok]
    return {
        "schema": "korpus.corpus-transport-rehearsal.v1",
        "measured_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "live": live,
        "restored": restored,
        "content_verification": content,
        "checks": checks,
        "failures": failures,
        "differences": {k: [live[k], restored.get(k)] for k in live if live[k] != restored.get(k)},
        "what_this_does_not_prove": (
            "Що відновлений корпус ВІДПОВІДАЄ. Тут звірено тотожність вмісту; здатність "
            "відповідати міряється запитами до піднятого на ньому сервісу."
        ),
    }


def selftest() -> int:
    """Отрути по ДАНИХ: вирок мусить залежати від вмісту, не від наявності словників."""
    full = {"documents": 256, "spans": 31464, "objects": 256, "h": "a"}
    empty = {"documents": 0, "spans": 0, "objects": 0, "h": "a"}
    good = {
        "objects_checked": 256,
        "bytes_hashed": 1,
        "content_addressing_holds": True,
        "mismatches": [],
    }
    torn = {**good, "content_addressing_holds": False, "mismatches": [{"name": "x", "actual": "y"}]}
    cases = [
        ("тотожні й непорожні — PASS", verdict(full, full, good)["status"], "PASS"),
        ("розбіжність — FAIL", verdict(full, {**full, "spans": 1}, good)["status"], "FAIL"),
        (
            "порожній корпус, перенесений тотожно, — FAIL",
            verdict(empty, empty, good)["status"],
            "FAIL",
        ),
        ("байти не дійшли — FAIL", verdict(full, full, torn)["status"], "FAIL"),
        (
            "нуль перевірених обʼєктів не є згодою",
            verdict(full, full, {**good, "objects_checked": 0})["status"],
            "FAIL",
        ),
        (
            "розбіжність названа",
            verdict(full, {**full, "spans": 1}, good)["differences"],
            {"spans": [31464, 1]},
        ),
    ]
    bad = [name for name, got, want in cases if got != want]
    for name in bad:
        print(f"  x {name}", file=sys.stderr)
    print(json.dumps({"selftest": len(cases), "failed": bad}, ensure_ascii=False))
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", type=Path, default=LIVE)
    parser.add_argument("--restored", type=Path)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.restored:
        parser.error("--restored обовʼязковий: без відновленої копії предмета виміру нема")
    payload = verdict(survey(args.live), survey(args.restored), content_holds(args.restored))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
