"""Оголошене ВІДНОВЛЕННЯ журналу: єдина дорога назад, яка не ховає втрати.

Якір — зовнішня контрольна точка: він каже, скільки подій ланцюг колись мав. Відновлення
з бекапа ВІДКОЧУЄ ланцюг, і якір це чесно ловить — `anchor_not_ahead` стає хибним, і
розгортання лишається не-готовим, доки журнал не дожене якір. Виміряно 08.09.2026 після
третього пошкодження: голова 29 010 при якорі 40 719, тобто 11 709 подій.

Дірка не в цьому вироку, а в тому, що ЗАКОННОМУ відновленню нема чим себе назвати.
Єдина дорога, яка сьогодні існує, — стерти або переписати файл якоря, і вона знищує саме
той доказ, заради якого якір є. Тому запис нижче — НЕ послаблення тамперостійкості, а її
посилення: він перетворює мовчазне затирання на підписаний, назавжди записаний акт.

Запис нічого не оголошує на віру. Він ПЕРЕВІРЯЄТЬСЯ трьома незалежними умовами:

  · MAC тим самим ключем аудиту, що захищає якір — отже ніякої НОВОЇ довіри не додано:
    хто може підробити цей запис, той уже може підробити якір;
  · точка відновлення мусить лежати В НИНІШНЬОМУ ланцюгу: подія з тим номером мусить
    мати саме той хеш;
  · запис мусить називати ТОЙ САМИЙ якір, який він пояснює. Щойно якір зрушить, запис
    перестає діяти — його не можна перевикористати на інший відкат.

Розрив лишається видимим завжди: `anchor_gap_events` і сам запис входять у знімок
готовності, і жодна умова їх не приховує.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RestoreRecordError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestoreRecord:
    backup_file: str
    backup_manifest_sha256: str
    restored_head_sequence: int
    restored_head_hash: str
    superseded_anchor_sequence: int
    superseded_anchor_hash: str
    restored_at: str


class SignedRestoreCodec:
    """Той самий рід підпису, що й у якоря, і НАВМИСНО той самий ключ."""

    def __init__(self, key: bytes) -> None:
        self.key = key

    def mac(self, record: RestoreRecord) -> str:
        message = (
            f"restore-v1:{record.backup_file}:{record.backup_manifest_sha256}:"
            f"{record.restored_head_sequence}:{record.restored_head_hash}:"
            f"{record.superseded_anchor_sequence}:{record.superseded_anchor_hash}"
        ).encode()
        return hmac.new(self.key, message, hashlib.sha256).hexdigest()

    def encode(self, record: RestoreRecord) -> dict[str, Any]:
        self._validate(record)
        return {
            "schema": 1,
            "backup_file": record.backup_file,
            "backup_manifest_sha256": record.backup_manifest_sha256,
            "restored_head_sequence": record.restored_head_sequence,
            "restored_head_hash": record.restored_head_hash,
            "superseded_anchor_sequence": record.superseded_anchor_sequence,
            "superseded_anchor_hash": record.superseded_anchor_hash,
            "restored_at": record.restored_at,
            "mac": self.mac(record),
        }

    def decode(self, payload: Any) -> RestoreRecord:
        try:
            if int(payload["schema"]) != 1:
                raise ValueError("unsupported schema")
            record = RestoreRecord(
                backup_file=str(payload["backup_file"]),
                backup_manifest_sha256=str(payload["backup_manifest_sha256"]),
                restored_head_sequence=int(payload["restored_head_sequence"]),
                restored_head_hash=str(payload["restored_head_hash"]),
                superseded_anchor_sequence=int(payload["superseded_anchor_sequence"]),
                superseded_anchor_hash=str(payload["superseded_anchor_hash"]),
                restored_at=str(payload["restored_at"]),
            )
            supplied = str(payload["mac"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RestoreRecordError("restore record is unreadable") from exc
        self._validate(record)
        if not hmac.compare_digest(self.mac(record), supplied):
            raise RestoreRecordError("restore record MAC mismatch")
        return record

    @staticmethod
    def _validate(record: RestoreRecord) -> None:
        if record.restored_head_sequence < 0 or record.superseded_anchor_sequence < 0:
            raise RestoreRecordError("restore record has a negative sequence")
        if len(record.restored_head_hash) != 64 or len(record.superseded_anchor_hash) != 64:
            raise RestoreRecordError("restore record has an invalid hash")
        if record.superseded_anchor_sequence <= record.restored_head_sequence:
            # Запис пояснює ВІДКАТ. Якір, що не попереду голови, відкату не потребує, і
            # приймати такий запис означало б дозволити його там, де він нічого не пояснює.
            raise RestoreRecordError("restore record does not describe a rollback")


def read_record(path: Path, key: bytes) -> RestoreRecord | None:
    """Запис або None. Нечитаний і непідписаний однаково НЕ приймаються."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return SignedRestoreCodec(key).decode(payload)
    except RestoreRecordError:
        return None


def restore_summary(record: RestoreRecord | None) -> dict[str, object] | None:
    """Що з запису показувати назовні: досить, щоб знайти бекап і перевірити його,
    і без MAC — підпис доводиться перерахунком над файлом, не переказом у відповіді."""
    if record is None:
        return None
    return {
        "backup_file": record.backup_file,
        "restored_head_sequence": record.restored_head_sequence,
        "superseded_anchor_sequence": record.superseded_anchor_sequence,
        "restored_at": record.restored_at,
    }


def rollback_accounted(
    record: RestoreRecord | None,
    *,
    anchor_sequence: int,
    anchor_hash: str,
    head_sequence: int,
    hash_at_restore_point: str | None,
) -> bool:
    """Чи пояснює запис САМЕ цей відкат — і чи лежить точка відновлення в ланцюгу."""
    if record is None:
        return False
    if record.superseded_anchor_sequence != anchor_sequence:
        return False
    if not hmac.compare_digest(record.superseded_anchor_hash, anchor_hash):
        return False
    if record.restored_head_sequence > head_sequence:
        return False
    if hash_at_restore_point is None:
        return False
    return hmac.compare_digest(record.restored_head_hash, hash_at_restore_point)
