"""Читальний жетон описує ОДИН стан корпусу — і кожна розбіжність його відкидає.

Відповідь робить кілька незалежних читань. Між ними схвалення чи скасування змінює те,
що бачить читач, і цитата починає посилатись на стан, якого вже немає. Жетон і монотонна
епоха існують рівно щоб цього не сталось, а `validate` — щоб розбіжність не пройшла
мовчки. Виміряно 08.09.2026: непокритими лишались саме відкидання.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from korpus.application.corpus_snapshot import CorpusConsistencyError, CorpusReadToken
from korpus.application.policy import PolicyEngine
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.corpus_snapshot import SqlCorpusSnapshotReader
from korpus.infrastructure.repository import SqlRepository
from sqlalchemy import delete

READER = Identity(
    subject="reader",
    roles=frozenset({"reader"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
)
AS_OF = date(2026, 9, 8)


def _reader(tmp_path: Path) -> SqlCorpusSnapshotReader:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'snapshot.db'}",
        "snapshot-audit-key",
        PolicyEngine(),
        tmp_path / "anchor.json",
    )
    repository.initialize(create_schema=True)
    snapshot = SqlCorpusSnapshotReader(repository)
    snapshot.initialize(create_schema=True)
    return snapshot


def test_a_token_for_another_scope_is_refused(tmp_path: Path) -> None:
    """Жетон іншого набору корпусів описує інший стан, хоч би збігалась епоха."""
    snapshot = _reader(tmp_path)
    token = snapshot.capture(READER, frozenset({"public"}), AS_OF)
    foreign = CorpusReadToken(
        state_epoch=token.state_epoch,
        release_id=token.release_id,
        as_of=token.as_of,
        corpus_ids=frozenset({"restricted"}),
        authorization_scope_id=token.authorization_scope_id,
    )
    with pytest.raises(CorpusConsistencyError, match="scope does not match"):
        snapshot.validate(READER, frozenset({"public"}), AS_OF, foreign)


def test_a_token_for_another_date_is_refused(tmp_path: Path) -> None:
    snapshot = _reader(tmp_path)
    token = snapshot.capture(READER, frozenset({"public"}), AS_OF)
    with pytest.raises(CorpusConsistencyError, match="historical date"):
        snapshot.validate(READER, frozenset({"public"}), date(2025, 1, 1), token)


def test_a_token_captured_before_the_state_moved_is_refused(tmp_path: Path) -> None:
    """Негативний контроль епохи: правило ловить ЗСУВ, а не сам факт перевірки."""
    from korpus.infrastructure.schema import corpus_state_epoch

    snapshot = _reader(tmp_path)
    token = snapshot.capture(READER, frozenset({"public"}), AS_OF)
    snapshot.validate(READER, frozenset({"public"}), AS_OF, token)

    with snapshot.engine.begin() as connection:
        connection.execute(
            corpus_state_epoch.update()
            .where(corpus_state_epoch.c.singleton_id == 1)
            .values(epoch=token.state_epoch + 1)
        )
    with pytest.raises(CorpusConsistencyError, match="state changed"):
        snapshot.validate(READER, frozenset({"public"}), AS_OF, token)


def test_an_uninitialized_epoch_is_refused(tmp_path: Path) -> None:
    """Немає епохи — немає монотонності. Це відмова, а не нуль."""
    from korpus.infrastructure.schema import corpus_state_epoch

    snapshot = _reader(tmp_path)
    with snapshot.engine.begin() as connection:
        connection.execute(delete(corpus_state_epoch))
    with pytest.raises(CorpusConsistencyError, match="epoch is not initialized"):
        snapshot.capture(READER, frozenset({"public"}), AS_OF)


def test_a_schema_without_the_singleton_epoch_row_is_refused(tmp_path: Path) -> None:
    """Рівно один рядок епохи, не «принаймні один».

    Другий рядок схема не пускає обмеженням, тож ця перевірка є другим рубежем —
    на випадок схеми, створеної не цим кодом. Досяжний її бік — коли рядка немає
    зовсім: тоді монотонність нема на чому будувати, і `initialize` без створення
    схеми мусить сказати це прямо, а не мовчки почати з нуля.
    """
    from korpus.infrastructure.schema import corpus_state_epoch

    snapshot = _reader(tmp_path)
    with snapshot.engine.begin() as connection:
        connection.execute(delete(corpus_state_epoch))
    with pytest.raises(RuntimeError, match="exactly singleton row 1"):
        snapshot.initialize(create_schema=False)
