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

sys.path.insert(0, str(ROOT / "scripts"))
from canonical_declaration import (  # noqa: E402
    canonical_branch,
)

#: Тест, що вписує відповідь константою, перевіряє не оголошення, а свою копію.
CANON = canonical_branch(ROOT)


def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _observation() -> dict[str, Any]:
    registry = _registry()
    publications = {item["remote"]: item for item in registry["publications"]}
    return {
        "head_branch": CANON,
        "branches": ["main", CANON],
        "remotes": {
            "gitlab": publications["gitlab"]["url"],
            "origin": publications["origin"]["url"],
        },
        "worktrees": [registry["canonical_root"], "/home/neuro7/.korpus-worktrees/a"],
        "root": registry["canonical_root"],
    }


def _registry_with_trunk() -> dict[str, Any]:
    """Реєстр із ЖИВИМ боргом відставання стовбура.

    01.09.2026 борг закрито: `main` став канонічною гілкою, тобто стовбур і канон —
    одна гілка, і `trunk_is_ancestor`/`trunk_staleness` стали тотожно істинними.
    Правила, які вони виражають, від цього не перестали бути правильними — вони
    просто не мають на що дивитись у ЦЬОМУ реєстрі. Тому їх далі міряють, але на
    синтетичному боргу: інакше зникнення блоку тихо забрало б із собою три перевірки.
    """
    registry = _registry()
    registry.pop("closed_debts", None)
    registry["trunk"] = {
        "branch": "release/legacy",
        "max_days": 2,
        "reason": "синтетичний борг: правила відставання мусять лишитись виміряними",
        "closes_when": "ніколи; цей запис існує лише всередині тесту",
    }
    return registry


def _measured() -> dict[str, Any]:
    registry = _registry()
    return {
        "trunk_behind": 126,
        "trunk_days": _registry_with_trunk()["trunk"]["max_days"] - 0.5,
        "trunk_is_ancestor": True,
        "publication_behind": {"gitlab": 107},
        "publication_days": {"gitlab": registry["publications"][0]["max_days"] - 0.5},
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
    findings = GATE.assess(
        _observation(), {**_measured(), "trunk_is_ancestor": False}, _registry_with_trunk()
    )
    assert _finding(findings, "trunk_is_ancestor")["verdict"] == "FAIL"


def test_the_trunk_is_judged_by_age_not_by_commit_count() -> None:
    """Перша версія міряла КІЛЬКІСТЬ комітів і почервоніла на першому ж власному.

    Кожен коміт у канонічну гілку додає одиницю до відставання, тож поріг довелося б
    піднімати щоразу — величина, яка росте від роботи, як поріг стає податком на
    роботу. Вік від роботи не росте: його збільшує лише час, а fast-forward обнуляє.
    """
    registry = _registry_with_trunk()
    assert "max_behind" not in registry["trunk"], "кількість комітів більше не судить"
    stale = GATE.assess(
        _observation(), {**_measured(), "trunk_days": registry["trunk"]["max_days"] + 0.1}, registry
    )
    assert _finding(stale, "trunk_staleness")["verdict"] == "FAIL"

    busy = GATE.assess(_observation(), {**_measured(), "trunk_behind": 100_000}, registry)
    assert GATE.verdict([_finding(busy, "trunk_staleness")]) == "PASS"
    assert _finding(busy, "trunk_behind")["verdict"] == "PASS", "кількість — спостереження"


def test_the_publication_is_judged_by_age_too() -> None:
    registry = _registry()
    stale = GATE.assess(
        _observation(),
        {
            **_measured(),
            "publication_days": {"gitlab": registry["publications"][0]["max_days"] + 1},
        },
        registry,
    )
    assert _finding(stale, "publication_staleness:gitlab")["verdict"] == "FAIL"


def test_age_is_measured_between_two_dates_and_missing_one_is_unknown() -> None:
    assert GATE.days_between("2026-08-30T20:54:00+03:00", "2026-09-01T08:54:00+03:00") == 1.5
    assert GATE.days_between(None, "2026-09-01T08:54:00+03:00") is None
    assert GATE.days_between("не дата", "2026-09-01T08:54:00+03:00") is None


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


def test_origin_is_an_integration_source_governed_by_the_branch_registry() -> None:
    findings = GATE.assess(_observation(), _measured(), _registry())
    assert _finding(findings, "publication_role_decided")["verdict"] == "PASS"
    assert _finding(findings, "publication_role:origin")["verdict"] == "PASS"
    assert not any(item["check"] == "publication_staleness:origin" for item in findings)


def test_the_undecided_remote_is_named_and_stays_red_until_decided() -> None:
    registry = _registry()
    origin = next(item for item in registry["publications"] if item["remote"] == "origin")
    registry["publications"].remove(origin)
    registry["awaiting_decision"] = [origin]
    findings = GATE.assess(_observation(), _measured(), registry)
    assert _finding(findings, "publication_role_decided")["verdict"] == "FAIL"


def test_an_integration_source_without_branch_governance_is_refused() -> None:
    registry = _registry()
    origin = next(item for item in registry["publications"] if item["remote"] == "origin")
    origin.pop("governed_by")
    findings = GATE.assess(_observation(), _measured(), registry)
    assert _finding(findings, "publication_role:origin")["verdict"] == "FAIL"


def test_an_unknown_publication_role_is_refused() -> None:
    registry = _registry()
    registry["publications"][0]["role"] = "decorative"
    findings = GATE.assess(_observation(), _measured(), registry)
    assert _finding(findings, "publication_role:gitlab")["verdict"] == "FAIL"


def test_measurement_never_treats_an_integration_source_as_a_mirror(monkeypatch: Any) -> None:
    refs: list[str] = []

    def remember(ref: str, *_args: Any, **_kwargs: Any) -> int:
        refs.append(ref)
        return 0

    monkeypatch.setattr(GATE, "behind", remember)
    monkeypatch.setattr(GATE, "committed_at", remember)
    monkeypatch.setattr(GATE, "is_ancestor", remember)
    measured = GATE.measure(_observation(), _registry())
    assert set(measured["publication_behind"]) == {"gitlab"}
    assert set(measured["publication_days"]) == {"gitlab"}
    assert not any(ref.startswith("origin/") for ref in refs)


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
    blind = {**_measured(), "trunk_days": None}
    assert (
        _finding(GATE.assess(_observation(), blind, _registry_with_trunk()), "trunk_staleness")[
            "verdict"
        ]
        == "UNKNOWN"
    )


def test_a_trunk_declared_as_the_canonical_branch_is_refused() -> None:
    """Перевірка, яка не має стану, де вона червоніє, — не перевірка.

    Стовбур, оголошений тією самою гілкою, що й канон, робить `trunk_is_ancestor`
    тотожно істинним, а `trunk_days` — нулем за побудовою. Гейт лишався б зеленим
    рівно в тому стані, заради якого існує.
    """
    registry = _registry_with_trunk()
    registry["trunk"]["branch"] = registry["canonical_branch"]
    findings = GATE.assess(_observation(), _measured(), registry)
    assert _finding(findings, "trunk_declared")["verdict"] == "FAIL"
    assert "тотожно істинними" in _finding(findings, "trunk_declared")["detail"]


def test_a_vanished_trunk_block_is_refused_unless_the_debt_was_closed() -> None:
    """Відсутність — це або закритий борг, або тиха втрата; розрізняє лише запис."""
    silent = _registry_with_trunk()
    silent.pop("trunk")
    assert (
        _finding(GATE.assess(_observation(), _measured(), silent), "trunk_declared")["verdict"]
        == "FAIL"
    )

    closed = dict(silent)
    closed["closed_debts"] = [{"name": "trunk_lag", "on": "2026-09-01", "why": "зіллявся"}]
    assert (
        _finding(GATE.assess(_observation(), _measured(), closed), "trunk_declared")["verdict"]
        == "PASS"
    )

    unexplained = dict(silent)
    unexplained["closed_debts"] = [{"name": "trunk_lag", "on": "2026-09-01", "why": "   "}]
    assert (
        _finding(GATE.assess(_observation(), _measured(), unexplained), "trunk_declared")["verdict"]
        == "FAIL"
    ), "запис без причини закриває борг лише на вигляд"


def test_the_declared_branch_and_remotes_are_observed_where_they_exist(tmp_path: Path) -> None:
    """Проба СТВОРЮЄ свій предмет, а не питає дерево, у якому опинилась.

    Доти це твердження зверталось до навколишнього репозиторію. У канонічному дереві
    воно було істинним, у чистому клоні — хибним, і не тому, що коміт зламаний, а тому,
    що клон має один віддалений `origin` замість оголошених. Виміряно 04.09.2026:
    `verify_clean_clone.sh` казав «коміт не стоїть сам по собі», а шість цілей із семи
    в голому клоні проходили; не стояла сама по собі конфігурація ремоутів розробника.
    Той самий тест роками тримав і CI.

    Тепер репозиторій із оголошеною гілкою й оголошеними ремоутами будується тут, і
    твердження стає про ГЕЙТ, а не про машину, на якій він біжить.
    """
    registry = _registry()
    declared = [item["remote"] for item in registry["publications"] + registry["awaiting_decision"]]
    root = tmp_path / "repo"
    root.mkdir()
    run = lambda *args: subprocess.run(  # noqa: E731 - локальний хелпер, не API
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    run("config", "user.email", "probe@example.invalid")
    run("config", "user.name", "probe")
    run("checkout", "--quiet", "-B", registry["canonical_branch"])
    (root / "seed").write_text("seed\n", encoding="utf-8")
    run("add", "seed")
    run("commit", "--quiet", "-m", "seed")
    for name in sorted(set(declared)):
        run("remote", "add", name, f"https://example.invalid/{name}.git")

    observation = GATE.observe(root)
    assert registry["canonical_branch"] in observation["branches"]
    for name in declared:
        assert name in observation["remotes"], name


def test_a_missing_declared_remote_is_visible_to_the_observer(tmp_path: Path) -> None:
    """Дуал: якби спостерігач бачив ремоут, якого немає, попередній тест нічого не вартий."""
    root = tmp_path / "bare"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    assert not GATE.observe(root)["remotes"]


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
