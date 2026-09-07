#!/usr/bin/env python3
"""Звірити всі розбіжні гілки з поіменним реєстром інтеграції."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config/operations/branch-integration.json"
SCHEMA = "korpus.branch-integration.v1"
CANONICAL_DECLARATION = "config/operations/canonical-state.json"


# ----------------------------------------------------------------- спостереження (I/O)


def _git(*args: str, root: Path = ROOT) -> str | None:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() if done.returncode == 0 else None


def refs(root: Path = ROOT) -> list[str]:
    """Гілки дерева без символічних голів віддалених.

    Відсіювати треба за ПОВНИМ іменем, не за коротким. `%(refname:short)` для
    `refs/remotes/origin/HEAD` дає «origin» — без скісної риски й без «HEAD», — тож
    фільтр по короткому імені його не бачив, і символічний вказівник на голову
    віддаленого рахувався звичайною гілкою. Далі `rev-list canonical..origin` дає
    ненульове число, і гейт оголошує покинуту роботу там, де її нема.

    ВИМІРЯНО 06.09.2026: `git clone` створює цей реф ЗАВЖДИ, тож перевірка червоніла
    на будь-якому клоні й була зелена в каноні лише тому, що канон не є клоном. Тобто
    зелена через ВІДСУТНІСТЬ ПРЕДМЕТА, а не через його стан — рівно те, що ця
    перевірка мала б ловити в інших.
    """
    listed = _git(
        "for-each-ref",
        "--format=%(refname)%09%(refname:short)",
        "refs/heads",
        "refs/remotes",
        root=root,
    )
    names: set[str] = set()
    for line in (listed or "").splitlines():
        full, _, short = line.partition("\t")
        if not short or full.endswith("/HEAD"):
            continue
        names.add(short)
    return sorted(names)


def active_worktree_branches(root: Path = ROOT) -> set[str]:
    listed = _git("worktree", "list", "--porcelain", root=root)
    prefix = "branch refs/heads/"
    return {
        line.removeprefix(prefix) for line in (listed or "").splitlines() if line.startswith(prefix)
    }


def unique_commits(canonical: str, ref: str, root: Path = ROOT) -> int | None:
    count = _git("rev-list", "--count", f"{canonical}..{ref}", root=root)
    try:
        return int(count) if count is not None else None
    except ValueError:
        return None


def merges_cleanly(canonical: str, ref: str, root: Path = ROOT) -> bool | None:
    done = subprocess.run(
        ["git", "-C", str(root), "merge-tree", "--write-tree", "--name-only", canonical, ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode not in (0, 1):
        return None
    return done.returncode == 0


def observe(canonical: str, root: Path = ROOT) -> dict[str, Any]:
    """Кожна гілка: скільки власних комітів і чи зливається чисто.

    Чистота міряється лише там, де є власні коміти: для решти питання не стоїть, а
    зайвий вимір коштував би часу на кожній гілці-предку.
    """
    found: dict[str, Any] = {}
    active = active_worktree_branches(root)
    for ref in refs(root):
        if ref == canonical or ref in active:
            continue
        count = unique_commits(canonical, ref, root=root)
        if not count:
            continue
        found[ref] = {"unique": count, "clean": merges_cleanly(canonical, ref, root=root)}
    return {"canonical": canonical, "active_worktree_branches": sorted(active), "diverged": found}


# --------------------------------------------------------------------- судження (чисте)


def _finding(check: str, verdict: str, detail: str) -> dict[str, str]:
    return {"check": check, "verdict": verdict, "detail": detail}


def _named(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = registry.get("stranded") if isinstance(registry, dict) else None
    if not isinstance(entries, list):
        return {}
    return {
        e["branch"]: e for e in entries if isinstance(e, dict) and isinstance(e.get("branch"), str)
    }


def assess(observation: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, str]]:
    diverged = observation.get("diverged")
    if diverged is None:
        return [_finding("branch_integration", "UNKNOWN", "гілки не прочитано")]
    named = _named(registry)
    findings: list[dict[str, str]] = []

    unnamed = sorted(set(diverged) - set(named))
    findings.append(
        _finding(
            "every_branch_named",
            "FAIL",
            "гілка з власними комітами, якої ніхто не назвав: " + ", ".join(unnamed),
        )
        if unnamed
        else _finding(
            "every_branch_named", "PASS", f"{len(diverged)} гілок поза каноном, усі названі"
        )
    )

    merged = sorted(set(named) - set(diverged))
    findings.append(
        _finding(
            "no_dead_entry",
            "FAIL",
            "запис про гілку, яка вже влита або зникла: " + ", ".join(merged),
        )
        if merged
        else _finding("no_dead_entry", "PASS", f"{len(named)} записів усі ще потрібні")
    )

    silent = sorted(
        branch
        for branch, entry in named.items()
        if branch in diverged
        and not (isinstance(entry.get("carries"), str) and len(entry["carries"].strip()) >= 20)
    )
    findings.append(
        _finding(
            "carries_is_named",
            "FAIL",
            "запис не каже, що саме гілка везе: " + ", ".join(silent),
        )
        if silent
        else _finding("carries_is_named", "PASS", "кожен запис називає свій вантаж")
    )

    lingering = sorted(
        branch
        for branch, state in diverged.items()
        if state.get("clean") and not named.get(branch, {}).get("clean_but_held")
    )
    findings.append(
        _finding(
            "clean_branch_not_left_hanging",
            "FAIL",
            "зливається ЧИСТО і досі не влита, причини не названо: " + ", ".join(lingering),
        )
        if lingering
        else _finding(
            "clean_branch_not_left_hanging", "PASS", "жодної чистої гілки без причини не влито"
        )
    )
    return findings


def verdict(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "UNKNOWN"
    verdicts = {item["verdict"] for item in findings}
    if "FAIL" in verdicts:
        return "FAIL"
    return "UNKNOWN" if "UNKNOWN" in verdicts else "PASS"


def _declared_canonical(registry: dict[str, Any], root: Path) -> str | None:
    if registry.get("canonical_branch_declared_in") != CANONICAL_DECLARATION:
        return None
    sys.path.insert(0, str(ROOT / "scripts"))
    from canonical_declaration import CanonicalDeclarationMissing, canonical_branch

    try:
        return canonical_branch(root)
    except CanonicalDeclarationMissing:
        return None


# ------------------------------------------------------------------ негативні контролі


def selftest() -> int:
    observation: dict[str, Any] = {
        "canonical": "work/x",
        "diverged": {"origin/a": {"unique": 355, "clean": False}},
    }
    registry: dict[str, Any] = {
        "stranded": [{"branch": "origin/a", "carries": "п'ять спроможностей, яких у каноні немає"}]
    }
    cases: list[tuple[str, dict[str, Any], dict[str, Any], str]] = [
        ("названо все — зелено", observation, registry, "PASS"),
        (
            "гілка з власними комітами, якої ніхто не назвав",
            {
                **observation,
                "diverged": {**observation["diverged"], "origin/b": {"unique": 7, "clean": False}},
            },
            registry,
            "FAIL",
        ),
        (
            "запис про гілку, яка вже влита",
            observation,
            {"stranded": registry["stranded"] + [{"branch": "origin/влита", "carries": "x" * 20}]},
            "FAIL",
        ),
        (
            "запис не каже, ЩО везе",
            observation,
            {"stranded": [{"branch": "origin/a", "carries": "бо"}]},
            "FAIL",
        ),
        (
            "чиста гілка висить без причини",
            {**observation, "diverged": {"origin/a": {"unique": 1, "clean": True}}},
            registry,
            "FAIL",
        ),
        (
            "чиста гілка з названою причиною тримається",
            {**observation, "diverged": {"origin/a": {"unique": 1, "clean": True}}},
            {
                "stranded": [
                    {"branch": "origin/a", "carries": "x" * 20, "clean_but_held": "причина"}
                ]
            },
            "PASS",
        ),
        ("гілок не прочитано — UNKNOWN, не PASS", {"diverged": None}, registry, "UNKNOWN"),
        ("жодної розбіжної гілки — зелено", {"diverged": {}}, {"stranded": []}, "PASS"),
    ]
    bad = 0
    for name, obs, reg, want in cases:
        got = verdict(assess(obs, reg))
        ok = got == want
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")
    print(f"\nнегативний контроль: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/branch-integration.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    try:
        registry = json.loads(arguments.registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"schema": SCHEMA, "status": "UNKNOWN", "reason": "реєстр не прочитано"}))
        return 2

    canonical = _declared_canonical(registry, arguments.root)
    if not isinstance(canonical, str):
        print(
            json.dumps(
                {"schema": SCHEMA, "status": "UNKNOWN", "reason": "канонічну гілку не названо"}
            )
        )
        return 2

    observation = observe(canonical, arguments.root)
    findings = assess(observation, registry)
    overall = verdict(findings)
    report = {"schema": SCHEMA, "status": overall, "observed": observation, "findings": findings}
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for item in findings:
        print(f"  [{item['verdict']}] {item['check']}: {item['detail'][:200]}")
    print(f"\nbranch-integration: {overall}  → {arguments.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
