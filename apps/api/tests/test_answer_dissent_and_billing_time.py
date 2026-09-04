"""Дві дрібні гілки з різних модулів, спільні тим, що обидві — про мовчання.

Вимір покриття гілок 04.09.2026: жодна не виконувалась. `_dissent` мусить віддати
порожній рядок, коли ЖОДНА вісь не заперечила — і це не те саме, що «все
перевірено». `_as_datetime` мусить дати часовому знаку без пояса пояс UTC — інакше
порівняння моментів мовчки порівнювало б різні шкали.
"""

from __future__ import annotations

from datetime import UTC, datetime

from korpus.application.answer_adjudication import AxisVerdict
from korpus.application.answer_query import _dissent
from korpus.application.billing_adjudication import _as_datetime


def test_no_objection_reads_as_empty_not_as_approval() -> None:
    """Осі, які утримались, лишаються утриманими.

    Порожній рядок означає «ніхто не заперечив». Якби сюди потрапила причина
    утримання, вона читалась би як заперечення; якби відсутність заперечення
    читалась як згода — утримання перетворилось би на голос «за».
    """
    verdicts = (
        AxisVerdict(axis="lexical", verdict="ABSTAIN", reason="осі бракує підстав"),
        AxisVerdict(axis="interrogative", verdict="SUPPORTS", reason="тип питання збігається"),
    )
    assert _dissent(verdicts) == ""


def test_the_strongest_objection_wins_over_a_weaker_one() -> None:
    """Негативне плече й порядок: пряме заперечення попереду неспроможності судити."""
    verdicts = (
        AxisVerdict(axis="a", verdict="CANNOT_ADJUDICATE", reason="не можу судити"),
        AxisVerdict(axis="b", verdict="DOES_NOT_SUPPORT", reason="цитата не про це"),
    )
    assert _dissent(verdicts) == "цитата не про це"


def test_a_naive_timestamp_is_read_as_utc_not_as_local_time() -> None:
    """Момент без пояса — не момент.

    Провайдер може прислати час без зони; порівняння його з часом у UTC або впало б,
    або мовчки зсунулось на зміщення машини. Пояс призначають явно й один раз.
    """
    naive = datetime(2026, 8, 14, 10, 0, 0)
    assert _as_datetime(naive) == datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)


def test_an_aware_timestamp_is_left_alone() -> None:
    """Негативне плече: призначення пояса не сміє переписувати вже названий."""
    aware = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)
    assert _as_datetime(aware) is aware
    assert _as_datetime(object()) is None
