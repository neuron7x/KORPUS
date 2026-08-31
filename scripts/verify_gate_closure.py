#!/usr/bin/env python3
"""Що саме означає «дерево зелене».

Виміряно 31.08.2026 на цьому Makefile: **193 цілі, з них 39 досяжні з `check`**;
перевірочних цілей — 44, і **31 із них недосяжна ні з `check`, ні з `validate`**.
Серед недосяжних: `audit-verify`, `span-hygiene`, `runtime-corpus-audit`,
`gate-liveness`, `determinism-gate`, `coverage-ratchet`, `provenance-verify`,
`verify-clean-clone`, `mutation-probe`. Три з них того ж дня перевірили руками —
усі три червоні.

Тобто речення «`make check` зелений» було твердженням про підмножину, якої ніхто
не перелічив, і розмір підмножини ніде не був записаний. Це не борг окремих
цілей — це те, що САМЕ СЛОВО «зелено» не мало означення.

Гейт дає йому означення й робить його виконуваним:

    кожна перевірочна ціль АБО досяжна з `check`,
    АБО названа в реєстрі — з причиною і датою.

Три речі, яких він НЕ пробачає, і кожна з них — окремий спосіб збрехати:

  ВІДСУТНІЙ ВИНЯТОК   нова перевірочна ціль, яку ніхто не підключив і ніхто не
                      назвав. Саме так з'явилась 31 попередня: жодна не була
                      рішенням, усі були тишею.
  МЕРТВИЙ ВИНЯТОК     запис про ціль, яка НАСПРАВДІ досяжна. Він каже читачеві,
                      що діри немає там, де її вже немає, — і привчає не вірити
                      реєстру. Мертвий виняток бреше не менше за відсутній.
  ПРИМАРНИЙ ВИНЯТОК   запис про ціль, якої в Makefile більше немає. Реєстр, що
                      накопичує привидів, з часом описує інший файл.

⚠ Пастка в самому парсері, і вона тієї ж форми, що й усе інше сьогодні. Ребро
графа — це не лише залежність у заголовку правила: `evidence-refresh` викликає
`$(MAKE) dependency-locks` у РЕЦЕПТІ. Парсер, що читає лише заголовки, оголосив
би `dependency-locks` недосяжною й вимагав би для неї виправдання, якого не
треба. Тобто перевірка досяжності, зроблена наївно, сама стає джерелом хибних
дір. Рецепти читаються (`_recipe_edges`), і на це є негативний контроль.

    verify_gate_closure.py
    verify_gate_closure.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
REGISTRY = ROOT / "config/operations/gate-closure.json"
SCHEMA = "korpus.gate-closure.v1"

#: Корені, з яких рахується досяжність. `check` — те, що людина запускає перед
#: злиттям; `validate` входить у нього, але названий окремо, бо саме його
#: запускають частіше й саме про нього кажуть «зелений».
ROOTS = ("check", "validate")

#: Що вважається ПЕРЕВІРОЧНОЮ ціллю. Правило за іменем, і воно свідомо широке:
#: хибно віднесена сюди неперевірочна ціль коштує одного запису в реєстрі з
#: причиною, а пропущена перевірочна коштує мовчазної діри. Ціна асиметрична,
#: тому й поріг асиметричний.
VERIFICATION = re.compile(
    r"verify|check|audit|gate|lint|hygiene|ratchet|integrity|liveness|validate|probe"
)

#: Заголовок правила. `:=` виключено — це присвоєння змінної, не ціль.
_RULE = re.compile(
    r"^(?P<names>[A-Za-z0-9._%/-]+(?:\s+[A-Za-z0-9._%/-]+)*)\s*:(?!=)\s*(?P<deps>.*)$"
)
_RECURSIVE_MAKE = re.compile(r"\$\(MAKE\)\s+([A-Za-z0-9._-]+)")
#: Скрипт, який рецепт справді запускає. Досяжність ЦІЛІ — не те саме, що виконання
#: перевірки: `validate` кличе `scripts/validate_infrastructure.py` і
#: `scripts/validate_kubernetes.py` прямо в рецепті, а цілі `infra-validate` і
#: `kubernetes-validate` роблять рівно те саме. Перевірка, що дивиться лише на граф
#: цілей, оголосила б їх дірами — і зажадала б виправдання для того, що вже
#: виконується. Тому одиниця обліку тут — СКРИПТ, а ціль лише його носій.
_SCRIPT = re.compile(r"(scripts/[A-Za-z0-9_./-]+\.(?:py|sh))")


# ------------------------------------------------------------------- граф (без I/O)


def parse_graph(text: str) -> tuple[dict[str, set[str]], list[str], dict[str, set[str]]]:
    """Ціль → її передумови, ребра з рецептів, і скрипти, які ціль запускає.

    Повертає (ребра, оголошені цілі, скрипти на ціль). Порядок оголошення
    зберігається, бо звіт, чий вміст залежить від планування, не можна порівняти
    між прогонами.
    """
    edges: dict[str, set[str]] = {}
    scripts: dict[str, set[str]] = {}
    declared: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("\t"):
            if current is not None:
                for match in _RECURSIVE_MAKE.finditer(line):
                    edges.setdefault(current, set()).add(match.group(1))
                for match in _SCRIPT.finditer(line):
                    scripts.setdefault(current, set()).add(match.group(1))
            continue
        matched = _RULE.match(line)
        if matched is None:
            continue
        names = matched.group("names").split()
        if names[0] == ".PHONY":
            current = None
            continue
        # Змінні в передумовах (`$(if ...)`) не є цілями і не можуть бути ребрами.
        dependencies = {d for d in matched.group("deps").split() if not d.startswith("$")}
        for name in names:
            if name not in edges:
                declared.append(name)
            edges.setdefault(name, set()).update(dependencies)
        current = names[0]
    return edges, declared, scripts


def reachable(edges: dict[str, set[str]], roots: tuple[str, ...]) -> set[str]:
    """Транзитивне замикання від коренів. Цикли не зациклюють: `seen` росте."""
    seen: set[str] = set()
    queue = deque(root for root in roots if root in edges)
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(edges.get(node, ()))
    return seen


def verification_targets(declared: list[str]) -> list[str]:
    return [name for name in declared if VERIFICATION.search(name)]


# ---------------------------------------------------------------- судження (без I/O)


def _finding(check: str, verdict: str, detail: str) -> dict[str, str]:
    return {"check": check, "verdict": verdict, "detail": detail}


def _named(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = registry.get("accepted") if isinstance(registry, dict) else None
    if not isinstance(entries, list):
        return {}
    return {
        entry["target"]: entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("target"), str)
    }


def enforced(
    edges: dict[str, set[str]],
    scripts: dict[str, set[str]],
    roots: tuple[str, ...] = ROOTS,
) -> set[str]:
    """Цілі, чия робота СПРАВДІ виконується під `check`.

    Ціль виконується, якщо вона досяжна графом АБО якщо кожен скрипт, який вона
    запускає, запускає ще й хтось досяжний. Друга умова — не поблажка: `validate`
    виконує ті самі два валідатори інфраструктури, що й `infra-validate`, і
    вимагати для них запису в реєстрі означало б назвати дірою те, що закрите.
    """
    covered = reachable(edges, roots)
    running: set[str] = set()
    for target in covered:
        running |= scripts.get(target, set())
    result = set(covered)
    for target, used in scripts.items():
        if used and used <= running:
            result.add(target)
    return result


def assess(
    edges: dict[str, set[str]],
    declared: list[str],
    registry: dict[str, Any],
    scripts: dict[str, set[str]] | None = None,
) -> list[dict[str, str]]:
    """Вирок над графом і реєстром. UNKNOWN — окремо і НЕ PASS."""
    if not declared:
        return [_finding("gate_closure", "UNKNOWN", "Makefile не розібрано: цілей нуль")]
    if not any(root in edges for root in ROOTS):
        return [
            _finding("gate_closure", "UNKNOWN", "жодного кореня " + ", ".join(ROOTS) + " немає")
        ]

    covered = enforced(edges, scripts or {})
    named = _named(registry)
    targets = verification_targets(declared)
    findings: list[dict[str, str]] = []

    missing = sorted(t for t in targets if t not in covered and t not in named)
    findings.append(
        _finding(
            "unregistered_gap",
            "FAIL",
            "перевірочна ціль ні під гейтом, ні в реєстрі: " + ", ".join(missing),
        )
        if missing
        else _finding("unregistered_gap", "PASS", f"{len(targets)} перевірочних цілей враховано")
    )

    dead = sorted(t for t in named if t in covered)
    findings.append(
        _finding(
            "dead_exemption", "FAIL", "виняток для цілі, яка вже під гейтом: " + ", ".join(dead)
        )
        if dead
        else _finding("dead_exemption", "PASS", f"{len(named)} записів реєстру всі ще потрібні")
    )

    ghosts = sorted(t for t in named if t not in edges)
    findings.append(
        _finding(
            "ghost_exemption",
            "FAIL",
            "виняток для цілі, якої немає в Makefile: " + ", ".join(ghosts),
        )
        if ghosts
        else _finding("ghost_exemption", "PASS", "жодного запису про неіснуючу ціль")
    )

    unreasoned = sorted(
        target
        for target, entry in named.items()
        if not isinstance(entry.get("reason"), str) or len(entry["reason"].strip()) < 20
    )
    findings.append(
        _finding(
            "unreasoned_exemption",
            "FAIL",
            "запис без причини (≥20 символів): " + ", ".join(unreasoned),
        )
        if unreasoned
        else _finding("unreasoned_exemption", "PASS", "кожен запис несе причину")
    )

    return findings


def verdict(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "UNKNOWN"
    verdicts = {finding["verdict"] for finding in findings}
    if "FAIL" in verdicts:
        return "FAIL"
    return "UNKNOWN" if "UNKNOWN" in verdicts else "PASS"


# ------------------------------------------------------------------ негативні контролі


def selftest() -> int:
    """Кожен спосіб збрехати мусить червоніти ОКРЕМО, і чистий граф — зеленіти."""
    clean_make = (
        "check: validate span-hygiene\n\tone\n"
        "validate: audit-verify\n\ttwo\n"
        "span-hygiene:\n\tthree\n"
        "audit-verify:\n\tfour\n"
    )
    recipe_make = "check:\n\t$(MAKE) span-hygiene\nspan-hygiene:\n\techo\n"
    orphan_make = clean_make + "gate-liveness:\n\tfive\n"

    def run(makefile: str, registry: dict[str, Any]) -> str:
        edges, declared, scripts = parse_graph(makefile)
        return verdict(assess(edges, declared, registry, scripts))

    reason = "причина, довша за двадцять символів"
    cases: list[tuple[str, str, dict[str, Any], str]] = [
        ("усе під гейтом", clean_make, {"accepted": []}, "PASS"),
        (
            "ребро з РЕЦЕПТА рахується як досяжність",
            recipe_make,
            {"accepted": []},
            "PASS",
        ),
        ("нова ціль, яку ніхто не підключив і не назвав", orphan_make, {"accepted": []}, "FAIL"),
        (
            "названа — і тоді дозволено",
            orphan_make,
            {"accepted": [{"target": "gate-liveness", "reason": reason, "on": "2026-08-31"}]},
            "PASS",
        ),
        (
            "мертвий виняток: ціль уже під гейтом",
            clean_make,
            {"accepted": [{"target": "span-hygiene", "reason": reason, "on": "2026-08-31"}]},
            "FAIL",
        ),
        (
            "примарний виняток: цілі в Makefile немає",
            clean_make,
            {"accepted": [{"target": "no-such-target", "reason": reason, "on": "2026-08-31"}]},
            "FAIL",
        ),
        (
            "виняток без причини",
            orphan_make,
            {"accepted": [{"target": "gate-liveness", "reason": "бо", "on": "2026-08-31"}]},
            "FAIL",
        ),
        ("порожній Makefile — UNKNOWN, не PASS", "", {"accepted": []}, "UNKNOWN"),
        (
            "є цілі, але немає жодного кореня — UNKNOWN, не PASS",
            "span-hygiene:\n\tone\n",
            {"accepted": []},
            "UNKNOWN",
        ),
        ("реєстр не список — читається як порожній, не як дозвіл", orphan_make, {}, "FAIL"),
    ]

    bad = 0
    for name, makefile, registry, expected in cases:
        got = run(makefile, registry)
        ok = got == expected
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")
    print(f"\nнегативний контроль: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makefile", type=Path, default=MAKEFILE)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/gate-closure.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    try:
        text = arguments.makefile.read_text(encoding="utf-8")
    except OSError as error:
        print(json.dumps({"schema": SCHEMA, "status": "UNKNOWN", "reason": str(error)}))
        return 2
    try:
        registry = json.loads(arguments.registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        registry = {}

    edges, declared, scripts = parse_graph(text)
    findings = assess(edges, declared, registry, scripts)
    overall = verdict(findings)
    covered = enforced(edges, scripts)
    targets = verification_targets(declared)
    report = {
        "schema": SCHEMA,
        "status": overall,
        "targets_declared": len(declared),
        "targets_reachable_from_check": len(covered & set(declared)),
        "verification_targets": len(targets),
        "accepted_gaps": len(_named(registry)),
        "findings": findings,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for finding in findings:
        print(f"  [{finding['verdict']}] {finding['check']}: {finding['detail']}")
    print(f"\ngate-closure: {overall}  → {arguments.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
