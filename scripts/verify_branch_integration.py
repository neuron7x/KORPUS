#!/usr/bin/env python3
"""Одна канонічна гілка — або названий перелік того, що поза нею.

Виміряно 01.09.2026. Гілок із власними комітами — 25; після мержу чистої лишилось 24.
Локальні всі до одної мають НУЛЬ унікальних комітів: `main`, чотири `fix/issue-*`,
дзеркала на GitLab — усе вже всередині канонічної. Уся відокремлена робота лежить на
`origin` і датована 13–19 серпня.

І вона НЕ застаріла. П'ять спроможностей існують там і в каноні відсутні цілком:
`temporal_corpus_snapshot`, `approval_provenance`, `nonforgeable_rls`,
`rls_binding_backend_identity`, `answer_snapshot` — разом 79 файлів, з них 57 під
`apps/api`. Тобто це не дубль зробленого, а зроблене й загублене.

Чому це не зливається автоматично, і причина не текстова. Обидві лінії пронумерували
міграції ОДНАКОВО з різним вмістом:

    0016  канон learning_course_graph   ·  github temporal_corpus_snapshot
    0017  канон learning_mastery        ·  github approval_provenance_boundary
    0018  канон operational_competencies·  github nonforgeable_rls_identity

Git такого конфлікту не бачить — файли різні. Побачить alembic, і вже після мержу.
Тому «змерджити все зелене автоматично» дає рівно одну гілку, а решта мусить бути
НАЗВАНА: що саме везе, скільки конфліктних файлів, і що закриє.

Гейт не зливає нічого. Він відмовляє, коли гілка з власними комітами не названа, і коли
запис описує гілку, яка вже влита або зникла.

    verify_branch_integration.py
    verify_branch_integration.py --selftest
"""

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


# ----------------------------------------------------------------- спостереження (I/O)


def _git(*args: str, root: Path = ROOT) -> str | None:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() if done.returncode == 0 else None


def refs(root: Path = ROOT) -> list[str]:
    listed = _git(
        "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes", root=root
    )
    return sorted({name for name in (listed or "").split() if not name.endswith("/HEAD")})


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
    for ref in refs(root):
        if ref == canonical:
            continue
        count = unique_commits(canonical, ref, root=root)
        if not count:
            continue
        found[ref] = {"unique": count, "clean": merges_cleanly(canonical, ref, root=root)}
    return {"canonical": canonical, "diverged": found}


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

    canonical = registry.get("canonical_branch")
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
