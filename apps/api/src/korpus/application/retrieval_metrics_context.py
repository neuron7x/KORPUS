"""Спостерігач набору кандидатів: розрізнювач, якого бракувало.

ВИМІРЯНО 02.09.2026. Гістограма `korpus_retrieval_candidates` була ОГОЛОШЕНА і не
наповнювалась жодним рядком дерева. Наслідок не косметичний: три конкурентні пояснення
хвостової затримки — промах кеша, черга за GIL, розростання набору кандидатів — давали
ОДНАКОВІ спостереження, тож жодне не можна було ні підтвердити, ні відкинути.

Порожній ряд у Prometheus і система без навантаження виглядають однаково: відсутність
ряду не відрізняється від нуля. Тому питати треба не «чи метрика є», а «чи вона БУВАЛА
іншою», і саме це тепер стереже `check_declared_metrics_are_observed.py`.

Форма списана з `pec_metrics_context`, а не вигадана заново: другий механізм для того
самого завдання розійшовся б із першим — це вже траплялось у цьому дереві з двома
оголошеннями оточення і з двома дайджестами під одним іменем поля.

Шар застосунку НЕ ЗНАЄ про Prometheus і не мусить: він повідомляє ЧИСЛО, а куди воно
піде — рішення композиційного кореня.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token

#: Скільки кандидатів дав пошук ДО доказових воріт, і скільки серед них різних версій.
#: Друге число — не прикраса: саме різноманітність версій крутить складність відбору,
#: і без неї «кандидатів стало більше» не відрізняється від «кандидати стали різнішими».
RetrievalObserver = Callable[[int, int], None]

_OBSERVER: ContextVar[RetrievalObserver | None] = ContextVar(
    "korpus_retrieval_observer", default=None
)


def set_retrieval_observer(observer: RetrievalObserver | None) -> Token[RetrievalObserver | None]:
    return _OBSERVER.set(observer)


def reset_retrieval_observer(token: Token[RetrievalObserver | None]) -> None:
    _OBSERVER.reset(token)


def emit_retrieval_observation(candidates: int, distinct_versions: int) -> None:
    """Мовчить, якщо ніхто не слухає: вимір не сміє валити дорогу, яку міряє."""
    observer = _OBSERVER.get()
    if observer is not None:
        observer(max(0, candidates), max(0, distinct_versions))
