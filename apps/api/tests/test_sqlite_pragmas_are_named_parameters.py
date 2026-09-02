"""Прагми з'єднання — НАЗВАНІ параметри з виміряними дефолтами, не магічні константи.

ВИМІРЯНО 02.09.2026 на обслуговуваному корпусі (276 МіБ, 31464 прольоти). Набори
чергувались A,B,A,B — щоб дрейф машини ліг на обидва однаково — і кожен прогін брав
НОВЕ з'єднання, інакше кеш попереднього виміряв би сам себе:

    baseline (дефолти SQLite)  n=30  середнє 58.67 мс  p95 66.88 мс
    tuned                      n=30  середнє 51.23 мс  p95 52.98 мс
                                            -12.7 %          -20.8 %

Число описує читання ФОРМИ СКАНУ на цій машині й цьому корпусі. Воно не переноситься
ані на іншу форму запиту, ані на інше залізо, і саме тому параметри лишились
ПАРАМЕТРАМИ: оточення, де відображення в пам'ять небажане, ставить `sqlite_mmap_mib=0`.

Чого тут НЕМАЄ і чому:
  * `synchronous` не чіпається. Це параметр ДОВГОВІЧНОСТІ, не швидкості: журнал аудиту
    — хеш-ланцюг, і рішення послабити його запис належить власникові системи.
  * серіалізація дописування не чіпається. Хеш N+1 залежить від N — це не вада, а
    цілісність; прискорити її можна лише груповим комітом, окремою зміною з окремим
    доказом.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from korpus.application.policy import PolicyEngine
from korpus.config import Settings, get_settings
from korpus.infrastructure.runtime import create_repository
from pydantic import ValidationError


def _pragmas(cache_mib: int, mmap_mib: int) -> dict[str, int | str]:
    with tempfile.TemporaryDirectory() as work:
        database = Path(work) / "probe.db"
        previous = os.environ.get("KORPUS_DATABASE_URL")
        os.environ["KORPUS_DATABASE_URL"] = f"sqlite:///{database}"
        os.environ["KORPUS_SQLITE_CACHE_MIB"] = str(cache_mib)
        os.environ["KORPUS_SQLITE_MMAP_MIB"] = str(mmap_mib)
        get_settings.cache_clear()
        try:
            repository = create_repository(get_settings(), PolicyEngine())
            repository.initialize()
            with repository.engine.connect() as connection:
                return {
                    name: connection.exec_driver_sql(f"PRAGMA {name}").scalar()
                    for name in ("cache_size", "mmap_size", "temp_store", "journal_mode")
                }
        finally:
            os.environ.pop("KORPUS_SQLITE_CACHE_MIB", None)
            os.environ.pop("KORPUS_SQLITE_MMAP_MIB", None)
            if previous is None:
                os.environ.pop("KORPUS_DATABASE_URL", None)
            else:
                os.environ["KORPUS_DATABASE_URL"] = previous
            get_settings.cache_clear()


def test_the_measured_defaults_reach_the_connection():
    """Дефолт мусить ДОХОДИТИ, а не лише бути оголошеним у конфізі."""
    settings = Settings()
    observed = _pragmas(settings.sqlite_cache_mib, settings.sqlite_mmap_mib)
    assert observed["cache_size"] == -settings.sqlite_cache_mib * 1024
    assert observed["mmap_size"] == settings.sqlite_mmap_mib * 1024 * 1024
    assert observed["temp_store"] == 2, "temp_store не MEMORY"
    assert observed["journal_mode"] == "wal", "WAL не має зникати разом із новими прагмами"


def test_the_parameters_are_parameters_and_not_constants():
    """Негативний контроль: інше значення мусить ДАТИ інший стан з'єднання.

    Без цього тест вище лишався б зеленим, якби прагми вкарбували константами й
    перестали читати конфіг — тобто рівно тоді, коли параметр перестав бути параметром.
    """
    small = _pragmas(cache_mib=8, mmap_mib=0)
    assert small["cache_size"] == -8 * 1024
    assert small["mmap_size"] == 0, "нуль мусить лишатись допустимим: є оточення без mmap"
    large = _pragmas(cache_mib=128, mmap_mib=64)
    assert large["cache_size"] == -128 * 1024
    assert large["mmap_size"] == 64 * 1024 * 1024
    assert small["cache_size"] != large["cache_size"]


def test_durability_is_not_traded_for_speed():
    """`synchronous` лишається дефолтним FULL: швидкість не купується довговічністю."""
    observed = _pragmas(cache_mib=64, mmap_mib=256)
    del observed
    with tempfile.TemporaryDirectory() as work:
        database = Path(work) / "durability.db"
        previous = os.environ.get("KORPUS_DATABASE_URL")
        os.environ["KORPUS_DATABASE_URL"] = f"sqlite:///{database}"
        get_settings.cache_clear()
        try:
            repository = create_repository(get_settings(), PolicyEngine())
            repository.initialize()
            with repository.engine.connect() as connection:
                assert connection.exec_driver_sql("PRAGMA synchronous").scalar() == 2, (
                    "synchronous опустили нижче FULL — це рішення власника системи "
                    "про довговічність журналу аудиту, а не оптимізація"
                )
        finally:
            if previous is None:
                os.environ.pop("KORPUS_DATABASE_URL", None)
            else:
                os.environ["KORPUS_DATABASE_URL"] = previous
            get_settings.cache_clear()


@pytest.mark.parametrize("mib", [1, 5000])
def test_the_cache_parameter_refuses_absurd_values(mib: int):
    """Межі — теж рішення: параметр без меж перестає бути параметром.

    Ловиться саме `ValidationError`, а не будь-який виняток: «щось упало» не доводить,
    що впала ПЕРЕВІРКА МЕЖІ — з тим самим успіхом це могла б бути помилка друку в імені
    поля, і тест лишався б зеленим на зламаній валідації.
    """
    with pytest.raises(ValidationError):
        Settings(sqlite_cache_mib=mib)
