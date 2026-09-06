#!/usr/bin/env python3
"""Веб-регресія як ДОКАЗ, а не як зелений вивід у чужому журналі.

`CLM-WEB` оголошувала доказом `reports/release/<release>/WEB_REGRESSION_REPORT.json`,
якого не писав ЖОДЕН крок: ні `web-build`, ні публікатор релізних доказів, ні лан.
Претензія була структурно недосяжною — вічний `PENDING_EVIDENCE`, і жодне
перезбирання не могло цього змінити. Виміряно 05.09.2026 під час термінального
закриття: `grep -rl WEB_REGRESSION_REPORT` знаходив лише саме оголошення претензії.

Сам факт при цьому був доведений — `web:test` серед вісімнадцяти обов'язкових джобів
конвеєра, зелений на кандидаті. Бракувало не властивості, а її запису: доказ жив у
чужому журналі й помирав разом із ним.

Пакет `apps/web` не має залежностей узагалі (`dependencies` і `devDependencies`
порожні), тож lint, test і build бігають локально без встановлення — доказ дешевий і
відтворюваний, а не привілей середовища CI.

Число тестів береться з TAP-підсумку `node --test`, а не з коду виходу: «rc=0» не
відрізняє 158 пройдених від нуля запущених, і саме цю підміну тут закривають
`tests`/`pass`/`fail`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.provenance import stamp  # noqa: E402
from release_identity import release_tag  # noqa: E402

OUT = ROOT / "var/web-regression.json"
STEPS = ("lint", "test", "build")


def _run(script: str) -> tuple[int, str]:
    done = subprocess.run(
        ["npm", "--prefix", "apps/web", "run", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def _tap_counts(text: str) -> dict[str, int]:
    """`# tests`/`# pass`/`# fail` із TAP. Відсутнє число — не нуль, а відсутність."""
    counts: dict[str, int] = {}
    for key in ("tests", "pass", "fail", "skipped"):
        found = re.search(rf"^# {key} (\d+)$", text, re.MULTILINE)
        if found:
            counts[key] = int(found.group(1))
    return counts


def main() -> int:
    results: dict[str, Any] = {}
    for script in STEPS:
        code, text = _run(script)
        results[script] = {"exit_code": code, "status": "PASS" if code == 0 else "FAIL"}
        if script == "test":
            results[script].update(_tap_counts(text))

    counts = results["test"]
    executed = counts.get("tests")
    # Виконання і вирок — РІЗНІ предикати. Нуль виконаних тестів із rc=0 не є успіхом,
    # і саме тому `tests` мусить бути додатнім, а не лише `fail == 0`.
    healthy = (
        all(step["exit_code"] == 0 for step in results.values())
        and isinstance(executed, int)
        and executed > 0
        and counts.get("fail") == 0
    )
    report = {
        "schema": "korpus.web-regression.v1",
        "release": release_tag(ROOT),
        "status": "PASS" if healthy else "FAIL",
        "steps": results,
        "tests": executed,
        "passed": counts.get("pass"),
        "failed": counts.get("fail"),
        "skipped": counts.get("skipped"),
        "evidence_class": "LOCAL_NODE_TEST_RUNNER",
        "provenance": stamp(ROOT, "scripts/publish_web_regression.py"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
