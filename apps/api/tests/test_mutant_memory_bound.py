"""Мутант не сміє коштувати машини.

09.09.2026 нічний лан `korpus-nightly-gates` з'їв 4,2 ГБ і загнав машину в 9,4 ГБ свопу;
фоновий процес сесії система вбила за браком памʼяті. Важким виявився НЕ гейт: сам
`verify_gate_closure.py` бере 25 МБ. Важким був один із його 59 мутантів — `flip`
перевертає `while (start := line.find(opener)) >= 0` на `< 0`, а `str.find` віддає -1,
коли не знайшов, тож цикл стає нескінченним і росте, доки не спрацює таймаут.

`probe_selftest_falsifiability.py` обмежував ЧАС (90 с) і не обмежував ПАМʼЯТЬ. Півтори
хвилини по кілька гігабайтів — щоночі, на машині, де поруч обслуговується корпус SQLite,
і де ця сама проба є частиною нічного лану.

Тести нижче тримають обидва боки лікування: межа мусить УБИВАТИ ненажеру і мусить
ПУСКАТИ сумлінну самоперевірку. Друге не менш важливе за перше — межа, яка вбиває чесні
проби, перетворила б увесь звіт на «спіймано» без жодного виміру.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "probe_selftest_falsifiability", ROOT / "scripts/probe_selftest_falsifiability.py"
)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)

#: Виміряно 09.09.2026: найважча ЧЕСНА самоперевірка з 69 наявних бере 62,7 МБ.
HEAVIEST_HONEST_SELFTEST_BYTES = 63 * 1024 * 1024


def _run(body: str) -> subprocess.CompletedProcess[bytes]:
    """Дочірній процес під ТІЄЮ САМОЮ межею, яку проба ставить мутантам."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        capture_output=True,
        timeout=60,
        preexec_fn=PROBE._cap_address_space,
        check=False,
    )


def test_the_limit_is_measured_not_guessed() -> None:
    """Стеля мусить лишати запас над найважчою чесною пробою, інакше вона зламає вимір."""
    assert PROBE.MEMORY_LIMIT_BYTES >= 8 * HEAVIEST_HONEST_SELFTEST_BYTES


def test_a_runaway_mutant_dies_instead_of_taking_the_machine() -> None:
    """Позитивний контроль ненажери: без межі цей код з'їв би всю памʼять."""
    done = _run(
        """
        blocks = []
        while True:
            blocks.append(bytearray(32 * 1024 * 1024))
        """
    )
    assert done.returncode != 0, "ненажера завершилась успішно — межа не діє"
    assert b"MemoryError" in done.stderr or b"Cannot allocate" in done.stderr


def test_an_honest_selftest_still_fits_under_the_limit() -> None:
    """Негативний контроль: межа не сміє вбивати сумлінну пробу."""
    done = _run(
        f"""
        block = bytearray({HEAVIEST_HONEST_SELFTEST_BYTES})
        print(len(block))
        """
    )
    assert done.returncode == 0, done.stderr[-400:]


def test_a_memory_blowup_reads_as_a_caught_mutant() -> None:
    """Вибух памʼяті мусить давати НЕНУЛЬОВИЙ код — тобто «самоперевірка не лишилась
    зеленою», той самий вирок, що й раніше, тільки платить його мутант, а не машина."""
    done = _run(
        """
        rows = []
        while True:
            rows.append("x" * 1_000_000)
        """
    )
    assert done.returncode != 0
