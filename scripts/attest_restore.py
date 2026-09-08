#!/usr/bin/env python3
"""Підписати ВІДКАТ журналу, що стався через законне відновлення з бекапа.

Якір — зовнішня контрольна точка: він каже, скільки подій ланцюг колись мав. Відновлення
з бекапа відкочує ланцюг, і якір це чесно ловить — розгортання лишається не-готовим.
Виміряно 08.09.2026 після третього пошкодження: голова 29 010 при якорі 40 719.

Дірка була не у вироку, а в тому, що законному відновленню нема чим себе назвати: єдина
дорога, яка існувала, — СТЕРТИ файл якоря, і вона знищує саме той доказ, заради якого
якір є. Цей запис її замінює на підписаний і назавжди видимий акт.

Нічого не приймається на слово. Перед підписом перевіряється ТРИ речі:

  · маніфест бекапа автентичний — HMAC тим самим ключем із реєстру, що й при знятті;
  · нинішня голова лежить у ланцюгу відновленої бази (подія з тим номером має той хеш);
  · якір СПРАВДІ попереду голови — інакше пояснювати нема чого, і запис відхиляється.

Розрив від цього не зникає: `readiness_snapshot` друкує і кількість утрачених подій, і
сам запис. «Пояснено» — не «не було».

    attest_restore.py --database DB --anchor ШЛЯХ --backup ФАЙЛ --backup-key-file КЛЮЧ \
                      --audit-key-file КЛЮЧ [--apply]
    attest_restore.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from backup_crypto import load_key  # noqa: E402
from backup_manifest import sign as sign_manifest  # noqa: E402
from backup_manifest import validate_fields  # noqa: E402
from korpus.infrastructure.audit_restore import (  # noqa: E402
    RestoreRecord,
    RestoreRecordError,
    SignedRestoreCodec,
)


def head_of(database: Path) -> tuple[int, str]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30)
    try:
        sequence, head_hash = connection.execute(
            "select sequence, head_hash from audit_heads where singleton_id=1"
        ).fetchone()
    finally:
        connection.close()
    return int(sequence), str(head_hash)


def hash_at(database: Path, sequence: int) -> str | None:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30)
    try:
        row = connection.execute(
            "select event_hash from audit_events where sequence=?", (sequence,)
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else str(row[0])


def refusals(
    *,
    manifest: dict[str, Any],
    backup_file: str,
    manifest_key: bytes,
    head_sequence: int,
    head_hash: str,
    chain_hash: str | None,
    anchor_sequence: int,
) -> list[str]:
    """Причини не підписувати. Порожній список — єдиний дозвіл."""
    problems: list[str] = []
    try:
        validate_fields(
            manifest, expected_file=backup_file, expected_key_id=str(manifest.get("key_id", ""))
        )
    except ValueError as error:
        problems.append(f"маніфест бекапа не проходить перевірку полів: {error}")
    if not hmac.compare_digest(
        str(manifest.get("manifest_hmac_sha256", "")), sign_manifest(manifest, manifest_key)
    ):
        problems.append("маніфест бекапа не автентичний: HMAC не збігається")
    if chain_hash is None or not hmac.compare_digest(chain_hash, head_hash):
        problems.append(
            "голова не лежить у ланцюгу відновленої бази: подія з таким номером має інший хеш"
        )
    if anchor_sequence <= head_sequence:
        problems.append(
            f"якір ({anchor_sequence}) не попереду голови ({head_sequence}): відкату нема, "
            "а запис існує лише щоб пояснити відкат"
        )
    return problems


class Case(TypedDict):
    """Вхід `refusals` як ОДИН предмет, щоб отруту можна було вносити по одному полю.

    Без нього самоперевірка будувала випадки через `dict(...)` і `{**clean, ...}`: обидва
    дають `dict[str, object]`, тож `refusals(**clean)` не перевірявся ЖОДНИМ типом —
    30 помилок mypy на один шаблон. Це той самий рід, що й у гейтах: перевірка стояла,
    але дивилась на форму, з якої знято тип.
    """

    manifest: dict[str, Any]
    backup_file: str
    manifest_key: bytes
    head_sequence: int
    head_hash: str
    chain_hash: str | None
    anchor_sequence: int


def selftest() -> int:
    """Негативний контроль: кожна з трьох умов мусить ВІДХИЛЯТИ окремо."""
    problems: list[str] = []
    key = b"k" * 32
    manifest = {
        "schema": "korpus-postgres-backup-v4",
        "encrypted": True,
        "cipher": "AES-256-GCM",
        "file": "b.tar.enc",
        "key_id": "probe-key",
        "bytes": 10,
        "plaintext_bytes": 10,
        "sha256": "a" * 64,
        "plaintext_sha256": "b" * 64,
    }
    manifest["manifest_hmac_sha256"] = sign_manifest(manifest, key)
    clean: Case = {
        "manifest": manifest,
        "backup_file": "b.tar.enc",
        "manifest_key": key,
        "head_sequence": 10,
        "head_hash": "c" * 64,
        "chain_hash": "c" * 64,
        "anchor_sequence": 99,
    }
    if refusals(**clean):
        problems.append(f"чистий випадок відхилено: {refusals(**clean)}")

    forged_key = clean.copy()
    forged_key["manifest_key"] = b"x" * 32
    if not refusals(**forged_key):
        problems.append("чужий ключ маніфеста не відхилено")

    off_chain = clean.copy()
    off_chain["chain_hash"] = "d" * 64
    if not refusals(**off_chain):
        problems.append("голова поза ланцюгом не відхилена")

    no_rollback = clean.copy()
    no_rollback["anchor_sequence"] = 10
    if not refusals(**no_rollback):
        problems.append("якір, що не попереду голови, не відхилено")

    other_backup = clean.copy()
    other_backup["backup_file"] = "other.tar.enc"
    if not refusals(**other_backup):
        problems.append("чуже імʼя файла бекапа не відхилено")

    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "anchor.restore"
        record = RestoreRecord(
            "b.tar.enc", "a" * 64, 10, "c" * 64, 99, "f" * 64, "2026-09-08T00:00:00Z"
        )
        target.write_text(
            json.dumps(SignedRestoreCodec(key).encode(record), ensure_ascii=False), encoding="utf-8"
        )
        try:
            SignedRestoreCodec(b"y" * 32).decode(json.loads(target.read_text(encoding="utf-8")))
            problems.append("запис прочитано ЧУЖИМ ключем аудиту")
        except RestoreRecordError:
            pass
    print(
        json.dumps(
            {"selftest": "korpus.restore-attestation", "cases": 6, "failures": problems},
            ensure_ascii=False,
        )
    )
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    """Усі шляхи необовʼязкові лише тому, що --selftest не потребує жодного; поза ним
    відсутність кожного — помилка розбору, а не мовчазний дефолт."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--anchor", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--backup-key-file", type=Path)
    parser.add_argument("--audit-key-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    return parser


def assess(arguments: argparse.Namespace) -> tuple[dict[str, object], RestoreRecord, bytes]:
    """Зібрати вирок і запис, НЕ записуючи нічого: план і застосування — різні дії."""
    manifest_path = Path(str(arguments.backup) + ".json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Ключ бекапа — ШІСТНАДЦЯТКОВИЙ рядок, не сирі байти. Перший прогін відхилив
    # СПРАВЖНІЙ маніфест «HMAC не збігається», бо я прочитав файл байтами: сторож
    # відмовляв правильно за формою і хибно по суті.
    manifest_key = load_key(arguments.backup_key_file)
    audit_key = arguments.audit_key_file.read_bytes().strip()
    anchor = json.loads(arguments.anchor.read_text(encoding="utf-8"))
    head_sequence, head_hash = head_of(arguments.database)
    problems = refusals(
        manifest=manifest,
        backup_file=arguments.backup.name,
        manifest_key=manifest_key,
        head_sequence=head_sequence,
        head_hash=head_hash,
        chain_hash=hash_at(arguments.database, head_sequence),
        anchor_sequence=int(anchor["sequence"]),
    )
    record = RestoreRecord(
        backup_file=arguments.backup.name,
        backup_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        restored_head_sequence=head_sequence,
        restored_head_hash=head_hash,
        superseded_anchor_sequence=int(anchor["sequence"]),
        superseded_anchor_hash=str(anchor["head_hash"]),
        restored_at=datetime.now(UTC).isoformat(),
    )
    plan = {
        "database": str(arguments.database),
        "anchor": str(arguments.anchor),
        "backup": arguments.backup.name,
        "head_sequence": head_sequence,
        "anchor_sequence": int(anchor["sequence"]),
        "rollback_events": int(anchor["sequence"]) - head_sequence,
        "refusals": problems,
        "status": "REFUSED" if problems else ("APPLIED" if arguments.apply else "PLANNED"),
    }
    return plan, record, audit_key


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    for name in ("database", "anchor", "backup", "backup_key_file", "audit_key_file"):
        if getattr(arguments, name) is None:
            parser.error(f"--{name.replace('_', '-')} обовʼязковий поза --selftest")
    plan, record, audit_key = assess(arguments)
    problems = plan["refusals"]
    if not problems and arguments.apply:
        target = arguments.anchor.with_suffix(".restore")
        target.write_text(
            json.dumps(SignedRestoreCodec(audit_key).encode(record), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        target.chmod(0o600)
        plan["written"] = str(target)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
