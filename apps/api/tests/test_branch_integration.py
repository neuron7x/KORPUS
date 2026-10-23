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
    registry = _registry()
    return {
        "canonical": CANON,
        "diverged": {
            entry["branch"]: {
                "head": entry["head"],
                "unique": entry["unique"],
                "clean": entry["clean"],
            }
            for entry in registry["stranded"]
        },
        "integrated": {
            entry["branch"]: {
                "head": entry["head"],
                "commit_exists": True,
                "ancestor_of_checkout": entry["disposition"] == "ancestor",
                **(
                    {
                        "archive_tag_object": "c" * 40,
                        "archive_tag_target": entry["head"],
                        "archive_remote_tag_object": "c" * 40,
                        "archive_remote_tag_target": entry["head"],
                        "archive_tag_verified": True,
                    }
                    if entry["disposition"] == "superseded_archive"
                    else {}
                ),
            }
            for entry in registry["integrated"]
        },
    }


def _finding(findings: list[dict[str, str]], check: str) -> dict[str, str]:
    return next(item for item in findings if item["check"] == check)


def _sample_entry() -> dict[str, Any]:
    """Negative controls must survive the successful state `stranded: []`."""
    return {
        "branch": "origin/synthetic-unmerged",
        "head": "a" * 40,
        "unique": 1,
        "clean": False,
        "carries": "synthetic payload used only by the decision-level negative controls",
    }


def _local_branches(root: Path = ROOT) -> list[str]:
    """Inventory only refs/heads; never interpret remote PR merge refs as local work."""
    listed = GATE._git("for-each-ref", "--format=%(refname:short)", "refs/heads", root=root)
    if listed is None:
        raise RuntimeError("cannot enumerate local branches: git ref query failed")
    return sorted(set(listed.splitlines()))


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
    registry["stranded"] = [{**_sample_entry(), "carries": "бо"}]
    observation = {
        "canonical": CANON,
        "diverged": {registry["stranded"][0]["branch"]: {"unique": 1, "clean": False}},
    }
    assert _finding(GATE.assess(observation, registry), "carries_is_named")["verdict"] == "FAIL"


def test_a_cleanly_merging_branch_may_not_linger_without_a_reason() -> None:
    """Що зливається чисто — зливається або має названу причину, чому ні."""
    registry = _registry()
    entry = _sample_entry()
    entry.pop("clean_but_held", None)
    registry["stranded"] = [entry]
    observation = {
        "canonical": CANON,
        "diverged": {entry["branch"]: {"unique": 1, "clean": True}},
    }
    finding = _finding(GATE.assess(observation, registry), "clean_branch_not_left_hanging")
    assert finding["verdict"] == "FAIL"


def test_the_real_registry_is_green_on_the_real_repository() -> None:
    """Реєстр описує КАНОНІЧНЕ робоче дерево, і вимір робиться саме там.

    Доти пропуск робився лише для чекауту конвеєра. Але чистий клон — не чекаут: у нього
    є локальна гілка й один віддалений `origin`, тож `workspace_kind` називав його
    робочим деревом, а `origin/*` приносив гілки, яких не називає жоден реєстр. Виміряно
    04.09.2026: саме цей тест і сусідній робили `verify_clean_clone.sh` червоним, і його
    речення «коміт не стоїть сам по собі» було хибним про світ — не стояла сама по собі
    конфігурація ремоутів розробника.

    Предмет називається ВИМІРОМ, а не прапорцем: у клоні немає жодної з гілок, які
    реєстр називає, тож кожен запис виглядає «влитим або зниклим» — `no_dead_entry`
    червоніє про дерево, якого реєстр не описує. Перша спроба цієї правки питала про
    ОГОЛОШЕНІ ВІДДАЛЕНІ й була інертною: у цьому реєстрі поля `publications` немає
    взагалі, тож перелік виходив порожній і пропуск не спрацьовував ніколи.
    """
    if workspace_kind(ROOT) == EPHEMERAL_CHECKOUT:
        pytest.skip(
            "чекаут конвеєра: гілок для зведення тут немає — реєстр описує канонічне "
            "робоче дерево, і вимір робиться там"
        )
    canonical_state = json.loads(
        (ROOT / "config/operations/canonical-state.json").read_text(encoding="utf-8")
    )
    if ROOT.resolve() != Path(canonical_state["canonical_root"]).resolve():
        pytest.skip("реальний гейт виконується лише в оголошеному канонічному корені")
    registry = _registry()
    findings = GATE.assess(GATE.observe(CANON, ROOT, registry), registry)
    assert GATE.verdict(findings) == "PASS", findings


def test_the_gate_reads_the_single_canonical_declaration() -> None:
    registry = _registry()
    assert GATE._declared_canonical(registry, ROOT) == CANON
    registry["canonical_branch_declared_in"] = "config/operations/other.json"
    assert GATE._declared_canonical(registry, ROOT) is None


def test_only_live_remote_heads_enter_inventory(tmp_path: Path) -> None:
    """Imported PR refs and stale remote-tracking refs are not live heads."""

    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()

    def git(root: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git(remote, "init", "--bare")
    git(local, "init", "-b", "main")
    git(
        local,
        "-c",
        "user.name=CI",
        "-c",
        "user.email=ci@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "baseline",
    )
    git(local, "remote", "add", "origin", str(remote))
    git(local, "push", "origin", "main", "main:live")
    git(local, "update-ref", "refs/remotes/origin/stale", "HEAD")
    git(local, "update-ref", "refs/remotes/pull/48/merge", "HEAD")
    git(local, "branch", "local/stranded")
    git(local, "switch", "local/stranded")
    git(
        local,
        "-c",
        "user.name=CI",
        "-c",
        "user.email=ci@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "unmerged-work",
    )
    git(local, "switch", "main")

    assert GATE.refs(local, {"origin": str(remote)}) == {
        "local/stranded": git(local, "rev-parse", "local/stranded"),
        "main": git(local, "rev-parse", "main"),
        "origin/live": git(local, "rev-parse", "main"),
        "origin/main": git(local, "rev-parse", "main"),
    }
    assert _local_branches(local) == ["local/stranded", "main"]
    assert GATE.unique_commits("main", git(local, "rev-parse", "local/stranded"), local) == 1


def test_stale_tracking_ref_cannot_make_a_live_head_disappear(
    tmp_path: Path, monkeypatch: Any
) -> None:
    remote = tmp_path / "remote.git"
    observer = tmp_path / "observer"
    writer = tmp_path / "writer"
    remote.mkdir()
    observer.mkdir()

    def git(root: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git(remote, "init", "--bare")
    git(observer, "init", "-b", "main")
    git(
        observer,
        "-c",
        "user.name=CI",
        "-c",
        "user.email=ci@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "baseline",
    )
    git(observer, "remote", "add", "origin", str(remote))
    git(observer, "push", "-u", "origin", "main", "main:live")
    stale = git(observer, "rev-parse", "refs/remotes/origin/live")
    git(tmp_path, "clone", str(remote), str(writer))
    git(writer, "switch", "live")
    git(
        writer,
        "-c",
        "user.name=CI",
        "-c",
        "user.email=ci@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "remote-only",
    )
    git(writer, "push", "origin", "live")
    live = git(writer, "rev-parse", "HEAD")

    assert stale != live
    assert git(observer, "rev-parse", "refs/remotes/origin/live") == stale
    assert GATE.refs(observer, {"origin": str(remote)})["origin/live"] == live
    monkeypatch.setattr(GATE.OBS, "integration_remotes", lambda _root: {"origin": str(remote)})
    with pytest.raises(RuntimeError, match="cannot count commits"):
        GATE.observe("main", observer, {"integrated": []})


def test_only_canonical_publications_supply_integration_branches() -> None:
    assert GATE.integration_remotes(ROOT) == {"origin": "git@github.com:neuron7x/KORPUS.git"}


def test_declared_url_not_a_local_remote_alias_is_the_live_authority(
    tmp_path: Path, monkeypatch: Any
) -> None:
    declared = "https://github.test/owner/KORPUS.git"
    state = tmp_path / "config/operations/canonical-state.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"publications": [{"remote": "origin", "role": "mirror", "url": declared}]}),
        encoding="utf-8",
    )
    head = "a" * 40

    monkeypatch.setattr(
        GATE.OBS,
        "_git",
        lambda *args, root: f"main\t{head}" if args[0] == "for-each-ref" else None,
    )

    def observed_remote(*args: str) -> str | None:
        assert declared in args
        assert "origin" not in args
        return f"{head}\trefs/heads/main"

    monkeypatch.setattr(GATE.OBS, "_remote_git", observed_remote)
    remotes = GATE.integration_remotes(tmp_path)
    assert remotes == {"origin": declared}
    assert GATE.refs(tmp_path, remotes) == {"main": head, "origin/main": head}


def _remote_with_head(root: Path, name: str) -> tuple[Path, str]:
    remote = root / f"{name}.git"
    writer = root / f"{name}-writer"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(writer)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(writer),
            "-c",
            "user.name=CI",
            "-c",
            "user.email=ci@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            name,
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(writer), "push", str(remote), "HEAD:main"],
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "-C", str(writer), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return remote, head


def test_repository_insteadof_cannot_substitute_remote_authority(tmp_path: Path) -> None:
    authority, authority_head = _remote_with_head(tmp_path, "authority")
    attacker, attacker_head = _remote_with_head(tmp_path, "attacker")
    observer = tmp_path / "observer"
    subprocess.run(["git", "init", "-b", "main", str(observer)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(observer),
            "config",
            f"url.{attacker}.insteadOf",
            str(authority),
        ],
        check=True,
        capture_output=True,
    )
    raw = subprocess.run(
        ["git", "-C", str(observer), "ls-remote", "--heads", "--refs", str(authority)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert attacker_head in raw and authority_head not in raw
    assert GATE.OBS._remote_heads("origin", str(authority), observer) == {
        "origin/main": authority_head
    }


def test_environment_insteadof_cannot_substitute_remote_authority(
    tmp_path: Path, monkeypatch: Any
) -> None:
    authority, authority_head = _remote_with_head(tmp_path, "authority")
    attacker, attacker_head = _remote_with_head(tmp_path, "attacker")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{attacker}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(authority))
    raw = subprocess.run(
        ["git", "ls-remote", "--heads", "--refs", str(authority)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert attacker_head in raw and authority_head not in raw
    assert GATE.OBS._remote_heads("origin", str(authority), tmp_path) == {
        "origin/main": authority_head
    }


def test_github_ssh_declaration_is_observed_over_https(monkeypatch: Any) -> None:
    calls: list[tuple[str, ...]] = []

    def observed(*args: str) -> str:
        calls.append(args)
        return f"{'a' * 40}\trefs/heads/main"

    monkeypatch.setattr(GATE.OBS, "_remote_git", observed)
    assert GATE.OBS._remote_heads("origin", "git@github.com:neuron7x/KORPUS.git", ROOT) == {
        "origin/main": "a" * 40
    }
    assert calls == [
        (
            "ls-remote",
            "--heads",
            "--refs",
            "--",
            "https://github.com/neuron7x/KORPUS.git",
        )
    ]


def test_missing_publication_declaration_fails_closed(tmp_path: Path) -> None:
    assert GATE.integration_remotes(tmp_path) is None
    assert GATE.refs(tmp_path, None) is None


def test_declared_remote_without_any_live_head_fails_closed(tmp_path: Path) -> None:
    remote = tmp_path / "empty.git"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    subprocess.run(["git", "-C", str(remote), "init", "--bare"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(local), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(local), "remote", "add", "origin", str(remote)],
        check=True,
        capture_output=True,
    )
    assert GATE.refs(local, {"origin": str(remote)}) is None


def test_local_branch_inventory_fails_closed_when_git_is_unavailable(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(GATE, "_git", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match="cannot enumerate local branches"):
        _local_branches(ROOT)


def test_commit_count_failure_is_not_misread_as_zero(monkeypatch: Any) -> None:
    monkeypatch.setattr(GATE.OBS, "_git", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match="cannot count commits"):
        GATE.unique_commits("main", "origin/unreadable", ROOT)


def test_merge_measurement_failure_is_not_misread_as_conflict(
    monkeypatch: Any, tmp_path: Path
) -> None:
    class FailedMerge:
        returncode = 128

    monkeypatch.setattr(GATE.OBS.subprocess, "run", lambda *_args, **_kwargs: FailedMerge())
    with pytest.raises(RuntimeError, match="cannot test merge"):
        GATE.merges_cleanly("main", "origin/unreadable", tmp_path)


def test_every_inactive_local_branch_is_already_inside_the_canonical_one() -> None:
    """Проти РЕАЛЬНОСТІ: активну роботу не плутати із покинутим backlog."""
    canonical = CANON
    active = GATE.active_worktree_branches(ROOT)
    assert active is not None
    for ref in _local_branches(ROOT):
        if ref == canonical or ref in active:
            continue
        if ref == "work/serving-surface":
            continue
        assert GATE.unique_commits(canonical, ref, ROOT) == 0, ref


def test_only_the_declared_checked_out_candidate_is_exempt(monkeypatch: Any) -> None:
    registry = _registry()
    candidate = registry["convergence_candidate_ref"].removeprefix("refs/heads/")
    monkeypatch.setattr(
        GATE.OBS,
        "refs",
        lambda _root, _remotes: {
            "main": "a" * 40,
            candidate: "b" * 40,
            f"origin/{candidate}": "b" * 40,
            "origin/old": "c" * 40,
        },
    )
    monkeypatch.setattr(
        GATE.OBS,
        "integration_remotes",
        lambda _root: {"origin": "git@github.com:neuron7x/KORPUS.git"},
    )
    monkeypatch.setattr(GATE.OBS, "active_worktree_branches", lambda _root: {"main", candidate})
    monkeypatch.setattr(GATE.OBS, "candidate_branch_head", lambda _root: (candidate, "b" * 40))
    monkeypatch.setattr(GATE.OBS, "unique_commits", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(GATE.OBS, "merges_cleanly", lambda *_args, **_kwargs: False)
    observed = GATE.observe("main", ROOT, registry)
    assert set(observed["diverged"]) == {"origin/old"}
    assert candidate in observed["active_worktree_branches"]


def test_a_remote_branch_with_a_different_head_is_not_hidden_by_an_active_local_name(
    monkeypatch: Any,
) -> None:
    registry = _registry()
    candidate = registry["convergence_candidate_ref"].removeprefix("refs/heads/")
    monkeypatch.setattr(
        GATE.OBS,
        "refs",
        lambda _root, _remotes: {
            "main": "a" * 40,
            candidate: "b" * 40,
            f"origin/{candidate}": "c" * 40,
        },
    )
    monkeypatch.setattr(
        GATE.OBS,
        "integration_remotes",
        lambda _root: {"origin": "git@github.com:neuron7x/KORPUS.git"},
    )
    monkeypatch.setattr(GATE.OBS, "active_worktree_branches", lambda _root: {"main", candidate})
    monkeypatch.setattr(GATE.OBS, "candidate_branch_head", lambda _root: (candidate, "b" * 40))
    monkeypatch.setattr(GATE.OBS, "unique_commits", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(GATE.OBS, "merges_cleanly", lambda *_args, **_kwargs: False)
    observed = GATE.observe("main", ROOT, registry)
    assert set(observed["diverged"]) == {f"origin/{candidate}"}


def test_arbitrary_checked_out_branch_with_matching_remote_head_cannot_hide_debt(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        GATE.OBS,
        "refs",
        lambda _root, _remotes: {
            "main": "a" * 40,
            "feature/live": "b" * 40,
            "origin/feature/live": "b" * 40,
        },
    )
    monkeypatch.setattr(
        GATE.OBS,
        "integration_remotes",
        lambda _root: {"origin": "git@github.com:neuron7x/KORPUS.git"},
    )
    monkeypatch.setattr(
        GATE.OBS, "active_worktree_branches", lambda _root: {"main", "feature/live"}
    )
    monkeypatch.setattr(GATE.OBS, "candidate_branch_head", lambda _root: ("feature/live", "b" * 40))
    monkeypatch.setattr(GATE.OBS, "unique_commits", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(GATE.OBS, "merges_cleanly", lambda *_args, **_kwargs: False)
    assert set(GATE.observe("main", ROOT, _registry())["diverged"]) == {
        "feature/live",
        "origin/feature/live",
    }


def test_ref_inventory_failure_is_unknown_not_green(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        GATE.OBS,
        "integration_remotes",
        lambda _root: {"origin": "git@github.com:neuron7x/KORPUS.git"},
    )
    monkeypatch.setattr(GATE.OBS, "refs", lambda _root, _remotes: None)
    observation = GATE.observe("main", ROOT)
    assert observation["diverged"] is None
    assert GATE.verdict(GATE.assess(observation, _registry())) == "UNKNOWN"


def test_unknown_is_never_a_pass() -> None:
    assert GATE.verdict(GATE.assess({"diverged": None}, _registry())) == "UNKNOWN"


def test_missing_stranded_registry_is_not_an_empty_success() -> None:
    registry = _registry()
    registry.pop("stranded")
    findings = GATE.assess({"diverged": {}, "integrated": {}}, registry)
    assert _finding(findings, "registry_schema")["verdict"] == "FAIL"
    assert GATE.verdict(findings) == "FAIL"


def test_transition_registry_requires_an_exact_candidate_ref() -> None:
    registry = _registry()
    registry.pop("convergence_candidate_ref")
    finding = _finding(GATE.assess(_observation(), registry), "registry_schema")
    assert finding["verdict"] == "FAIL" and "convergence_candidate_ref" in finding["detail"]


def test_integrated_targets_must_match_the_declared_candidate_ref() -> None:
    registry = _registry()
    registry["convergence_candidate_ref"] = "refs/heads/arbitrary/checkout"
    finding = _finding(GATE.assess(_observation(), registry), "registry_schema")
    assert finding["verdict"] == "FAIL" and "different convergence candidate" in finding["detail"]


@pytest.mark.parametrize("field,replacement", [("head", "b" * 40), ("unique", 999)])
def test_recorded_branch_measurement_must_match_observation_exactly(
    field: str, replacement: object
) -> None:
    observation = _observation()
    branch = next(iter(observation["diverged"]))
    observation["diverged"][branch][field] = replacement
    finding = _finding(GATE.assess(observation, _registry()), "recorded_branch_state_exact")
    assert finding["verdict"] == "FAIL" and branch in finding["detail"]


def test_archive_tag_must_resolve_to_the_recorded_head() -> None:
    observation = _observation()
    registry = _registry()
    archived = next(
        entry for entry in registry["integrated"] if entry["disposition"] == "superseded_archive"
    )
    observation["integrated"][archived["branch"]]["archive_tag_target"] = "b" * 40
    finding = _finding(GATE.assess(observation, registry), "integrated_head_provenance")
    assert finding["verdict"] == "FAIL" and archived["branch"] in finding["detail"]


def test_archive_tag_signature_must_be_trusted() -> None:
    observation = _observation()
    registry = _registry()
    archived = next(
        entry for entry in registry["integrated"] if entry["disposition"] == "superseded_archive"
    )
    observation["integrated"][archived["branch"]]["archive_tag_verified"] = False
    finding = _finding(GATE.assess(observation, registry), "integrated_head_provenance")
    assert finding["verdict"] == "FAIL" and "signature" in finding["detail"]


def test_archived_disposition_is_not_exact_for_an_ancestor() -> None:
    observation = _observation()
    registry = _registry()
    archived = next(
        entry for entry in registry["integrated"] if entry["disposition"] == "superseded_archive"
    )
    observation["integrated"][archived["branch"]]["ancestor_of_checkout"] = True
    finding = _finding(GATE.assess(observation, registry), "integrated_head_provenance")
    assert finding["verdict"] == "FAIL" and "already an ancestor" in finding["detail"]


def test_locally_signed_but_unpublished_archive_tag_is_refused() -> None:
    observation = _observation()
    registry = _registry()
    archived = next(
        entry for entry in registry["integrated"] if entry["disposition"] == "superseded_archive"
    )
    state = observation["integrated"][archived["branch"]]
    assert state["archive_tag_verified"] is True
    state["archive_remote_tag_object"] = None
    state["archive_remote_tag_target"] = None
    finding = _finding(GATE.assess(observation, registry), "integrated_head_provenance")
    assert finding["verdict"] == "FAIL" and "not published" in finding["detail"]


def test_archive_observation_reads_remote_tag_namespace(tmp_path: Path, monkeypatch: Any) -> None:
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()

    def git(root: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git(remote, "init", "--bare")
    git(local, "init", "-b", "main")
    git(
        local,
        "-c",
        "user.name=CI",
        "-c",
        "user.email=ci@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "baseline",
    )
    git(local, "remote", "add", "origin", str(remote))
    git(local, "push", "origin", "main")
    git(
        local,
        "-c",
        "user.name=CI",
        "-c",
        "user.email=ci@example.invalid",
        "tag",
        "-a",
        "local-only",
        "-m",
        "not published",
    )
    monkeypatch.setattr(GATE.OBS, "archive_tag_verified", lambda *_args: True)
    state = GATE.OBS.archive_observation(
        {
            "branch": "origin/old",
            "archive_tag": "local-only",
            "archive_signer": "ci@example.invalid",
            "archive_signer_fingerprint": "SHA256:" + "x" * 43,
        },
        local,
        {"origin": str(remote)},
    )

    assert state["archive_tag_verified"] is True
    assert state["archive_tag_object"] == git(local, "rev-parse", "local-only^{tag}")
    assert state["archive_remote_tag_object"] is None
    assert state["archive_remote_tag_target"] is None


def test_registry_schema_rejects_unknown_fields() -> None:
    registry = _registry()
    registry["stranded"][0]["unchecked_assertion"] = True
    finding = _finding(GATE.assess(_observation(), registry), "registry_schema")
    assert finding["verdict"] == "FAIL" and "unknown fields" in finding["detail"]


def test_closed_registry_cannot_retain_a_phantom_blocker() -> None:
    registry = _registry()
    registry["stranded"] = []
    finding = _finding(GATE.assess({"diverged": {}, "integrated": {}}, registry), "registry_schema")
    assert finding["verdict"] == "FAIL" and "blocker" in finding["detail"]


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
