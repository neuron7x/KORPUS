"""Перелік цілей продакшенного PostgreSQL-гейта — сам предмет перевірки.

Гейт зветься «postgres security», а до 01.09.2026 міряв лише гранти репозиторію
й відмови доступу. Деструктивні контролі самої МЕЖІ — підробка claim'ів RLS,
стан політик, знищення дрейфу прав, походження затвердження — до нього не
потрапили б самі: перелік цілей це звичайний список, і викреслений рядок нічого
не ламає. Гейт, який називає властивість, якої не запускає, є твердженням без
виміру.

Тому перелік тримається тут, а не лише в скрипті: тепер його скорочення —
червоний тест, а не тиша.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import run_postgres_security_gate as gate  # noqa: E402

#: Кожна з них питає, що ПРОХОДИТЬ, не маючи права.
REQUIRED_DESTRUCTION_CONTROLS = {
    "apps/api/tests/test_postgres_rls_claim_forgery.py",
    "apps/api/tests/test_postgres_rls_policy_state.py",
    "apps/api/tests/test_postgres_role_reprovision_boundary.py",
    "apps/api/tests/test_postgres_approval_provenance.py",
}

#: І хоча б один, що питає протилежне: чи чесний шлях узагалі працює. Набір із
#: самих заборон зелений і тоді, коли система не робить нічого.
REQUIRED_POSITIVE_CONTROLS = {
    "apps/api/tests/test_postgres_integration.py",
}


def test_the_gate_runs_every_destruction_control_of_the_boundary() -> None:
    assert set(gate.TARGETS) >= REQUIRED_DESTRUCTION_CONTROLS, sorted(
        REQUIRED_DESTRUCTION_CONTROLS - set(gate.TARGETS)
    )


def test_the_gate_runs_at_least_one_positive_control() -> None:
    assert set(gate.TARGETS) >= REQUIRED_POSITIVE_CONTROLS, sorted(
        REQUIRED_POSITIVE_CONTROLS - set(gate.TARGETS)
    )


def test_every_named_target_exists_on_disk() -> None:
    """Ціль, якої немає, не виконується — і `targets_present` це вже ловить.

    Тут воно ще й НАЗВАНЕ: інакше єдиним симптомом був би `FAIL` гейта з чеком
    `target_files_present`, і причину довелося б шукати в JSON-звіті.
    """
    missing = [target for target in gate.TARGETS if not (ROOT / target).is_file()]
    assert missing == [], missing
