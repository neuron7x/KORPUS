"""Що саме означає «канонічне».

Виміряно 01.09.2026: кандидатів на канон ТРИ, і вони розходяться.

    локальна work/converge-semantic   уся робота дня
    main                              позаду на 125 (30.08 20:54), СТРОГИЙ предок
    gitlab/work/converge-semantic     позаду на 106

Жодна перевірка цього не бачила — та сама форма, що вчора мало слово «зелено».

Три факти роблять це не косметикою: `.gitlab-ci.yml` вмикає розгортання продакшену
правилом `$CI_COMMIT_BRANCH == "main"`; опублікована на GitLab голова збігалася з
ТИМЧАСОВИМ деревом мертвої сесії у `/tmp/.../scratchpad/`; і серед віддалених є той,
чия роль не вирішена.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_canonical_state.py"
REGISTRY = ROOT / "config/operations/canonical-state.json"
SPEC = importlib.util.spec_from_file_location("verify_canonical_state", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

CANON = "work/converge-semantic"


def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _observation() -> dict[str, Any]:
    registry = _registry()
    return {
        "head_branch": CANON,
        "branches": ["main", CANON],
        "remotes": {
            "gitlab": registry["publications"][0]["url"],
            "origin": "git@github.com:x/y.git",
        },
        "worktrees": [registry["canonical_root"], "/home/neuro7/.korpus-worktrees/a"],
        "root": registry["canonical_root"],
    }


def _measured() -> dict[str, Any]:
    registry = _registry()
    return {
        "trunk_behind": registry["trunk"]["max_behind"],
        "trunk_is_ancestor": True,
        "publication_behind": {"gitlab": registry["publications"][0]["max_behind"]},
    }


def _finding(findings: list[dict[str, str]], check: str) -> dict[str, str]:
    """Конкретна перевірка, не сукупний вирок: інакше мутант ховається за сусідньою."""
    return next(item for item in findings if item["check"] == check)


def test_the_registry_names_one_canonical_branch_and_root() -> None:
    registry = _registry()
    assert registry["canonical_branch"] == CANON
    assert Path(registry["canonical_root"]).name.startswith("Ядро")


def test_a_trunk_that_diverged_is_not_merely_behind() -> None:
    """Відставання лікується fast-forward; розходження — ні, і плутати їх не можна."""
    findings = GATE.assess(_observation(), {**_measured(), "trunk_is_ancestor": False}, _registry())
    assert _finding(findings, "trunk_is_ancestor")["verdict"] == "FAIL"


def test_the_trunk_lag_is_a_ratchet_in_both_directions() -> None:
    registry = _registry()
    ceiling = registry["trunk"]["max_behind"]
    worse = GATE.assess(_observation(), {**_measured(), "trunk_behind": ceiling + 1}, registry)
    assert _finding(worse, "trunk_behind")["verdict"] == "FAIL"
    better = GATE.assess(_observation(), {**_measured(), "trunk_behind": 0}, registry)
    lowered = _finding(better, "trunk_behind")
    assert lowered["verdict"] == "PASS" and "знизити до 0" in lowered["detail"]


def test_an_undeclared_publication_surface_is_refused() -> None:
    """Віддалений — поверхня публікації; неоголошена нічим не краща за неоголошену базу."""
    observation = _observation()
    observation["remotes"]["чужий"] = "git@example.com:a/b.git"
    findings = GATE.assess(observation, _measured(), _registry())
    assert _finding(findings, "publication_declared")["verdict"] == "FAIL"


def test_a_remote_pointing_somewhere_else_than_declared_is_refused() -> None:
    observation = _observation()
    observation["remotes"]["gitlab"] = "git@gitlab.com:чуже/repo.git"
    findings = GATE.assess(observation, _measured(), _registry())
    assert _finding(findings, "publication_url:gitlab")["verdict"] == "FAIL"


def test_the_undecided_remote_is_named_and_stays_red_until_decided() -> None:
    """`origin` існує й відповідає; це суперечить записаному рішенню про канон.

    Гейт не вирішує сам: він каже про це щоразу, доки власник не вирішить.
    """
    findings = GATE.assess(_observation(), _measured(), _registry())
    pending = _finding(findings, "publication_role_decided")
    assert pending["verdict"] == "FAIL" and "origin" in pending["detail"]
    assert any(item["remote"] == "origin" for item in _registry()["awaiting_decision"])


def test_a_worktree_that_is_not_the_canonical_root_cannot_judge_the_checkout() -> None:
    """Гейт не сміє червоніти з ВЛАСНОЇ причини — вада, яку він сам існує ловити."""
    observation = {
        **_observation(),
        "root": "/home/neuro7/.korpus-worktrees/a",
        "head_branch": "інша",
    }
    finding = _finding(GATE.assess(observation, _measured(), _registry()), "canonical_checked_out")
    assert finding["verdict"] == "UNKNOWN"


def test_transient_session_worktrees_do_not_count_against_the_ceiling() -> None:
    """Інакше реєстр правився б щоразу, коли чиясь сесія закінчилась."""
    registry = _registry()
    observation = _observation()
    # Тимчасових БІЛЬШЕ за стелю навмисно: інакше правило «не рахувати» не можна
    # відрізнити від «рахувати», і мутант на ньому виживає — виміряно.
    transient = [f"/tmp/claude-1000/{i}/scratchpad/x" for i in range(registry["max_worktrees"] + 2)]
    observation["worktrees"] = observation["worktrees"] + transient
    assert len(observation["worktrees"]) > registry["max_worktrees"]
    assert (
        _finding(GATE.assess(observation, _measured(), registry), "persistent_worktrees")["verdict"]
        == "PASS"
    )


def test_unknown_is_never_a_pass() -> None:
    assert GATE.verdict(GATE.assess({"branches": []}, _measured(), _registry())) == "UNKNOWN"
    blind = {**_measured(), "trunk_behind": None}
    assert (
        _finding(GATE.assess(_observation(), blind, _registry()), "trunk_behind")["verdict"]
        == "UNKNOWN"
    )


def test_the_real_repository_still_has_the_declared_branch_and_remotes() -> None:
    """Проти РЕАЛЬНОСТІ, не синтетики."""
    observation = GATE.observe(ROOT)
    registry = _registry()
    assert registry["canonical_branch"] in observation["branches"]
    for item in registry["publications"] + registry["awaiting_decision"]:
        assert item["remote"] in observation["remotes"], item["remote"]


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
