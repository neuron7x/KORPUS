"""Оголошений відкат журналу: єдина дорога назад, яка не ховає втрати.

Якір каже, скільки подій ланцюг колись мав. Відновлення з бекапа ВІДКОЧУЄ ланцюг, і якір
це чесно ловить: розгортання лишається не-готовим, доки журнал не дожене якір. Виміряно
08.09.2026 після третього пошкодження за добу — голова 29 010 при якорі 40 719.

Дірка була не у вироку, а в тому, що ЗАКОННОМУ відновленню нема чим себе назвати: єдина
дорога, яка існувала, — стерти файл якоря, тобто знищити доказ. Тести нижче тримають
обидва боки цієї заміни: запис МУСИТЬ підніматися лише перевіреним, і розрив МУСИТЬ
лишатися видимим навіть тоді, коли він пояснений.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from korpus.application.policy import PolicyEngine
from korpus.infrastructure.audit_restore import (
    RestoreRecord,
    RestoreRecordError,
    SignedRestoreCodec,
)
from korpus.infrastructure.repository import SqlRepository

KEY = "seam-audit-key"
HEAD_AT_RESTORE = 3


def _repository(tmp_path: Path) -> SqlRepository:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'restore.db'}", KEY, PolicyEngine(), tmp_path / "anchor.json"
    )
    repository.initialize()
    return repository


def _rolled_back(tmp_path: Path, admin_identity: object) -> tuple[SqlRepository, int, str, int]:
    """Розгортання ПІСЛЯ відкату: якір попереду голови, як після відновлення з бекапа."""
    repository = _repository(tmp_path)
    for index in range(HEAD_AT_RESTORE):
        repository.append_audit(admin_identity, "probe", "test", str(index), {"i": index})
    head = repository.readiness_snapshot(max_pending_events=64, max_pending_age_seconds=60.0)
    head_sequence = int(head["audit_head_sequence"])
    head_hash = str(head["audit_head_hash"])
    ahead = head_sequence + 500
    repository.anchor_store.write(ahead, "f" * 64)
    return repository, head_sequence, head_hash, ahead


def _write_record(repository: SqlRepository, payload: dict[str, object]) -> None:
    path = Path(repository.anchor_store.path).with_suffix(".restore")
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _snapshot(repository: SqlRepository) -> dict[str, object]:
    return repository.readiness_snapshot(max_pending_events=64, max_pending_age_seconds=60.0)


def _record(head_sequence: int, head_hash: str, ahead: int) -> RestoreRecord:
    return RestoreRecord(
        backup_file="korpus-probe.tar.enc",
        backup_manifest_sha256="a" * 64,
        restored_head_sequence=head_sequence,
        restored_head_hash=head_hash,
        superseded_anchor_sequence=ahead,
        superseded_anchor_hash="f" * 64,
        restored_at="2026-09-08T15:20:18Z",
    )


def test_a_rollback_without_a_record_stays_not_ready(
    tmp_path: Path, admin_identity: object
) -> None:
    """Умовчання fail-closed: відкат без пояснення — це втрачені рядки, і так і звітується."""
    repository, _, _, _ = _rolled_back(tmp_path, admin_identity)

    snapshot = _snapshot(repository)

    assert snapshot["anchor_not_ahead"] is False
    assert snapshot["rollback_accounted"] is False
    assert snapshot["ready"] is False


def test_a_verified_record_accounts_for_the_rollback(
    tmp_path: Path, admin_identity: object
) -> None:
    repository, head_sequence, head_hash, ahead = _rolled_back(tmp_path, admin_identity)
    codec = SignedRestoreCodec(KEY.encode("utf-8"))
    _write_record(repository, codec.encode(_record(head_sequence, head_hash, ahead)))

    snapshot = _snapshot(repository)

    assert snapshot["rollback_accounted"] is True
    assert snapshot["ready"] is True


def test_the_gap_stays_visible_even_when_it_is_accounted(
    tmp_path: Path, admin_identity: object
) -> None:
    """«Пояснено» — не «не було». Число втрачених подій лишається в знімку назавжди."""
    repository, head_sequence, head_hash, ahead = _rolled_back(tmp_path, admin_identity)
    codec = SignedRestoreCodec(KEY.encode("utf-8"))
    _write_record(repository, codec.encode(_record(head_sequence, head_hash, ahead)))

    snapshot = _snapshot(repository)

    assert snapshot["rollback_events"] == ahead - head_sequence
    assert snapshot["anchor_sequence"] == ahead
    assert snapshot["restore_record"] is not None


def test_a_forged_record_does_not_account_for_anything(
    tmp_path: Path, admin_identity: object
) -> None:
    """Підпис тим самим ключем, що й якір: хто може підробити запис, той уже може якір."""
    repository, head_sequence, head_hash, ahead = _rolled_back(tmp_path, admin_identity)
    payload = SignedRestoreCodec(b"not-the-audit-key").encode(
        _record(head_sequence, head_hash, ahead)
    )
    _write_record(repository, payload)

    snapshot = _snapshot(repository)

    assert snapshot["rollback_accounted"] is False
    assert snapshot["ready"] is False


def test_a_record_for_another_anchor_cannot_be_reused(
    tmp_path: Path, admin_identity: object
) -> None:
    """Запис пояснює САМЕ той якір, який називає. Інакше він був би багаторазовим дозволом."""
    repository, head_sequence, head_hash, ahead = _rolled_back(tmp_path, admin_identity)
    codec = SignedRestoreCodec(KEY.encode("utf-8"))
    stale = _record(head_sequence, head_hash, ahead)
    _write_record(repository, codec.encode(stale))
    repository.anchor_store.write(ahead + 1, "e" * 64)

    snapshot = _snapshot(repository)

    assert snapshot["rollback_accounted"] is False
    assert snapshot["ready"] is False


def test_a_restore_point_outside_the_chain_is_refused(
    tmp_path: Path, admin_identity: object
) -> None:
    """Точка відновлення мусить ЛЕЖАТИ в нинішньому ланцюгу, а не просто бути названою."""
    repository, head_sequence, _, ahead = _rolled_back(tmp_path, admin_identity)
    codec = SignedRestoreCodec(KEY.encode("utf-8"))
    _write_record(repository, codec.encode(_record(head_sequence, "b" * 64, ahead)))

    snapshot = _snapshot(repository)

    assert snapshot["rollback_accounted"] is False
    assert snapshot["ready"] is False


def test_a_record_beyond_the_head_is_refused(tmp_path: Path, admin_identity: object) -> None:
    repository, head_sequence, head_hash, ahead = _rolled_back(tmp_path, admin_identity)
    codec = SignedRestoreCodec(KEY.encode("utf-8"))
    _write_record(repository, codec.encode(_record(head_sequence + 10, head_hash, ahead)))

    snapshot = _snapshot(repository)

    assert snapshot["rollback_accounted"] is False
    assert snapshot["ready"] is False


def test_a_record_that_describes_no_rollback_is_refused_at_construction() -> None:
    """Якір, що не попереду голови, відкату не потребує — і запис там нічого не пояснює."""
    codec = SignedRestoreCodec(KEY.encode("utf-8"))
    with pytest.raises(RestoreRecordError, match="does not describe a rollback"):
        codec.encode(_record(10, "c" * 64, 10))
