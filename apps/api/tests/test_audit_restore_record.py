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
    read_record,
    rollback_accounted,
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


# Кожна умова `rollback_accounted` мусить мати ВЛАСНОГО свідка. Через знімок готовності
# цього не досягти: у справжній базі номер поза ланцюгом і хеш поза ланцюгом настають
# РАЗОМ, тож одна умова прикриває другу і мутант у прикритій виживає. Тому нижче — прямі
# проби чистої функції, де кожен вхід задається окремо.
def _accounted(
    *,
    record: RestoreRecord | None = None,
    anchor_sequence: int = 500,
    anchor_hash: str = "f" * 64,
    head_sequence: int = 10,
    hash_at_restore_point: str | None = "c" * 64,
) -> bool:
    if record is None:
        record = RestoreRecord(
            backup_file="korpus-probe.tar.enc",
            backup_manifest_sha256="a" * 64,
            restored_head_sequence=10,
            restored_head_hash="c" * 64,
            superseded_anchor_sequence=500,
            superseded_anchor_hash="f" * 64,
            restored_at="2026-09-08T15:20:18Z",
        )
    return rollback_accounted(
        record,
        anchor_sequence=anchor_sequence,
        anchor_hash=anchor_hash,
        head_sequence=head_sequence,
        hash_at_restore_point=hash_at_restore_point,
    )


def test_the_clean_case_is_accounted() -> None:
    """Позитивний контроль: без нього кожна проба нижче була б зеленою і порожньою."""
    assert _accounted() is True


def test_the_record_is_bound_to_the_anchor_number_not_only_to_its_hash() -> None:
    """Той самий хеш під ІНШИМ номером — окремий свідок для перевірки номера."""
    assert _accounted(anchor_sequence=501) is False


def test_the_record_is_bound_to_the_anchor_hash_not_only_to_its_number() -> None:
    """Той самий номер із ІНШИМ хешем — окремий свідок для перевірки хеша."""
    assert _accounted(anchor_hash="e" * 64) is False


def test_a_restore_point_beyond_the_head_is_refused_even_if_the_hash_agrees() -> None:
    """Голова нижча за точку відновлення: запис пояснював би те, чого ще не сталося."""
    assert _accounted(head_sequence=9) is False


def test_a_restore_point_absent_from_the_chain_is_refused() -> None:
    """Немає події з тим номером — немає чого порівнювати; мовчазне True тут заборонене."""
    assert _accounted(hash_at_restore_point=None) is False


def test_a_restore_point_with_another_hash_is_refused() -> None:
    assert _accounted(hash_at_restore_point="d" * 64) is False


# Ратчет покриття 08.09.2026 назвав три гілки, яких не бачив ЖОДЕН тест, і всі три —
# ВІДМОВИ. Відмова без свідка не відрізняється від відсутньої: код стоїть, вирок ніхто
# не міряв. Нижче кожна дістає свого.
def _payload(**overrides: object) -> dict[str, object]:
    codec = SignedRestoreCodec(KEY.encode("utf-8"))
    payload = codec.encode(_record(10, "c" * 64, 500))
    payload.update(overrides)
    return payload


def test_a_record_of_another_schema_is_refused() -> None:
    with pytest.raises(RestoreRecordError, match="unreadable"):
        SignedRestoreCodec(KEY.encode("utf-8")).decode(_payload(schema=2))


def test_a_record_missing_a_field_is_refused() -> None:
    payload = _payload()
    del payload["restored_head_hash"]
    with pytest.raises(RestoreRecordError, match="unreadable"):
        SignedRestoreCodec(KEY.encode("utf-8")).decode(payload)


def test_a_negative_sequence_is_refused_at_construction() -> None:
    codec = SignedRestoreCodec(KEY.encode("utf-8"))
    with pytest.raises(RestoreRecordError, match="negative sequence"):
        codec.encode(_record(-1, "c" * 64, 500))


def test_a_hash_of_the_wrong_length_is_refused_at_construction() -> None:
    """64 шістнадцяткові знаки — не стиль, а форма предмета: коротший хеш не з ланцюга."""
    codec = SignedRestoreCodec(KEY.encode("utf-8"))
    with pytest.raises(RestoreRecordError, match="invalid hash"):
        codec.encode(_record(10, "c" * 63, 500))


def test_an_unreadable_file_is_not_a_record(tmp_path: Path) -> None:
    """Нечитане і непідписане однаково НЕ приймаються — і однаково мовчки, без винятку."""
    target = tmp_path / "anchor.restore"
    target.write_text("{це не json", encoding="utf-8")
    assert read_record(target, KEY.encode("utf-8")) is None


def test_a_file_that_is_json_but_not_a_record_is_not_a_record(tmp_path: Path) -> None:
    target = tmp_path / "anchor.restore"
    target.write_text(json.dumps({"schema": 1}), encoding="utf-8")
    assert read_record(target, KEY.encode("utf-8")) is None


def test_a_missing_file_is_not_a_record(tmp_path: Path) -> None:
    assert read_record(tmp_path / "absent.restore", KEY.encode("utf-8")) is None


class _StoreWithoutAPath:
    """Якір, що живе не у файловій системі (як віддалений у GCS) — атрибута `path` нема."""


def test_an_anchor_store_without_a_path_carries_no_record(
    tmp_path: Path, admin_identity: object
) -> None:
    """Якщо якір не файл, запису відкату нема ЗВІДКИ взяти.

    Мовчазне `None` тут єдине правильне: вигадати шлях означало б шукати пояснення
    відкату не там, де живе предмет. Підміняється саме сховище, а не його поле —
    занулення `path` у файловому сховищі ламає сам якір, і тоді проба міряла б падіння
    замість гілки.
    """
    repository = _repository(tmp_path)
    reader = repository._audit_reader
    reader.anchor_store = _StoreWithoutAPath()  # type: ignore[assignment]
    assert reader._restore_record() is None
