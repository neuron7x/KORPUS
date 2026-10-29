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

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import run_postgres_security_gate as gate  # noqa: E402

#: Кожна з них питає, що ПРОХОДИТЬ, не маючи права.
REQUIRED_DESTRUCTION_CONTROLS = {
    "apps/api/tests/test_postgres_rls_claim_forgery.py",
    "apps/api/tests/test_postgres_rls_claim_mutations.py",
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


@pytest.mark.parametrize(
    ("summary", "status"),
    [
        ("111 passed in 7.12s", "PASS"),
        ("1 passed, 1 skipped in 0.01s", "FAIL"),
        ("2 skipped in 0.01s", "FAIL"),
        ("1 xfailed in 0.01s", "FAIL"),
        ("1 xpassed in 0.01s", "FAIL"),
        ("1 passed, 1 xfailed in 0.01s", "FAIL"),
        ("1 passed, 1 xpassed in 0.01s", "FAIL"),
        ("1 passed, 1 skipped, 1 xfailed in 0.01s", "FAIL"),
        ("1 xfailed, 1 xpassed in 0.01s", "FAIL"),
        ("no tests ran in 0.01s", "FAIL"),
        ("1 passed, 2 warnings in 0.01s", "PASS"),
    ],
)
def test_skipped_postgres_destruction_tests_never_satisfy_security_gate(
    monkeypatch, tmp_path: Path, summary: str, status: str
) -> None:
    """A zero pytest exit is not proof that mandatory poison tests executed."""
    for target in gate.TARGETS:
        fixture = tmp_path / target
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text("# isolated gate target\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(
        gate, "process_run", lambda *_args: subprocess.CompletedProcess([], 0, "static", "")
    )
    monkeypatch.setattr(
        gate, "process_runtime", lambda *_args: (True, 0, f"--- stdout ---\n{summary}")
    )
    monkeypatch.setattr(gate, "compute_source_digest", lambda _: "f" * 64)
    monkeypatch.setattr(gate, "release_tag", lambda: "v0.9.7")
    assert (gate.main() == 0) is (status == "PASS")
    report = json.loads((tmp_path / "var/production/postgres_security-gate.json").read_text())
    assert report["status"] == status
