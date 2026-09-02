"""Розрізнювачі гіпотез про хвостову затримку мусять СПОСТЕРІГАТИСЬ.

ВИМІРЯНО 02.09.2026. Три конкурентні пояснення затримки p95 — промах кеша, черга за
GIL, розростання набору кандидатів — давали ОДНАКОВІ спостереження, бо гістограма
`korpus_retrieval_candidates` була оголошена й не наповнювалась ЖОДНИМ рядком дерева.

Це не косметика. Порожній ряд у Prometheus і система без навантаження виглядають
однаково: відсутність ряду не відрізняється від нуля. Умова ідентифікованості
`∃O: P(O|Hᵢ) ≠ P(O|Hⱼ)` не виконувалась, тож будь-яка оптимізація била б навмання.

Друге число — різних версій серед кандидатів — теж не прикраса: саме різноманітність
крутить складність відбору, і без неї «кандидатів побільшало» не відрізняється від
«кандидати стали різнішими» — дві різні причини з однаковим наслідком у латентності.
"""

from __future__ import annotations

from korpus.application.retrieval_metrics_context import (
    emit_retrieval_observation,
    reset_retrieval_observer,
    set_retrieval_observer,
)


def test_the_observation_reaches_an_attached_observer():
    seen: list[tuple[int, int]] = []
    token = set_retrieval_observer(lambda candidates, versions: seen.append((candidates, versions)))
    try:
        emit_retrieval_observation(256, 20)
    finally:
        reset_retrieval_observer(token)
    assert seen == [(256, 20)]


def test_it_is_silent_without_an_observer():
    """Вимір не сміє валити дорогу, яку міряє."""
    emit_retrieval_observation(1, 1)  # не мусить кинути


def test_negative_counts_cannot_enter_the_series():
    """Від'ємна кількість кандидатів — це дефект виміру, а не спостереження про систему."""
    seen: list[tuple[int, int]] = []
    token = set_retrieval_observer(lambda candidates, versions: seen.append((candidates, versions)))
    try:
        emit_retrieval_observation(-5, -1)
    finally:
        reset_retrieval_observer(token)
    assert seen == [(0, 0)]


def test_the_retrieval_path_emits_the_observation():
    """Головне: спостереження мусить іти з ТІЄЇ дороги, про яку твердження.

    Без цього попередні три тести доводили б лише, що контекстна змінна працює — а не
    те, що шлях пошуку її вживає. Саме таким був стан до 02.09.2026: механізм існував,
    метрика існувала, і між ними не було жодного рядка.

    ВИПРАВЛЕНО 02.09.2026, того самого дня. Перша редакція брала `inspect.getsource` і
    шукала ПІДРЯДОК. `getsource` віддає докстрінги й коментарі, тож твердження проходило
    б на модулі, де виклику НЕМАЄ, а є лише згадка. Виміряно на цьому ж модулі:
    виконуваних викликів 1, згадок у сирому тексті 2 — тест звіряв ДРУГЕ число.

    Тепер судиться РОЗБІР: `ast.Call`, а не текст. Коментар не є викликом.
    """
    import ast
    import inspect

    from korpus.application import retrieval_hybrid

    tree = ast.parse(inspect.getsource(retrieval_hybrid))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "emit_retrieval_observation"
    ]
    assert calls, (
        "шлях пошуку не ВИКЛИКАЄ повідомлення про кількість кандидатів — розрізнювач "
        "знову недосяжний; згадка в коментарі викликом не є"
    )


def test_the_test_itself_cannot_be_satisfied_by_a_comment():
    """Негативний контроль на попередній тест: спосіб перевірки мусить розрізняти.

    Без цього «розбір замість тексту» лишалося б твердженням у докстрінгу.
    """
    import ast

    commented = ast.parse(
        '"""емить emit_retrieval_observation()"""\n# emit_retrieval_observation()\n'
    )
    executable = ast.parse("emit_retrieval_observation(1, 2)\n")

    def calls(tree: ast.Module) -> int:
        return sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "emit_retrieval_observation"
        )

    assert calls(commented) == 0, "коментар зарахований як виклик"
    assert calls(executable) == 1, "виконуваний виклик не побачено"


def test_the_observability_object_exposes_both_series():
    from korpus.infrastructure.observability import Observability

    assert hasattr(Observability, "observe_retrieval_candidates")
    signature = __import__("inspect").signature(Observability.observe_retrieval_candidates)
    assert list(signature.parameters)[1:] == ["candidates", "distinct_versions"], (
        "друге число зникло: без нього зростання набору не відрізняється від зростання "
        "різноманітності"
    )
