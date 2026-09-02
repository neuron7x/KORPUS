"""Прийняте червоне мусить мати стелю, інакше воно просто червоне.

`span-hygiene` був FAIL ще до 31.08.2026 і не червонив нічого: ціль не була досяжна з
жодного входу, бо міряє РОЗГОРТАННЯ, а `make check` мусить проходити там, де корпусу
немає. Підключити як є — зробити щоденний гейт червоним; лишити мовчки — вдавати, що
діри немає. Третій стан: борг названий, має стелю, і гейт відмовляє на погіршенні.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/check_deployment_debt.py"
REGISTRY = ROOT / "config/operations/deployment-debt.json"
SPEC = importlib.util.spec_from_file_location("check_deployment_debt", SCRIPT)
assert SPEC and SPEC.loader
DEBT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEBT)

ENTRY = {"target": "t", "metric": "spans_dirty", "ceiling": 89}


def test_worsening_by_one_is_refused() -> None:
    """Ратчет існує рівно заради цього випадку."""
    result = DEBT.judge(ENTRY, {"spans_dirty": 90})
    assert result["verdict"] == "FAIL" and "+1" in result["detail"]


def test_sitting_on_the_ceiling_passes() -> None:
    assert DEBT.judge(ENTRY, {"spans_dirty": 89})["verdict"] == "PASS"


def test_improvement_demands_a_lower_ceiling() -> None:
    """Ратчет, який не помічає покращення, з часом стає дозволом."""
    result = DEBT.judge(ENTRY, {"spans_dirty": 40})
    assert result["verdict"] == "PASS" and result["lower_ceiling_to"] == 40


def test_a_missing_metric_is_unknown_not_pass() -> None:
    """Звіт без метрики нічого не доводить; нуль тут оголосив би борг закритим тим,
    що його не міряли."""
    assert DEBT.judge(ENTRY, {"other": 1})["verdict"] == "UNKNOWN"
    assert DEBT.judge(ENTRY, None)["verdict"] == "UNKNOWN"


def test_a_boolean_is_not_a_measurement() -> None:
    """`True` є `int` у Python — саме так проходить те, що не мало права."""
    assert DEBT.judge(ENTRY, {"spans_dirty": True})["verdict"] == "UNKNOWN"


def test_an_entry_without_a_ceiling_is_refused_not_allowed() -> None:
    assert DEBT.judge({"target": "t", "metric": "x"}, {"x": 1})["verdict"] == "FAIL"


def test_every_registered_debt_names_a_reason_a_ceiling_and_a_way_out() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert registry["accepted"], "порожній реєстр боргу читався б як відсутність боргу"
    for entry in registry["accepted"]:
        assert isinstance(entry["ceiling"], int) and not isinstance(entry["ceiling"], bool)
        assert len(entry["reason"].strip()) >= 40, entry["target"]
        assert entry["closes_when"].strip(), entry["target"]
        assert isinstance(entry["command"], list) and entry["command"]


def test_registry_python_commands_are_portable_between_worktrees() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    python_commands = [
        entry["command"] for entry in registry["accepted"] if entry["command"][0] == "{python}"
    ]
    assert python_commands
    assert all(
        DEBT.resolve_command(command, ROOT)[0] == sys.executable for command in python_commands
    )


def test_runtime_paths_bind_to_the_declared_runtime_root(tmp_path: Path) -> None:
    command = DEBT.resolve_command(["tool", "{runtime_root}/var/corpus.db"], tmp_path)
    assert command == ["tool", str(tmp_path / "var/corpus.db")]
    assert DEBT.resolve_command(["tool", "{runtime_root}/var/corpus.db"]) is None


def test_make_commands_use_the_current_worktree_interpreter() -> None:
    command = DEBT.resolve_command(["make", "production-assurance-verify"])
    assert command == [
        "make",
        "production-assurance-verify",
        f"PY={DEBT.shlex.quote(sys.executable)}",
    ]


def test_runtime_root_comes_from_the_canonical_state_registry() -> None:
    registry = json.loads((ROOT / "config/operations/canonical-state.json").read_text())
    assert DEBT.declared_runtime_root() == Path(registry["canonical_root"])


def test_missing_gate_binary_is_unknown_instead_of_crashing() -> None:
    assert DEBT.run_entry({"command": ["korpus-command-that-does-not-exist"]}) is None


def test_non_string_command_parts_are_not_executed() -> None:
    assert DEBT.resolve_command([sys.executable, 7]) is None


def test_the_span_hygiene_ceiling_is_the_measured_number() -> None:
    """Стеля — виміряне значення дня, не кругле й не із запасом."""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entry = next(e for e in registry["accepted"] if e["target"] == "span-hygiene")
    assert entry["ceiling"] == 89 and entry["metric"] == "spans_dirty"


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


# ------------------------------------- перелік відмов як число: врядування → метрика


def test_a_list_of_failures_is_measured_by_its_length() -> None:
    """`production-assurance-verify` називає відмови поіменно й не рахує їх.

    Без цього стелю на «скільки саме» поставити було б нічим, і врядувальна відмовка
    («реєстри підписантів порожні») лишалась би словом, а не числом, яке помічає і
    погіршення, і покращення.
    """
    entry = {"target": "t", "metric": "failures", "metric_kind": "length", "ceiling": 2}
    assert DEBT.judge(entry, {"failures": ["a", "b"]})["verdict"] == "PASS"
    assert DEBT.judge(entry, {"failures": ["a", "b", "c"]})["verdict"] == "FAIL"
    improved = DEBT.judge(entry, {"failures": ["a"]})
    assert improved["verdict"] == "PASS" and improved["lower_ceiling_to"] == 1


def test_a_list_is_not_a_number_unless_the_entry_says_so() -> None:
    """Мовчазне читання списку як числа зробило б стелю випадковою."""
    assert DEBT.metric_at({"failures": ["a"]}, "failures") is None
    assert DEBT.metric_at({"failures": ["a"]}, "failures", "length") == 1


def test_length_of_something_that_is_not_a_list_is_unknown() -> None:
    assert DEBT.metric_at({"failures": 3}, "failures", "length") is None
    assert DEBT.metric_at({"failures": {"a": 1}}, "failures", "length") is None


def test_the_real_registry_names_a_ceiling_for_production_assurance() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entry = next(e for e in registry["accepted"] if e["target"] == "production-assurance-verify")
    assert entry["metric_kind"] == "length" and isinstance(entry["ceiling"], int)
    assert "недосяжн" in entry["reason"], "запис мусить називати спростоване твердження"
