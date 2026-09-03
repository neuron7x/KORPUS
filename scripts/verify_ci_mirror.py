#!/usr/bin/env python3
"""Дзеркало лану: CI виконує ТЕ САМЕ, що локальний `make validate` / `make check`, чи лише схоже.

Зелений локальний гейт не є моделлю зеленої CI. Перелік цілей у Makefile і перелік
команд у `.gitlab-ci.yml` — два оголошення одного лану, і вони розходяться мовчки
саме тоді, коли хтось додає перевірку в одне місце. Виміряно 03.09.2026: замінник
SI-7 моделі впевненості читав `var/ci-mirror.json`, якого не виробляв ніхто, — тобто
«дзеркало звірене» було полем без виробника.

## Що вимірюється

Кожен скрипт, який лан запускає локально (транзитивно від коренів `validate` і
`check`), мусить запускатись у CI ТІЄЮ САМОЮ командою. Тотожність команди — та сама,
що в `verify_gate_closure.normalise_invocation`: ім'я скрипта плюс усі аргументи,
крім названих несемантичними. `--selftest` і повний прогін — різні команди; CI, що
ганяє лише самоперевірку, гейт не виконує.

Джерело істини — сам `.gitlab-ci.yml`, прочитаний як YAML. Джоб рахується частиною
дзеркала лише коли він виконується на КОЖНОМУ конвеєрі і його відмова валить конвеєр:
`rules:` / `only:` / `when: manual` / `allow_failure: true` виводять джоб із дзеркала.
Червоний джоб, що не валить конвеєр, — не гейт, а повідомлення.

## Що НЕ вимагається

`check-deployment` міряє розгортання, якого в раннері немає; `check-nightly` копіює
дерево або переганяє повний набір і за побудовою дорогий. Обидва звітуються числом
`local_only`, не вимогою.

Прийняті розбіжності живуть у `config/operations/ci-mirror.json` з причиною й датою.
Запис про команду, яку CI вже виконує, — МЕРТВИЙ виняток; про команду, якої лан не
має, — ПРИМАРНИЙ. Обидва — відмова, як у `verify_gate_closure`.

    verify_ci_mirror.py [--out ФАЙЛ]
    verify_ci_mirror.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_gate_closure import invocations, parse_graph, reachable

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
PIPELINE = ROOT / ".gitlab-ci.yml"
REGISTRY = ROOT / "config/operations/ci-mirror.json"
SCHEMA = "korpus.ci-mirror.v1"

#: Лани, які CI мусить віддзеркалювати. `validate` — те, про що кажуть «зелений»;
#: `check` — те, що людина запускає перед злиттям.
MIRRORED_ROOTS: tuple[str, ...] = ("validate", "check")
#: Лани, які за побудовою живуть лише локально. Звітуються числом.
LOCAL_ONLY_ROOTS: tuple[str, ...] = ("check-deployment", "check-nightly")

#: `make ціль` у рядку CI: джоб може запускати лан цілком, і тоді він виконує все, що лан.
_MAKE_CALL = re.compile(
    r"(?:^|[;&|]\s*|\s)make\s+(?:-C\s+\S+\s+)?([A-Za-z0-9._-]+(?:\s+[A-Za-z0-9._-]+)*)"
)
_MAKE_TARGET = re.compile(r"^[A-Za-z0-9._-]+$")

#: Повний прогін покриття самоперевірками: він сам запускає кожен `--selftest`.
SELFTEST_COVERAGE = "scripts/verify_selftest_coverage.py"

#: Поля, за якими джоб перестає бути гейтом кожного конвеєра.
_CONDITIONAL_FIELDS = ("rules", "only", "except")


# ------------------------------------------------------------------- розбір (без I/O)


def lane_invocations(makefile: str, roots: tuple[str, ...]) -> dict[str, set[str]]:
    """Тотожність команди → цілі лану, які її запускають (транзитивно від коренів)."""
    edges, _declared, scripts = parse_graph(makefile)
    found: dict[str, set[str]] = {}
    for target in reachable(edges, roots):
        for identity in scripts.get(target, ()):
            found.setdefault(identity, set()).add(target)
    return found


def _job_is_gate(job: dict[str, Any]) -> tuple[bool, str]:
    """Чи джоб виконується на кожному конвеєрі і чи його відмова валить конвеєр."""
    for field in _CONDITIONAL_FIELDS:
        if job.get(field):
            return False, f"умовний ({field})"
    if job.get("when") in ("manual", "never", "delayed"):
        return False, f"when: {job['when']}"
    if job.get("allow_failure") is True:
        return False, "allow_failure: true — червоний не валить конвеєр"
    return True, ""


def _job_lines(name: str, job: dict[str, Any], pipeline: dict[str, Any]) -> list[str]:
    """Усі рядки, які джоб виконує: успадковані через `extends` + власні."""
    merged: dict[str, Any] = {}
    parents = job.get("extends") or []
    for parent in [parents] if isinstance(parents, str) else parents:
        base = pipeline.get(str(parent))
        if isinstance(base, dict):
            merged.update(base)
    merged.update(job)
    lines: list[str] = []
    for key in ("before_script", "script", "after_script"):
        for entry in merged.get(key) or []:
            if isinstance(entry, str):
                lines.extend(entry.splitlines())
            elif isinstance(entry, list):
                lines.extend(str(item) for item in entry)
    return lines


def _line_identities(
    line: str, edges: dict[str, set[str]], scripts: dict[str, set[str]]
) -> set[str]:
    """Тотожності, які виконує один рядок CI: прямі запуски плюс усе, що тягне `make ціль`."""
    found = set(invocations(line))
    for call in _MAKE_CALL.finditer(line):
        targets = tuple(t for t in call.group(1).split() if _MAKE_TARGET.match(t))
        for target in reachable(edges, targets):
            found.update(scripts.get(target, ()))
    return found


def pipeline_invocations(
    pipeline: dict[str, Any], makefile: str
) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Тотожність команди → джоби-гейти, що її виконують; плюс джоби поза дзеркалом.

    `make ціль` у рядку CI розгортається через граф Makefile: джоб, що кличе лан
    цілком, виконує все, що лан. Джоб, у якого `make` кличе неіснуючу ціль, не
    виконує нічого — і саме так це й рахується.
    """
    edges, _declared, scripts = parse_graph(makefile)
    found: dict[str, set[str]] = {}
    excluded: dict[str, str] = {}
    for name, job in pipeline.items():
        if not isinstance(job, dict) or str(name).startswith("."):
            continue
        if "script" not in job and "extends" not in job:
            continue
        gate, why = _job_is_gate(job)
        if not gate:
            excluded[str(name)] = why
            continue
        for line in _job_lines(str(name), job, pipeline):
            for identity in _line_identities(line, edges, scripts):
                found.setdefault(identity, set()).add(str(name))
    return found, excluded


def _finding(check: str, items: list[str], bad: str, good: str) -> dict[str, Any]:
    return {
        "check": check,
        "verdict": "FAIL" if items else "PASS",
        "detail": bad if items else good,
        "items": items,
    }


def assess(
    lane: dict[str, set[str]],
    ci: dict[str, set[str]],
    accepted: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Чотири способи збрехати, кожен — окрема знахідка: відсутнє, мертве, примарне, без причини."""
    registered = {str(item.get("invocation")) for item in accepted}
    # `X --selftest` у лані виконується в CI ТРАНЗИТИВНО, якщо CI ганяє повний
    # `verify_selftest_coverage.py`: той сам знаходить кожен скрипт із оголошеним прапорцем
    # і запускає його (див. `verify_gate_closure.selftest_only`). Без нього самоперевірка
    # в CI не бігає, і тоді це справжня діра, а не оформлення.
    via_coverage = SELFTEST_COVERAGE in ci
    covered = {
        identity
        for identity in lane
        if via_coverage and identity.endswith(" --selftest") and identity.startswith("scripts/")
    }
    missing = sorted(i for i in lane if i not in ci and i not in registered and i not in covered)
    dead = sorted(identity for identity in registered if identity in ci)
    ghost = sorted(identity for identity in registered if identity not in lane)
    unreasoned = sorted(
        str(item.get("invocation"))
        for item in accepted
        if len(str(item.get("reason") or "").strip()) < 40 or not item.get("on")
    )
    return [
        _finding(
            "missing_in_ci",
            missing,
            f"{len(missing)} команд лану CI не виконує: {missing[:6]}",
            f"кожна з {len(lane)} команд лану виконується в CI або прийнята з причиною",
        ),
        _finding(
            "dead_exemption",
            dead,
            f"реєстр виправдовує команди, які CI вже виконує: {dead}",
            f"{len(registered)} записів реєстру всі ще потрібні",
        ),
        _finding(
            "ghost_exemption",
            ghost,
            f"реєстр виправдовує команди, яких лан не має: {ghost}",
            "жодного запису про команду поза ланом",
        ),
        _finding(
            "unreasoned_exemption",
            unreasoned,
            f"записи без причини або дати: {unreasoned}",
            "кожен запис несе причину й дату",
        ),
    ]


def verdict(findings: list[dict[str, Any]]) -> str:
    return "FAIL" if any(item["verdict"] != "PASS" for item in findings) else "PASS"


# ------------------------------------------------------------------ негативні контролі

_CLEAN_MAKE = "validate: a-gate\n\na-gate:\n\t$(PY) scripts/a.py --strict\n\ncheck: validate\n"
_CLEAN_CI = {"j": {"stage": "s", "script": ["PYTHONPATH=x python scripts/a.py --strict"]}}
_CASES: list[tuple[str, str, dict[str, Any], list[dict[str, Any]], str]] = [
    ("чисте дзеркало — PASS", _CLEAN_MAKE, _CLEAN_CI, [], "PASS"),
    ("CI не виконує команду лану", _CLEAN_MAKE, {"j": {"script": ["echo"]}}, [], "FAIL"),
    (
        "CI ганяє лише --selftest — ІНША команда",
        _CLEAN_MAKE,
        {"j": {"script": ["python scripts/a.py --selftest"]}},
        [],
        "FAIL",
    ),
    (
        "той самий скрипт без семантичного прапорця — інша команда",
        _CLEAN_MAKE,
        {"j": {"script": ["python scripts/a.py"]}},
        [],
        "FAIL",
    ),
    (
        "allow_failure: true — джоб не гейт",
        _CLEAN_MAKE,
        {"j": {"script": ["python scripts/a.py --strict"], "allow_failure": True}},
        [],
        "FAIL",
    ),
    (
        "rules: — джоб умовний, не дзеркало",
        _CLEAN_MAKE,
        {"j": {"script": ["python scripts/a.py --strict"], "rules": [{"if": "$X"}]}},
        [],
        "FAIL",
    ),
    (
        "`make validate` у CI розгортається через граф",
        _CLEAN_MAKE,
        {"j": {"script": ["make validate"]}},
        [],
        "PASS",
    ),
    (
        "команда успадкована через extends",
        _CLEAN_MAKE,
        {".base": {"script": ["python scripts/a.py --strict"]}, "j": {"extends": ".base"}},
        [],
        "PASS",
    ),
    (
        "прийнято з причиною — PASS",
        _CLEAN_MAKE,
        {"j": {"script": ["echo"]}},
        [{"invocation": "scripts/a.py --strict", "on": "2026-09-03", "reason": "x" * 40}],
        "PASS",
    ),
    (
        "мертвий виняток: CI вже виконує",
        _CLEAN_MAKE,
        _CLEAN_CI,
        [{"invocation": "scripts/a.py --strict", "on": "2026-09-03", "reason": "x" * 40}],
        "FAIL",
    ),
    (
        "примарний виняток: лан такого не має",
        _CLEAN_MAKE,
        _CLEAN_CI,
        [{"invocation": "scripts/zzz.py", "on": "2026-09-03", "reason": "x" * 40}],
        "FAIL",
    ),
    (
        "виняток без причини",
        _CLEAN_MAKE,
        {"j": {"script": ["echo"]}},
        [{"invocation": "scripts/a.py --strict", "on": "2026-09-03", "reason": "коротко"}],
        "FAIL",
    ),
    (
        "`--selftest` покритий транзитивно через verify_selftest_coverage.py у CI",
        "validate: a-gate\n\na-gate:\n\t$(PY) scripts/a.py --selftest\n\t$(PY) scripts/a.py --strict\n\ncheck: validate\n",
        {
            "j": {
                "script": [
                    "python scripts/a.py --strict",
                    "python scripts/verify_selftest_coverage.py",
                ]
            }
        },
        [],
        "PASS",
    ),
    (
        "`--selftest` без selftest-coverage у CI — справжня діра",
        "validate: a-gate\n\na-gate:\n\t$(PY) scripts/a.py --selftest\n\t$(PY) scripts/a.py --strict\n\ncheck: validate\n",
        {"j": {"script": ["python scripts/a.py --strict"]}},
        [],
        "FAIL",
    ),
    (
        "команда поза ланом (check-deployment) не вимагається",
        "validate: a-gate\n\na-gate:\n\t$(PY) scripts/a.py --strict\n\ncheck: validate\n\n"
        "check-deployment: live\n\nlive:\n\t$(PY) scripts/live.py\n",
        _CLEAN_CI,
        [],
        "PASS",
    ),
]


def selftest() -> int:
    """Кожен спосіб збрехати мусить червоніти ОКРЕМО, а чисте дзеркало — зеленіти."""
    bad = 0
    for name, makefile, pipeline, accepted, expected in _CASES:
        lane = lane_invocations(makefile, MIRRORED_ROOTS)
        ci, _excluded = pipeline_invocations(pipeline, makefile)
        got = verdict(assess(lane, ci, accepted))
        ok = got == expected
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")
    print(f"\nнегативний контроль: {len(_CASES) - bad}/{len(_CASES)}")
    return 1 if bad else 0


# ----------------------------------------------------------------------------- I/O


def _head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    ).stdout.strip()


def measure(root: Path) -> dict[str, Any]:
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    pipeline = yaml.safe_load((root / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    if not isinstance(pipeline, dict):
        raise SystemExit("`.gitlab-ci.yml` не є мапою джобів")
    registry = json.loads((root / "config/operations/ci-mirror.json").read_text(encoding="utf-8"))
    accepted = list(registry.get("accepted") or [])
    lane = lane_invocations(makefile, MIRRORED_ROOTS)
    ci, excluded = pipeline_invocations(pipeline, makefile)
    local_only = {name: len(lane_invocations(makefile, (name,))) for name in LOCAL_ONLY_ROOTS}
    findings = assess(lane, ci, accepted)
    mirrored = sorted(identity for identity in lane if identity in ci)
    return {
        "schema": SCHEMA,
        "commit": _head(root),
        "ran_at": datetime.now(UTC).isoformat(),
        "roots": list(MIRRORED_ROOTS),
        "lane_invocations": len(lane),
        "mirrored": len(mirrored),
        "accepted": len(accepted),
        "jobs_outside_mirror": excluded,
        "local_only_lanes": local_only,
        "findings": findings,
        "status": verdict(findings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "var/ci-mirror.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    report = measure(arguments.root)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for item in report["findings"]:
        print(f"  [{item['verdict']}] {item['check']}: {item['detail']}")
    print(
        f"\nci-mirror: {report['status']}  ({report['mirrored']}/{report['lane_invocations']} "
        f"команд лану в CI, {report['accepted']} прийнято)  → {arguments.out}"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
