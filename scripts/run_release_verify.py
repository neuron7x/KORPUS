#!/usr/bin/env python3
"""Одна команда, що доводить готовність — або називає, чого бракує, і виходить ненулем.

Порядок тут не за смаком. Він ВИВЕДЕНИЙ прогонами 02.09.2026, і кожен крок стоїть там,
де стоїть, через конкретну спійману помилку:

1. Дерево мусить бути чисте ДО початку. Вимір на дереві, що рухається, дає числа про
   різні дерева: `postgres_adversarial_suite` дав FALSE рівно тому, що я правив джерело
   під час прогону, і два провали були `source_manifest` та `module_budget`, а не безпека.

2. `evidence-refresh` перший. Маніфест будується з ВІДСТЕЖЕНИХ файлів, тож новий файл,
   ще не закомічений, у нього не потрапляє — і тест паритету червоніє на кроці, який до
   цього не має стосунку.

3. Виробники, потім СПОЖИВАЧ. `operational-gate` хешує звіти виробників, тож поставлений
   перед ними він судить файли, яких уже немає. Тричі за один вечір це дало три різні
   червоні з однією причиною.

4. Зовнішні гейти ПІСЛЯ того, як джерело остаточне. Будь-яка правка розв'язує їхню
   прив'язку: `live_postgres_rls` став unbound саме так, і це правильна робота контуру.

5. Після коміту доказу HEAD зсувається, і щойно знятий лан стає неприв'язаним. Нерухома
   точка сходиться: `operational-gate` і `lane-report` лишають дерево чистим, тож
   повторний прогін ЦИХ ДВОХ замикає цикл без нового коміту.

Код виходу: 0 лише коли вирок ACCEPTED. Усе інше — ненуль, бо «не виміряно» і «виміряно
й зламано» однаково не є готовністю.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import compute_source_digest  # noqa: E402

#: (ціль, роль). Роль пояснює, чому крок стоїть саме тут, і читається у звіті.
STEPS: tuple[tuple[str, str], ...] = (
    ("evidence-refresh", "маніфест описує це дерево"),
    ("api-test", "виробник"),
    ("mutation", "виробник"),
    ("eval", "виробник"),
    ("migration-gate", "виробник"),
    ("scale", "виробник"),
    ("operational-gate", "споживач: хешує звіти виробників"),
    ("assemble-assurance", "збірка доказу"),
    ("snapshot", "публікація доказу"),
    ("validate", "гейти"),
    ("gate-liveness", "чи гейти здатні почервоніти"),
    ("release-surface", "знаменник не скоротився"),
    ("lane-report", "що виміряно, а що не встигло"),
    ("corpus-axes", "профіль осей"),
)

#: Зовнішні гейти. Ідуть ПІСЛЯ джерела й потребують docker.
EXTERNAL: tuple[tuple[str, str], ...] = (
    ("production-postgres-security", "справжній PostgreSQL"),
    ("production-exact-environment-image", "точний інтерпретатор у продакшенному образі"),
    ("production-hard-predicates", "перелік того, що ще зовні"),
)

#: Після коміту доказу HEAD зсувається. Ці двоє лишають дерево чистим, тож замикають цикл.
CLOSURE: tuple[str, ...] = ("operational-gate", "lane-report")


def run(target: str, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        done = subprocess.run(
            ["make", target],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"target": target, "state": "TIMED_OUT", "code": None, "seconds": timeout}
    return {
        "target": target,
        "state": "PASSED" if done.returncode == 0 else "FAILED",
        "code": done.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "tail": (done.stdout + done.stderr).strip().splitlines()[-3:] if done.returncode else [],
    }


def git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def verdict() -> dict[str, Any]:
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_branch_consolidation.py"),
            "--canonical",
            "main",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return dict(json.loads(done.stdout))
    except json.JSONDecodeError:
        return {"verdict": "UNREADABLE", "problems": [done.stderr.strip()[:300]], "unknown": []}


def sequence(with_external: bool, timeout: float) -> tuple[list[dict[str, Any]], str | None]:
    """Кроки до першої відмови. Спинятись треба: далі числа були б про інше дерево."""
    results: list[dict[str, Any]] = []
    planned = [*STEPS, *(EXTERNAL if with_external else ())]
    for target, role in planned:
        outcome = run(target, timeout)
        outcome["role"] = role
        results.append(outcome)
        if outcome["state"] != "PASSED":
            return results, target
    return results, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-external", action="store_true", help="без docker-гейтів")
    parser.add_argument("--closure-only", action="store_true", help="лише замикання після коміту")
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--out", type=Path, default=ROOT / "var/release-verify.json")
    args = parser.parse_args()

    head = git("rev-parse", "HEAD")
    dirty = [line for line in git("status", "--porcelain").splitlines() if line]
    if dirty and not args.closure_only:
        refusal: dict[str, Any] = {
            "status": "REFUSED",
            "reason": "дерево брудне до початку — вимір на дереві, що рухається, дає числа про різні дерева",
            "dirty": dirty[:10],
            "head": head,
        }
        print(json.dumps(refusal, ensure_ascii=False, indent=2))
        return 2

    # Тотожність ПРЕДМЕТА до й після. Вимір, що змінює те, що міряє, не є виміром:
    # виміряно 02.09.2026 — усі 15 артефактів прогону лягли в `reports/`, і НУЛЬ із них
    # у обсязі джерела. Це властивість, а не випадковість, тож вона мусить перевірятись
    # щоразу, а не бути спостереженням, зробленим одного разу.
    source_before = compute_source_digest(ROOT)
    if args.closure_only:
        results = [run(target, args.timeout) for target in CLOSURE]
        stopped = next((r["target"] for r in results if r["state"] != "PASSED"), None)
    else:
        results, stopped = sequence(not args.skip_external, args.timeout)
    source_after = compute_source_digest(ROOT)
    if source_after != source_before:
        moved: dict[str, Any] = {
            "status": "INVALID",
            "reason": "джерело змінилось ПІД ЧАС виміру — числа нижче про різні дерева",
            "source_before": source_before,
            "source_after": source_after,
            "steps": results,
        }
        print(json.dumps(moved, ensure_ascii=False, indent=2))
        return 3

    final = (
        verdict() if stopped is None else {"verdict": "NOT_REACHED", "problems": [], "unknown": []}
    )
    after = git("rev-parse", "HEAD")
    report: dict[str, Any] = {
        "schema": "korpus.release-verify.v1",
        "head_before": head,
        "head_after": after,
        "head_moved": head != after,
        "source_digest": source_before,
        "source_unmoved_during_run": True,
        "steps": results,
        "stopped_at": stopped,
        "verdict": final.get("verdict"),
        "problems": final.get("problems", []),
        "unknown": final.get("unknown", []),
        "tree_dirty_after": len(
            [line for line in git("status", "--porcelain").splitlines() if line]
        ),
        "status": "PASS" if final.get("verdict") == "ACCEPTED" else "FAIL",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
