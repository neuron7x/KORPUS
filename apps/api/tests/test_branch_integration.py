"""Одна канонічна гілка — або НАЗВАНИЙ перелік того, що поза нею.

Виміряно 01.09.2026. Усі локальні гілки — `main`, чотири `fix/issue-*`, дзеркала на
GitLab — мають НУЛЬ унікальних комітів: усе вже в канонічній. Уся відокремлена робота
лежить на `origin` і датована 13–19 серпня, і вона НЕ застаріла: п'ять спроможностей
(`temporal_corpus_snapshot`, `approval_provenance`, `nonforgeable_rls`,
`rls_binding_backend_identity`, `answer_snapshot`) існують лише там, 79 файлів, 57 під
`apps/api`.

Автоматично зливається рівно ОДНА гілка. Решту тримає блокер, якого git не бачить:
обидві лінії пронумерували міграції однаково з різним вмістом (0016, 0017, 0018).
Файли різні, тож конфлікту немає; побачить alembic, і вже після мержу.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_branch_integration.py"
REGISTRY = ROOT / "config/operations/branch-integration.json"
SPEC = importlib.util.spec_from_file_location("verify_branch_integration", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

sys.path.insert(0, str(ROOT / "scripts"))
from canonical_declaration import (  # noqa: E402
    EPHEMERAL_CHECKOUT,
    canonical_branch,
    workspace_kind,
)

#: Ім'я канону НЕ вписане тут константою: чотири копії цього рядка вже розійшлись,
#: і кожна тихо судила про інший предмет.
CANON = canonical_branch(ROOT)


def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _observation() -> dict[str, Any]:
    return {
        "canonical": CANON,
        "diverged": {
            entry["branch"]: {"unique": entry["unique"], "clean": entry["clean"]}
            for entry in _registry()["stranded"]
        },
    }


def _finding(findings: list[dict[str, str]], check: str) -> dict[str, str]:
    return next(item for item in findings if item["check"] == check)


def test_a_branch_with_its_own_commits_must_be_named() -> None:
    observation = _observation()
    observation["diverged"]["origin/нова"] = {"unique": 9, "clean": False}
    finding = _finding(GATE.assess(observation, _registry()), "every_branch_named")
    assert finding["verdict"] == "FAIL" and "origin/нова" in finding["detail"]


def test_a_record_about_an_already_merged_branch_is_refused() -> None:
    """Мертвий запис бреше не менше за відсутній: каже, що робота поза каноном."""
    registry = _registry()
    registry["stranded"] = registry["stranded"] + [
        {"branch": "origin/влита", "unique": 1, "clean": False, "carries": "x" * 25}
    ]
    finding = _finding(GATE.assess(_observation(), registry), "no_dead_entry")
    assert finding["verdict"] == "FAIL" and "origin/влита" in finding["detail"]


def test_an_entry_that_does_not_say_what_it_carries_is_refused() -> None:
    """«Розберемось потім» не є планом; запис мусить називати вантаж."""
    registry = _registry()
    registry["stranded"] = [{**registry["stranded"][0], "carries": "бо"}]
    observation = {
        "canonical": CANON,
        "diverged": {registry["stranded"][0]["branch"]: {"unique": 1, "clean": False}},
    }
    assert _finding(GATE.assess(observation, registry), "carries_is_named")["verdict"] == "FAIL"


def test_a_cleanly_merging_branch_may_not_linger_without_a_reason() -> None:
    """Що зливається чисто — зливається або має названу причину, чому ні."""
    registry = _registry()
    entry = dict(registry["stranded"][0])
    entry.pop("clean_but_held", None)
    registry["stranded"] = [entry]
    observation = {
        "canonical": CANON,
        "diverged": {entry["branch"]: {"unique": 1, "clean": True}},
    }
    finding = _finding(GATE.assess(observation, registry), "clean_branch_not_left_hanging")
    assert finding["verdict"] == "FAIL"


def _declared_remotes(registry: dict[str, Any]) -> list[str]:
    return sorted(
        {item["remote"] for item in registry.get("publications", []) if item.get("remote")}
    )


def test_the_real_registry_is_green_on_the_real_repository() -> None:
    """Реєстр описує КАНОНІЧНЕ робоче дерево, і вимір робиться саме там.

    Доти пропуск робився лише для чекауту конвеєра. Але чистий клон — не чекаут: у нього
    є локальна гілка й один віддалений `origin`, тож `workspace_kind` називав його
    робочим деревом, а `origin/*` приносив гілки, яких не називає жоден реєстр. Виміряно
    04.09.2026: саме цей тест і сусідній робили `verify_clean_clone.sh` червоним, і його
    речення «коміт не стоїть сам по собі» було хибним про світ — не стояла сама по собі
    конфігурація ремоутів розробника.

    Предмет називається виміром, а не прапорцем: дерево без ОГОЛОШЕНИХ віддалених за
    визначенням не є тим деревом, яке описує реєстр.
    """
    if workspace_kind(ROOT) == EPHEMERAL_CHECKOUT:
        pytest.skip(
            "чекаут конвеєра: гілок для зведення тут немає — реєстр описує канонічне "
            "робоче дерево, і вимір робиться там"
        )
    registry = _registry()
    present = (
        subprocess.run(
            ["git", "-C", str(ROOT), "remote"], capture_output=True, text=True, check=False
        ).stdout
    ).split()
    absent = [name for name in _declared_remotes(registry) if name not in present]
    if absent:
        pytest.skip(
            f"дерево не несе оголошених віддалених {absent}: реєстр описує не його, "
            "і вирок про чужі гілки був би твердженням про інший предмет"
        )
    findings = GATE.assess(GATE.observe(CANON, ROOT), registry)
    assert GATE.verdict(findings) == "PASS", findings


def test_the_gate_reads_the_single_canonical_declaration() -> None:
    registry = _registry()
    assert GATE._declared_canonical(registry, ROOT) == CANON
    registry["canonical_branch_declared_in"] = "config/operations/other.json"
    assert GATE._declared_canonical(registry, ROOT) is None


def test_the_migration_collision_is_recorded_as_the_blocker() -> None:
    """Блокер не текстовий, і саме тому його треба записати словами.

    Git конфлікту не бачить: файли різні. Побачить alembic — після мержу.
    """
    blocker = _registry()["blocker"]
    assert blocker["kind"] == "alembic_revision_collision"
    for number in ("0016", "0017", "0018"):
        assert number in blocker["detail"], number


def test_every_inactive_local_branch_is_already_inside_the_canonical_one() -> None:
    """Проти РЕАЛЬНОСТІ: активну роботу не плутати із покинутим backlog."""
    canonical = CANON
    active = GATE.active_worktree_branches(ROOT)
    for ref in GATE.refs(ROOT):
        if ref.startswith(("origin/", "gitlab/")) or ref == canonical or ref in active:
            continue
        if ref == "work/serving-surface":
            continue
        assert GATE.unique_commits(canonical, ref, ROOT) == 0, ref


def test_an_active_worktree_branch_is_not_misreported_as_stranded(monkeypatch: Any) -> None:
    monkeypatch.setattr(GATE, "refs", lambda _root: ["main", "feature/live", "origin/old"])
    monkeypatch.setattr(GATE, "active_worktree_branches", lambda _root: {"main", "feature/live"})
    monkeypatch.setattr(GATE, "unique_commits", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(GATE, "merges_cleanly", lambda *_args, **_kwargs: False)
    observed = GATE.observe("main", ROOT)
    assert set(observed["diverged"]) == {"origin/old"}
    assert "feature/live" in observed["active_worktree_branches"]


def test_unknown_is_never_a_pass() -> None:
    assert GATE.verdict(GATE.assess({"diverged": None}, _registry())) == "UNKNOWN"


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
