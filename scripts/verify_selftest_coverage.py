#!/usr/bin/env python3
"""Негативний контроль, який не бігає, негативним контролем не є.

Виміряно 01.09.2026: 37 скриптів у `scripts/` оголошують `--selftest`, і **22 з них не
виконуються ЖОДНОЮ дорогою**. Серед них ті, чиї самоперевірки якраз і доводять, що
інструмент здатен ПОЧЕРВОНІТИ: `validate_span_hygiene` (15/15), `verify_public_surface`
(13/13), `recheck_blocked_sources` (24/24), `threshold_distance` (14/14),
`capture_source_evidence` (41/41). Тобто те, що робить гейт гейтом, саме ніде не
перевірялось — і якби воно зламалось, зелений колір не змінився б.

Разом вони йдуть 2,7 секунди. Ціна мовчання була нульова, і саме тому ніхто не помітив.

Форма ліків важлива. Можна було виписати 22 рядки в Makefile і поставити ще один гейт,
який стежить, щоб перелік не відставав — але тоді перелік став би ДРУГИМ оголошенням
того самого факту, і розійшовся б мовчки, як уже розходились юніт зі скриптом
розгортання. Тому тут немає переліку: гейт САМ знаходить кожен скрипт, що оголошує
`--selftest`, і САМ його запускає. «Самоперевірка, яку забули підключити» перестає бути
станом, у який можна потрапити.

    verify_selftest_coverage.py
    verify_selftest_coverage.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "korpus.selftest-coverage.v1"
TIMEOUT = 180

#: Оголошення прапорця, а не згадка. Форм ДВІ, і доти гейт знав одну: шість скриптів
#: розбирають `sys.argv` напряму, і гейт їх не бачив, звітуючи «жодної пропущеної» —
#: твердження про власний регекс, не про дерево. Вимір і межа:
#: `test_selftest_coverage.test_discovery_finds_the_declarations_not_the_mentions`.
DECLARES = re.compile(
    r"""add_argument\(\s*["']--selftest["']"""
    r"""|["']--selftest["']\s+in\s+sys\.argv"""
)

#: Згадують прапорець, не оголошуючи. Іменовані навмисно: без переліку ширший регекс
#: лише змінив би одну сліпу зону на іншу, а третя форма зникла б так само мовчки.
MENTIONS_WITHOUT_DECLARING = {
    # Константа, якою цей скрипт шукає прапорець У ЧУЖИХ модулях, не у власному.
    "scripts/check_module_budget.py",
    # Рядки-мутанти: літерал усередині мутацій, які скрипт СІЄ в чужий код.
    "scripts/run_mutation_tests.py",
}

#: Будь-яка згадка літерала — знаменник, проти якого міряється повнота розбору.
MENTIONS = re.compile(r"""["']--selftest["']""")


def declaring(root: Path = ROOT) -> list[str]:
    """Скрипти, які САМІ оголошують `--selftest`. Порядок сталий."""
    found: list[str] = []
    for path in sorted((root / "scripts").glob("*.py")):
        if DECLARES.search(path.read_text(encoding="utf-8", errors="ignore")):
            found.append(f"scripts/{path.name}")
    return found


def undeclared_mentions(root: Path = ROOT) -> list[str]:
    """Межа сліпої зони: згадка, форму якої гейт не розібрав і яка не названа.

    Без неї «нуль пропущених» нерозрізненний із «я не дивився».
    """
    declared = set(declaring(root))
    unseen: list[str] = []
    for path in sorted((root / "scripts").glob("*.py")):
        name = f"scripts/{path.name}"
        if name in declared or name in MENTIONS_WITHOUT_DECLARING:
            continue
        if MENTIONS.search(path.read_text(encoding="utf-8", errors="ignore")):
            unseen.append(name)
    return unseen


#: Єдиний скрипт поза власною гарантією: запустити свій `--selftest` усередині себе
#: означало б нескінченну рекурсію.
SELF = "scripts/verify_selftest_coverage.py"


def _blind_spot_is_bounded(root: Path = ROOT) -> dict[str, Any]:
    """Чи не з'явилась форма оголошення, якої цей гейт не розбирає."""
    unseen = undeclared_mentions(root)
    return {
        "check": "no_unparsed_declaration_form",
        "verdict": "PASS" if not unseen else "FAIL",
        "detail": (
            "кожна згадка `--selftest` або розібрана як оголошення, або названа винятком"
            if not unseen
            else f"форма оголошення не розібрана, і ці скрипти не бігають ніде: {unseen}"
        ),
    }


def _self_is_covered(root: Path = ROOT) -> dict[str, Any]:
    """Хто ж перевіряє перевіряльника.

    Виняток для себе законний, але він лишає гарантію неповною рівно на один скрипт, і
    покривається вона ОДНИМ рядком рецепта `selftest-coverage`. Прибери той рядок — і
    `--selftest` цього гейта не бігатиме НІДЕ, мовчки, а звіт і далі казатиме «жодної
    пропущеної»: виключений зі знаменника не з'явиться серед пропущених. Тому наявність
    того рядка — теж перевірка, а не домовленість.
    """
    makefile = (root / "Makefile").read_text(encoding="utf-8", errors="ignore")
    invoked = f"{SELF} --selftest" in makefile
    return {
        "check": "the_checker_itself_is_checked",
        "verdict": "PASS" if invoked else "FAIL",
        "detail": (
            f"рецепт запускає `{SELF} --selftest`"
            if invoked
            else f"НІХТО не запускає `{SELF} --selftest`: єдиний виняток лишився без покриття"
        ),
    }


def run_one(script: str, root: Path = ROOT, python: str = sys.executable) -> dict[str, Any]:
    """Один запуск. Таймаут — теж відмова: самоперевірка, що висить, нічого не доводить."""
    try:
        completed = subprocess.run(
            [python, script, "--selftest"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
            env={"PYTHONPATH": str(root / "apps/api/src"), "PATH": "/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired:
        return {"script": script, "verdict": "FAIL", "detail": f"висить понад {TIMEOUT} с"}
    if completed.returncode != 0:
        tail = (completed.stdout + completed.stderr).strip().splitlines()
        return {
            "script": script,
            "verdict": "FAIL",
            "detail": f"rc={completed.returncode}: " + (tail[-1][:160] if tail else "без виводу"),
        }
    return {"script": script, "verdict": "PASS", "detail": "негативні контролі пройшли"}


def assess(results: list[dict[str, Any]], expected: list[str]) -> list[dict[str, str]]:
    """Вирок над результатами. Пропущений скрипт — НЕ мовчазний успіх."""
    if not expected:
        return [{"check": "selftest_coverage", "verdict": "UNKNOWN", "detail": "жодного скрипта"}]
    seen = {item["script"] for item in results}
    missed = sorted(set(expected) - seen)
    findings: list[dict[str, str]] = []
    findings.append(
        {
            "check": "every_declared_selftest_ran",
            "verdict": "FAIL",
            "detail": "оголошено `--selftest`, але не запускалось: " + ", ".join(missed),
        }
        if missed
        else {
            "check": "every_declared_selftest_ran",
            "verdict": "PASS",
            "detail": f"{len(expected)} самоперевірок запущено, жодної пропущеної",
        }
    )
    failed = sorted(item["script"] for item in results if item["verdict"] != "PASS")
    findings.append(
        {
            "check": "every_selftest_passes",
            "verdict": "FAIL",
            "detail": "самоперевірка не пройшла: " + ", ".join(failed),
        }
        if failed
        else {
            "check": "every_selftest_passes",
            "verdict": "PASS",
            "detail": f"{len(results)} самоперевірок зелені",
        }
    )
    return findings


def verdict(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "UNKNOWN"
    verdicts = {finding["verdict"] for finding in findings}
    if "FAIL" in verdicts:
        return "FAIL"
    return "UNKNOWN" if "UNKNOWN" in verdicts else "PASS"


def selftest() -> int:
    """Сам гейт мусить червоніти на кожен спосіб збрехати — і на власний теж."""
    cases: list[tuple[str, list[dict[str, Any]], list[str], str]] = [
        (
            "усі запущені й зелені",
            [{"script": "a.py", "verdict": "PASS"}, {"script": "b.py", "verdict": "PASS"}],
            ["a.py", "b.py"],
            "PASS",
        ),
        (
            "один оголошений і НЕ запущений — не мовчазний успіх",
            [{"script": "a.py", "verdict": "PASS"}],
            ["a.py", "b.py"],
            "FAIL",
        ),
        (
            "один запущений і червоний",
            [{"script": "a.py", "verdict": "PASS"}, {"script": "b.py", "verdict": "FAIL"}],
            ["a.py", "b.py"],
            "FAIL",
        ),
        ("нічого не оголошено — UNKNOWN, не PASS", [], [], "UNKNOWN"),
        ("оголошено, не запущено нічого", [], ["a.py"], "FAIL"),
    ]
    bad = 0
    for name, results, expected, want in cases:
        got = verdict(assess(results, expected))
        ok = got == want
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")

    # Виявлення мусить бачити ОГОЛОШЕННЯ прапорця, а не будь-яку згадку рядка:
    # інакше документація вимагала б самоперевірки від скрипта, який її не має.
    checks = [
        ('parser.add_argument("--selftest", action="store_true")', True),
        ("parser.add_argument('--selftest')", True),
        ("# запусти з --selftest, щоб побачити негативні контролі", False),
        ('print("вжиток: script.py --selftest")', False),
    ]
    for text, want_found in checks:
        got_found = DECLARES.search(text) is not None
        ok = got_found == want_found
        bad += not ok
        print(
            f"  [{'ok' if ok else 'ЗБІЙ'}] виявлення {'ловить' if want_found else 'мовчить'}: {text[:46]}"
        )

    total = len(cases) + len(checks)
    print(f"\nнегативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def _head(root: Path) -> str:
    """Прив'язка звіту до дерева: без неї звіт про вчорашній HEAD задовольняв би
    замінник SI-4 моделі впевненості сьогодні."""
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "var/selftest-coverage.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    expected = [s for s in declaring(arguments.root) if s != SELF]
    results = [run_one(script, arguments.root) for script in expected]
    bounds = [_self_is_covered(arguments.root), _blind_spot_is_bounded(arguments.root)]
    findings = [*assess(results, expected), *bounds]
    overall = verdict(findings)
    report = {
        "schema": SCHEMA,
        "status": overall,
        "commit": _head(arguments.root),
        "declared": len(expected),
        "findings": findings,
        "results": results,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for item in results:
        if item["verdict"] != "PASS":
            print(f"  [{item['verdict']}] {item['script']}: {item['detail']}")
    for item in findings:
        print(f"  [{item['verdict']}] {item['check']}: {item['detail']}")
    print(f"\nselftest-coverage: {overall}  → {arguments.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
