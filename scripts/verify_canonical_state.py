#!/usr/bin/env python3
"""Перевірити канонічний checkout і виконувані ролі віддалених поверхонь."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config/operations/canonical-state.json"
SCHEMA = "korpus.canonical-state.v1"
MIRROR = "mirror"
INTEGRATION_SOURCE = "integration-source"
INTEGRATION_REGISTRY = "config/operations/branch-integration.json"


# ----------------------------------------------------------------- спостереження (I/O)


def _git(*args: str, root: Path = ROOT) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def observe(root: Path = ROOT, fetch: bool = False) -> dict[str, Any]:
    """Стан репозиторію. Тут дозволено I/O і заборонено судити."""
    branches = (
        _git("for-each-ref", "--format=%(refname:short)", "refs/heads", root=root) or ""
    ).split()
    remotes = (_git("remote", root=root) or "").split()
    if fetch:
        for name in remotes:
            subprocess.run(
                ["git", "-C", str(root), "fetch", "--quiet", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
    worktrees = [
        line.split(" ", 1)[1]
        for line in (_git("worktree", "list", "--porcelain", root=root) or "").splitlines()
        if line.startswith("worktree ")
    ]
    return {
        "head_branch": _git("rev-parse", "--abbrev-ref", "HEAD", root=root),
        "branches": sorted(branches),
        "remotes": {name: _git("remote", "get-url", name, root=root) for name in remotes},
        "worktrees": worktrees,
        "root": str(root),
    }


def behind(reference: str, target: str, root: Path = ROOT) -> int | None:
    """Скільки комітів `reference` позаду `target`. None — порівняти неможливо."""
    count = _git("rev-list", "--count", f"{reference}..{target}", root=root)
    try:
        return int(count) if count is not None else None
    except ValueError:
        return None


def committed_at(reference: str, root: Path = ROOT) -> str | None:
    """Дата верхівки гілки в ISO. None — гілки немає або git недоступний."""
    return _git("log", "-1", "--format=%cI", reference, root=root)


def days_between(earlier: str | None, later: str | None) -> float | None:
    """Скільки діб між двома датами. None — якщо бракує хоч однієї."""
    if not earlier or not later:
        return None
    try:
        start = datetime.fromisoformat(earlier)
        end = datetime.fromisoformat(later)
    except ValueError:
        return None
    return (end - start).total_seconds() / 86400.0


def is_ancestor(reference: str, target: str, root: Path = ROOT) -> bool | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", reference, target],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in (0, 1):
        return None
    return completed.returncode == 0


# --------------------------------------------------------------------- судження (чисте)


def _finding(check: str, verdict: str, detail: str) -> dict[str, str]:
    return {"check": check, "verdict": verdict, "detail": detail}


def _check_canonical_branch(
    observation: dict[str, Any], registry: dict[str, Any]
) -> dict[str, str]:
    declared = registry.get("canonical_branch")
    if not isinstance(declared, str):
        return _finding("canonical_branch", "FAIL", "реєстр не називає канонічної гілки")
    if declared not in observation.get("branches", []):
        return _finding(
            "canonical_branch", "FAIL", f"названої гілки {declared} у репозиторії немає"
        )
    return _finding("canonical_branch", "PASS", f"канонічна гілка названа: {declared}")


def _check_checked_out(observation: dict[str, Any], registry: dict[str, Any]) -> dict[str, str]:
    """Чи КАНОНІЧНИЙ каталог стоїть на канонічній гілці.

    У worktree відповідь інша за побудовою, і оголосити це відмовою означало б
    червоніти з ВЛАСНОЇ причини — вада, яку цей самий гейт існує ловити.
    """
    declared_root = registry.get("canonical_root")
    if not isinstance(declared_root, str):
        return _finding("canonical_checked_out", "UNKNOWN", "реєстр не називає канонічного кореня")
    if observation.get("root") != declared_root:
        return _finding(
            "canonical_checked_out",
            "UNKNOWN",
            f"це не канонічний корінь ({observation.get('root')}) — судити нема про що",
        )
    head = observation.get("head_branch")
    if head != registry.get("canonical_branch"):
        return _finding(
            "canonical_checked_out",
            "FAIL",
            f"канонічний корінь стоїть на {head}, а не на {registry.get('canonical_branch')}",
        )
    return _finding("canonical_checked_out", "PASS", f"канонічний корінь на {head}")


def _closed(registry: dict[str, Any], name: str) -> bool:
    """Чи цей борг ЗАКРИТО названим записом, а не просто зник із реєстру."""
    closed = registry.get("closed_debts")
    if not isinstance(closed, list):
        return False
    return any(
        isinstance(item, dict) and item.get("name") == name and str(item.get("why", "")).strip()
        for item in closed
    )


def _check_trunk(measured: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, str]]:
    trunk = registry.get("trunk")
    if not isinstance(trunk, dict):
        # Відсутність — це або закритий борг, або тиха втрата. Розрізняє лише запис.
        if _closed(registry, "trunk_lag"):
            return [
                _finding(
                    "trunk_declared",
                    "PASS",
                    "стовбур і канон — одна гілка; борг відставання закрито названим записом",
                )
            ]
        return [_finding("trunk_declared", "FAIL", "реєстр не називає стовбура")]
    name = trunk.get("branch")
    if name == registry.get("canonical_branch"):
        # Перевірка, яка не має стану, де вона червоніє, — не перевірка. Стовбур,
        # оголошений тією самою гілкою, що й канон, робить `trunk_is_ancestor` і
        # `trunk_staleness` тотожно істинними: вони міряли б нуль за побудовою.
        return [
            _finding(
                "trunk_declared",
                "FAIL",
                f"стовбур {name} оголошено тією самою гілкою, що й канон — "
                "перевірки відставання стають тотожно істинними; закрий борг записом",
            )
        ]
    ancestor = measured.get("trunk_is_ancestor")
    lag = measured.get("trunk_behind")
    found = []
    if ancestor is None:
        found.append(_finding("trunk_is_ancestor", "UNKNOWN", f"порівняти {name} не вдалося"))
    elif not ancestor:
        found.append(
            _finding(
                "trunk_is_ancestor",
                "FAIL",
                f"{name} РОЗІЙШОВСЯ з канонічною гілкою — це вже не відставання",
            )
        )
    else:
        found.append(_finding("trunk_is_ancestor", "PASS", f"{name} — строгий предок"))
    found.append(
        _staleness("trunk_staleness", name, measured.get("trunk_days"), trunk.get("max_days"))
    )
    found.append(
        _finding("trunk_behind", "PASS", f"{name}: позаду на {lag} комітів (спостереження)")
        if lag is not None
        else _finding("trunk_behind", "UNKNOWN", f"{name}: відставання не виміряно")
    )
    return found


def _staleness(check: str, name: Any, days: float | None, ceiling: Any) -> dict[str, str]:
    """Скільки діб відстає, проти НАЗВАНОГО порогу.

    Це поріг, а не ратчет, і різниця тут суттєва. Перша версія міряла кількість
    комітів відставання й ставила стелю на виміряному числі — і почервоніла на
    ПЕРШОМУ ж власному коміті: кожен коміт у канонічну гілку додає одиницю, тож
    стелю довелося б піднімати щоразу. Ратчет на величині, яка росте від роботи,
    перетворюється на податок на роботу.

    Вік стовбура від роботи не росте: його збільшує лише ЧАС, а fast-forward
    обнуляє. Саме це ми й хочемо сказати — «стовбур мусить оновлюватись», а не
    «працюйте менше».
    """
    if days is None:
        return _finding(check, "UNKNOWN", f"{name}: вік не виміряно")
    if not isinstance(ceiling, (int, float)):
        return _finding(check, "FAIL", f"{name}: поріг не є числом")
    if days > ceiling:
        return _finding(check, "FAIL", f"{name}: відстає на {days:.1f} доби проти порогу {ceiling}")
    return _finding(check, "PASS", f"{name}: відстає на {days:.1f} доби, поріг {ceiling}")


def _ratchet(check: str, name: Any, measured: int | None, ceiling: Any) -> dict[str, str]:
    """Відставання під стелею. Погіршення — відмова; поліпшення ВИМАГАЄ знизити стелю."""
    if measured is None:
        return _finding(check, "UNKNOWN", f"{name}: не виміряно")
    if not isinstance(ceiling, int):
        return _finding(check, "FAIL", f"{name}: стеля не є цілим числом")
    if measured > ceiling:
        return _finding(
            check,
            "FAIL",
            f"{name}: позаду на {measured} проти стелі {ceiling} (+{measured - ceiling})",
        )
    if measured < ceiling:
        return _finding(
            check,
            "PASS",
            f"{name}: {measured} проти {ceiling} — стелю треба знизити до {measured}",
        )
    return _finding(check, "PASS", f"{name}: на стелі, {measured}")


def _check_publications(
    observation: dict[str, Any], measured: dict[str, Any], registry: dict[str, Any]
) -> list[dict[str, str]]:
    declared = registry.get("publications")
    declared = declared if isinstance(declared, list) else []
    by_name = {item["remote"]: item for item in declared if isinstance(item.get("remote"), str)}
    pending = registry.get("awaiting_decision")
    known = set(by_name) | {
        item["remote"]
        for item in (pending if isinstance(pending, list) else [])
        if isinstance(item.get("remote"), str)
    }
    seen = set(observation.get("remotes", {}))
    found: list[dict[str, str]] = []

    extra = sorted(seen - known)
    found.append(
        _finding(
            "publication_declared",
            "FAIL",
            "поверхня публікації, якої ніхто не назвав: " + ", ".join(extra),
        )
        if extra
        else _finding("publication_declared", "PASS", f"{len(seen)} віддалених, усі названі")
    )

    ghosts = sorted(set(by_name) - seen)
    found.append(
        _finding(
            "publication_ghost", "FAIL", "запис про віддалений, якого немає: " + ", ".join(ghosts)
        )
        if ghosts
        else _finding("publication_ghost", "PASS", "жодного запису про неіснуючий віддалений")
    )

    for name in sorted(set(by_name) - set(ghosts)):
        found.extend(_publication_findings(name, by_name[name], observation, measured))
    return found


def _publication_findings(
    name: str,
    entry: dict[str, Any],
    observation: dict[str, Any],
    measured: dict[str, Any],
) -> list[dict[str, str]]:
    found = [_publication_role(name, entry)]
    url = observation["remotes"].get(name)
    if entry.get("url") and url != entry["url"]:
        found.append(
            _finding(
                f"publication_url:{name}",
                "FAIL",
                f"{name} вказує на {url}, а названо {entry['url']}",
            )
        )
        return found
    if entry.get("role") == MIRROR:
        found.append(
            _staleness(
                f"publication_staleness:{name}",
                name,
                measured.get("publication_days", {}).get(name),
                entry.get("max_days"),
            )
        )
    return found


def _publication_role(name: str, entry: dict[str, Any]) -> dict[str, str]:
    role = entry.get("role")
    if role == MIRROR:
        valid = isinstance(entry.get("tracks"), str) and isinstance(entry.get("max_days"), int)
    elif role == INTEGRATION_SOURCE:
        valid = entry.get("governed_by") == INTEGRATION_REGISTRY
    else:
        return _finding(f"publication_role:{name}", "FAIL", f"невідома роль: {role}")
    detail = f"роль {role} має виконуваний контракт" if valid else f"роль {role} без контракту"
    return _finding(f"publication_role:{name}", "PASS" if valid else "FAIL", detail)


def _check_worktrees(observation: dict[str, Any], registry: dict[str, Any]) -> dict[str, str]:
    """Ратчетити постійні дерева; ігнорувати задекларовані тимчасові префікси."""
    transient = tuple(registry.get("transient_worktree_prefixes") or ())
    persistent = [
        path
        for path in observation.get("worktrees", [])
        if not any(path.startswith(prefix) for prefix in transient)
    ]
    return _ratchet(
        "persistent_worktrees",
        "постійних дерев",
        len(persistent),
        registry.get("max_worktrees"),
    )


def _check_undecided(observation: dict[str, Any], registry: dict[str, Any]) -> dict[str, str]:
    """Поверхня публікації, чия РОЛЬ ще не вирішена.

    Це не недбалість і не діра в реєстрі: вона названа, виміряна й описана. Але поки
    рішення немає, вона лишається другою поверхнею публікації, якої не міряє жодна
    вісь, — і гейт мусить казати про це щоразу, а не один раз у листуванні.
    """
    pending = registry.get("awaiting_decision")
    pending = pending if isinstance(pending, list) else []
    live = sorted(
        item["remote"]
        for item in pending
        if isinstance(item.get("remote"), str) and item["remote"] in observation.get("remotes", {})
    )
    if live:
        return _finding(
            "publication_role_decided",
            "FAIL",
            "роль поверхні публікації не вирішена власником: " + ", ".join(live),
        )
    return _finding("publication_role_decided", "PASS", "кожна поверхня публікації має роль")


def assess(
    observation: dict[str, Any], measured: dict[str, Any], registry: dict[str, Any]
) -> list[dict[str, str]]:
    if not observation.get("branches"):
        return [_finding("canonical_state", "UNKNOWN", "репозиторій не прочитано")]
    findings = [
        _check_canonical_branch(observation, registry),
        _check_checked_out(observation, registry),
    ]
    findings.extend(_check_trunk(measured, registry))
    findings.extend(_check_publications(observation, measured, registry))
    findings.append(_check_undecided(observation, registry))
    findings.append(_check_worktrees(observation, registry))
    return findings


def verdict(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "UNKNOWN"
    verdicts = {finding["verdict"] for finding in findings}
    if "FAIL" in verdicts:
        return "FAIL"
    return "UNKNOWN" if "UNKNOWN" in verdicts else "PASS"


def measure(
    observation: dict[str, Any], registry: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    canonical = registry.get("canonical_branch")
    trunk = registry.get("trunk") or {}
    publications = registry.get("publications") or []
    behind_map: dict[str, int | None] = {}
    for item in publications:
        if item.get("role") != MIRROR:
            continue
        name, branch = item.get("remote"), item.get("tracks") or canonical
        if isinstance(name, str) and isinstance(branch, str):
            behind_map[name] = behind(f"{name}/{branch}", str(canonical), root=root)
    canonical_at = committed_at(str(canonical), root=root)
    days_map = {
        item["remote"]: days_between(
            committed_at(f"{item['remote']}/{item.get('tracks') or canonical}", root=root),
            canonical_at,
        )
        for item in publications
        if item.get("role") == MIRROR and isinstance(item.get("remote"), str)
    }
    return {
        "trunk_behind": behind(str(trunk.get("branch")), str(canonical), root=root),
        "trunk_days": days_between(committed_at(str(trunk.get("branch")), root=root), canonical_at),
        "trunk_is_ancestor": is_ancestor(str(trunk.get("branch")), str(canonical), root=root),
        "publication_behind": behind_map,
        "publication_days": days_map,
    }


# ------------------------------------------------------------------ негативні контролі


def selftest() -> int:
    mirror = {"role": MIRROR, "tracks": "main", "max_days": 2}
    observation: dict[str, Any] = {
        "head_branch": "work/converge-semantic",
        "branches": ["main", "work/converge-semantic"],
        "remotes": {"gitlab": "git@gitlab.com:x/y.git"},
        "worktrees": ["/canon", "/wt1"],
        "root": "/canon",
    }
    registry: dict[str, Any] = {
        "canonical_branch": "work/converge-semantic",
        "canonical_root": "/canon",
        "trunk": {"branch": "main", "max_days": 2},
        "publications": [{"remote": "gitlab", "url": "git@gitlab.com:x/y.git", **mirror}],
        "max_worktrees": 2,
        "transient_worktree_prefixes": ["/tmp/claude-"],
    }
    measured: dict[str, Any] = {
        "trunk_behind": 124,
        "trunk_days": 1.4,
        "trunk_is_ancestor": True,
        "publication_behind": {"gitlab": 105},
        "publication_days": {"gitlab": 1.4},
    }
    cases: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any], str]] = [
        ("усе названо й на стелі", observation, measured, registry, "PASS"),
        (
            "стовбур СТАРІШИЙ за поріг",
            observation,
            {**measured, "trunk_days": 2.1},
            registry,
            "FAIL",
        ),
        (
            "нові коміти в канон НЕ роблять стовбур червоним",
            observation,
            {**measured, "trunk_behind": 100000},
            registry,
            "PASS",
        ),
        (
            "стовбур РОЗІЙШОВСЯ — це не відставання",
            observation,
            {**measured, "trunk_is_ancestor": False},
            registry,
            "FAIL",
        ),
        (
            "віддалений, якого ніхто не назвав",
            {
                **observation,
                "remotes": {**observation["remotes"], "origin": "git@github.com:a/b.git"},
            },
            measured,
            registry,
            "FAIL",
        ),
        (
            "запис про віддалений, якого немає",
            {**observation, "remotes": {}},
            measured,
            registry,
            "FAIL",
        ),
        (
            "віддалений вказує НЕ туди, куди названо",
            {**observation, "remotes": {"gitlab": "git@gitlab.com:чуже/repo.git"}},
            measured,
            registry,
            "FAIL",
        ),
        (
            "опубліковане СТАРІШЕ за поріг",
            observation,
            {**measured, "publication_days": {"gitlab": 9.0}},
            registry,
            "FAIL",
        ),
        (
            "канонічний корінь стоїть не на тій гілці",
            {**observation, "head_branch": "main"},
            measured,
            registry,
            "FAIL",
        ),
        (
            "це не канонічний корінь — UNKNOWN, не FAIL",
            {**observation, "root": "/worktree", "head_branch": "інша"},
            measured,
            registry,
            "UNKNOWN",
        ),
        (
            "названої гілки в репозиторії немає",
            {**observation, "branches": ["main"]},
            measured,
            registry,
            "FAIL",
        ),
        (
            "worktree більше за стелю",
            {**observation, "worktrees": ["/canon", "/wt1", "/wt2"]},
            measured,
            registry,
            "FAIL",
        ),
        (
            "вік не виміряно — UNKNOWN, не PASS",
            observation,
            {**measured, "trunk_days": None},
            registry,
            "UNKNOWN",
        ),
        ("порожній репозиторій — UNKNOWN", {"branches": []}, measured, registry, "UNKNOWN"),
        (
            "віддалений, чия роль ще не вирішена, — окрема відмова",
            {
                **observation,
                "remotes": {**observation["remotes"], "origin": "git@github.com:a/b.git"},
            },
            measured,
            {**registry, "awaiting_decision": [{"remote": "origin", "reason": "x" * 20}]},
            "FAIL",
        ),
        (
            "тимчасові дерева не рахуються у стелю постійних",
            {**observation, "worktrees": ["/canon", "/wt1", "/tmp/claude-1/x", "/tmp/claude-2/y"]},
            measured,
            registry,
            "PASS",
        ),
    ]
    bad = 0
    for name, obs, mea, reg, want in cases:
        got = verdict(assess(obs, mea, reg))
        ok = got == want
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")

    improved = _ratchet("t", "main", 3, 124)
    ok = improved["verdict"] == "PASS" and "знизити до 3" in improved["detail"]
    bad += not ok
    print(
        f"  [{'ok' if ok else 'ЗБІЙ'}] поліпшення вимагає знизити стелю: {improved['detail'][:60]}"
    )

    total = len(cases) + 1
    print(f"\nнегативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/canonical-state.json")
    parser.add_argument("--fetch", action="store_true", help="оновити віддалені перед виміром")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    try:
        registry = json.loads(arguments.registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"schema": SCHEMA, "status": "UNKNOWN", "reason": "реєстр не прочитано"}))
        return 2

    observation = observe(arguments.root, fetch=arguments.fetch)
    measured = measure(observation, registry, root=arguments.root)
    findings = assess(observation, measured, registry)
    overall = verdict(findings)
    report = {
        "schema": SCHEMA,
        "status": overall,
        "observed": observation,
        "measured": measured,
        "findings": findings,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for item in findings:
        print(f"  [{item['verdict']}] {item['check']}: {item['detail']}")
    print(f"\ncanonical-state: {overall}  → {arguments.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
