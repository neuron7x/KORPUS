#!/usr/bin/env python3
"""Звірити всі розбіжні гілки з поіменним реєстром інтеграції."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import branch_integration_contract as CONTRACT  # noqa: E402
import branch_integration_observation as OBS  # noqa: E402

CANONICAL_DECLARATION = CONTRACT.CANONICAL_DECLARATION
REGISTRY_SCHEMA = CONTRACT.REGISTRY_SCHEMA
registry_errors = CONTRACT.registry_errors
assess = CONTRACT.assess
verdict = CONTRACT.verdict
_git = OBS.git_output
active_worktree_branches = OBS.active_worktree_branches
archive_tag_verified = OBS.archive_tag_verified
integration_remotes = OBS.integration_remotes
is_ancestor = OBS.is_ancestor
merges_cleanly = OBS.merges_cleanly
observe = OBS.observe
refs = OBS.refs
unique_commits = OBS.unique_commits

REGISTRY = ROOT / "config/operations/branch-integration.json"
SCHEMA = "korpus.branch-integration.v1"


def _declared_canonical(registry: dict[str, Any], root: Path) -> str | None:
    if registry.get("canonical_branch_declared_in") != CANONICAL_DECLARATION:
        return None
    from canonical_declaration import CanonicalDeclarationMissing, canonical_branch

    try:
        return canonical_branch(root)
    except CanonicalDeclarationMissing:
        return None


def _base_selftest() -> tuple[dict[str, Any], dict[str, Any]]:
    head = "a" * 40
    observation = {
        "canonical": "work/x",
        "diverged": {"origin/a": {"head": head, "unique": 355, "clean": False}},
        "integrated": {
            "origin/a": {"head": head, "commit_exists": True, "ancestor_of_checkout": True}
        },
    }
    registry = {
        "schema": REGISTRY_SCHEMA,
        "canonical_branch_declared_in": CANONICAL_DECLARATION,
        "blocker": {
            "kind": "pending_pull_request",
            "detail": "The synthetic branch still awaits the canonical pull request.",
            "closes_when": "The synthetic canonical pull request is merged and verified.",
        },
        "integrated": [
            {
                "branch": "origin/a",
                "head": head,
                "disposition": "ancestor",
                "into": "work/x",
                "note": "Exact ancestor carried into the synthetic candidate.",
                "on": "2026-10-19",
            }
        ],
        "integration_order": [
            "Merge the synthetic pull request after every required check passes."
        ],
        "measured_at": "2026-10-19",
        "note": "Synthetic complete registry used only by executable negative controls.",
        "stranded": [
            {
                "branch": "origin/a",
                "head": head,
                "unique": 355,
                "clean": False,
                "carries": "Synthetic capabilities absent from the canonical branch.",
                "closes_when": "The synthetic canonical pull request is merged and verified.",
            }
        ],
    }
    return observation, registry


def _empty_registry(registry: dict[str, Any]) -> dict[str, Any]:
    empty = {**registry, "integrated": [], "stranded": []}
    empty.pop("blocker")
    empty.pop("integration_order")
    return empty


def _selftest_cases() -> list[tuple[str, dict[str, Any], dict[str, Any], str]]:
    observation, registry = _base_selftest()
    head = "a" * 40
    unnamed = copy.deepcopy(observation)
    unnamed["diverged"]["origin/b"] = {"head": "b" * 40, "unique": 7, "clean": False}
    dead = copy.deepcopy(registry)
    dead["stranded"].append({**dead["stranded"][0], "branch": "origin/dead", "head": "b" * 40})
    silent = copy.deepcopy(registry)
    silent["stranded"][0]["carries"] = "no"
    clean_observation = copy.deepcopy(observation)
    clean_observation["diverged"]["origin/a"] = {"head": head, "unique": 1, "clean": True}
    held = copy.deepcopy(registry)
    held["stranded"][0].update(
        unique=1, clean=True, clean_but_held="Named synthetic hold reason for review."
    )
    wrong_head = copy.deepcopy(observation)
    wrong_head["diverged"]["origin/a"]["head"] = "b" * 40
    wrong_disposition = copy.deepcopy(observation)
    wrong_disposition["integrated"]["origin/a"]["ancestor_of_checkout"] = False
    extra = copy.deepcopy(registry)
    extra["unexpected"] = True
    return [
        ("complete exact registry", observation, registry, "PASS"),
        ("unnamed live head", unnamed, registry, "FAIL"),
        ("dead registry entry", observation, dead, "FAIL"),
        ("unnamed payload", observation, silent, "FAIL"),
        ("clean head without hold", clean_observation, registry, "FAIL"),
        ("clean head with exact hold", clean_observation, held, "PASS"),
        ("unreadable heads", {"diverged": None}, registry, "UNKNOWN"),
        (
            "zero divergent heads",
            {"diverged": {}, "integrated": {}},
            _empty_registry(registry),
            "PASS",
        ),
        (
            "missing stranded",
            {"diverged": {}, "integrated": {}},
            {**registry, "stranded": None},
            "FAIL",
        ),
        ("wrong head", wrong_head, registry, "FAIL"),
        ("wrong disposition", wrong_disposition, registry, "FAIL"),
        ("unknown schema field", observation, extra, "FAIL"),
    ]


def selftest() -> int:
    failures = 0
    cases = _selftest_cases()
    for name, observation, registry, wanted in cases:
        actual = verdict(assess(observation, registry))
        passed = actual == wanted
        failures += not passed
        print(f"  [{'ok' if passed else 'ЗБІЙ'}] {name}: {actual}")
    print(f"\nнегативний контроль: {len(cases) - failures}/{len(cases)}")
    return 1 if failures else 0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/branch-integration.json")
    parser.add_argument("--selftest", action="store_true")
    return parser.parse_args()


def _read_registry(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _unknown(reason: str) -> int:
    print(json.dumps({"schema": SCHEMA, "status": "UNKNOWN", "reason": reason}))
    return 2


def main() -> int:
    arguments = _arguments()
    if arguments.selftest:
        return selftest()
    registry = _read_registry(arguments.registry)
    if registry is None:
        return _unknown("реєстр не прочитано")
    canonical = _declared_canonical(registry, arguments.root)
    if not isinstance(canonical, str):
        return _unknown("канонічну гілку не названо")
    try:
        observation = observe(canonical, arguments.root, registry)
    except RuntimeError as error:
        return _unknown(str(error))
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
    raise SystemExit(main())
