"""Інструмент не сміє лишати стану в дереві, з якого імпортує живий сервіс.

31.08.2026 о 23:30 прогін проби вбито `timeout` (SIGTERM). Обробника сигналу не було,
тож `finally` не виконався, і мутація лишилась у дереві:
`adaptive_contracts.py:92` мав `or` замість `and` — ослаблений валідатор, який приймає
нецілі значення, бо `x >= 0` істинне для float. Це те саме дерево, з якого імпортує
публічний API: перезапуск сервера у тому вікні підняв би ослаблену перевірку.

Знайдено випадково — суцільним `ruff format`, а не жодною перевіркою.

Тести тримають ПРИЧИНУ, не наслідок: не «цей рядок правильний», а «редагується не те
дерево, що обслуговує читача, і сигнал не обходить відновлення».
"""

from __future__ import annotations

import importlib.util
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/probe_uncatalogued_mutation.py"
SPEC = importlib.util.spec_from_file_location("probe_uncatalogued_mutation", SCRIPT)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
# Реєстрація ДО виконання: `@dataclass` шукає власний модуль у `sys.modules`, і без
# цього декоратор падає з AttributeError на `None.__dict__`.
sys.modules["probe_uncatalogued_mutation"] = PROBE
SPEC.loader.exec_module(PROBE)

SOURCE = SCRIPT.read_text(encoding="utf-8")


def test_the_probe_edits_a_copy_by_default() -> None:
    """Копія прибирає клас цілком: що б не сталося з процесом, дерево не змінюється."""
    assert "--in-place" in SOURCE, "режим редагування на місці мусить бути ЯВНИМ вибором"
    assert "shutil.copytree" in SOURCE, "проба більше не працює на копії"
    assert "if not args.in_place:" in SOURCE, "копія перестала бути типовою"


def test_a_signal_does_not_bypass_the_restore() -> None:
    """SIGTERM не підіймає винятку — саме так `finally` було обійдено."""
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        assert f"signal.{name}" in SOURCE, f"{name} не переводиться у виняток"


def test_the_workspace_is_a_parameter_not_a_global() -> None:
    """Стан цієї програми — саме те, що вона лишає в дереві; ховати його в глобалі
    означає зробити невидимим те, чим вона небезпечна."""
    assert "global WORKSPACE" not in SOURCE
    assert "def apply(mutant: Seeded, workspace: Path)" in SOURCE
    assert "def suite_kills(timeout_seconds: float, workspace: Path)" in SOURCE


def test_an_orphaned_lock_is_reported_as_an_event(tmp_path: Path, monkeypatch) -> None:
    """Замок без перевірки живості блокує НАЗАВЖДИ після аварії — і мовчки."""
    lock = tmp_path / "mutation-probe.lock"
    lock.write_text("pid=999999999\n", encoding="utf-8")
    monkeypatch.setattr(PROBE, "LOCK", lock)
    assert PROBE._lock_pid() == 999999999
    assert PROBE._lock_holder_alive() is False


def test_a_live_holder_is_recognised(tmp_path: Path, monkeypatch) -> None:
    """Дуал: замок живого власника мусить лишатись чинним, інакше проба перезапише
    чужий прогін і обидва дадуть сміття."""
    import os

    lock = tmp_path / "mutation-probe.lock"
    lock.write_text(f"pid={os.getpid()}\n", encoding="utf-8")
    monkeypatch.setattr(PROBE, "LOCK", lock)
    assert PROBE._lock_holder_alive() is True


def test_a_missing_lock_has_no_holder(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(PROBE, "LOCK", tmp_path / "absent.lock")
    assert PROBE._lock_pid() is None
    assert PROBE._lock_holder_alive() is False


def test_the_dirty_tree_refusal_is_scoped_to_in_place() -> None:
    """Вимога чистого дерева була НАСЛІДКОМ редагування на місці. З копією передумова
    зникла, і тримати заборону далі означало б боронити те, чого вже немає."""
    assert "if args.in_place and not args.allow_dirty" in SOURCE


def test_signal_numbers_are_real() -> None:
    """Дешевий дуал: імена сигналів мусять існувати в цій системі."""
    assert {signal.SIGTERM, signal.SIGINT, signal.SIGHUP}
