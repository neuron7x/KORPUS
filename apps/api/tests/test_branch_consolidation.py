"""Після зведення «загублене» і «ніколи не існувало» виглядають однаково.

01.09.2026 гілок було сорок: локальні, `gitlab/*` і двадцять п'ять `origin/*` із лінії,
що розійшлася 12–19 серпня. Їх зводили в одну канонічну. Знімок зроблено ДО — і зроблено
ТЕГАМИ, а не файлом: файл у теці процесу переживе не кожен день, тег живе в самому
репозиторії й тримає коміт від збирача сміття.

Найважливіший тест тут — останній. Перша версія цього інструмента сказала ACCEPTED
одразу після мержу, коли лан насправді мав ТРИ червоні: вона прочитала домерджевий
`lane-validate.json` і звірила мутантів на ВНУТРІШНЮ узгодженість (511 із 511) замість
звірки з каталогом, що виріс до 523. Сторож доповідав про власний застарілий вхід як про
стан предмета — той самий клас, що `pgrep -f`, який матчить сам себе.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_branch_consolidation import _literal, alembic_heads  # noqa: E402


def test_a_revision_is_read_from_its_assignment() -> None:
    assert _literal("revision = '0018_operational_competencies'", "revision") == (
        "0018_operational_competencies"
    )


def test_none_is_absence_not_a_name() -> None:
    """Корінь ланцюга має `down_revision = None`; прочитати це як ім'я — втратити голову."""
    assert _literal("down_revision = None", "down_revision") is None


def test_an_empty_string_is_absence_too() -> None:
    assert _literal("down_revision = ''", "down_revision") is None


def test_a_commented_line_is_not_an_assignment() -> None:
    """Негативний контроль: розбір, що читає коментарі, вигадає голови з нічого."""
    assert _literal("# revision = 'x'", "revision") is None


def test_this_tree_has_exactly_one_alembic_head() -> None:
    """Головне твердження зведення.

    Канонічна лінія й GitHub-лінія пронумерували міграції ОДНАКОВО з різним вмістом:
    0016 `learning_course_graph` проти `temporal_corpus_snapshot`, і те саме на 0017 та
    0018. Файли різні, тож текстового конфлікту при мержі НЕМАЄ — побачить лише alembic,
    і вже після нього. Дві голови означають базу, яку не можна мігрувати.
    """
    heads = alembic_heads()

    assert len(heads) == 1, heads


def test_the_head_is_the_one_the_deployed_base_expects() -> None:
    """Не просто «одна», а САМЕ ТА, яку очікує розгорнута база.

    Оновлено 01.09.2026 при портуванні знімка корпусу з GitHub-лінії: ланцюг подовжено
    на одну міграцію (`0019_temporal_corpus_snapshot`), і
    пін зсунуто СВІДОМО. Пін існує, щоб зсув не стався непоміченим, а не щоб його
    заборонити — тому змінюється він разом із міграцією, в одному комітті з нею.
    """
    assert alembic_heads() == ["0023_evidence_search_vector.py"]


# ── Найдорожча помилка цього інструмента: він довіряв власному застарілому входові.


def test_a_report_taken_before_the_head_is_stale() -> None:
    """Звіт, знятий до поточного HEAD, описує ІНШЕ дерево — і саме так з'явився ACCEPTED
    там, де лан мав три червоні."""
    from verify_branch_consolidation import report_is_stale

    assert report_is_stale("1970-01-01T00:00:10+00:00", head_epoch=100)


def test_a_report_taken_after_the_head_is_current() -> None:
    """Негативний контроль: правило, що зве все застарілим, нічого не розрізняє."""
    from verify_branch_consolidation import report_is_stale

    assert not report_is_stale("1970-01-01T00:10:00+00:00", head_epoch=100)


def test_an_unreadable_timestamp_is_stale_not_fresh() -> None:
    """Доводити свіжість мусить ЗВІТ. Порожній штамп — не «щойно», а «невідомо»."""
    from verify_branch_consolidation import report_is_stale

    assert report_is_stale("", head_epoch=0)
    assert report_is_stale("не-дата", head_epoch=0)
