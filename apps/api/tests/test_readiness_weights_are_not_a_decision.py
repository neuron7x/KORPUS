"""«Зважений індекс готовності» арифметично тотожний підрахунку пройдених критеріїв.

ВИМІРЯНО 02.09.2026 зовнішнім рецензентом і перевірено тут. У ОБОХ профілях
(`engineering-readiness-94.7.v1.json`, `engineering-readiness-87.v1.json`) для КОЖНОГО з
восьми вимірів виконано `w_i · 100 = n_i`, де `n_i` — кількість критеріїв виміру, і
`Σ n_i = 100`. Разом із формулами

    raw_i = 100 · passed_i / n_i          (engineering_readiness.py:95)
    R     = Σ w_i · score_i               (assurance_calculus.py:270)

це дає, поки стеля класу доказу не ріже score:

    R = Σ (n_i/100) · (100 · passed_i / n_i) = Σ passed_i

Тобто «зважений індекс зрілості» — це **кількість пройдених критеріїв зі ста**, а вага
не є врядувальним рішенням: вона є кількістю критеріїв, поділеною на сто. Один критерій
`ui_ux` важить рівно стільки ж, скільки один критерій `security_internal`.

ЧОМУ ЦЕ ТЕСТ, А НЕ ПРАВКА. Зробити ваги справді різними — рішення того, хто приймає
систему, а не розробника: воно оголошує, що безпека важить більше за UI, і це твердження
про цінності, не про код. Тому тут стан НАЗВАНО, а не змінено. Якщо колись ваги стануть
самостійним рішенням, цей тест почервоніє й змусить оновити твердження в
`docs/formal/ASSURANCE_ALGEBRA.md`, яке сьогодні подає цю тотожність як інспектовану
чутливість («no hidden weight can dominate the index») — істинно, але порожньо.

Рішення лишається можливим. Невидимим — ні.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROFILES = (
    ROOT / "config/assurance/engineering-readiness-94.7.v1.json",
    ROOT / "config/assurance/engineering-readiness-87.v1.json",
)


def _dimensions(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    dimensions = payload.get("dimensions")
    assert isinstance(dimensions, dict) and dimensions, f"{path.name}: немає вимірів"
    return dimensions


def test_every_weight_equals_its_criteria_count_over_one_hundred():
    for path in PROFILES:
        identical = []
        for name, spec in _dimensions(path).items():
            weight = float(spec["weight"])
            count = len(spec["criteria"])
            identical.append((name, abs(weight * 100.0 - count) < 1e-9))
        assert all(ok for _, ok in identical), (
            f"{path.name}: вага перестала дорівнювати кількості критеріїв — "
            f"тепер це САМОСТІЙНЕ рішення, і його треба оголосити: "
            f"{[n for n, ok in identical if not ok]}"
        )


def test_the_criteria_counts_sum_to_one_hundred():
    """Другий множник тотожності. Без нього індекс був би часткою, а не кількістю."""
    for path in PROFILES:
        total = sum(len(spec["criteria"]) for spec in _dimensions(path).values())
        assert total == 100, f"{path.name}: критеріїв {total}, а не 100"


def test_the_index_equals_the_count_of_passed_criteria():
    """Тотожність доводиться ОБЧИСЛЕННЯМ, не переказом арифметики в докстрінгу."""
    for path in PROFILES:
        dimensions = _dimensions(path)
        # Пройдено рівно половину критеріїв кожного виміру, округлено вниз.
        passed = {name: len(spec["criteria"]) // 2 for name, spec in dimensions.items()}
        index = sum(
            float(spec["weight"]) * (100.0 * passed[name] / len(spec["criteria"]))
            for name, spec in dimensions.items()
        )
        assert abs(index - sum(passed.values())) < 1e-9, (
            f"{path.name}: індекс {index} не дорівнює кількості пройдених "
            f"{sum(passed.values())} — тотожність розійшлася"
        )
