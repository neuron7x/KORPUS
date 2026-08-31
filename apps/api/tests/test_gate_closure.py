"""Покриття гейтами — саме воно тепер під гейтом.

Виміряно 31.08.2026 на цьому Makefile: 193 цілі, з них під `check` виконуються 44;
перевірочних цілей 44, і 27 не виконуються ЖОДНОЮ дорогою. Три з них того ж дня
перевірили руками — усі три червоні. Тобто речення «дерево зелене» було твердженням
про підмножину, якої ніхто не перелічив.

Тести тримають не список із 27 (він мусить порожніти), а ЧОТИРИ властивості:
покриття міряється виконанням скрипта, а не досяжністю цілі; нова діра червонить;
мертвий і примарний винятки червонять теж; і сам гейт покриття стоїть під гейтом.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_gate_closure.py"
REGISTRY = ROOT / "config/operations/gate-closure.json"
SPEC = importlib.util.spec_from_file_location("verify_gate_closure", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def _real() -> tuple[dict[str, set[str]], list[str], dict[str, set[str]]]:
    return GATE.parse_graph((ROOT / "Makefile").read_text(encoding="utf-8"))


# ------------------------------------------------- покриття = виконання, не досяжність


def test_a_target_whose_script_another_target_runs_is_not_a_gap() -> None:
    """Найдорожча помилка цього гейта — оголосити дірою те, що закрите.

    `validate` виконує `scripts/validate_infrastructure.py` і
    `scripts/validate_kubernetes.py` прямо в рецепті, а цілі `infra-validate` і
    `kubernetes-validate` роблять рівно те саме. Перевірка, що дивиться лише на граф
    цілей, зажадала б для них виправдання — і реєстр почав би описувати вигадані діри.
    """
    edges, _declared, scripts = _real()
    covered = GATE.enforced(edges, scripts)
    for target in ("infra-validate", "kubernetes-validate"):
        assert target in covered, f"{target} оголошено дірою, хоча його скрипт виконується"


def test_reachability_alone_would_call_those_targets_gaps() -> None:
    """Дуал до попереднього: без обліку скриптів вони СПРАВДІ виглядають дірами.

    Без цього твердження перший тест був би сумісний із гейтом, який просто нічого не
    перевіряє: він мусить показати, що різниця між двома означеннями існує.
    """
    edges, _declared, _scripts = _real()
    bare = GATE.reachable(edges, GATE.ROOTS)
    assert "infra-validate" not in bare and "kubernetes-validate" not in bare


def test_recipe_edges_count_as_reachability() -> None:
    """`evidence-refresh` кличе `$(MAKE) dependency-locks` у рецепті, не в заголовку."""
    edges, _declared, _scripts = _real()
    assert "dependency-locks" in edges.get("evidence-refresh", set())


# --------------------------------------------------------- три способи збрехати


def _verdict(makefile: str, registry: dict) -> str:
    edges, declared, scripts = GATE.parse_graph(makefile)
    return GATE.verdict(GATE.assess(edges, declared, registry, scripts))


def test_a_new_unwired_verification_target_reddens_on_the_real_makefile() -> None:
    """Негативний контроль проти РЕАЛЬНОСТІ, не проти синтетики."""
    poisoned = (ROOT / "Makefile").read_text(encoding="utf-8") + (
        "\nsomething-new-verify:\n\t$(PY) scripts/nothing.py\n"
    )
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert _verdict(poisoned, registry) == "FAIL"


def test_an_exemption_for_something_already_enforced_reddens() -> None:
    """Мертвий виняток бреше не менше за відсутній: він каже, що діра є, коли її нема."""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["accepted"].append(
        {"target": "module-budget", "class": "accepted_red", "reason": "x" * 40, "on": "2026-08-31"}
    )
    assert _verdict((ROOT / "Makefile").read_text(encoding="utf-8"), registry) == "FAIL"


def test_an_exemption_for_a_target_that_no_longer_exists_reddens() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["accepted"].append(
        {"target": "gone-verify", "class": "not_a_gate", "reason": "y" * 40, "on": "2026-08-31"}
    )
    assert _verdict((ROOT / "Makefile").read_text(encoding="utf-8"), registry) == "FAIL"


# ---------------------------------------------------- гейт покриття сам під гейтом


def test_the_closure_gate_is_itself_reached_by_check() -> None:
    """Гейт про покриття гейтами, який сам не під гейтом, спростовує себе першим рядком."""
    edges, _declared, scripts = _real()
    assert "gate-closure" in GATE.enforced(edges, scripts)


def test_the_real_tree_has_no_unregistered_gap() -> None:
    """Стан репозиторію, а не синтетика: кожна діра або закрита, або названа."""
    edges, declared, scripts = _real()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    findings = GATE.assess(edges, declared, registry, scripts)
    assert GATE.verdict(findings) == "PASS", findings


def test_every_accepted_gap_names_a_reason_and_a_date() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for entry in registry["accepted"]:
        assert len(entry["reason"].strip()) >= 20, entry["target"]
        assert entry["on"] == "2026-08-31" or len(entry["on"]) == 10, entry["target"]


def test_unknown_is_never_a_pass() -> None:
    assert _verdict("", {"accepted": []}) == "UNKNOWN"
    assert _verdict("span-hygiene:\n\tone\n", {"accepted": []}) == "UNKNOWN"


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
